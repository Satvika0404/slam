"""One immutable input/run shared by every workflow view. No model or external writes."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import queue
import stat
import threading
import uuid
import zipfile
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from slam.contracts import AuditRequest, CaseAnswer, CaseContext, EvidenceBundle
from slam.ingestion import ingest, load_requests
from slam.pipeline import eligible_evidence_ids
from slam.planning import export_output_csv
from slam.planning.engine import plan_case
from slam.planning.validation import validate_answer
from slam.reconstruction import linking, reconstruct_with_links
from slam.runtime.events import observe

from . import service

STORAGE = Path(__file__).resolve().parents[3] / "artifacts/aftertrace/workflow"
REQUIRED = (
    "deletion_requests.csv",
    "user_identities.csv",
    "user_audit_log.csv",
    "system_activity.csv",
    "deletion_rules.csv",
    "evidence_files.csv",
)
INPUTS: dict[str, Input] = {}
RUNS: dict[str, Run] = {}
AUDIT_LOCK = threading.Lock()


@dataclass
class Input:
    id: str
    root: Path
    name: str
    fingerprint: str
    requests: int
    sources: int
    formats: dict[str, int]

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items() if k != "root"}


@dataclass
class Run:
    id: str
    input: Input
    status: str = "running"
    bundle: EvidenceBundle | None = None
    requests: dict[str, AuditRequest] = field(default_factory=dict)
    contexts: dict[str, CaseContext] = field(default_factory=dict)
    answers: dict[str, CaseAnswer] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    csv: str | None = None

    def case(self, case_id: str) -> dict[str, Any]:
        if self.bundle is None or case_id not in self.answers:
            raise HTTPException(404, "This request has no completed audit in this run")
        return service.case_view(
            case_id,
            "dataset",
            self.input.root,
            prepared=(
                self.requests[case_id],
                self.bundle,
                self.contexts[case_id],
                self.answers[case_id],
            ),
        )


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def register_input(root: Path, name: str) -> Input:
    root = root.resolve()
    if any(not (root / name).is_file() for name in REQUIRED):
        raise HTTPException(
            422, "A dataset needs the six required CSV files and its evidence directory"
        )
    entries = rows(root / "evidence_files.csv")
    paths = [root / name for name in REQUIRED]
    formats: dict[str, int] = {}
    for entry in entries:
        path = (root / entry.get("file_path", "")).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(422, "The manifest references a missing or unsafe evidence path")
        paths.append(path)
        kind = path.suffix.lower().lstrip(".") or "other"
        formats[kind] = formats.get(kind, 0) + 1
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    fingerprint = digest.hexdigest()
    item = Input(
        uuid.uuid4().hex,
        root,
        name,
        fingerprint,
        len(rows(root / REQUIRED[0])),
        len(entries),
        formats,
    )
    if item.requests == 0:
        raise HTTPException(422, "No audit requests were supplied")
    INPUTS[item.id] = item
    return item


def get_run(run_id: str) -> Run:
    if run_id not in RUNS:
        raise HTTPException(404, "Run is unavailable; start an audit from your dataset")
    return RUNS[run_id]


def event_stream(work: Callable[[Callable[..., None], threading.Event], None]) -> StreamingResponse:
    async def generate() -> AsyncIterator[bytes]:
        messages: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=128)
        stopped = threading.Event()
        sequence = 0

        def send(event: str, **payload: Any) -> None:
            nonlocal sequence
            if stopped.is_set():
                raise InterruptedError("Client stopped following")
            sequence += 1
            frame = {
                "event": event,
                "sequence": sequence,
                "at": datetime.now(UTC).isoformat(),
                "payload": payload,
            }
            while not stopped.is_set():
                try:
                    messages.put(frame, timeout=0.1)
                    return
                except queue.Full:
                    continue
            raise InterruptedError("Client stopped following")

        def worker() -> None:
            try:
                work(send, stopped)
            except InterruptedError:
                pass
            except Exception as exc:
                if not stopped.is_set():
                    send(
                        "run.failed",
                        message="Execution could not finish",
                        error_type=type(exc).__name__,
                    )
            finally:
                while not stopped.is_set():
                    try:
                        messages.put(None, timeout=0.1)
                        break
                    except queue.Full:
                        continue

        def take() -> tuple[bool, dict[str, Any] | None]:
            try:
                return True, messages.get(timeout=0.5)
            except queue.Empty:
                return False, None

        threading.Thread(target=worker, daemon=True).start()
        try:
            while True:
                available, frame = await asyncio.to_thread(take)
                if not available:
                    yield b": keepalive\n\n"
                elif frame is None:
                    break
                else:
                    yield (
                        "event: execution\ndata: " + json.dumps(frame, default=str) + "\n\n"
                    ).encode()
        finally:
            stopped.set()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class AuditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_id: str


def executable(context: CaseContext, answer: CaseAnswer) -> bool:
    return (
        context.request_intent.value == "DELETION"
        and context.subject_id is not None
        and not context.coverage_issues
        and not context.unresolved_conflicts
        and not answer.trace.get("not_certified_because")
        and all(
            r.supporting_evidence_ids and not r.uncertain and not r.conflicting_evidence_ids
            for r in context.resource_states
        )
    )


def start_audit(item: Input) -> StreamingResponse:
    # Pin bytes before execution. Uploaded and configured inputs remain read-only.
    fresh = register_input(item.root, item.name)
    INPUTS.pop(fresh.id, None)
    if fresh.fingerprint != item.fingerprint:
        raise HTTPException(409, "Dataset changed; load it again before auditing")
    run = Run(uuid.uuid4().hex, item)

    def work(send: Callable[..., None], stopped: threading.Event) -> None:
        if not AUDIT_LOCK.acquire(blocking=False):
            send("run.failed", message="Another audit is running; wait for it to finish")
            return
        RUNS[run.id] = run
        try:
            send("run.started", run_id=run.id, input=item.public(), api_calls=0)
            send("stage.started", stage="ingestion")

            def observer(kind: str, payload: dict[str, Any]) -> None:
                if kind == "source.completed":
                    send(kind, **payload)

            with observe(observer):
                bundle = ingest(item.root, provider=None)
            run.bundle = bundle
            requests = load_requests(item.root)
            run.requests = {r.case_id: r for r in requests}
            send(
                "stage.completed",
                stage="ingestion",
                sources=[s.model_dump(mode="json") for s in bundle.sources],
                observations=len(bundle.observations),
            )
            send("stage.started", stage="linking")
            model = linking.fit(bundle, requests)
            send("stage.completed", stage="linking", learned_groups=len(model.groups))
            for index, request in enumerate(requests):
                if stopped.is_set():
                    run.status = "cancelled"
                    return
                send("case.started", case_id=request.case_id, index=index + 1, total=len(requests))

                def checkpoint(
                    kind: str, payload: dict[str, Any], case_id: str = request.case_id
                ) -> None:
                    if kind.startswith("stage."):
                        send(kind, case_id=case_id, stage=payload.get("stage"))

                try:
                    with observe(checkpoint):
                        context = reconstruct_with_links(request, bundle, model, provider=None)
                    send("stage.started", case_id=request.case_id, stage="policy")
                    answer = plan_case(context, bundle)
                    send("stage.completed", case_id=request.case_id, stage="policy")
                    send("stage.started", case_id=request.case_id, stage="validation")
                    if answer.deletion_status is not None:
                        answer = validate_answer(
                            answer,
                            eligible_evidence_ids=eligible_evidence_ids(bundle, request.audit_at),
                        )
                    run.contexts[request.case_id] = context
                    run.answers[request.case_id] = answer
                    send("stage.completed", case_id=request.case_id, stage="validation")
                    send(
                        "case.completed",
                        case_id=request.case_id,
                        status=answer.deletion_status,
                        steps=len(answer.steps),
                        actions=sum(s.phase.value == "REMEDIATION" for s in answer.steps),
                        uncertain=bool(answer.trace.get("not_certified_because")),
                        executable=executable(context, answer),
                    )
                except InterruptedError:
                    raise
                except Exception as exc:
                    run.errors[request.case_id] = type(exc).__name__
                    send("case.failed", case_id=request.case_id, error_type=type(exc).__name__)
            if not run.errors and all(a.ready_for_export for a in run.answers.values()):
                directory = STORAGE / run.id
                directory.mkdir(parents=True, exist_ok=True)
                output = directory / "original-audit.csv"
                export_output_csv(tuple(run.answers.values()), tuple(run.requests), output)
                run.csv = output.read_text(encoding="utf-8")
            run.status = "completed"
            send(
                "run.completed",
                run_id=run.id,
                processed=len(run.answers),
                failed=len(run.errors),
                csv_available=run.csv is not None,
                api_calls=0,
            )
        except InterruptedError:
            run.status = "cancelled"
            raise
        except Exception:
            run.status = "failed"
            raise
        finally:
            AUDIT_LOCK.release()

    return event_stream(work)


def source_for(run: Run, evidence_id: str) -> dict[str, Any]:
    assert run.bundle is not None
    source = next((s for s in run.bundle.sources if s.source_id == evidence_id), None)
    if source:
        path = (run.input.root / source.path).resolve()
        if not path.is_relative_to(run.input.root) or not path.is_file():
            raise HTTPException(404, "Source is unavailable")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source.sha256:
            raise HTTPException(409, "Source bytes changed since this audit; reload the dataset")
        return {
            "id": evidence_id,
            "kind": source.kind.value,
            "at": source.captured_at.isoformat(),
            "sha256": source.sha256,
            "path": path,
            "content": None,
        }
    for collection, id_field, time_field in [
        (run.bundle.activities, "activity_id", "occurred_at"),
        (run.bundle.identity_changes, "audit_id", "changed_at"),
        (run.bundle.current_identities, "source_id", "updated_at"),
    ]:
        row = next((r for r in collection if getattr(r, id_field) == evidence_id), None)
        if row:
            return {
                "id": evidence_id,
                "kind": "csv",
                "at": getattr(row, time_field).isoformat(),
                "sha256": None,
                "path": None,
                "content": row.model_dump_json(indent=2),
            }
    raise HTTPException(404, "Evidence does not belong to this run")


def make_router(default_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/workflow", tags=["One-dataset workflow"])

    @router.get("/input")
    def default_input() -> dict[str, Any]:
        if not (default_root / REQUIRED[0]).is_file():
            return {"available": False, "input": None}
        return {
            "available": True,
            "input": register_input(default_root, "Local participant dataset").public(),
        }

    @router.post("/input")
    async def upload(request: Request) -> dict[str, Any]:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 32 * 1024 * 1024:
                raise HTTPException(413, "ZIP upload exceeds 32 MiB")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
            members = archive.infolist()
        except zipfile.BadZipFile as exc:
            raise HTTPException(
                422, "Upload a ZIP containing a participant-format dataset"
            ) from exc
        if len(members) > 10000 or sum(m.file_size for m in members) > 128 * 1024 * 1024:
            raise HTTPException(413, "Expanded dataset exceeds the input limit")
        destination = (STORAGE / "inputs" / uuid.uuid4().hex).resolve()
        # Validate the entire archive before creating files; never extract archive paths blindly.
        for member in members:
            path = (destination / member.filename.replace("\\", "/")).resolve()
            if (
                not path.is_relative_to(destination)
                or ":" in member.filename
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise HTTPException(422, "Unsafe ZIP path or symbolic link")
        for member in members:
            if member.is_dir():
                continue
            path = (destination / member.filename.replace("\\", "/")).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(member))
        candidates = [
            p.parent
            for p in destination.rglob(REQUIRED[0])
            if all((p.parent / name).is_file() for name in REQUIRED)
        ]
        if len(candidates) != 1:
            raise HTTPException(422, "ZIP must contain exactly one dataset root")
        return register_input(candidates[0], "Uploaded dataset").public()

    @router.post("/runs")
    def audit(body: AuditBody) -> Response:
        item = INPUTS.get(body.input_id)
        if item is None:
            raise HTTPException(404, "Load a dataset first")
        return start_audit(item)

    @router.get("/runs/{run_id}")
    def run_info(run_id: str) -> dict[str, Any]:
        from .remediation import SANDBOXES

        run = get_run(run_id)
        return {
            "id": run.id,
            "input": run.input.public(),
            "status": run.status,
            "cases": [
                {
                    "case_id": key,
                    "status": answer.deletion_status,
                    "actions": sum(s.phase.value == "REMEDIATION" for s in answer.steps),
                    "steps": len(answer.steps),
                    "uncertain": bool(answer.trace.get("not_certified_because")),
                    "executable": executable(run.contexts[key], answer),
                }
                for key, answer in run.answers.items()
            ],
            "errors": run.errors,
            "csv_available": run.csv is not None,
            "working_copies": {
                copy.case_id: copy.id for copy in SANDBOXES.values() if copy.run.id == run.id
            },
        }

    @router.get("/runs/{run_id}/cases/{case_id}")
    def case(run_id: str, case_id: str) -> dict[str, Any]:
        return get_run(run_id).case(case_id)

    @router.get("/runs/{run_id}/export")
    def export(run_id: str) -> Response:
        run = get_run(run_id)
        if run.csv is None:
            raise HTTPException(409, "Original audit output is not exportable")
        return Response(
            run.csv,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="original-audit.csv"'},
        )

    @router.get("/runs/{run_id}/evidence/{evidence_id}")
    def evidence(run_id: str, evidence_id: str) -> dict[str, Any]:
        item = source_for(get_run(run_id), evidence_id)
        path = item.pop("path")
        if path:
            if item["kind"] in {"image", "pdf"}:
                item["content"] = None
            else:
                item["content"] = path.read_text(encoding="utf-8", errors="replace")[:131072]
        return item

    @router.get("/runs/{run_id}/evidence/{evidence_id}/raw")
    def raw(run_id: str, evidence_id: str) -> Response:
        item = source_for(get_run(run_id), evidence_id)
        if item["path"]:
            return FileResponse(
                item["path"],
                media_type=(
                    "application/pdf"
                    if item["kind"] == "pdf"
                    else "image/png"
                    if item["kind"] == "image"
                    else "text/plain"
                ),
                content_disposition_type="inline",
                headers={"X-Content-Type-Options": "nosniff"},
            )
        return Response(item["content"], media_type="text/plain")

    return router
