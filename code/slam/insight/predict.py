"""LightGBM failure predictor: how likely is it that a deletion the workflow reported will fail?

The label is the deterministic audit verdict. The inputs are only the workflow's *claims*
(``facts.FEATURES``), so this answers a triage question: "given what the workflow says, which
requests deserve a closer look first?" It is a prioritisation aid. It never replaces the audit.

Honesty rules built in:

* every per-case probability for the 518 evaluation cases is **out-of-fold** (the model that scored
  a case never saw it), and the TreeSHAP drivers come from that same fold model;
* the model is compared with two baselines (the majority class, and "trust the reported status");
* the 32 public sample cases are held out entirely and scored against HackerRank's published
  answers, which is the only check that does not grade the audit with itself;
* labels are the audit's own verdicts (about 0.91 status agreement with the published samples), so
  every metric here is agreement with the audit, not accuracy on the hidden answers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
from sklearn.metrics import (  # type: ignore[import-untyped]
    accuracy_score,
    brier_score_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold  # type: ignore[import-untyped]

from slam.insight.facts import FAILURE_TYPES, FEATURES, CaseFacts

SEED = 7
FOLDS = 5
MIN_TYPE_POSITIVES = 15
TOP_DRIVERS = 3
PARAMS: dict[str, Any] = {
    "n_estimators": 150,
    "learning_rate": 0.05,
    "num_leaves": 7,
    "min_child_samples": 10,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "random_state": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "n_jobs": 1,
    "verbose": -1,
}

Matrix = npt.NDArray[np.float64]
Labels = npt.NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class CaseRisk:
    case_id: str
    p_failure: float
    drivers: tuple[tuple[str, float], ...]  # (feature, signed SHAP contribution), largest first
    type_probs: Mapping[str, float]
    likely_type: str | None


@dataclass(slots=True)
class ModelReport:
    algorithm: str
    params: dict[str, Any]
    n_train: int
    n_failed: int
    features_used: list[str]
    folds: int
    cv: dict[str, float]
    baselines: dict[str, dict[str, float]]
    calibration: list[dict[str, float]]
    importance: list[dict[str, Any]]
    per_type: list[dict[str, Any]]
    type_hit_at_1: float | None
    type_hit_baseline: float | None  # always guessing the most common failure type
    external: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


def _matrix(facts: Sequence[CaseFacts]) -> Matrix:
    return np.array([item.features for item in facts], dtype=np.float64)


def _classifier() -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(**PARAMS)


def _proba(model: lgb.LGBMClassifier, x: Matrix) -> npt.NDArray[np.float64]:
    """P(class 1) for every row."""

    return np.asarray(model.predict_proba(x), dtype=np.float64)[:, 1]


def _scores(y: Labels, p: npt.NDArray[np.float64]) -> dict[str, float]:
    guess = (p >= 0.5).astype(np.int64)
    return {
        "auc": float(roc_auc_score(y, p)),
        "accuracy": float(accuracy_score(y, guess)),
        "precision": float(precision_score(y, guess, zero_division=0)),
        "recall": float(recall_score(y, guess, zero_division=0)),
        "brier": float(brier_score_loss(y, p)),
    }


def _baseline(y: Labels, guess: npt.NDArray[np.int64]) -> dict[str, float]:
    return {
        "accuracy": float(accuracy_score(y, guess)),
        "precision": float(precision_score(y, guess, zero_division=0)),
        "recall": float(recall_score(y, guess, zero_division=0)),
    }


def _trust_report(facts: Sequence[CaseFacts]) -> npt.NDArray[np.int64]:
    """Believe the workflow: only a report of COMPLETE counts as a success."""

    return np.array([item.reported_status != "COMPLETE" for item in facts], dtype=np.int64)


def _oof(
    x: Matrix, y: Labels, *, contributions: bool
) -> tuple[npt.NDArray[np.float64], Matrix | None]:
    folds = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=SEED)
    probs = np.zeros(len(y), dtype=np.float64)
    contrib = np.zeros_like(x) if contributions else None
    for train, valid in folds.split(x, y):
        model = _classifier().fit(x[train], y[train])
        probs[valid] = _proba(model, x[valid])
        if contrib is not None:
            raw: Matrix = np.asarray(
                model.booster_.predict(x[valid], pred_contrib=True), dtype=np.float64
            )
            contrib[valid] = raw[:, :-1]
    return probs, contrib


def _calibration(y: Labels, p: npt.NDArray[np.float64]) -> list[dict[str, float]]:
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0000001]
    rows = []
    for low, high in pairwise(edges):
        mask = (p >= low) & (p < high)
        if mask.any():
            rows.append(
                {
                    "low": low,
                    "high": min(high, 1.0),
                    "n": float(mask.sum()),
                    "mean_predicted": float(p[mask].mean()),
                    "observed_rate": float(y[mask].mean()),
                }
            )
    return rows


def _drivers(
    row: npt.NDArray[np.float64], names: Sequence[str]
) -> tuple[tuple[str, float], ...]:
    order = np.argsort(-np.abs(row), kind="stable")[:TOP_DRIVERS]
    return tuple((names[i], float(row[i])) for i in order if abs(row[i]) > 1e-9)


def train_and_score(
    training: Sequence[CaseFacts],
    holdout: Sequence[CaseFacts],
    gold: Mapping[str, str],
) -> tuple[dict[str, CaseRisk], ModelReport]:
    """Fit on the audited evaluation cases, score every case, validate on the held-out samples."""

    rows = [item for item in training if item.is_audited]
    x_all = _matrix(rows)
    y = np.array([item.failed for item in rows], dtype=np.int64)

    keep = [i for i in range(x_all.shape[1]) if float(np.ptp(x_all[:, i])) > 0.0]
    names = [FEATURES[i] for i in keep]
    x = x_all[:, keep]

    probs, contrib = _oof(x, y, contributions=True)
    assert contrib is not None

    # One model per failure type: which kind of failure is it likely to be?
    type_probs: dict[str, npt.NDArray[np.float64]] = {}
    per_type: list[dict[str, Any]] = []
    for kind in FAILURE_TYPES:
        target = np.array([kind in item.failure_types for item in rows], dtype=np.int64)
        positives = int(target.sum())
        row: dict[str, Any] = {"type": kind, "positives": positives, "auc": None}
        if positives >= MIN_TYPE_POSITIVES:
            p_kind, _ = _oof(x, target, contributions=False)
            type_probs[kind] = p_kind
            row["auc"] = float(roc_auc_score(target, p_kind))
        per_type.append(row)

    typed = [i for i, item in enumerate(rows) if item.failed and item.failure_types]
    hits = [
        max(type_probs, key=lambda k: type_probs[k][i]) in rows[i].failure_types
        for i in typed
        if type_probs
    ]
    common = max(FAILURE_TYPES, key=lambda k: sum(k in rows[i].failure_types for i in typed))
    baseline_hits = [common in rows[i].failure_types for i in typed]

    risks: dict[str, CaseRisk] = {}
    for i, item in enumerate(rows):
        by_type = {kind: float(type_probs[kind][i]) for kind in type_probs}
        risks[item.case_id] = CaseRisk(
            case_id=item.case_id,
            p_failure=float(probs[i]),
            drivers=_drivers(contrib[i], names),
            type_probs=by_type,
            likely_type=max(by_type, key=lambda k: by_type[k]) if by_type else None,
        )

    final = _classifier().fit(x, y)
    gains = np.asarray(final.booster_.feature_importance(importance_type="gain"), dtype=np.float64)
    total = float(gains.sum()) or 1.0
    importance = [
        {"feature": names[i], "share": float(gains[i] / total)}
        for i in np.argsort(-gains, kind="stable")
        if gains[i] > 0
    ]

    report = ModelReport(
        algorithm=f"LightGBM {lgb.__version__} (gradient-boosted trees)",
        params={k: v for k, v in PARAMS.items() if k not in {"verbose", "n_jobs"}},
        n_train=len(rows),
        n_failed=int(y.sum()),
        features_used=names,
        folds=FOLDS,
        cv=_scores(y, probs),
        baselines={
            "majority_class": _baseline(y, np.ones_like(y)),
            "trust_reported_status": _baseline(y, _trust_report(rows)),
        },
        calibration=_calibration(y, probs),
        importance=importance,
        per_type=per_type,
        type_hit_at_1=float(np.mean(hits)) if hits else None,
        type_hit_baseline=float(np.mean(baseline_hits)) if baseline_hits else None,
        notes=[
            "Labels are the deterministic audit's verdicts, not hidden ground truth.",
            "Four date-arithmetic features (lags and days-since) were dropped after repeated "
            "5-fold CV over 3 seeds showed they only add variance (AUC 0.757 with, 0.786 without). "
            "That choice was made by looking at CV, so the held-out samples are the unbiased "
            "check.",
            "All case probabilities are out-of-fold; the case was never in its own model's "
            "training data.",
        ],
    )

    scored_holdout = [item for item in holdout if item.is_audited and item.case_id in gold]
    if scored_holdout:
        x_hold = _matrix(scored_holdout)[:, keep]
        p_hold = _proba(final, x_hold)
        report.external = _external(scored_holdout, p_hold, gold)
    return risks, report


def _external(
    cases: Sequence[CaseFacts], p: npt.NDArray[np.float64], gold: Mapping[str, str]
) -> dict[str, Any]:
    keep = [i for i, item in enumerate(cases) if gold[item.case_id] in {"COMPLETE", "INCOMPLETE"}]
    truth = np.array([gold[cases[i].case_id] == "INCOMPLETE" for i in keep], dtype=np.int64)
    audit = np.array([cases[i].failed for i in keep], dtype=np.int64)
    return {
        "source": "dataset/sample_output.csv (public, held out, never trained on)",
        "n": len(keep),
        "n_incomplete": int(truth.sum()),
        "model": _scores(truth, p[keep]) if 0 < truth.sum() < len(truth) else None,
        "trust_reported_status": _baseline(truth, _trust_report([cases[i] for i in keep])),
        "audit_vs_published": _baseline(truth, audit),
    }
