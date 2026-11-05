# Plan: mapping account (and other resource) IDs to people

Status: PLAN, nothing implemented. Evidence below was measured on participant data only
(never on the answer key, which is used for evaluation only).

## 1. Confirmed facts

There is **no single rule** that maps an account ID to a person. Four evidence tiers exist.

| Fact | Measured |
|---|---|
| Users / account IDs in activities / in observations / with an identified owner | 850 / 989 / 597 / **570** (0 conflicting owners) |
| Activity-stream account IDs that appear in *no* observation | 695 of 989 |
| Answer key's 32 account resources: explicit owner / observed, no link / activity only | **14 / 3 / 15** (one, `account_004`, appears in no participant file) |
| Naming shortcut `account_N == user_N` | 4 of 55 explicit pairs -> **not a rule** |
| Activities carrying a subject identifier | 12 `LINK_RESOURCE_IDENTITY` only |
| Time alone (absolute proximity to `reported_at`) | 30.5% nearest-correct; 0/55 when "unique within 5 min" -> **rejected** |
| Time **signature** (signed offset) per activity type and target system | very tight; see tier 3 |

Correction to an earlier claim: support **attachments are attributable**. Their raw `uploaded_by`
is the requester's email (22/22) but ingestion's `IDENTIFIER_FIELDS` drops it. That is an
ingestion gap, not missing data.

## 2. The linking tiers

| Tier | Link | Confidence | Rule |
|---|---|---|---|
| L1 | **Explicit owner evidence**: the resource id and an exact subject identifier (email, hash, phone, user_id) in the same record or trace | `EXACT` | SQL rows (`resource_id`+`user_id`), JSON records, log `trace_id` join (`lookup_key`), `LINK_RESOURCE_IDENTITY`, text/PDF/image rows, **attachment `uploaded_by`** |
| L2 | **Resource-id closure**: once R belongs to S, everything else about R belongs to S (identifier-less 404 lookups, anonymized readbacks, worker activities, replica copies) | `CORROBORATED` | only evidence at or before `audit_at`; a resource with two owners is a conflict, never merged |
| L3 | **Temporal signature + elimination** for resources with no L1/L2 owner | `CORROBORATED`, `review_required` | see below |
| L4 | Anything else | none | stays unresolved and blocks `COMPLETE` |

### Tier 3, as measured (windows learned only from L1-labelled pairs)

Candidate pool for subject S and activity type T on system X = activities of (T, X) whose
`reported_at - occurred_at` lies in the learned window, **minus every resource explicitly owned by
another person**. Attribute only when exactly one candidate remains.

| Activity, target system | Labelled pairs | Window (min before `reported_at`) | Correct | **Wrong** | Ambiguous | None |
|---|---|---|---|---|---|---|
| `DELETE_RECORD`, account_service | 246 | 43..76 | 185 | **0** | 53 | 8 |
| `DELETE_RECORD`, search_service | 275 | 44..93 (after) | 259 | **0** | 0 | 16 |
| `DELETE_RECORD`, export_service | 30 | after 39 | 30 | **0** | 0 | 0 |
| `ANONYMIZE_RECORD`, analytics_platform | 73 | 38..118 (after) | 68 | **0** | 2 | 3 |
| `REDACT_RECORD`, support_platform | 155 | wide, 1 candidate left | 153 | **0** | 0 | 2 |
| `DISABLE_DATA_FLOW`, integration_service | 33 | 6..16 | 33 | **0** | 0 | 0 |
| `BLOCK_RESTORE`, backup_service | 33 | 2..9 | 33 | **0** | 0 | 0 |

These are in-sample. They only become evidence after the validation protocol in section 4.

## 3. Using the links (what each tier unlocks)

1. **Absence** of an owned record R in system X: the *latest scoped snapshot of X captured at or
   before `audit_at`* has no row for R -> `ResourceState ABSENT`, cite that snapshot's `file_id`.
   (This is why the key cites `evidence_54` for `account_001`: a snapshot that *lacks* it.)
2. **Anonymized**: an identifier-less `PRESENT` record plus a successful `ANONYMIZE_RECORD` on the same
   owned id -> `ANONYMIZED`, cite the readback file.
3. **Remaining/redact/delete** findings for owned records with identifiers, as today.
4. Unresolved candidates in a subject's windows -> coverage issue (`unattributed:<resource>`), so the
   case is never certified `COMPLETE` on partial attribution.

## 4. Validation protocol (no answer key in the loop)

1. **k-fold** over L1 pairs: learn windows on k-1 folds, test on the held-out fold. Adopt a window
   only if held-out *wrong* = 0 and the Wilson 95% upper bound on the wrong-rate is below 2%.
2. **Leave-one-subject-out**: hide a labelled subject's explicit evidence, confirm the pipeline
   recovers the same resource or abstains, never a different one.
3. **Metamorphic**: shuffle rows, add unrelated people, drop a labelled person -> attributions
   unchanged or correctly absent; one-to-one (a resource has at most one owner).
4. **Independent check** on the 32 public samples: use `sample_output.csv` only to *score* owner
   recovery. Expect a different timing regime there (offsets of 0..8 min), so tier 3 may abstain on
   samples; that is a recall limit, not a precision failure.
5. **Success criteria**: 0 wrong attributions on labelled data; no false `COMPLETE`; step F1 and exact
   cases reported with and without tier 3 so its contribution is visible.

## 5. Build sequence (one PR-sized step each)

| Step | Owner | Work |
|---|---|---|
| S0 | Ashish | map `uploaded_by` (and value-shape fallback); structure the 12 `LINK_RESOURCE_IDENTITY` links into `attributes` |
| S1 | Manya | `ResourceOwnerIndex` (L1) + closure (L2) in reconstruction; conflicts for double owners |
| S2 | Manya | `temporal_link` (L3): learn windows from L1 pairs at run time, deterministic, cross-validated |
| S3 | Manya | snapshot-absence and anonymized states with correct citations |
| S4 | Satvika | planner consumes the new states; `unattributed:*` blocks `COMPLETE` |
| S5 | Integrator | seam tests, metrics with/without L3, update `evaluation_report.md` |

## 6. Limits and risks

- Some key resources are unreachable: `account_004` appears in no participant file, so any answer would
  be a guess. Expect a ceiling below 100% on step recall.
- Tier 3 rests on regularities of this generator. It is disclosed as `CORROBORATED`, flagged for review,
  and never used to certify without an explicit abstention check.
- Windows are learned per (activity type, target system); a hidden dataset with new systems needs the
  same calibration, not hard-coded numbers.

## 7. Decisions needed

1. Approve tier 3 as `CORROBORATED` + `review_required` (the spec lists timestamps as a legitimate link).
2. Ashish: approve S0 (ingestion change).
3. Satvika: agree that unresolved attribution blocks `COMPLETE`.
