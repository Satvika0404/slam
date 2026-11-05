# Evaluation report

Scored with `slam.evaluation.scorer` against the 32 answers HackerRank publishes in `dataset/sample_output.csv` (32 cases, offline, no model call). HackerRank publishes no answers for the 518 evaluation requests, so those cannot be scored here.

| Metric | Value |
|---|---|
| Case-level deletion-status accuracy | 0.906 |
| Row-level (exact case) accuracy | 0.344 |
| Step precision / recall / F1 | 0.744 / 0.663 / 0.701 |
| Field-level accuracy | 0.771 |
| Sequence accuracy | 0.344 |
| False COMPLETE count | 0 |

Full run: 518 cases, statuses {'INCOMPLETE': 355, 'COMPLETE': 153, 'NOT_APPLICABLE': 10}, 1 not certified (uncertain), 0 failed. Output is byte-identical on a fresh CRLF clone of the official repository.

Timing signatures learned and validated at run time (nothing is hard-coded):
  - BLOCK_RESTORE@backup_service window 2..9 min, 33 pairs, 97% resolved
  - CHECK_DATA_FLOW@integration_service window -117..-37 min, 83 pairs, 87% resolved
  - CHECK_RESTORE_ACCESS@backup_service window -86..-38 min, 25 pairs, 76% resolved
  - DELETE_RECORD@account_service window 44..76 min, 165 pairs, 76% resolved
  - DELETE_RECORD@export_service window -66..-39 min, 29 pairs, 93% resolved
  - DELETE_RECORD@search_service window -91..-42 min, 270 pairs, 96% resolved
  - DELETE_RECORD@support_platform window -76..-37 min, 27 pairs, 89% resolved
  - DISABLE_DATA_FLOW@integration_service window 6..16 min, 33 pairs, 97% resolved
  - REDACT_RECORD@support_platform window -113..23 min, 154 pairs, 87% resolved
  - SYNC_RECORD@account_replication_cluster window -61..-38 min, 53 pairs, 94% resolved
  - SYNC_RECORD@search_service window -62..-39 min, 29 pairs, 93% resolved

## Additional evaluation cases (created by us)

- `tests/planning/test_engine.py`: a clean COMPLETE case; an INCOMPLETE case with an active flow and a restorable backup in the specified step order; a non-deletion request (NOT_APPLICABLE, no steps); a retained record exported after the cutoff (future check only, never in a COMPLETE answer).
- `tests/reconstruction/test_linking.py`: an invented world (system names, id formats, activity types and offsets that exist nowhere in the dataset) proving the account linking is learned, validated, abstains on ambiguity and never attributes a contested resource.
- `tests/integration/test_diagram_conformance.py`: every box of the project flowchart maps to code that exists.

## Failures found and improvements made

| Failure found | Evidence | Improvement |
|---|---|---|
| Intent classifier missed most deletion wording | 20/32 samples, 248/518 unclear, one false NOT_APPLICABLE | broader multilingual rules with negation and marketing scoping: 32/32, 0 unclear |
| Mitigation activities read as risks | 116 flow + 58 restore edges came from `DISABLE_*`/`CHECK_*`/`BLOCK_*` | token-based activity classes |
| Plain records read as data flows | 303 of 417 flow edges | exact category match |
| Step order invented | sequence accuracy 3% | order exactly as the problem statement |
| Bulleted table rows read as prose, always PRESENT | explicit `NOT_FOUND` ignored; 3 false findings | parser accepts list bullets |
| Retained records dropped when their file was exported after the cutoff | 7 missing presence checks | uncited verification-only states |
| Timing left 2-6 candidate accounts | batches share report times | learned status/result agreement filter: 97 -> 127 of 165 correct, 0 wrong |

Step F1 on the official samples moved 0.335 -> 0.441 (order) -> 0.456 (linking) -> 0.701 (parser, retained checks, agreement). Remaining gaps and the evidence for each are in `docs/integration/RCA_ACCURACY.md`: 7 hand-made teaching cases in a different timing regime, 7 inherently ambiguous cases (request order, case number and activity-id order were tested as tiebreakers and are at chance), 2 support-record delete-vs-redact cases.

## Model cross-check (optional pass, nothing here feeds `output.csv`)

Provider `groq`, model `qwen/qwen3.8-27b`. The two model fallbacks never fire on this dataset, so they were called on purpose and compared with the rules and with OCR. Agreement is not accuracy: HackerRank publishes no answers for these requests, and neither the rules nor the model is ground truth.

**Request intent:** 60 requests sampled (every request the rules did not call a deletion, then evenly spaced ones); 0 had no usable model answer; of 60 compared, 60 agree with the rules (100.0%).

**Screenshots:** model read 37 identifiers against OCR's 58; 33 in common (OCR identifiers the model also found: 56.9%; model identifiers OCR also found: 89.2%).

| file | OCR ids | model ids | shared | model issues |
|---|---|---|---|---|
| evidence_04 | 7 | 2 | 2 | IMAGE_MODEL_RECORD_REJECTED |
| evidence_09 | 6 | 4 | 4 | - |
| evidence_14 | 4 | 4 | 4 | IMAGE_MODEL_RECORD_REJECTED |
| evidence_19 | 3 | 0 | 0 | IMAGE_MODEL_INVALID, IMAGE_MODEL_RECORD_REJECTED, IMAGE_MODEL_RECORD_REJECTED, IMAGE_MODEL_RECORD_REJECTED |
| evidence_23 | 12 | 8 | 8 | - |
| evidence_28 | 3 | 1 | 1 | IMAGE_MODEL_RECORD_REJECTED |
| evidence_32 | 9 | 8 | 5 | - |
| evidence_37 | 7 | 7 | 7 | - |
| evidence_42 | 2 | 0 | 0 | IMAGE_MODEL_INVALID, IMAGE_MODEL_RECORD_REJECTED, IMAGE_MODEL_RECORD_REJECTED, IMAGE_MODEL_RECORD_REJECTED |
| evidence_46 | 2 | 0 | 0 | IMAGE_MODEL_RECORD_REJECTED |
| evidence_60 | 3 | 3 | 2 | - |
