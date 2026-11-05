# AFTERTRACE — the eight requested acceptance points

This checklist is the user's agreed scope. Development dashboard integration is separate and must
not replace these behaviours. Read [setup and boundaries](AFTERTRACE_CONNECTED_WORKFLOW.md).

| # | Implemented behaviour | Evidence |
| --- | --- | --- |
| 1 | SQLite snapshot connection, explicit column/policy mapping, typed single-email request, non-deletion and ambiguous identity execution blocked | `tests/web/test_connected_workflow.py`; connected browser tests |
| 2 | Row selection exposes subject/resource/state/time and clickable source citations; current/historical identity opens the existing evidence-backed identity renderer; observation IDs accompany field inspection | Record evidence chain, source drawer, identity renderer; existing historical-identity regression tests |
| 3 | All systems/records established for the request are fitted before execution; exact row nodes and field-treatment previews distinguish DELETE, REDACT/ANONYMIZE and retained content | Connected graph browser test; committed redaction/preview backend test |
| 4 | Committed delete plus independent read-back produces the receipt and removal animation; field changes use actual before/after payloads; stable positions/history/replay retain provenance; failed actions remain marked with errors | Test-only real SQLite trigger aborts second DELETE after the first commits: exactly one deleted node, one failed surviving row and one receipt |
| 5 | Two isolated branches start with the same imported row, set sync enabled/disabled BEFORE deleting, then execute the same worker; independent reads measure recreation versus absence | `experiments.sync`: one original row -> zero after deletion -> one/zero after sync; JSON receipt |
| 6 | A supported table-header parser failure actually recovers during audit in a separate validated copy; UI highlights the real file/component, retry, adapter version and validation; unresolved snippets stay amber/blocked | Actual-audit recovery backend/browser tests; collision/shape/value negative cases; no source mutation or implicit future promotion |
| 7 | Existing timing model reports current-run grounded pair count, robust window and two-fold held-out resolution; missing groups and ambiguous owner states remain explicit | Existing attribution tests and current-run panel; no invented language-model training |
| 8 | Laptop composition fits graph plus action list/control; responsive/reduced-motion, success/failure/history/recovery/retention scenarios and final evidence are tested; changes documented | Connected 1366x768 bounding checks, 390/1024/1440 overflow checks, original graph regression suite |

The read-only source database is never treated as an external execution connector. Mutations happen
in the materialized request working store. A complete graph means the evidence-supported request
graph, not an unobserved organization-wide inventory.

For a field preview, open **Inspect field treatment** on a record. Proposed changes are labelled
before execution. After execution, removed fields appear with their original values struck out and
an actual verified-removal label; preserved content remains. Open the receipt for full before/after
payloads. For a historical identity path, click **Explore current and historical identity** in a
selected row's evidence chain.

To demonstrate real in-run recovery with a fictional input, copy your participant-format dataset,
change only the `email` header in `user_identities.csv` to `Email Address`, ZIP that copied input,
upload it and run. **Self-healing** shows `user_identities.csv` as **Recovered this run** only after
the adapted copy passes the ordinary table validator. The uploaded original retains its bytes.
An unsupported or colliding header blocks recovery. Generic snippet recovery remains a separately
labelled experiment; production code does not autonomously rewrite itself.

The baseline of 29/32 status decisions and 11/32 exact sample outputs is not improved by these
display/execution additions. Evidence navigation exposes omissions; it does not fabricate missing
verification steps. Future adapter promotion requires a versioned, reviewed change plus regression
checks. Current pattern fitting is deterministic per input, not persistent cross-customer learning.
