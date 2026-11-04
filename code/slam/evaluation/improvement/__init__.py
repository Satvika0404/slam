"""Development-only, bounded reliability-improvement tools.

Nothing in this package is called by the production audit pipeline. It stores
sanitized reproduction metadata, creates fictional inputs, and evaluates
reviewable candidate patches under a fixed offline Docker command.
"""

from slam.evaluation.improvement.candidates import (
    CandidateMetrics,
    CandidateResult,
    ScenarioPrediction,
    evaluate_candidate,
    evaluate_candidate_sets,
    score_scenarios,
)
from slam.evaluation.improvement.failures import FailureRecord, FailureStore
from slam.evaluation.improvement.loop import ImprovementLoop, LoopStage
from slam.evaluation.improvement.recovery import (
    RecoveryAction,
    RecoveryPolicy,
    RecoveryResult,
    run_recovery,
)
from slam.evaluation.improvement.reporting import report_for_suite, write_improvement_report
from slam.evaluation.improvement.scenarios import (
    EventKind,
    ScenarioEvent,
    ScenarioEvidence,
    generate_scenario,
)

__all__ = [
    "CandidateMetrics",
    "CandidateResult",
    "EventKind",
    "FailureRecord",
    "FailureStore",
    "ImprovementLoop",
    "LoopStage",
    "RecoveryAction",
    "RecoveryPolicy",
    "RecoveryResult",
    "ScenarioEvent",
    "ScenarioEvidence",
    "ScenarioPrediction",
    "evaluate_candidate",
    "evaluate_candidate_sets",
    "generate_scenario",
    "report_for_suite",
    "run_recovery",
    "score_scenarios",
    "write_improvement_report",
]
