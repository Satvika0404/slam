"""Reusable validation and scoring logic for the challenge output contract."""

from slam.evaluation.data_quality import (
    CaseCoverageEstimate,
    DataQualityIssue,
    DiagnosticFinding,
    EvidenceImpactEstimate,
    EvidenceQualityReport,
    analyze_evidence_patterns,
    analyze_evidence_quality,
    estimate_case_coverage,
    render_quality_markdown,
    write_quality_reports,
)
from slam.evaluation.scorer import EvaluationMetrics, score_outputs
from slam.evaluation.validator import OutputValidationError, validate_output_csv

__all__ = [
    "CaseCoverageEstimate",
    "DataQualityIssue",
    "DiagnosticFinding",
    "EvaluationMetrics",
    "EvidenceImpactEstimate",
    "EvidenceQualityReport",
    "OutputValidationError",
    "analyze_evidence_patterns",
    "analyze_evidence_quality",
    "estimate_case_coverage",
    "render_quality_markdown",
    "score_outputs",
    "validate_output_csv",
    "write_quality_reports",
]
