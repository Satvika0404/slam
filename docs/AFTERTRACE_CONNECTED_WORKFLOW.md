# AFTERTRACE — connected records, live graph and reliability experiments

Implemented 5 November 2026. Read alongside [the workflow reference](AFTERTRACE_WORKFLOW.md).
This increment preserves the existing SVG SystemGraph and SLAM 1.1.0 shared contracts.

## User flow

1. **Connect SQLite** uploads a snapshot. Inspect its tables, choose a stable row key, email and
   optional stable subject column, and explicitly choose DELETE, REDACT, ANONYMIZE or RETAIN per
   mapped table. Tables without an email mapping are excluded.
2. Enter a request containing exactly one subject email. The actual intent and identity engines
   evaluate it. Non-deletion requests do not authorize execution; ambiguous identities block it.
   A connected snapshot requires a request. Participant-format ZIPs can use their supplied requests.
3. **Begin the audit** runs ingestion, linking, reconstruction, policy and validation. The frontend
   advances on actual SSE events. One typed request counts as one audit, even with other input users.
4. The console initially fits **all systems and records established for the selected request**.
   This is the investigation's evidence scope, not every row in the company. Click a record for its
   resolved subject, resource, observed state/time, source citations and conflicting evidence.
5. **Prepare working copy**, review the plan, then **Execute reviewed plan**. Existing controls check
   intent, identity, citations, uncertainty, retention and dependency order. SQL changes happen in
   the request's isolated materialized SQLite store.
6. Running states follow backend events. After committed DELETE and independent read-back, exactly
   the affected record nodes and membership edges fade out. Systems and retained records remain.
   REDACT/ANONYMIZE keep their nodes. Failed actions do not receive successful deletion animations.
7. **Show deleted nodes in graph history**, **Before**, per-receipt checkpoints and **Latest state**
   expose the recorded sequence. Muted historical nodes retain evidence. Replay is labelled playback;
   it does not delete again. Reduced motion suppresses animated transitions.
8. The final report separates the original audit cutoff from fresh working-copy verification.
   Source evidence and the original audit CSV remain unchanged.

## What the reliability panels actually do

**Patterns** exposes the existing deterministic timing-window attribution model in
`code/slam/reconstruction/linking.py`. It groups explicitly owned request/activity pairs by activity
type and target system, learns robust offset windows, then enables groups passing two-fold held-out
validation. Requirements include at least 20 grounded pairs, at least 50% held-out resolution and
zero wrong attributions in that validation. Ownership/candidate guards remain in the engine.

The panel shows only current-run windows, pair counts and measured held-out resolution. Small inputs
commonly have no qualifying groups; direct identifiers still work. The model is refitted per run.
There is no persistent cross-customer training or claim that an LLM learns after every click.
Evidence diagnostics run again after contexts are reconstructed. Conflicts, duplicates and affected/
reachable counts are descriptive measures, not calibrated probabilities of an incorrect answer.

**Self-healing** uses the merged bounded `run_recovery` machinery. The starting snippet contains
the current request email and a current resource, with disclosed alternative header spellings to
exercise the adapter. Users can replace the snippet. Successful recovery highlights the CSV adapter
in teal; unresolved input is amber. The handler normalizes allowlisted email/resource header aliases,
case and surrounding space. It rejects colliding columns, missing/invalid values, malformed row widths
and duplicate resource keys. One attempt, a two-second cooperative budget and zero model tokens apply.
Two development, two held-out and two rejection checks gate review eligibility. Attempts, adapter
version, missing fields and validated output are recorded under ignored artifacts.

This is bounded input recovery with **review eligibility**, not automatic production-code rewriting
or adapter promotion. The integrated improvement-loop framework additionally supports diagnosis,
reproduction, proposal and evaluation; see [its reference](evaluation/improvement-loop.md). Broader
regression evidence and acceptance are required before future-run promotion.

**Sync experiment** runs the same worker against two independent copies of a completed execution
store, using the selected verified-deleted row's original payload as the upstream record:

| Branch | Before worker | Control | Measured outcome |
| --- | --- | --- | --- |
| Control | Row absent | Sync enabled | Worker recreates the row |
| Protected | Row absent | Sync disabled | Worker skips it; row remains absent |

