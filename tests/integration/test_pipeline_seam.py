"""Seam S1/S3 on the real corpus: ingest -> reconstruct -> plan -> export -> validate.

Skipped when ``dataset/`` is absent (it is gitignored). Without Tesseract the screenshots fail
explicitly, so the thresholds below hold in the Docker image and are lenient on the host.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from slam.contracts import DeletionStatus

DATASET = Path(__file__).resolve().parents[2] / "dataset"
pytestmark = pytest.mark.skipif(
    not (DATASET / "deletion_requests.csv").exists(), reason="dataset/ not present"
)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    from slam.ingestion.api import ingest, load_requests
    from slam.pipeline import answer_cases

    bundle = ingest(DATASET)
    requests = load_requests(DATASET)
    answers, failures = answer_cases(requests, bundle)
    return bundle, requests, answers, failures


def test_every_request_gets_a_supported_answer(world) -> None:  # type: ignore[no-untyped-def]
    _, requests, answers, failures = world
    assert not failures and len(answers) == len(requests) == 518
    assert all(a.deletion_status is not None for a in answers)


def test_only_non_deletion_requests_are_not_applicable(world) -> None:  # type: ignore[no-untyped-def]
    _, _, answers, _ = world
    na = [a for a in answers if a.deletion_status is DeletionStatus.NOT_APPLICABLE]
    assert 0 < len(na) <= 20 and all(a.steps == () for a in na)


def test_pipeline_output_is_valid_and_deterministic(world, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from slam.pipeline import run

    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    one = run(DATASET, first)
    two = run(DATASET, second)
    assert one.ok and two.ok and first.read_bytes() == second.read_bytes()


def test_public_samples_never_produce_a_false_complete() -> None:
    from slam.pipeline import evaluate_samples

    _, metrics = evaluate_samples(DATASET)
    assert metrics.false_complete_count == 0
    assert metrics.status_accuracy >= 0.85
