"""Owner linking (L1/L2/L3) and absence inference, on an invented world.

Every system name, id format, activity type and time offset here is made up and appears nowhere
in the real dataset, so these tests prove the behaviour is learned from the data, not built in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from conftest import digest
from slam.contracts import (
    Activity,
    AuditRequest,
    ConfidenceClass,
    CurrentIdentity,
    EvidenceBundle,
    Observation,
    SourceKind,
    SourceRecord,
    SourceSpan,
)
from slam.reconstruction import linking, reconstruct, reconstruct_with_links
from slam.reconstruction.ownership import build_owner_index, owners_as_of

BASE = datetime(2026, 3, 1, tzinfo=UTC)
GROUP = ("PURGE_ENTRY", "ledger_service")


def email(n: int | str) -> str:
    return f"person{n}@mail.test"


def request(n: int, *, reported_offset_days: float | None = None) -> AuditRequest:
    reported = BASE + timedelta(days=n if reported_offset_days is None else reported_offset_days)
    return AuditRequest(
        case_id=f"c{n}",
        email=email(n),
        requested_at=reported - timedelta(days=1),
        reported_status="COMPLETE",
        reported_at=reported,
        audit_at=reported + timedelta(days=2),
        request_text="Please delete my account.",
    )


def identity(n: int | str) -> CurrentIdentity:
    return CurrentIdentity(
        user_id=f"u{n}",
        name=f"Person {n}",
        email=email(n),
        email_normalized=email(n),
        phone=f"+1555000{str(n).zfill(4)}",
        email_hash=digest(f"h{n}"),
        updated_at=BASE - timedelta(days=30),
        source_id="ids",
    )


def source(source_id: str, when: datetime) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        kind=SourceKind.JSON,
        origin="t",
        path=f"{source_id}.json",
        captured_at=when,
        sha256=digest(source_id),
        parse_status="parsed",
    )


def obs(
    label: str,
    resource: str,
    state: str = "PRESENT",
    *,
    who: int | None = None,
    category: str = "LEDGER_ENTRY",
    system: str = "ledger_service",
    src: str = "s1",
    when: datetime = BASE,
) -> Observation:
    ident = {"email": email(who)} if who is not None else {}
    return Observation(
        observation_id=digest(label),
        subject_hints=(email(who),) if who is not None else (),
        system_id=system,
        resource_id=resource,
        category=category,
        observed_state=state,
        effective_time=when,
        source_kind=SourceKind.JSON,
        identifiers=ident,
        fields={"evidence_nature": "observation", "source": {}},
        spans=(SourceSpan(source_id=src, json_path=f"$.{label}"),),
    )


def purge(activity_id: str, resource: str, when: datetime, kind: str = "PURGE_ENTRY") -> Activity:
    return Activity(
        activity_id=activity_id,
        activity_type=kind,
        occurred_at=when,
        system_id="ledger_service",
        resource_id=resource,
        reported_result="SUCCESS",
        attributes={"details": f"worker handled {resource}"},
    )


def world(
    labelled: int = 30,
    extra_acts: tuple[Activity, ...] = (),
    extra_obs: tuple[Observation, ...] = (),
) -> tuple[EvidenceBundle, list[AuditRequest]]:
    """`labelled` people each own one ledger entry explicitly and have a purge ~50-56 min before
    their report; a lone unlabelled person (n=100) has only the purge."""

    people = [*range(1, labelled + 1), 100]
    requests = [request(n) for n in people]
    observations = [obs(f"own{n}", f"ledger_{n}", who=n) for n in range(1, labelled + 1)]
    activities: list[Activity] = []
    for n in people:
        res = f"ledger_{n}"
        offset = 50 + (n % 7)
        activities.append(
            purge(f"a{n}", res, requests[people.index(n)].reported_at - timedelta(minutes=offset))
        )
    for j in range(40):  # decoys: other people's entries, purged far from any report
        activities.append(purge(f"d{j}", f"ledger_x{j}", BASE + timedelta(days=200 + j)))
    bundle = EvidenceBundle(
        sources=(source("s1", BASE), source("ids", BASE - timedelta(days=30))),
        current_identities=tuple(identity(n) for n in people),
        observations=(*observations, *extra_obs),
        activities=(*activities, *extra_acts),
    )
    return bundle, requests


def test_signature_is_learned_validated_and_used_for_an_unlabelled_person() -> None:
    bundle, requests = world()
    model = linking.fit(bundle, tuple(requests))
    assert [g.key for g in model.groups] == [GROUP]
    low, high = model.groups[0].window
    assert 48 <= low <= 52 and 56 <= high <= 58  # learned, not configured
    target = requests[-1]
    assert [a.resource_id for a in model.for_case(target.case_id).attributed] == ["ledger_100"]

    context = reconstruct_with_links(target, bundle, model)
    links = [link for link in context.identity_links if link.relationship == "owns_resource"]
    assert [(link.right_identifier, link.confidence, link.review_required) for link in links] == [
        ("ledger_100", ConfidenceClass.CORROBORATED, True)
    ]
    assert all(i in context.evidence_captured_at for i in links[0].evidence_ids)


def test_without_a_model_only_explicit_ownership_applies() -> None:
    bundle, requests = world()
    context = reconstruct(requests[-1], bundle)
    assert [link for link in context.identity_links if link.relationship == "owns_resource"] == []
    explicit = reconstruct(requests[0], bundle)
    exact = [link for link in explicit.identity_links if link.relationship == "owns_resource"]
    assert [(link.right_identifier, link.confidence) for link in exact] == [
        ("ledger_1", ConfidenceClass.EXACT)
    ]


def test_noise_groups_fail_validation_and_are_never_used() -> None:
    noise = tuple(
        purge(
            f"t{n}",
            f"ledger_{n}",
            BASE + timedelta(days=n, minutes=(n * 4177) % 1400 - 700),
            "TOUCH_ENTRY",
        )
        for n in range(1, 31)
    )
    decoys = tuple(  # unowned entries touched at random times, as in a real routine job
        purge(
            f"y{j}",
            f"ledger_y{j}",
            BASE + timedelta(days=1 + j % 30, minutes=(j * 977) % 1400 - 700),
            "TOUCH_ENTRY",
        )
        for j in range(120)
    )
    bundle, requests = world(extra_acts=(*noise, *decoys))
    keys = [g.key for g in linking.fit(bundle, tuple(requests)).groups]
    assert ("TOUCH_ENTRY", "ledger_service") not in keys and GROUP in keys


def test_ambiguity_is_reported_as_candidates_never_attributed() -> None:
    rival = purge("rival", "ledger_rival", request(100).reported_at - timedelta(minutes=53))
    bundle, requests = world(extra_acts=(rival,))
    case = linking.fit(bundle, tuple(requests)).for_case("c100")
    assert case.attributed == ()
    assert {a.resource_id for a in case.candidates} == {"ledger_100", "ledger_rival"}
    context = reconstruct_with_links(requests[-1], bundle, linking.fit(bundle, tuple(requests)))
    assert {
        link.confidence for link in context.identity_links if link.relationship == "owns_resource"
    } == {ConfidenceClass.CANDIDATE}


def test_resources_explicitly_owned_by_someone_else_are_eliminated() -> None:
    rival = purge("rival", "ledger_other", request(100).reported_at - timedelta(minutes=53))
    other = obs("other", "ledger_other", who=1)  # explicitly person 1's, so not person 100's
    bundle, requests = world(extra_acts=(rival,), extra_obs=(other,))
    case = linking.fit(bundle, tuple(requests)).for_case("c100")
    assert [a.resource_id for a in case.attributed] == ["ledger_100"]


def test_a_resource_claimed_by_two_people_is_withdrawn_from_both() -> None:
    bundle, requests = world()
    twin = request(101, reported_offset_days=100)  # reported at the same moment as person 100
    twin = twin.model_copy(
        update={"reported_at": requests[-1].reported_at, "audit_at": requests[-1].audit_at}
    )
    bundle = bundle.model_copy(
        update={"current_identities": (*bundle.current_identities, identity(101))}
    )
    model = linking.fit(bundle, (*requests, twin))
    assert model.for_case("c100").attributed == () and model.for_case("c101").attributed == ()


def test_activity_after_the_cutoff_is_never_a_candidate() -> None:
    bundle, requests = world()
    early = requests[-1].model_copy(
        update={"audit_at": requests[-1].reported_at - timedelta(minutes=60)}
    )
    model = linking.fit(bundle, (*requests[:-1], early))
    assert model.for_case("c100").attributed == ()


def test_fit_is_deterministic_under_row_shuffling() -> None:
    bundle, requests = world()
    shuffled = bundle.model_copy(
        update={
            "activities": tuple(reversed(bundle.activities)),
            "observations": tuple(reversed(bundle.observations)),
        }
    )
    a, b = linking.fit(bundle, tuple(requests)), linking.fit(shuffled, tuple(reversed(requests)))
    assert a.groups == b.groups and a.cases == b.cases


def test_owner_closure_attaches_identifier_less_evidence_of_an_owned_resource() -> None:
    later = obs("lookup", "ledger_1", "NOT_FOUND", src="s2", when=BASE + timedelta(days=1, hours=1))
    bundle, requests = world(extra_obs=(later,))
    bundle = bundle.model_copy(
        update={"sources": (*bundle.sources, source("s2", BASE + timedelta(days=1, hours=1)))}
    )
    context = reconstruct(requests[0], bundle)
    assert later.observation_id in context.eligible_observation_ids
    state = next(s for s in context.resource_states if s.resource_id == "ledger_1")
    assert state.state == "NOT_FOUND"


def test_a_name_alone_never_creates_ownership() -> None:
    namesake = obs("n", "ledger_n").model_copy(update={"identifiers": {"name": "Person 1"}})
    bundle, _ = world(extra_obs=(namesake,))
    assert "ledger_n" not in build_owner_index(bundle)


def test_a_shared_resource_is_nobodys_alone() -> None:
    both = obs("both", "ledger_shared", who=1).model_copy(
        update={"identifiers": {"email": email(1)}, "subject_hints": (email(1), email(2))}
    )
    bundle, _ = world(extra_obs=(both,))
    index = build_owner_index(bundle)
    assert owners_as_of(index, "ledger_shared", BASE + timedelta(days=400)) == {"u1", "u2"}


def test_absence_is_proven_by_the_latest_complete_snapshot_lacking_the_resource() -> None:
    bundle, requests = world()

    def scope(label: str, src: str) -> Observation:
        return obs(label, f"snapshot_scope:{src}", "SCOPED", category="SNAPSHOT_SCOPE", src=src)

    listing = obs("row", "ledger_2", who=2, src="snapA")
    bundle = bundle.model_copy(
        update={
            "sources": (
                *bundle.sources,
                source("snapA", BASE + timedelta(days=99)),
            ),
            "observations": (*bundle.observations, scope("scopeA", "snapA"), listing),
        }
    )
    # person 100 reports on day 100; snapA (day 99) lists ledger_2 but not ledger_100
    context = reconstruct_with_links(requests[-1], bundle, linking.fit(bundle, tuple(requests)))
    absent = [s for s in context.resource_states if s.resource_id == "ledger_100"]
    assert [(s.state, s.supporting_evidence_ids, s.category, s.uncertain) for s in absent] == [
        ("ABSENT", ("snapA",), "LEDGER_ENTRY", False)
    ]
    # a newer complete snapshot that lists it overrides: the record is present, not absent
    relisted = obs("row100", "ledger_100", who=100, src="snapB")
    newer = bundle.model_copy(
        update={
            "sources": (*bundle.sources, source("snapB", BASE + timedelta(days=100, hours=1))),
            "observations": (*bundle.observations, scope("scopeB", "snapB"), relisted),
        }
    )
    context = reconstruct_with_links(requests[-1], newer, linking.fit(newer, tuple(requests)))
    assert [s.state for s in context.resource_states if s.resource_id == "ledger_100"] == [
        "PRESENT"
    ]


def test_a_learned_status_result_agreement_breaks_timing_ties() -> None:
    """Every labelled COMPLETE case here pairs with SUCCESS, so a FAILED rival is not theirs."""

    rival = purge("rival", "ledger_rival", request(100).reported_at - timedelta(minutes=53))
    failed = rival.model_copy(update={"reported_result": "FAILED"})
    bundle, requests = world(extra_acts=(failed,))
    model = linking.fit(bundle, tuple(requests))
    assert dict(model.groups[0].agree) == {"COMPLETE": "SUCCESS"}  # learned, not configured
    assert [a.resource_id for a in model.for_case("c100").attributed] == ["ledger_100"]

    same = rival  # a rival with the *same* result still cannot be told apart
    bundle, requests = world(extra_acts=(same,))
    assert linking.fit(bundle, tuple(requests)).for_case("c100").attributed == ()
