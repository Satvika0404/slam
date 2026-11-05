"""Small development-loop state machine; never imported by production pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from slam.evaluation.improvement.candidates import CandidateResult, CandidateSuiteResult
from slam.evaluation.improvement.reporting import ImprovementReport, write_improvement_report


class LoopStage(StrEnum):
    DIAGNOSE = "diagnose"
    REPRODUCE = "reproduce"
    GENERATE_SCENARIOS = "generate_scenarios"
    PROPOSE_REPAIR = "propose_repair"
    EVALUATE = "evaluate"
    ACCEPT = "accept"
    REJECT = "reject"
    RECORD = "record"


@dataclass(slots=True)
class ImprovementLoop:
    """Record-only coordinator enforcing bounded attempts and terminal decisions."""

    max_attempts: int = 3
    stage: LoopStage = LoopStage.DIAGNOSE
    history: list[str] = field(default_factory=lambda: [LoopStage.DIAGNOSE.value])
    attempts: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")

    def advance(self, next_stage: LoopStage) -> None:
        allowed = {
            LoopStage.DIAGNOSE: {LoopStage.REPRODUCE},
            LoopStage.REPRODUCE: {LoopStage.GENERATE_SCENARIOS},
            LoopStage.GENERATE_SCENARIOS: {LoopStage.PROPOSE_REPAIR},
            LoopStage.PROPOSE_REPAIR: {LoopStage.EVALUATE},
            LoopStage.EVALUATE: {LoopStage.ACCEPT, LoopStage.REJECT},
            LoopStage.ACCEPT: {LoopStage.RECORD},
            LoopStage.REJECT: {LoopStage.PROPOSE_REPAIR, LoopStage.RECORD},
            LoopStage.RECORD: set(),
        }
        if next_stage not in allowed[self.stage]:
            raise ValueError(f"invalid improvement-loop transition: {self.stage} -> {next_stage}")
        if next_stage is LoopStage.PROPOSE_REPAIR:
            self.attempts += 1
            if self.attempts > self.max_attempts:
                raise ValueError("repair attempt limit exceeded")
        self.stage = next_stage
        self.history.append(next_stage.value)

    def record_candidate(self, result: CandidateResult) -> None:
        """Record only the decision, never merge, deploy, or alter an audit result."""
        if self.stage is not LoopStage.EVALUATE:
            raise ValueError("candidate can be recorded only after evaluation")
        self.advance(LoopStage.ACCEPT if result.accepted else LoopStage.REJECT)

    def record_suite(self, result: CandidateSuiteResult) -> None:
        """Record the combined decision after both development and held-out comparisons."""
        if self.stage is not LoopStage.EVALUATE:
            raise ValueError("candidate suite can be recorded only after evaluation")
        self.advance(LoopStage.ACCEPT if result.accepted else LoopStage.REJECT)

    def write_report(self, report: ImprovementReport, json_path: Path, markdown_path: Path) -> None:
        """Persist the terminal decision and close the loop with both report formats."""
        if self.stage not in {LoopStage.ACCEPT, LoopStage.REJECT}:
            raise ValueError("a report can be written only after candidate acceptance or rejection")
        expected = (
            "accepted_for_review" if self.stage is LoopStage.ACCEPT else "rejected_or_blocked"
        )
        if report.decision != expected:
            raise ValueError("report decision does not match recorded candidate result")
        write_improvement_report(report, json_path, markdown_path)
        self.advance(LoopStage.RECORD)
