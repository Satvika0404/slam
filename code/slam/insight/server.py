"""Local live-analysis server: re-run the insight stages on a what-if deletion, on demand.

The published dashboard is a static page and cannot run Python, Neo4j or a model. This server
serves the same page and adds ``POST /api/run``: the page sends the systems the user deleted in
the graph, the server re-audits the cases, deletes the systems in Neo4j, retrains the LightGBM
model, re-clusters with DBSCAN and asks the language model to explain the changed cases, then
streams progress lines and the final data back. Nothing is written to ``output.csv``.

Because a run can spend API tokens it is closed by default: it listens on loopback only unless a
host is given, accepts one run at a time, caps the number of model calls per run and refuses any
request whose ``Origin`` is not this server.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from slam.config import Settings
from slam.insight import build, graph
from slam.runtime.factory import build_provider
from slam.runtime.metering import UsageLedger

MAX_BODY_BYTES = 4096
MAX_LLM_CASES = 40
DEFAULT_PORT = 8765

Emit = Callable[[str, str], None]


@dataclass(frozen=True, slots=True)
class RunRequest:
    removed: frozenset[str]
    llm_cases: int


class BadRequestError(ValueError):
    pass


def parse_request(raw: bytes, systems: frozenset[str], max_llm: int) -> RunRequest:
    """Validate a ``/api/run`` body. Unknown systems and bad numbers are rejected, not ignored."""

    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BadRequestError("the body must be JSON") from None
    if not isinstance(body, dict):
        raise BadRequestError("the body must be a JSON object")
    removed = body.get("removed", [])
    if not isinstance(removed, list) or not all(isinstance(item, str) for item in removed):
        raise BadRequestError("removed must be a list of system ids")
    unknown = sorted(set(removed) - systems)
    if unknown:
        raise BadRequestError(f"unknown systems: {', '.join(unknown[:5])}")
    llm = body.get("llm_cases", 0)
    if isinstance(llm, bool) or not isinstance(llm, int) or not 0 <= llm <= max_llm:
        raise BadRequestError(f"llm_cases must be a whole number from 0 to {max_llm}")
    return RunRequest(removed=frozenset(removed), llm_cases=llm)


class LiveServer:
    """HTTP front end. The analysis itself is injected, so it can be replaced in tests."""

    def __init__(
        self,
        *,
        page: Path,
        status: Callable[[], dict[str, Any]],
        run: Callable[[RunRequest, Emit], dict[str, Any]],
        systems: frozenset[str],
        max_llm: int = MAX_LLM_CASES,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
    ) -> None:
        self._page, self._status, self._run = page, status, run
        self._systems, self._max_llm = systems, max_llm
        self._busy = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "SlamLive"

            def log_message(self, format: str, *args: Any) -> None:
                return  # request lines can carry nothing sensitive, but keep the console clean

            def _send(self, code: int, body: bytes, kind: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, default=str).encode("utf-8")
                self._send(code, body, "application/json")

            def do_GET(self) -> None:
                if self.path in {"/", "/index.html"}:
                    if not outer._page.is_file():
                        self._json(HTTPStatus.NOT_FOUND, {"error": "run dashboard/build_page.py"})
                        return
                    self._send(HTTPStatus.OK, outer._page.read_bytes(), "text/html; charset=utf-8")
                elif self.path == "/api/status":
                    self._json(HTTPStatus.OK, outer._status())
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

            def do_POST(self) -> None:
                if self.path != "/api/run":
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                origin = self.headers.get("Origin")
                if origin is not None and origin != f"http://{self.headers.get('Host', '')}":
                    self._json(HTTPStatus.FORBIDDEN, {"error": "cross-origin request refused"})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    size = -1
                if not 0 < size <= MAX_BODY_BYTES:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "missing or oversized body"})
                    return
                try:
                    request = parse_request(self.rfile.read(size), outer._systems, outer._max_llm)
                except BadRequestError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                if not outer._busy.acquire(blocking=False):
                    self._json(HTTPStatus.CONFLICT, {"error": "a run is already in progress"})
                    return
                try:
                    self._stream(request)
                finally:
                    outer._busy.release()

            def _stream(self, request: RunRequest) -> None:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()  # HTTP/1.0: the body ends when the connection closes
                started = time.monotonic()

                def line(payload: dict[str, Any]) -> None:
                    self.wfile.write(json.dumps(payload, default=str).encode("utf-8") + b"\n")
                    self.wfile.flush()

                def emit(stage: str, detail: str) -> None:
                    seconds = round(time.monotonic() - started, 1)
                    line({"stage": stage, "detail": detail, "t": seconds})

                try:
                    data = outer._run(request, emit)
                    seconds = round(time.monotonic() - started, 1)
                    line({"done": True, "seconds": seconds, "data": data})
                except build.AnalysisError as exc:
                    line({"error": str(exc)})
                except Exception as exc:  # report the kind of failure, never a stack or a secret
                    line({"error": f"{type(exc).__name__}: the run failed"})

        self.httpd = ThreadingHTTPServer((host, port), Handler)

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.httpd.server_address[:2]
        return str(host), int(port)

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def serve(
    dataset_dir: Path, dashboard_dir: Path, settings: Settings, *, host: str, port: int, cache: Path
) -> LiveServer:
    """Audit once, then answer live runs from memory."""

    prep = build.prepare(dataset_dir, dashboard_dir / "dashboard_data.json")
    return serve_prepared(prep, dashboard_dir, settings, host=host, port=port, cache=cache)


def serve_prepared(
    prep: build.Prepared,
    dashboard_dir: Path,
    settings: Settings,
    *,
    host: str,
    port: int,
    cache: Path,
) -> LiveServer:
    neo, neo_status = graph.connect_neo4j(settings)
    if neo is not None:
        neo.close()
    baseline = {s: sum(f.status == s for f in prep.facts) for s in ("INCOMPLETE", "COMPLETE")}
    max_llm = min(MAX_LLM_CASES, settings.api_max_calls) if settings.api_max_calls else 0

    def run(request: RunRequest, emit: Emit) -> dict[str, Any]:
        provider = build_provider(settings, UsageLedger()) if request.llm_cases else None
        return build.analyse(
            prep,
            settings=settings,
            provider=provider,
            llm_cases=request.llm_cases,
            removed=request.removed,
            cache_path=cache,
            progress=emit,
        ).data

    def status() -> dict[str, Any]:
        return {
            "live": True,
            "systems": sorted(prep.topology.nodes),
            "neo4j": neo_status,
            "model": {
                "provider": settings.model_provider.value,
                "name": settings.model,
                "max_calls": settings.api_max_calls,
                "max_tokens": settings.api_max_tokens,
            },
            "max_llm_cases": max_llm,
            "baseline": baseline,
        }

    return LiveServer(
        page=dashboard_dir / "ghost-data-console.html",
        status=status,
        run=run,
        systems=frozenset(prep.topology.nodes),
        max_llm=max_llm,
        host=host,
        port=port,
    )
