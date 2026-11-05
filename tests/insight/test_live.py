"""Deletion what-if and the live server: answers stay valid, and the server refuses unsafe use."""

from __future__ import annotations

import http.client
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from slam.contracts import Operation, Phase, Step, StepState
from slam.insight.build import AnalysisError
from slam.insight.facts import FEATURES, CaseFacts, Finding, apply_deletion, retention_lost
from slam.insight.server import Emit, LiveServer, RunRequest, parse_request

T0 = datetime(2026, 5, 1, tzinfo=UTC)
SYSTEMS = frozenset(
    {"search_service", "support_platform", "security_service", "integration_service"}
)


def _step(
    n: int, phase: Phase, op: Operation, state: StepState, system: str, res: str, ev: str = ""
) -> Step:
    return Step(
        step_no=n,
        phase=phase,
        system_id=system,
        resource_id=res,
        operation=op,
        state=state,
        evidence_id=ev,
    )


def _case(
    status: str, steps: list[Step], findings: list[Finding], *, uncertain: tuple[str, ...] = ()
) -> CaseFacts:
    return CaseFacts(
        "case_1",
        "evaluation",
        status,
        "COMPLETE",
        T0,
        tuple(findings),
        tuple(steps),
        tuple([0.0] * len(FEATURES)),
        uncertain,
    )


def _incomplete_two_systems() -> CaseFacts:
    f1 = Finding(
        1,
        "REPORT_REMAINING_RECORD",
        "REMAINING_RECORD",
        "search_service",
        "s1",
        "SEARCH_INDEX_ENTRY",
        "evidence_1",
    )
    f2 = Finding(
        2,
        "REPORT_EXPOSED_PII",
        "EXPOSED_PII",
        "support_platform",
        "m1",
        "SUPPORT_MESSAGE",
        "evidence_1",
    )
    steps = [
        _step(
            1,
            Phase.FINDING,
            Operation.REPORT_REMAINING_RECORD,
            StepState.PRESENT,
            "search_service",
            "s1",
            "evidence_1",
        ),
        _step(
            2,
            Phase.FINDING,
            Operation.REPORT_EXPOSED_PII,
            StepState.PRESENT,
            "support_platform",
            "m1",
            "evidence_1",
        ),
        _step(
            3, Phase.REMEDIATION, Operation.DELETE_RECORD, StepState.ABSENT, "search_service", "s1"
        ),
        _step(
            4,
            Phase.REMEDIATION,
            Operation.REDACT_RECORD,
            StepState.REDACTED,
            "support_platform",
            "m1",
        ),
        _step(
            5,
            Phase.VERIFICATION,
            Operation.VERIFY_RECORD_ABSENT,
            StepState.ABSENT,
            "search_service",
            "s1",
        ),
        _step(
            6,
            Phase.VERIFICATION,
            Operation.VERIFY_RECORD_REDACTED,
            StepState.REDACTED,
            "support_platform",
            "m1",
        ),
        _step(
            7,
            Phase.VERIFICATION,
            Operation.VERIFY_RECORD_PRESENT,
            StepState.PRESENT,
            "security_service",
            "a1",
        ),
    ]
    return _case("INCOMPLETE", steps, [f1, f2])


def test_nothing_deleted_changes_nothing() -> None:
    case = _incomplete_two_systems()
    assert apply_deletion(case, frozenset()) is case


def test_deleting_one_system_resolves_only_its_findings() -> None:
    after = apply_deletion(_incomplete_two_systems(), frozenset({"search_service"}))
    assert after.status == "INCOMPLETE"
    assert [f.system_id for f in after.findings] == ["support_platform"]
    assert [s.step_no for s in after.steps] == list(range(1, len(after.steps) + 1))
    phases = [s.phase for s in after.steps]
    assert phases == sorted(phases, key=list(Phase).index)  # findings, remediation, verification
    assert not [
        s
        for s in after.steps
        if s.phase is not Phase.VERIFICATION and s.system_id == "search_service"
    ]


def test_deleting_every_failing_system_completes_with_verification_only() -> None:
    after = apply_deletion(
        _incomplete_two_systems(), frozenset({"search_service", "support_platform"})
    )
    assert after.status == "COMPLETE"
    assert {s.phase for s in after.steps} == {Phase.VERIFICATION}
    removed_ops = {
        s.operation for s in after.steps if s.system_id in {"search_service", "support_platform"}
    }
    assert removed_ops == {Operation.VERIFY_RECORD_ABSENT}  # a deleted record is verified absent
    assert all(
        s.state is StepState.ABSENT for s in after.steps if s.system_id != "security_service"
    )


def test_losing_a_retained_record_breaks_the_case_even_if_it_was_complete() -> None:
    complete = _case(
        "COMPLETE",
        [
            _step(
                1,
                Phase.VERIFICATION,
                Operation.VERIFY_RECORD_PRESENT,
                StepState.PRESENT,
                "security_service",
                "a1",
                "evidence_2",
            ),
        ],
        [],
    )
    removed = frozenset({"security_service"})
    assert retention_lost(complete, removed)
    assert apply_deletion(complete, removed).status == "INCOMPLETE"
    assert not retention_lost(complete, frozenset({"search_service"}))


def test_uncertain_cases_are_never_promoted_to_complete() -> None:
    case = _incomplete_two_systems()
    uncertain = _case(
        "INCOMPLETE", list(case.steps), list(case.findings), uncertain=("conflict:x",)
    )
    after = apply_deletion(uncertain, frozenset({"search_service", "support_platform"}))
    assert after.status == "INCOMPLETE"


