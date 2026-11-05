# RCA: output quality vs HackerRank's 32 published answers (status 0.906, step F1 0.701 after the second pass)

Method: ran the real pipeline on the 32 public samples, diffed every case against
`sample_output.csv`, traced each missing step back to the files, and did not tune anything to the
key (AGENTS.md forbids case-family shortcuts). Reproduce: `python scripts/smoke_test.py --seed N`.

## Summary

| # | Root cause | Evidence | Effect | Status |
|---|---|---|---|---|
| 1 | **Records with no identifier cannot be attributed to a person.** 404 lookups, anonymized analytics and attachments carry null identifiers; the activity stream names only resource ids, never a subject (only 12 `LINK_RESOURCE_IDENTITY` rows do). | `analytics_9406` appears in exactly two places: an all-null log line and an `ANONYMIZE_RECORD` activity. `account_001` appears only in one `DELETE_RECORD` activity; the key cites `evidence_54`, a SQL snapshot that does not contain it. | 25 missing `VERIFY_RECORD_ABSENT`, 7 `VERIFY_RECORD_ANONYMIZED`, 4 `DELETE_RECORD`; 3 safe-side status misses | **Open - needs a team decision**, not a code fix |
| 2 | Timestamps are too loose to substitute for an identity link. | Worker activities sit -114..+74 min around `reported_at`, and bursts interleave several people. | Using time would invent false attributions | Rejected on purpose |
| 3 | Replica copies are not aliased to their primary (`support_replica` vs `support_platform`). | `case_10`: key reports `support_platform/support_002`, we hold `support_replica/support_002`. | 1/32 cases | Open, 3 resources corpus-wide |
| 4 | The right action for a support record (DELETE vs REDACT) depends on content ("shared context", rule 05), which ingestion does not expose as a field. | `case_07` (PDF record) key=DELETE, we REDACT. | 1-2/32 cases | Open |

## Defects found and FIXED on the way (they were hiding in the same numbers)

| Defect | Evidence | Fix |
|---|---|---|
| Intent classifier missed most deletion wording | 20/32 samples, 248/518 `UNCLEAR`, one false `NOT_APPLICABLE` | 32/32, 0/518 unclear; the 10 non-deletion requests match the 10 `CLASSIFY_REQUEST` claims |
| `DISABLE_DATA_FLOW` / `CHECK_*` / `BLOCK_RESTORE` read as risks | 116 flow + 58 restore edges | token-based activity classes |
| Plain search/export records counted as data flows | 303 of 417 flow edges | exact `DATA_FLOW` category |
| Info-level ingestion notes blocked certification | 204/518 contexts | only error/relevant-warning issues block |
| **Step order was invented, not the specified one** | The problem statement ("Rules") fixes order: phase, then the operation order of its table, then `system_id`, then `resource_id` ascending. The planner used its own order (copies before profile). | Sequence accuracy 3.1% -> 12.5%, step F1 0.335 -> 0.441, exact cases 3.1% -> 12.5%; found only by reading the spec after the question "what is missing?" | sort key = (operation order, system_id, resource_id) |
| Injection guard missed plurals ("ignore all previous instructions") | found by a new test | `instructions?` |
| Contract 1.1.0 fields not populated | Lalith's `fa6076a` | reconstruction fills `policy_rules`, `evidence_captured_at`; `plan(context)` now works |

## Safety property that held throughout

0 false COMPLETE on the samples. All 3 status misses are the safe side (key COMPLETE, we INCOMPLETE).
Every uncertain or unattributable case degrades to INCOMPLETE, never to COMPLETE.

## What would close cause 1 (decision needed from Manya, Ashish, Satvika)

Either (a) a grounded owner link for account ids (e.g. an additional file the organizers can confirm),
or (b) accept that those verification steps cannot be produced, and score status only. A heuristic
based on `account_N` numbering or time proximity would be fitted to the samples and is not proposed.


## Second pass (all measured against HackerRank's own `sample_output.csv`, on a fresh official clone)

| Metric | Before | After |
|---|---|---|
| Step F1 | 0.456 | **0.701** |
| Step precision / recall | 0.491 / 0.425 | **0.744 / 0.663** |
| Exact cases | 4/32 | **11/32** |
| HackerRank steps reproduced | 147/193 | **161/193 (83%)** |
| Status accuracy / false COMPLETE | 0.906 / 0 | 0.906 / 0 |

### Defects found and fixed in this pass

| # | Root cause | Evidence | Fix |
|---|---|---|---|
| D1 | **Ingestion parser bug.** A handover note writes table rows as list items (`- 2026-10-01T... | account_3677 | USER_PROFILE | NOT_FOUND | email`). The row pattern required a leading timestamp, so those rows fell to the prose path, became anchor facts, and were always `PRESENT`; the printed `NOT_FOUND` and `SUPPORT_ATTACHMENT` columns were ignored. | 3 false `REPORT_REMAINING_RECORD` + `DELETE_RECORD` findings (cases 11, 13, 14) | accept an optional list bullet; regression test |
| D2 | **Retained records seen before the cutoff in a file exported after it** were dropped. | 7 missing `VERIFY_RECORD_PRESENT` on `audit_record_*`; e.g. event 08:52 vs cutoff 09:00, file exported two days later | such a record becomes an **uncited, verification-only** state: never a finding, never a violation, never inside a COMPLETE answer |
| D3 | Timing alone left 2-6 candidate deletions per window. | batches of cases share report times | learn the `reported_status` <-> activity `reported_result` agreement from labelled pairs (COMPLETE/SUCCESS 89 of 90, NOT_STARTED/FAILED 25 of 25, PARTIALLY_COMPLETE/PARTIAL 50 of 50) and use it as a validated filter: correct unique attributions 97 -> 127 of 165, still **0 wrong** |

### What was tested and rejected (so nobody re-tries it)

- **Ordering as a tiebreaker inside a batch**: request time, case number and activity-ID order are at chance (48.1%, 39.6%); `reported_at` order is consistent but almost always tied. The 7 remaining ambiguous cases have **no further discriminating signal in the data**.
- **Numeric id correlation** (`account_N` = `user_N`): 4 of 55 explicit pairs; it only describes the 8 hand-made teaching cases.
- **A DELETE-vs-REDACT rule for support records**: HackerRank redacts three records that show no content and deletes a PDF record and a replica copy; two cases cannot justify a rule.

### Still open (honest)

| Gap | Cases | Why |
|---|---|---|
| Account absence for the hand-made teaching cases (`account_001`..`010`) | 7 | different timing regime (about 0 min) with too few labelled pairs to validate; they will not appear in the 518 |
| Account absence where several candidates remain | 7 | inherent ambiguity (see above) |
| Support record DELETE vs REDACT, replica aliasing | 2 | no safe general rule |
| `analytics_9914` finding is DELETE in the key, ANONYMIZE ours | 1 | unexplained |

Caution on the metric: the 32 public samples are a *proxy*. Some of their timing patterns (e.g. analytics anonymization offsets) differ from the 518, so the samples can under-state the linker.
