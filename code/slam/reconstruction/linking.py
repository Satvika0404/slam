"""Tier L3: attribute resources with no explicit owner by a learned timing signature.

Some resources carry no identifier at all (a deleted account, an anonymized profile) and are
known only from worker activities, which name a resource but never a person. What *is* shared
is timing: a deletion run performs each kind of operation at a characteristic offset from the
moment the case was reported.

Nothing about that signature is built in. ``LinkModel.fit`` learns it from the data:

1. A *labelled pair* is (request, activity) where the activity's resource is explicitly owned
   (tier L1) by that request's subject.
2. Pairs are grouped by ``(activity_type, target_system)`` and each group's offset window is a
   robust quantile range of its own pairs.
3. A group is *enabled* only if it passes two-fold held-out validation: a window learned on one
   half must attribute the other half with **zero wrong** attributions and resolve at least
   ``MIN_RESOLVED`` of it, over at least ``MIN_PAIRS`` pairs. Noisy groups (routine syncs,
   cache refreshes) fail this automatically and are never used.
4. For a subject with no owned resource in an enabled group, the candidates are that group's
   activities inside the window **minus every resource owned by someone else**. Exactly one
   distinct candidate is attributed (tier L3, ``CORROBORATED``); several are reported only as
   ``CANDIDATE`` links; none means nothing is claimed.
5. A resource claimed by two subjects is withdrawn from both.

Everything is deterministic and uses only activities at or before each request's ``audit_at``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from slam.contracts import Activity, AuditRequest, EvidenceBundle

from .identity import resolve_identity
from .ownership import OwnerIndex, build_owner_index, owned_by, owners_as_of

MIN_PAIRS = 20  # smallest group that can be validated
MIN_RESOLVED = 0.5  # fraction of held-out pairs that must be attributed correctly
AGREE_PURITY = 0.95  # share of a status's pairs one result must cover to become a filter
AGREE_MIN = 5  # fewest pairs a status needs before an agreement can be learned
_TAIL = 0.02  # quantile tails trimmed from each side of a window
_MARGIN_MINUTES = 1.0

GroupKey = tuple[str, str]  # (activity_type, target system)


@dataclass(frozen=True, slots=True)
class Attribution:
    resource_id: str
    system_id: str
    group: GroupKey
    activity_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroupModel:
    key: GroupKey
    window: tuple[float, float]  # minutes before reported_at
    pairs: int
    resolved: float
    # request.reported_status -> the activity result that (almost) always accompanies it
    agree: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CaseLinks:
    attributed: tuple[Attribution, ...] = ()
    candidates: tuple[Attribution, ...] = ()


@dataclass(frozen=True, slots=True)
class LinkModel:
    owner_index: OwnerIndex
    groups: tuple[GroupModel, ...] = ()
    cases: dict[str, CaseLinks] = field(default_factory=dict)

    def for_case(self, case_id: str) -> CaseLinks:
        return self.cases.get(case_id, CaseLinks())


@dataclass(frozen=True, slots=True)
class _Pair:
    case_id: str
    resource_id: str
    offset: float
    status: str
    result: str | None


def _offset(request: AuditRequest, activity: Activity) -> float:
    return (request.reported_at - activity.occurred_at).total_seconds() / 60.0


def _learn_agreement(pairs: list[_Pair]) -> dict[str, str]:
    """Which activity result accompanies each reported status, learned from labelled pairs.

    A workflow's claim ("COMPLETE", "NOT_STARTED") and its activity result ("SUCCESS", "FAILED")
    tend to agree. A status is only mapped when one result covers at least ``AGREE_PURITY`` of
    its pairs, so an uninformative group simply learns nothing and filters nothing.
    """

    seen: dict[str, Counter[str]] = defaultdict(Counter)
    for pair in pairs:
        if pair.result:
            seen[pair.status][pair.result] += 1
    learned: dict[str, str] = {}
    for status, counts in sorted(seen.items()):
        result, top = counts.most_common(1)[0]
        if sum(counts.values()) >= AGREE_MIN and top / sum(counts.values()) >= AGREE_PURITY:
            learned[status] = result
    return learned


def _window(offsets: list[float]) -> tuple[float, float]:
    ordered = sorted(offsets)
    low = ordered[int(_TAIL * (len(ordered) - 1))]
    high = ordered[int((1 - _TAIL) * (len(ordered) - 1))]
    return low - _MARGIN_MINUTES, high + _MARGIN_MINUTES


def _candidates(
    pool: list[Activity],
    request: AuditRequest,
    subject: str,
    window: tuple[float, float],
    index: OwnerIndex,
    agree: dict[str, str] | None = None,
) -> dict[str, list[Activity]]:
    """Resources with an in-window activity that nobody else is known to own."""

    found: dict[str, list[Activity]] = defaultdict(list)
    for activity in pool:
        if activity.occurred_at > request.audit_at or activity.resource_id is None:
            continue
        if not window[0] <= _offset(request, activity) <= window[1]:
            continue
        expected = (agree or {}).get(request.reported_status)
        if expected is not None and activity.reported_result != expected:
            continue
        if owners_as_of(index, activity.resource_id, request.audit_at) <= {subject}:
            found[activity.resource_id].append(activity)
    return found


def _validate(
    pairs: list[_Pair],
    pool: list[Activity],
    requests: dict[str, AuditRequest],
    subjects: dict[str, str],
    index: OwnerIndex,
) -> GroupModel | None:
    """Two-fold held-out check; ``None`` means the group is not reliable enough to use."""

    if len(pairs) < MIN_PAIRS:
        return None
    ordered = sorted(pairs, key=lambda p: (p.case_id, p.resource_id))
    correct = wrong = 0
    for fold in (0, 1):
        training = [p for i, p in enumerate(ordered) if i % 2 != fold]
        if len(training) < MIN_PAIRS // 2:
            return None
        window = _window([p.offset for p in training])
        agree = _learn_agreement(training)
        for i, pair in enumerate(ordered):
            if i % 2 != fold:
                continue
            request, subject = requests[pair.case_id], subjects[pair.case_id]
            found = _candidates(pool, request, subject, window, index, agree)
            if len(found) == 1:
                resource = next(iter(found))
                if owners_as_of(index, resource, request.audit_at) == {subject}:
                    correct += 1
                else:
                    wrong += 1
    resolved = correct / len(ordered)
    if wrong or resolved < MIN_RESOLVED:
        return None
    key = (pool[0].activity_type, pool[0].system_id or "")
    learned = tuple(sorted(_learn_agreement(ordered).items()))
    return GroupModel(key, _window([p.offset for p in ordered]), len(ordered), resolved, learned)


def fit(bundle: EvidenceBundle, requests: tuple[AuditRequest, ...]) -> LinkModel:
    """Learn which timing signatures are reliable and attribute every request's resources."""

    index = build_owner_index(bundle)
    by_id = {request.case_id: request for request in requests}
    subjects = {
        request.case_id: subject
        for request in requests
        if (subject := resolve_identity(request, bundle).subject_id) is not None
    }
    pools: dict[GroupKey, list[Activity]] = defaultdict(list)
    by_resource: dict[str, list[Activity]] = defaultdict(list)
    for activity in sorted(bundle.activities, key=lambda a: (a.occurred_at, a.activity_id)):
        if activity.resource_id and activity.system_id:
            pools[(activity.activity_type, activity.system_id)].append(activity)
            by_resource[activity.resource_id].append(activity)

    labelled: dict[GroupKey, list[_Pair]] = defaultdict(list)
    owned: dict[str, set[str]] = {}
    for case_id, subject in subjects.items():
        request = by_id[case_id]
        owned[case_id] = set(owned_by(index, subject, request.audit_at))
        for resource in owned[case_id]:
            for activity in by_resource.get(resource, []):
                if activity.occurred_at <= request.audit_at and activity.system_id:
                    key = (activity.activity_type, activity.system_id)
                    labelled[key].append(
                        _Pair(
                            case_id,
                            resource,
                            _offset(request, activity),
                            request.reported_status,
                            activity.reported_result,
                        )
                    )

    groups = tuple(
        model
        for key, pairs in sorted(labelled.items())
        if (model := _validate(pairs, pools[key], by_id, subjects, index)) is not None
    )

    claims: dict[str, list[Attribution]] = defaultdict(list)
    maybe: dict[str, list[Attribution]] = defaultdict(list)
    for case_id, subject in sorted(subjects.items()):
        request = by_id[case_id]
        mine = owned[case_id]
        for group in groups:
            pool = pools[group.key]
            if any(a.resource_id in mine for a in pool):
                continue  # this subject's resource in the group is already known explicitly
            found = _candidates(pool, request, subject, group.window, index, dict(group.agree))
            attributions = [
                Attribution(res, group.key[1], group.key, tuple(a.activity_id for a in acts))
                for res, acts in sorted(found.items())
            ]
            if len(attributions) == 1:
                claims[case_id].append(attributions[0])
            elif attributions:
                maybe[case_id].extend(attributions)

    contested = {
        resource
        for resource, n in Counter(a.resource_id for v in claims.values() for a in v).items()
        if n > 1
    }
    cases = {
        case_id: CaseLinks(
            attributed=tuple(a for a in claims.get(case_id, []) if a.resource_id not in contested),
            candidates=tuple(
                [
                    *maybe.get(case_id, []),
                    *(a for a in claims.get(case_id, []) if a.resource_id in contested),
                ]
            ),
        )
        for case_id in sorted(subjects)
    }
    return LinkModel(index, groups, cases)