def test_non_deletion_requests_are_untouched() -> None:
    case = _case("NOT_APPLICABLE", [], [])
    assert apply_deletion(case, frozenset(SYSTEMS)) is case


# ------------------------------------------------------------------------------- request parsing
def test_request_parsing_rejects_unknown_systems_and_bad_numbers() -> None:
    ok = parse_request(b'{"removed":["search_service"],"llm_cases":5}', SYSTEMS, 40)
    assert ok == RunRequest(frozenset({"search_service"}), 5)
    for body in (
        b"not json",
        b"[]",
        b'{"removed":"search_service"}',
        b'{"removed":["nope"]}',
        b'{"llm_cases":41}',
        b'{"llm_cases":-1}',
        b'{"llm_cases":true}',
        b'{"llm_cases":1.5}',
    ):
        with pytest.raises(ValueError):
            parse_request(body, SYSTEMS, 40)


# ------------------------------------------------------------------------------------- the server
class _Harness:
    def __init__(self, tmp_path: Path, run: Any = None) -> None:
        page = tmp_path / "page.html"
        page.write_text("<title>console</title>", encoding="utf-8")
        self.calls: list[RunRequest] = []

        def default_run(request: RunRequest, emit: Emit) -> dict[str, Any]:
            self.calls.append(request)
            emit("audit", "one")
            emit("model", "two")
            return {"ok": True, "removed": sorted(request.removed)}

        self.server = LiveServer(
            page=page,
            status=lambda: {"live": True},
            run=run or default_run,
            systems=SYSTEMS,
            max_llm=10,
            host="127.0.0.1",
            port=0,
        )
        self.port = self.server.address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(
            method, path, body=body, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        )
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def post(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> tuple[int, bytes]:
        raw = json.dumps(payload).encode()
        return self.request(
            "POST", "/api/run", raw, {"Content-Length": str(len(raw)), **(headers or {})}
        )

    def close(self) -> None:
        self.server.close()


@pytest.fixture
def harness(tmp_path: Path):  # type: ignore[no-untyped-def]
    h = _Harness(tmp_path)
    yield h
    h.close()


def test_serves_the_page_and_status(harness: _Harness) -> None:
    assert harness.request("GET", "/") == (200, b"<title>console</title>")
    status, body = harness.request("GET", "/api/status")
    assert status == 200 and json.loads(body) == {"live": True}
    assert harness.request("GET", "/nope")[0] == 404


def test_a_run_streams_progress_then_the_data(harness: _Harness) -> None:
    status, body = harness.post({"removed": ["search_service"], "llm_cases": 3})
    lines = [json.loads(line) for line in body.decode().splitlines()]
    assert status == 200
    assert [m["stage"] for m in lines[:2]] == ["audit", "model"]
    assert lines[-1]["done"] is True and lines[-1]["data"] == {
        "ok": True,
        "removed": ["search_service"],
    }
    assert harness.calls == [RunRequest(frozenset({"search_service"}), 3)]


def test_a_cross_origin_request_is_refused_before_anything_runs(harness: _Harness) -> None:
    status, _ = harness.post({"removed": [], "llm_cases": 0}, {"Origin": "https://evil.example"})
    assert status == 403 and harness.calls == []
    same = f"http://127.0.0.1:{harness.port}"
    assert harness.post({"removed": [], "llm_cases": 0}, {"Origin": same})[0] == 200


def test_bad_bodies_are_refused(harness: _Harness) -> None:
    assert harness.post({"removed": ["nope"], "llm_cases": 0})[0] == 400
    assert harness.post({"removed": [], "llm_cases": 11})[0] == 400  # above this server's cap
    assert harness.request("POST", "/api/run", b"", {"Content-Length": "0"})[0] == 400
    big = b"x" * 5000
    assert harness.request("POST", "/api/run", big, {"Content-Length": "5000"})[0] == 400
    assert harness.calls == []


def test_only_one_run_at_a_time(tmp_path: Path) -> None:
    gate, started = threading.Event(), threading.Event()

    def slow(request: RunRequest, emit: Emit) -> dict[str, Any]:
        started.set()
        gate.wait(5)
        return {}

    h = _Harness(tmp_path, run=slow)
    try:
        first = threading.Thread(target=lambda: h.post({"removed": [], "llm_cases": 0}))
        first.start()
        assert started.wait(5)
        assert h.post({"removed": [], "llm_cases": 0})[0] == 409
        gate.set()
        first.join(5)
        assert h.post({"removed": [], "llm_cases": 0})[0] == 200  # free again afterwards
    finally:
        gate.set()
        h.close()


def test_failures_report_the_kind_not_the_details(tmp_path: Path) -> None:
    def boom(request: RunRequest, emit: Emit) -> dict[str, Any]:
        if request.llm_cases:
            raise AnalysisError("this deletion leaves nothing to predict")
        raise RuntimeError("secret-token-123 leaked in a message")

    h = _Harness(tmp_path, run=boom)
    try:
        _, body = h.post({"removed": [], "llm_cases": 1})
        assert json.loads(body.decode().splitlines()[-1]) == {
            "error": "this deletion leaves nothing to predict"
        }
        _, body = h.post({"removed": [], "llm_cases": 0})
        message = json.loads(body.decode().splitlines()[-1])["error"]
        assert "secret-token" not in message and "RuntimeError" in message
    finally:
        h.close()
