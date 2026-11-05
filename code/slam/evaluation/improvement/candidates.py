"""Candidate evaluation and isolated, fixed-command Docker regression checks."""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_PATHS = (
    "code/slam/evaluation/improvement/",
    "tests/evaluation/",
)
_DIFF_PATH = re.compile(r"^(?:a|b)/([A-Za-z0-9_./-]+)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True, slots=True)
class CandidateMetrics:
    cases: int
    false_complete_count: int
    status_accuracy: float
    step_accuracy: float
    defect_detection_precision: float
    defect_detection_recall: float
    latency_ms: int
    fixture_set_id: str
    scenario_ids: tuple[str, ...] = ()
    api_calls: int = 0
    cost_usd: float | None = 0.0
    regression_count: int | None = None
    label: str = "synthetic"

    def __post_init__(self) -> None:
        if self.cases < 0 or self.false_complete_count < 0:
            raise ValueError("metric counts cannot be negative")
        if self.false_complete_count > self.cases:
            raise ValueError("false COMPLETE count cannot exceed evaluated cases")
        if self.regression_count is not None and self.regression_count < 0:
            raise ValueError("regression_count cannot be negative")
        if self.latency_ms < 0 or self.api_calls < 0:
            raise ValueError("latency and API call counts cannot be negative")
        if not self.fixture_set_id:
            raise ValueError("fixture_set_id is required to establish identical evaluation inputs")
        for metric in (
            self.status_accuracy,
            self.step_accuracy,
            self.defect_detection_precision,
            self.defect_detection_recall,
        ):
            if not math.isfinite(metric) or not 0.0 <= metric <= 1.0:
                raise ValueError("accuracy and recall metrics must be finite values in [0, 1]")
        if self.cost_usd is not None and (not math.isfinite(self.cost_usd) or self.cost_usd < 0):
            raise ValueError("cost_usd must be non-negative and finite when known")
        if tuple(sorted(set(self.scenario_ids))) != self.scenario_ids:
            raise ValueError("scenario_ids must be unique and deterministically sorted")
        if len(self.scenario_ids) != self.cases:
            raise ValueError("scenario_ids must identify every case in the evaluation denominator")
        if self.label not in {"synthetic", "real"}:
            raise ValueError("label must be synthetic or real")

    @property
    def false_complete_rate(self) -> float | None:
        return self.false_complete_count / self.cases if self.cases else None


@dataclass(frozen=True, slots=True)
class CandidateResult:
    accepted: bool
    decision: str
    baseline: CandidateMetrics
    candidate: CandidateMetrics
    reproduced_failure_fixed: bool
    checks_passed: bool
    within_budget: bool
    attempt: int
    patch_paths: tuple[str, ...] = ()
    check_output: str = ""


@dataclass(frozen=True, slots=True)
class CandidateSuiteResult:
    development: CandidateResult
    held_out: CandidateResult
    accepted: bool
    decision: str


@dataclass(frozen=True, slots=True)
class ScenarioPrediction:
    status: str
    steps: tuple[str, ...] = ()
    detected_defects: tuple[str, ...] = ()


def score_scenarios(
    *,
    predictions: dict[str, ScenarioPrediction],
    expected_statuses: dict[str, str],
    expected_steps: dict[str, tuple[str, ...]],
    expected_defects: dict[str, tuple[str, ...]],
    fixture_set_id: str,
    latency_ms: int,
    baseline_predictions: dict[str, ScenarioPrediction] | None = None,
    api_calls: int = 0,
    cost_usd: float | None = 0.0,
    label: str = "synthetic",
) -> CandidateMetrics:
    """Score predictions against a separate oracle mapping; only predictions go to the agent."""
    case_ids = set(expected_statuses)
    if not case_ids or set(predictions) != case_ids:
        raise ValueError("prediction and expected case IDs must match and be non-empty")
    if set(expected_steps) != case_ids or set(expected_defects) != case_ids:
        raise ValueError("all reference maps must use the same case IDs")
    if baseline_predictions is not None and set(baseline_predictions) != case_ids:
        raise ValueError("baseline and candidate predictions must use identical case IDs")
    status_correct = sum(predictions[case].status == expected_statuses[case] for case in case_ids)
    predicted_steps = {(case, step) for case in case_ids for step in predictions[case].steps}
    expected_step_pairs = {(case, step) for case in case_ids for step in expected_steps[case]}
    step_denominator = max(len(predicted_steps), len(expected_step_pairs))
    step_accuracy = (
        len(predicted_steps & expected_step_pairs) / step_denominator if step_denominator else 1.0
    )
    predicted_defects = {
        (case, defect) for case in case_ids for defect in predictions[case].detected_defects
    }
    expected_defect_pairs = {
        (case, defect) for case in case_ids for defect in expected_defects[case]
    }
    defect_tp = len(predicted_defects & expected_defect_pairs)
    defect_precision = (
        defect_tp / len(predicted_defects)
        if predicted_defects
        else float(not expected_defect_pairs)
    )
    defect_recall = (
        defect_tp / len(expected_defect_pairs)
        if expected_defect_pairs
        else float(not predicted_defects)
    )
    false_complete_count = sum(
        predictions[case].status == "COMPLETE" and expected_statuses[case] != "COMPLETE"
        for case in case_ids
    )
    regression_count = 0
    if baseline_predictions is not None:
        for case in case_ids:
            baseline = baseline_predictions[case]
            candidate = predictions[case]
            baseline_status_ok = baseline.status == expected_statuses[case]
            candidate_status_ok = candidate.status == expected_statuses[case]
            baseline_step_f1 = _set_f1(baseline.steps, expected_steps[case])
            candidate_step_f1 = _set_f1(candidate.steps, expected_steps[case])
            baseline_defect_f1 = _set_f1(baseline.detected_defects, expected_defects[case])
            candidate_defect_f1 = _set_f1(candidate.detected_defects, expected_defects[case])
            if (
                (baseline_status_ok and not candidate_status_ok)
                or candidate_step_f1 < baseline_step_f1
                or candidate_defect_f1 < baseline_defect_f1
                or (candidate.status == "COMPLETE" and expected_statuses[case] != "COMPLETE")
            ):
                regression_count += 1
    return CandidateMetrics(
        cases=len(case_ids),
        false_complete_count=false_complete_count,
        status_accuracy=status_correct / len(case_ids),
        step_accuracy=step_accuracy,
        defect_detection_precision=defect_precision,
        defect_detection_recall=defect_recall,
        latency_ms=latency_ms,
        fixture_set_id=fixture_set_id,
        scenario_ids=tuple(sorted(case_ids)),
        api_calls=api_calls,
        cost_usd=cost_usd,
        regression_count=regression_count if baseline_predictions is not None else None,
        label=label,
    )


def _set_f1(predicted: tuple[str, ...], expected: tuple[str, ...]) -> float:
    predicted_set = set(predicted)
    expected_set = set(expected)
    true_positive = len(predicted_set & expected_set)
    if not predicted_set and not expected_set:
        return 1.0
    precision = true_positive / len(predicted_set) if predicted_set else 0.0
    recall = true_positive / len(expected_set) if expected_set else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def validate_patch_paths(patch: str) -> tuple[str, ...]:
    """Reject a patch unless every touched path is in an owner-approved area."""
    paths: set[str] = set()
    for line in patch.splitlines():
        if not (line.startswith("+++ ") or line.startswith("--- ")):
            continue
        raw = line[4:].split("\t", 1)[0]
        if raw == "/dev/null":
            continue
        match = _DIFF_PATH.fullmatch(raw)
        if match is None:
            raise ValueError(f"unsafe patch path: {raw}")
        path = match.group(1)
        parts = Path(path).parts
        if path.startswith("/") or ".." in parts or ":" in path:
            raise ValueError(f"unsafe patch path: {raw}")
        if not path.startswith(_ALLOWED_PATHS):
            raise ValueError(f"patch changes a path outside the allowlist: {path}")
        paths.add(path)
    if not paths:
        raise ValueError("patch contains no allowlisted file changes")
    return tuple(sorted(paths))


def evaluate_candidate(
    *,
    baseline: CandidateMetrics,
    candidate: CandidateMetrics,
    reproduced_failure_fixed: bool,
    checks_passed: bool,
    within_budget: bool,
    attempt: int,
    max_attempts: int = 3,
    patch_paths: tuple[str, ...] = (),
    check_output: str = "",
) -> CandidateResult:
    """Apply deterministic acceptance rules; held-out false-COMPLETE cannot worsen."""
    if not 1 <= max_attempts <= 3 or not 1 <= attempt <= max_attempts:
        raise ValueError("repair attempts must be within the declared limit of at most 3")
    if baseline.label != candidate.label:
        raise ValueError("baseline and candidate must use the same scenario-set label")
    if baseline.fixture_set_id != candidate.fixture_set_id:
        raise ValueError("baseline and candidate must use identical fixture sets")
    if baseline.scenario_ids != candidate.scenario_ids:
        raise ValueError("baseline and candidate must use identical scenario IDs")
    if baseline.cases != candidate.cases:
        raise ValueError("baseline and candidate must have the same evaluation denominator")
    no_false_complete_regression = (
        candidate.false_complete_count <= baseline.false_complete_count
        and candidate.false_complete_rate is not None
        and baseline.false_complete_rate is not None
        and candidate.false_complete_rate <= baseline.false_complete_rate
    )
    accepted = (
        reproduced_failure_fixed
        and checks_passed
        and within_budget
        and no_false_complete_regression
        and candidate.regression_count == 0
    )
    decision = "accepted_for_review" if accepted else "rejected_or_blocked"
    return CandidateResult(
        accepted,
        decision,
        baseline,
        candidate,
        reproduced_failure_fixed,
        checks_passed,
        within_budget,
        attempt,
        tuple(sorted(set(patch_paths))),
        check_output[-4000:],
    )


def evaluate_candidate_sets(
    *,
    development_baseline: CandidateMetrics,
    development_candidate: CandidateMetrics,
    held_out_baseline: CandidateMetrics,
    held_out_candidate: CandidateMetrics,
    reproduced_failure_fixed: bool,
    checks_passed: bool,
    within_budget: bool,
    attempt: int,
) -> CandidateSuiteResult:
    """Require distinct dev/held-out inputs and reject regressions on either set."""
    if development_baseline.label != "synthetic" or held_out_baseline.label != "synthetic":
        raise ValueError("the default improvement suite accepts synthetic sets only")
    dev_fixture_ids = set(development_baseline.scenario_ids)
    held_fixture_ids = set(held_out_baseline.scenario_ids)
    if dev_fixture_ids & held_fixture_ids:
        raise ValueError("development and held-out scenario IDs must be disjoint")
    if development_baseline.fixture_set_id == held_out_baseline.fixture_set_id:
        raise ValueError("development and held-out fixture set IDs must differ")
    development = evaluate_candidate(
        baseline=development_baseline,
        candidate=development_candidate,
        reproduced_failure_fixed=reproduced_failure_fixed,
        checks_passed=checks_passed,
        within_budget=within_budget,
        attempt=attempt,
    )
    held_out = evaluate_candidate(
        baseline=held_out_baseline,
        candidate=held_out_candidate,
        reproduced_failure_fixed=reproduced_failure_fixed,
        checks_passed=checks_passed,
        within_budget=within_budget,
        attempt=attempt,
    )
    accepted = development.accepted and held_out.accepted
    return CandidateSuiteResult(
        development,
        held_out,
        accepted,
        "accepted_for_review" if accepted else "rejected_or_blocked",
    )


def _copy_repair_workspace(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for filename in ("pyproject.toml", "uv.lock"):
        shutil.copy2(source / filename, destination / filename)
    for directory in ("code/slam", "tests/evaluation"):
        shutil.copytree(source / directory, destination / directory)


def _apply_unified_patch(checkout: Path, patch: str) -> None:
    """Apply text hunks without invoking a shell or a patch-provided executable."""
    lines = patch.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old_name = lines[index][4:].strip().split("\t", 1)[0]
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ValueError("malformed unified patch header")
        new_name = lines[index][4:].strip().split("\t", 1)[0]
        index += 1
        target_name = new_name if new_name != "/dev/null" else old_name
        target_path = target_name[2:] if target_name.startswith(("a/", "b/")) else target_name
        destination = (checkout / target_path).resolve()
        if checkout.resolve() not in destination.parents:
            raise ValueError("patch destination escapes disposable checkout")
        original = (
            []
            if old_name == "/dev/null"
            else destination.read_text(encoding="utf-8").splitlines(keepends=True)
        )
        output: list[str] = []
        cursor = 0
        while index < len(lines) and not lines[index].startswith(("--- ", "diff --git ")):
            header = _HUNK.match(lines[index])
            if header is None:
                index += 1
                continue
            old_start = int(header.group(1))
            new_start = int(header.group(3))
            if new_start > len(output) + (len(original) - cursor) + 1:
                raise ValueError("invalid unified patch hunk offset")
            prefix_end = max(0, old_start - 1)
            if prefix_end < cursor or prefix_end > len(original):
                raise ValueError("overlapping or invalid unified patch hunk")
            output.extend(original[cursor:prefix_end])
            cursor = prefix_end
            index += 1
            while index < len(lines) and lines[index][:1] in {" ", "+", "-", "\\"}:
                line = lines[index]
                if line.startswith("\\"):
                    index += 1
                    continue
                content = line[1:]
                if line.startswith((" ", "-")):
                    if cursor >= len(original) or original[cursor] != content:
                        raise ValueError("unified patch context does not match checkout")
                    if line.startswith(" "):
                        output.append(original[cursor])
                    cursor += 1
                if line.startswith("+"):
                    output.append(content)
                index += 1
        output.extend(original[cursor:])
        if new_name == "/dev/null":
            destination.unlink(missing_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("".join(output), encoding="utf-8", newline="")


def _docker_checks(checkout: Path, *, timeout_seconds: int) -> tuple[bool, str]:
    """Run a fixed offline test command; no candidate-provided command is executed."""
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
    }
    cache_volume = f"slam-repair-uv-{uuid.uuid4().hex}"
    started = time.monotonic()
    try:
        created = subprocess.run(
            ["docker", "volume", "create", "--name", cache_volume],
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if created.returncode:
            return False, "isolated Docker cache volume could not be created"
        copied = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=128m",
                "--mount",
                "type=volume,source=slam_uv-cache,target=/source,readonly",
                "--mount",
                f"type=volume,source={cache_volume},target=/target",
                "--entrypoint",
                "/bin/sh",
                "slam-dev:py311",
                "-c",
                "cp -a /source/. /target/",
            ],
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=max(1, timeout_seconds - int(time.monotonic() - started)),
            check=False,
        )
        if copied.returncode:
            return False, "isolated Docker dependency cache could not be prepared offline"
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=512m",
            "--tmpfs",
            "/opt/venv:rw,exec,nosuid,size=2g",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--mount",
            f"type=volume,source={cache_volume},target=/root/.cache/uv",
            "--mount",
            f"type=bind,source={checkout.resolve()},target=/workspace,readonly",
            "--workdir",
            "/workspace",
            "--entrypoint",
            "/bin/sh",
            "slam-dev:py311",
            "-c",
            "uv sync --frozen --offline && python -m pytest "
            "-p no:cacheprovider -q tests/evaluation",
        ]
        remaining = timeout_seconds - int(time.monotonic() - started)
        if remaining <= 0:
            return False, "candidate evaluation exceeded its time budget"
        result = subprocess.run(
            command,
            cwd=checkout,
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"isolated Docker check unavailable or timed out ({type(exc).__name__})"
    finally:
        subprocess.run(
            ["docker", "volume", "rm", "--force", cache_volume],
            env=clean_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, output[-4000:]


def evaluate_patch_in_isolation(
    *,
    repository: Path,
    patch: str,
    timeout_seconds: int = 600,
    check_runner: Callable[[Path, int], tuple[bool, str]] | None = None,
) -> tuple[bool, tuple[str, ...], str]:
    """Apply a reviewable diff to a disposable copy and run fixed Docker checks."""
    if not 1 <= timeout_seconds <= 1800:
        raise ValueError("timeout_seconds must be between 1 and 1800")
    paths = validate_patch_paths(patch)
    with tempfile.TemporaryDirectory(prefix="slam-repair-") as temporary:
        checkout = Path(temporary) / "checkout"
        _copy_repair_workspace(repository.resolve(), checkout)
        try:
            _apply_unified_patch(checkout, patch)
        except (OSError, UnicodeError, ValueError) as exc:
            return False, paths, f"candidate patch rejected ({type(exc).__name__})"
        started = time.monotonic()
        runner = check_runner or (lambda path, limit: _docker_checks(path, timeout_seconds=limit))
        passed, output = runner(checkout, timeout_seconds)
        if time.monotonic() - started > timeout_seconds:
            return False, paths, "candidate evaluation exceeded its time budget"
        return passed, paths, output[-4000:]
