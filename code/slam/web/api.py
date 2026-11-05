"""Local API: python -m uvicorn slam.web.api:app --host 127.0.0.1 --port 8000."""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response

from slam.contracts import CaseAnswer
from slam.planning import export_output_csv

from . import service
from .live import LiveRunRequest, runtime_info, stream_run
from .models import CaseView

ROOT = Path(
    os.environ.get("SLAM_DATASET_DIR", Path(__file__).resolve().parents[3] / "dataset")
).resolve()
Mode = Literal["demo", "dataset"]
app = FastAPI(title="AFTERTRACE", version="0.1.0")

# The default product is one dataset -> one audit run -> isolated execution -> report.
from . import remediation, workflow  # noqa: E402

app.include_router(workflow.make_router(ROOT))
app.include_router(remediation.router)


@app.get("/api/runtime")
def runtime() -> dict[str, Any]:
    return runtime_info()


@app.post("/api/runs/stream")
def live_run(body: LiveRunRequest) -> Response:
    return stream_run(body, ROOT)


@app.exception_handler(FileNotFoundError)
async def missing_dataset(_request: Any, _exc: FileNotFoundError) -> Response:
    return Response(
        '{"detail":"Participant dataset is not installed on this server."}',
        status_code=503,
        media_type="application/json",
    )


@app.exception_handler(KeyError)
async def missing_record(_request: Any, _exc: KeyError) -> Response:
    return Response(
        '{"detail":"Evidence or case was not found."}',
        status_code=404,
        media_type="application/json",
    )


@app.exception_handler(ValueError)
async def invalid_request(_request: Any, _exc: ValueError) -> Response:
    return Response(
        '{"detail":"Invalid request or unsafe evidence path."}',
        status_code=422,
        media_type="application/json",
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ready",
        "dataset_available": (ROOT / "deletion_requests.csv").is_file(),
        "engine": "SLAM deterministic reconstruction and planning",
    }


@app.get("/api/cases")
def cases(mode: Mode = "demo") -> list[dict[str, str]]:
    return service.case_list(mode, ROOT)


@app.get("/api/cases/{case_id}", response_model=CaseView)
def case(case_id: str, mode: Mode = "demo", cutoff: datetime | None = None) -> dict[str, Any]:
    return service.case_view(case_id, mode, ROOT, cutoff)


@app.get("/api/cases/{case_id}/search")
def search(
    case_id: str, q: str = Query(default="", max_length=1000), mode: Mode = "demo"
) -> list[str]:
    return service.search(case_id, mode, ROOT, q)


@app.get("/api/evidence/{evidence_id}")
def evidence(evidence_id: str, case_id: str, mode: Mode = "demo") -> dict[str, Any]:
    return service.source_detail(evidence_id, case_id, mode, ROOT)


@app.get("/api/evidence/{evidence_id}/raw")
def raw_evidence(evidence_id: str, case_id: str, mode: Mode = "demo") -> Response:
    _, bundle, documents = service.inputs(case_id, mode, ROOT)
    if mode == "demo":
        if evidence_id not in documents:
            detail = service.source_detail(evidence_id, case_id, mode, ROOT)
            return Response(detail["content"], media_type="text/plain")
        return Response(documents[evidence_id], media_type="text/plain")
    row = next((s for s in bundle.sources if s.source_id == evidence_id), None)
    if row is None:
        detail = service.source_detail(evidence_id, case_id, mode, ROOT)
        return Response(detail["content"], media_type="text/plain")
    path = (ROOT / row.path).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise HTTPException(404, "Original source unavailable")
    media = (
        "application/pdf"
        if row.kind.value == "pdf"
        else "image/png"
        if row.kind.value == "image"
        else "text/plain"
    )
    return FileResponse(
        path,
        media_type=media,
        filename=path.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.post("/api/runs")
def run(mode: Mode = "demo") -> dict[str, Any]:
    start = time.perf_counter()
    if mode == "dataset":
        service.dataset.cache_clear()
        requests, bundle = service.dataset(str(ROOT))
        count = len(requests)
    else:
        _, bundle, _ = service.inputs("demo_024", mode, ROOT)
        count = 3
    return {
        "status": "ingestion_complete",
        "mode": mode,
        "cases": count,
        "sources": len(bundle.sources),
        "observations": len(bundle.observations),
        "elapsed_ms": round((time.perf_counter() - start) * 1000),
        "message": "Ingestion finished. Open a case to audit it. External data was not modified.",
    }


@app.get("/api/cases/{case_id}/export")
def export(case_id: str, mode: Mode = "demo", cutoff: datetime | None = None) -> Response:
    view = service.case_view(case_id, mode, ROOT, cutoff)
    answer = CaseAnswer.model_validate(view["answer"])
    if not answer.ready_for_export:
        raise HTTPException(
            409, "This case is blocked and cannot be exported as a completed audit."
        )
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "case.csv"
        export_output_csv((answer,), (case_id,), path)
        return Response(
            path.read_bytes(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="aftertrace-case.csv"'},
        )
