"""Bounded SSE execution of the real engine, with opt-in model calls and no fake delays."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from slam.config import ProviderName, Settings
from slam.contracts import AuditRequest, CaseAnswer, CaseContext, EvidenceBundle, RequestIntent
from slam.ingestion import ingest, load_requests
from slam.planning import export_output_csv, plan
from slam.reconstruction import reconstruct
from slam.runtime.events import emit, observe
from slam.runtime.metering import UsageLedger
from slam.runtime.provider import (
    ModelBudgetError,
    ModelImageInput,
    ModelProvider,
    ModelResult,
    StructuredT,
)

from . import service
from .demo import corpus
from .models import CaseView

_lock = threading.BoundedSemaphore(1)


class LiveRunRequest(BaseModel):
    mode: Literal["demo", "dataset"] = "demo"
    case_id: str = Field(default="demo_024", min_length=1, max_length=200)
    scope: Literal["case", "all"] = "case"
    cutoff: datetime | None = None
    use_model: bool = False
    max_model_calls: int = Field(default=4, ge=1, le=32)


def runtime_info() -> dict[str, Any]:
    try:
        settings = Settings()
        configured = settings.model_provider is ProviderName.OPENAI
        return {
            "model_available": configured,
            "provider": "openai" if configured else "none",
            "model": settings.model if configured else None,
            "model_role": (
                "Optional image extraction and ambiguous-request proposals; "
                "deterministic graph and policy decisions."
            ),
        }
    except ValueError:
        return {
            "model_available": False,
            "provider": "unavailable",
            "model": None,
            "model_role": "Server model configuration is incomplete. Keys must stay on the server.",
        }


class ObservedProvider:
    def __init__(self, provider: ModelProvider, ledger: UsageLedger, limit: int):
        self.provider, self.ledger, self.limit, self.calls = provider, ledger, limit, 0

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def model(self) -> str:
        return self.provider.model

    def generate(
        self,
        *,
        prompt: str,
        prompt_version: str,
        response_model: type[StructuredT],
        images: Sequence[ModelImageInput] = (),
    ) -> ModelResult[StructuredT]:
        if self.calls >= self.limit:
            emit("model.blocked", reason="Per-run model-call limit reached")
            raise ModelBudgetError("Per-run model-call limit reached")
        self.calls += 1
        emit(
            "model.started",
            provider=self.name,
            model=self.model,
            prompt_version=prompt_version,
            schema=response_model.__name__,
            images=len(images),
            call=self.calls,
        )
        try:
            result = self.provider.generate(
                prompt=prompt,
                prompt_version=prompt_version,
                response_model=response_model,
                images=images,
            )
        except Exception as exc:
            emit(
                "model.failed", error_type=type(exc).__name__, provider=self.name, model=self.model
            )
            raise
        self.ledger.record(result.metadata)
        emit("model.completed", **asdict(result.metadata))
        return result


def stream_run(body: LiveRunRequest, root: Path) -> StreamingResponse:
    if body.cutoff is not None and (body.cutoff.tzinfo is None or body.cutoff.utcoffset() is None):
        raise HTTPException(422, "Audit cutoff must include a timezone")
    if body.scope == "all" and body.cutoff is not None:
        raise HTTPException(422, "Full-dataset runs use each request's original audit cutoff")
    provider: ModelProvider | None = None
    ledger = UsageLedger()
    if body.use_model:
        try:
            settings = Settings()
        except ValueError as exc:
            raise HTTPException(422, "Server model configuration is incomplete") from exc
        if settings.model_provider is not ProviderName.OPENAI:
            raise HTTPException(422, "No API model is configured on this server")
        from slam.runtime.openai_provider import OpenAIModelProvider

        provider = ObservedProvider(OpenAIModelProvider(settings), ledger, body.max_model_calls)

    async def events() -> AsyncIterator[bytes]:
        if not _lock.acquire(blocking=False):
            yield (
                b'event: execution\ndata: {"event":"run.failed","payload":'
                b'{"message":"Another run is active. Retry after it finishes."}}\n\n'
            )
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=128)
        stopped = threading.Event()
        started = time.perf_counter()
        run_id = uuid.uuid4().hex
        sequence = 0
        current_request: AuditRequest | None = None
        bundle: EvidenceBundle | None = None
        preview: CaseContext | None = None
        preview_intent = RequestIntent.UNCLEAR

        def send(event: str, payload: dict[str, Any]) -> None:
            nonlocal sequence, preview, preview_intent
            if stopped.is_set():
                raise InterruptedError("Live run disconnected")
            if event == "stage.completed" and bundle is not None and current_request is not None:
                stage = payload.get("stage")
                if stage == "intent":
                    preview_intent = RequestIntent(payload["intent"])
                if stage == "identity":
                    preview = CaseContext(
                        request=current_request,
                        request_intent=preview_intent,
                        subject_id=payload["subject_id"],
                        identity_links=payload["identity_links"],
                        policy_rules=bundle.policy_rules,
                        evidence_captured_at=payload["evidence_times"],
                        coverage_issues=tuple(payload["coverage_issues"]),
                        unresolved_conflicts=tuple(payload["conflicts"]),
                    )
                if preview is not None and stage in {"timeline", "graph"}:
                    extra = {
                        k: v
                        for k, v in payload.items()
                        if k
                        in {
                            "resource_states",
                            "eligible_observation_ids",
                            "excluded_future_observation_ids",
                            "active_flows",
                            "restore_risks",
                        }
                    }
                    extra["coverage_issues"] = (
                        *preview.coverage_issues,
                        *payload["coverage_issues"],
                    )
                    extra["unresolved_conflicts"] = (
                        *preview.unresolved_conflicts,
                        *payload["conflicts"],
                    )
                    preview = CaseContext.model_validate({**preview.model_dump(), **extra})
                if preview is not None and stage in {"identity", "timeline", "graph"}:
                    waiting = CaseAnswer(
                        case_id=current_request.case_id,
                        ready_for_export=False,
                        blocking_issues=("Execution is in progress; no final answer exists yet.",),
                    )
                    payload = {
                        **payload,
                        "snapshot": CaseView.model_validate(
                            service.case_view(
                                current_request.case_id,
                                body.mode,
                                root,
                                prepared=(current_request, bundle, preview, waiting),
                            )
                        ).model_dump(mode="json"),
                    }
            sequence += 1
            item = {
                "event": event,
                "run_id": run_id,
                "sequence": sequence,
                "at": datetime.now(UTC).isoformat(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "case_id": current_request.case_id if current_request else None,
                "payload": payload,
            }
            future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
            while not future.done():
                if stopped.wait(0.05):
                    future.cancel()
                    raise InterruptedError("Live run disconnected")
            future.result()

        def worker() -> None:
            nonlocal current_request, bundle, preview
            try:
                with observe(send):
                    emit(
                        "run.started",
                        mode=body.mode,
                        scope=body.scope,
                        provider=provider.name if provider else "none",
                        model=provider.model if provider else None,
                        model_call_limit=body.max_model_calls,
                        external_mutations=False,
                    )
                    emit("stage.started", stage="ingestion")
                    if body.mode == "dataset":
                        if not (root / "deletion_requests.csv").is_file():
                            raise FileNotFoundError("Participant dataset is not installed")
                        requests = load_requests(root)
                        if body.scope == "case":
                            requests = tuple(r for r in requests if r.case_id == body.case_id)
                        if not requests:
                            raise KeyError("Case not found")
                        bundle = ingest(
                            root,
                            cache_dir=root.parent / "artifacts" / "aftertrace" / "ingestion-cache",
                            provider=provider,
                        )
                    else:
                        keys = (
                            [r["case_id"] for r in service.case_list("demo", root)]
                            if body.scope == "all"
                            else [body.case_id]
                        )
                        requests = tuple(corpus(key)[0] for key in keys)
                        _, bundle, _ = corpus(requests[0].case_id)
                    emit(
                        "stage.completed",
                        stage="ingestion",
                        cases=len(requests),
                        sources=len(bundle.sources),
                        observations=len(bundle.observations),
                        issues=len(bundle.issues),
                        source_records=[s.model_dump(mode="json") for s in bundle.sources],
                        input_kind="fictional demo corpus"
                        if body.mode == "demo"
                        else "participant files",
                    )
                    answers: list[CaseAnswer] = []
                    for index, request in enumerate(sorted(requests, key=lambda r: r.case_id), 1):
                        current_request = (
                            request.model_copy(update={"audit_at": body.cutoff})
                            if body.cutoff
                            else request
                        )
                        preview = None
                        if body.mode == "demo":
                            _, bundle, _ = corpus(request.case_id)
                        emit(
                            "case.started",
                            position=index,
                            total=len(requests),
                            audit_at=current_request.audit_at.isoformat(),
                        )
                        try:
                            context = reconstruct(current_request, bundle, provider=provider)
                            if current_request.audit_at < current_request.requested_at:
                                context = context.model_copy(
                                    update={
                                        "coverage_issues": (
                                            *context.coverage_issues,
                                            "Selected cutoff precedes the deletion request.",
                                        )
                                    }
                                )
                            if context.request_intent is RequestIntent.NON_DELETION:
                                emit(
                                    "stage.skipped",
                                    stage="timeline",
                                    reason="Request does not authorize deletion",
                                )
                                emit(
                                    "stage.skipped",
                                    stage="graph",
                                    reason="Request does not authorize deletion",
                                )
                            emit("stage.started", stage="planning")
                            answer = plan(context)
                            emit(
                                "stage.completed",
                                stage="planning",
                                answer=answer.model_dump(mode="json"),
                            )
                            emit("stage.started", stage="validation")
                            answer = CaseAnswer.model_validate(answer.model_dump())
                            view = CaseView.model_validate(
                                service.case_view(
                                    request.case_id,
                                    body.mode,
                                    root,
                                    prepared=(current_request, bundle, context, answer),
                                )
                            )
                            emit(
                                "stage.completed",
                                stage="validation",
                                ready_for_export=answer.ready_for_export,
                                blocking_issues=list(answer.blocking_issues),
                                snapshot=view.model_dump(mode="json"),
                            )
                            answers.append(answer)
                            emit(
                                "case.completed",
                                position=index,
                                total=len(requests),
                                answer=answer.model_dump(mode="json"),
                            )
                        except InterruptedError:
                            raise
                        except Exception as exc:
                            answer = CaseAnswer(
                                case_id=request.case_id,
                                ready_for_export=False,
                                blocking_issues=(f"Case processing failed ({type(exc).__name__})",),
                            )
                            answers.append(answer)
                            emit(
                                "case.failed",
                                error_type=type(exc).__name__,
                                answer=answer.model_dump(mode="json"),
                            )
                    output_csv = None
                    if all(a.ready_for_export for a in answers):
                        with tempfile.TemporaryDirectory() as directory:
                            path = Path(directory) / "output.csv"
                            export_output_csv(
                                tuple(answers), tuple(r.case_id for r in requests), path
                            )
                            output_csv = path.read_text(encoding="utf-8")
                    emit(
                        "run.completed",
                        processed=len(answers),
                        blocked=sum(not a.ready_for_export for a in answers),
                        answers=[a.model_dump(mode="json") for a in answers],
                        output_csv=output_csv,
                        usage=ledger.summary(),
                    )
            except InterruptedError:
                pass
            except Exception as exc:
                if not stopped.is_set():
                    send(
                        "run.failed",
                        {
                            "message": "Execution stopped before a final result was produced.",
                            "error_type": type(exc).__name__,
                        },
                    )
            finally:
                _lock.release()
                if not stopped.is_set():
                    asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), 15)
                except TimeoutError:
                    yield b": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield (
                    "event: execution\ndata: " + json.dumps(item, separators=(",", ":")) + "\n\n"
                ).encode()
        finally:
            stopped.set()
            # A synchronous API call may finish; no subsequent stage starts after disconnect.
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
