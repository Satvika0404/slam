"""DBSCAN failure-pattern discovery.

Every failed case has a *signature*: the set of ``CATEGORY:FAILURE_TYPE`` items the audit found
(for example ``SEARCH_INDEX_ENTRY:REMAINING_RECORD``). Two cases are close when their signatures
overlap (Jaccard distance). DBSCAN needs no cluster count, groups recurring signatures, and labels
everything that fits no group as noise, which is exactly the "rare or unseen" set a reviewer wants.

"Unseen" is made time-aware: after a warm-up of ``WARMUP`` audited cases, a case is *novel at
audit time* when no earlier case (by ``audit_at``) is within ``eps`` of it, i.e. nothing like it had
been seen yet. A case that fits no recurring pattern at all (DBSCAN noise) is also reported.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt
from sklearn.cluster import DBSCAN  # type: ignore[import-untyped]
from sklearn.metrics import pairwise_distances  # type: ignore[import-untyped]

from slam.insight.facts import CaseFacts

EPS = 0.4
MIN_SAMPLES = 4
WARMUP = 30
SWEEP = (0.2, 0.3, 0.4, 0.5, 0.67)
NOISE = "NOISE"
_CORE_PREVALENCE = 0.5


@dataclass(frozen=True, slots=True)
class Pattern:
    pattern_id: str
    label: str
    size: int
    core: tuple[tuple[str, float], ...]  # (signature item, share of cases that carry it)
    systems: tuple[tuple[str, int], ...]
    reported_complete_share: float
    mean_p_failure: float | None
    first_audit_at: datetime
    established_at: datetime | None  # audit date of the MIN_SAMPLES-th case
    last_audit_at: datetime
    novel_at_audit: int
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PatternReport:
    patterns: tuple[Pattern, ...]
    assignment: Mapping[str, str]  # case_id -> pattern_id (or NOISE)
    novel: frozenset[str]
    eps: float
    min_samples: int
    sweep: tuple[dict[str, float], ...]


def humanize(item: str) -> str:
    category, _, failure = item.partition(":")
    return f"{category.replace('_', ' ').lower()} · {failure.replace('_', ' ').lower()}"


def _vectors(
    cases: Sequence[CaseFacts],
) -> tuple[npt.NDArray[np.bool_], list[str]]:
    vocabulary = sorted({item for case in cases for item in case.signature})
    column = {item: i for i, item in enumerate(vocabulary)}
    matrix = np.zeros((len(cases), len(vocabulary)), dtype=np.bool_)
    for row, case in enumerate(cases):
        for item in case.signature:
            matrix[row, column[item]] = True
    return matrix, vocabulary


def _cluster(distance: npt.NDArray[np.float64], eps: float) -> npt.NDArray[np.int64]:
    model = DBSCAN(eps=eps, min_samples=MIN_SAMPLES, metric="precomputed")
    return np.asarray(model.fit_predict(distance), dtype=np.int64)


def discover(
    failed: Sequence[CaseFacts], p_failure: Mapping[str, float], *, eps: float = EPS
) -> PatternReport:
    """Cluster the failed cases; patterns are numbered P1.. from the largest down."""

    cases = sorted(failed, key=lambda c: (c.audit_at, c.case_id))
    matrix, _ = _vectors(cases)
    distance = np.asarray(pairwise_distances(matrix, metric="jaccard"), dtype=np.float64)

    sweep = []
    for value in SWEEP:
        labels = _cluster(distance, value)
        sweep.append(
            {
                "eps": value,
                "clusters": float(len(set(labels.tolist()) - {-1})),
                "noise": float((labels == -1).sum()),
            }
        )

    labels = _cluster(distance, eps)
    sizes = Counter(int(v) for v in labels.tolist() if v != -1)
    rank = {raw: f"P{i}" for i, (raw, _) in enumerate(sizes.most_common(), 1)}
    assignment = {
        case.case_id: rank[int(raw)] if raw != -1 else NOISE
        for case, raw in zip(cases, labels.tolist(), strict=True)
    }

    novel = {case_id for case_id, pid in assignment.items() if pid == NOISE}
    for position in range(WARMUP, len(cases)):  # chronological: only earlier cases count
        if float(distance[position, :position].min()) > eps:
            novel.add(cases[position].case_id)

    by_pattern: dict[str, list[CaseFacts]] = {}
    for case in cases:
        by_pattern.setdefault(assignment[case.case_id], []).append(case)

    patterns = []
    for pid in [*rank.values(), NOISE]:
        members = by_pattern.get(pid, [])
        if not members:
            continue
        tally = Counter(item for member in members for item in member.signature)
        core = tuple(
            (item, tally[item] / len(members))
            for item, _ in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
            if tally[item] / len(members) >= _CORE_PREVALENCE
        )
        probs = [p_failure[m.case_id] for m in members if m.case_id in p_failure]
        label = " + ".join(humanize(item) for item, _ in core) or "no recurring signature"
        patterns.append(
            Pattern(
                pattern_id=pid,
                label=label if pid != NOISE else "unmatched / rare combinations",
                size=len(members),
                core=core,
                systems=tuple(
                    Counter(s for m in members for s in m.violating_systems).most_common(4)
                ),
                reported_complete_share=sum(m.reported_status == "COMPLETE" for m in members)
                / len(members),
                mean_p_failure=float(np.mean(probs)) if probs else None,
                first_audit_at=members[0].audit_at,
                established_at=members[MIN_SAMPLES - 1].audit_at
                if len(members) >= MIN_SAMPLES and pid != NOISE
                else None,
                last_audit_at=members[-1].audit_at,
                novel_at_audit=sum(m.case_id in novel for m in members),
                examples=tuple(m.case_id for m in members[:5]),
            )
        )
    return PatternReport(
        patterns=tuple(patterns),
        assignment=assignment,
        novel=frozenset(novel),
        eps=eps,
        min_samples=MIN_SAMPLES,
        sweep=tuple(sweep),
    )
