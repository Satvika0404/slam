from datetime import UTC, datetime

from conftest import change, current, request
from slam.contracts import EvidenceBundle
from slam.reconstruction.identity import resolve_identity


def test_historical_email_resolves_to_current_subject_with_provenance() -> None:
    bundle = EvidenceBundle(
        current_identities=(current(),),
        identity_changes=(change(),),
    )
    result = resolve_identity(request(), bundle)
    assert result.subject_id == "user_1"
    assert "old@example.test" in result.match_values
    historical = [link for link in result.links if link.right_identifier == "old@example.test"]
    assert historical and historical[0].valid_to == datetime(2026, 1, 5, tzinfo=UTC)
    assert historical[0].evidence_ids == ("audit_1",)


def test_similar_people_are_not_merged_without_exact_corroboration() -> None:
    bundle = EvidenceBundle(current_identities=(current(email="other@example.test"),))
    result = resolve_identity(request(email="othar@example.test"), bundle)
    assert result.subject_id is None
    assert result.links == ()
    assert result.coverage_issues


def test_multiple_exact_subjects_are_an_explicit_conflict() -> None:
    bundle = EvidenceBundle(
        current_identities=(
            current(user_id="user_1", email="same@example.test", source_id="identity_1"),
            current(user_id="user_2", email="same@example.test", source_id="identity_2"),
        )
    )
    result = resolve_identity(request(email="same@example.test"), bundle)
    assert result.subject_id is None
    assert "multiple subjects" in result.conflicts[0]


def test_consecutive_changes_create_bounded_identifier_intervals() -> None:
    bundle = EvidenceBundle(
        current_identities=(current(email="third@example.test"),),
        identity_changes=(
            change(old="first@example.test", new="second@example.test", audit_id="audit_1"),
            change(
                old="second@example.test",
                new="third@example.test",
                at=datetime(2026, 1, 15, tzinfo=UTC),
                audit_id="audit_2",
            ),
        ),
    )
    result = resolve_identity(request(email="first@example.test"), bundle)
    second = next(
        link
        for link in result.links
        if link.relationship == "changed_email"
        and link.right_identifier == "second@example.test"
    )
    assert second.valid_from == datetime(2026, 1, 5, tzinfo=UTC)
    assert second.valid_to == datetime(2026, 1, 15, tzinfo=UTC)
