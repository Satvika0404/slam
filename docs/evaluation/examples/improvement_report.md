# Illustrative SLAM improvement-loop report

This example is fabricated to demonstrate report shape; it is not measured project performance.

- Scenario set: **synthetic**
- Fixture set ID: `repair-heldout-v1`
- Failure fingerprint: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
- Seed: `123`; attempt: `1` of at most 3
- Decision: **rejected_or_blocked**

## Baseline and candidate

| Metric | Baseline | Candidate |
|---|---:|---:|
| False COMPLETE | 1/2 (0.5000) | 1/2 (0.5000) |
| Status accuracy | 0.9000 | 0.9000 |
| Step accuracy | 0.8000 | 0.8000 |
| Defect precision | 0.7500 | 0.7500 |
| Defect detection recall | 0.7000 | 0.7000 |
| Latency (ms) | 100 | 100 |
| API calls | 0 | 0 |
| Cost (USD) | 0.0 | 0.0 |
| Observed regressions | 0 | 1 |

Results are finite-set measurements, not a guarantee of correctness. Synthetic and real-data results are reported separately.

## Checks and patch

- Reproduced failure fixed: `true`
- Required checks passed: `true`
- Within declared budgets: `true`
- Patch paths: `code/slam/evaluation/improvement/example.py`

## Assumptions and unknowns

- Assumption: baseline and candidate used the same frozen held-out fixture set.
- Unknown: no participant dataset was available for real-data evaluation.
