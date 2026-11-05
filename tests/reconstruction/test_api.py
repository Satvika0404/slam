from conftest import change, current, observation, request, source
from slam.contracts import EvidenceBundle, RequestIntent
from slam.reconstruction import reconstruct


def test_reconstruct_returns_grounded_case_context() -> None:
    record = observation("record")
    bundle = EvidenceBundle(
        sources=(source(),),
        current_identities=(current(),),
        identity_changes=(change(),),
        observations=(record,),
    )
    context = reconstruct(request(), bundle)
    assert context.request_intent is RequestIntent.DELETION
    assert context.subject_id == "user_1"
    assert context.eligible_observation_ids == (record.observation_id,)
    assert context.resource_states[0].supporting_evidence_ids == ("evidence_1",)


def test_non_deletion_returns_no_resource_decision() -> None:
    bundle = EvidenceBundle(
        current_identities=(current(),),
        identity_changes=(change(),),
        observations=(observation("record"),),
    )
    context = reconstruct(request(text="Please export a copy of my data"), bundle)
    assert context.request_intent is RequestIntent.NON_DELETION
    assert context.resource_states == ()
    assert context.active_flows == ()


def test_reconstruction_is_deterministic_under_bundle_shuffling() -> None:
    first = observation("first", resource="account_1")
    second = observation("second", resource="search_1", system="search_service")
    common = {
        "sources": (source(),),
        "current_identities": (current(),),
        "identity_changes": (change(),),
    }
    forward = EvidenceBundle(**common, observations=(first, second))
    reverse = EvidenceBundle(**common, observations=(second, first))
    assert (
        reconstruct(request(), forward).model_dump_json()
        == reconstruct(request(), reverse).model_dump_json()
    )


def test_ingestion_error_and_uncertain_observation_reach_coverage() -> None:
    from slam.contracts import IngestionIssue, IssueSeverity

    uncertain = observation("uncertain", fields={"uncertain": True})
    bundle = EvidenceBundle(
        sources=(source(),),
        current_identities=(current(),),
        identity_changes=(change(),),
        observations=(uncertain,),
        issues=(
            IngestionIssue(
                severity=IssueSeverity.ERROR,
                code="PARSER_FAILED",
                message="failed safely",
                source_id="evidence_1",
            ),
        ),
    )
    context = reconstruct(request(), bundle)
    assert any("PARSER_FAILED" in issue for issue in context.coverage_issues)
    assert any("uncertain" in issue for issue in context.coverage_issues)