Independent SQLite reads measure each result. JSON receipts include timestamp, resource, system,
scope and SHA-256. The source and actual execution store stay unchanged. This proves the specific
local control behaviour, not a customer's external replication/restore system. The graph continues
to show the execution store rather than either experiment branch.

## Integration map

| Part | Files | API |
| --- | --- | --- |
| Snapshot and mapping | `code/slam/web/connect.py`, `frontend/src/workflow/Connect.tsx` | POST `/api/workflow/databases`; POST `/api/workflow/databases/{id}/map` |
| Request and diagnostics | `code/slam/web/workflow.py` | POST `/api/workflow/runs` adds optional `request_text`; GET run adds `request_count` and `intelligence` |
| Record graph and evidence | `workflow/Workflow.tsx`, existing `console/SystemGraph.tsx` | Existing graph plus record membership; stable IDs `row:{system}:{resource}` |
| Recovery and sync | `code/slam/web/experiments.py`, `workflow/Intelligence.tsx` | POST `/api/workflow/experiments/recovery`; POST `/api/workflow/experiments/sync` |
| Execution and proof | Existing `code/slam/web/remediation.py` | Existing sandbox execution, receipts and exports |
| Independent checks | `tests/web/test_connected_workflow.py`, `frontend/e2e/connected.spec.ts` | Actual SQLite/API/browser interactions; no key |

Connections support SQLite snapshots up to 32 MiB and 20,000 mapped rows. Mapping uses inspected
schema names, quoted SQL identifiers, unique stable keys and valid email checks. Per-table actions
are user-supplied policy, not automatic legal interpretation. The execution store materializes audited
resources; it does not reproduce arbitrary source foreign keys, triggers, binary cells or all database
semantics. There are no live Postgres/MySQL/SaaS execution connectors in this increment.

The API remains local and unauthenticated, with in-memory registries. Restart loses registry access;
ignored receipts remain on disk. Hosted production use still needs authentication, tenant isolation,
durable jobs and deployment hardening. No new model, key or package is required.

## Run and test

From the repository root in PowerShell:

```powershell
$env:SLAM_MODEL_PROVIDER = 'fake'
docker compose --profile web up -d --build aftertrace-api
cd frontend
npm ci
npm run dev -- --port 5173
```

Open http://127.0.0.1:5173. Connect a SQLite snapshot or upload a participant-format ZIP. Enter an
explicit request with one email from the snapshot. Review the graph/plan, execute, inspect history,
run the sync/recovery experiments and open the final report.

```powershell
# repository root
docker compose run --rm -e SLAM_MODEL_PROVIDER=fake slam-dev pytest -q tests/web
docker compose run --rm slam-dev ruff check code tests scripts
docker compose run --rm slam-dev mypy code/slam code/main.py
# frontend
npm run build
npm run format:check
npx playwright test
```

Earlier sample results were 29/32 statuses and 11/32 exact answers. These interface and working-copy
features do not establish improved benchmark accuracy or correctness on hidden cases.

## Verification and rating

The full Python suite passed 683 tests with 18 skips. Five additional negative/authorization cases
were then added and the final web subset passed all 32 tests. All 37 browser checks passed, followed
by six passing changed-workflow checks after final validation/progress refinements. Production build,
Prettier, Ruff and strict mypy (75 source files) passed. Browser console errors were asserted absent
in the connected workflow, and overflow was checked at 390, 1024 and 1440 widths.

The connected browser case establishes two real DELETEs, a retained row, two preserved systems,
exactly two disappearing record nodes, evidence inspection, history, a real recreation control
experiment, successful recovery and blocked recovery. Backend tests additionally establish unchanged
source bytes, explicit request requirements, rejected access/ambiguous-identity execution and
recovery rejection for invalid emails, duplicate keys and malformed row widths.

Engineering judgement: **8/10 for the tested local workflow and presentation; 5/10 for production
readiness**. These are qualitative assessments, not measured benchmark scores. Live external
connectors, authentication/durable jobs, automatic recovery promotion and the existing 11/32 exact
sample-output limit prevent a higher readiness rating.
