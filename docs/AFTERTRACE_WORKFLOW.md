# AFTERTRACE: one dataset, one continuous workflow

The [connected workflow addendum](AFTERTRACE_CONNECTED_WORKFLOW.md) documents SQLite table mapping,
typed requests, full request-scoped record graphs, actual deletion animations and measured
recovery/pattern/sync panels added on 5 November 2026.

The default interface is now **Dataset -> Audit -> Intelligence Console -> Final report**.
The former ten chapters grew from separate audit, imported-analysis and execution views. They are
retained only as a development archive for renderer regression checks (`?legacy=1`), with no link
or demo/source selector in the main product. The main workflow never imports console snapshot
statistics or demo cases to fill a gap.

## What the user does

1. Use the installed participant dataset or upload one ZIP with the six required CSV files and
   manifest-linked evidence. A ZIP can wrap the dataset in a directory, but must have one root.
2. Click **Begin the audit**. Actual parser events and request/stage completions drive progress.
3. The Intelligence Console opens when the audit finishes. Select a request from this run. Its
   graph, identity, original evidence, findings and timeline all use that request's recorded result.
4. Review the ordered remediation list. **Prepare working copy** creates an isolated SQLite copy
   of that request's supported resource states. It does not edit source files or external systems.
5. **Execute reviewed plan** runs supported actions against that SQLite database. Each committed
   action is read back through a separate database connection before receiving verified status.
6. The graph remains visible after execution. Inspect ended links, changed resource counters,
   before/after states, timestamps and proof. Recorded replay is explicitly labelled historical
   playback; it never runs a second deletion or invents a backend delay.
7. Continue to the final report. Original audit output and the new working-copy verification are
   shown separately and downloaded separately.

All workflow execution is currently keyless. The new paths pass `provider=None`; optional model
configuration elsewhere cannot silently spend tokens here.

## One input and truth boundary

`code/slam/web/workflow.py` registers a dataset by hashing the required CSVs and every referenced
evidence file. A run pins that fingerprint, loaded bundle, requests, reconstructed contexts and
answers. Every case/detail/export/evidence endpoint is under its run ID; a view does not silently
re-ingest another dataset or recompute policy.

Uploads are isolated under ignored `artifacts/aftertrace/workflow/inputs/`. The receiver rejects
unsafe paths, symlinks, multiple roots, missing required inputs and oversized archives (32 MiB
compressed / 128 MiB expanded). It never extracts over the official dataset. Input changes before
execution are rejected. Original source inspection verifies its file hash and rejects changed bytes.

The frontend ignores stale default-input responses after ZIP selection. Changing input clears the
current run/view state. Request switches cancel stale requests and use run-scoped evidence URLs.
Session restore recovers the selected run/request/view and existing working copy while the API
process retains them. Restarting the API expires the in-memory run registry.

## Preserved graph and meaningful transitions

The renderer remains `frontend/src/console/SystemGraph.tsx`, based on the existing directed
system graph and SVG paths. Existing graph algorithms, node IDs, relationships, original HTML
reference, archived handlers and scenario tests are retained. No new graph library was installed.

The workflow supplies graph data from the actual recorded case instead of `snapshot.json`:

- Systems remain on the map when a record is deleted; deleting one record does not delete a system.
- Each system shows actual imported-resource and present-record counts from the working copy.
- A running action marks its system; a verified receipt changes counters and retained history.
- DELETE removes the SQLite row. Its resource tile becomes grey ABSENT history, with proof/time.
- REDACT and ANONYMIZE scrub payload fields/known identifier values and update the resource state.
- DISABLE_DATA_FLOW and BLOCK_RESTORE update their SQLite control representation and read it back.
  A specifically mapped control edge becomes a grey ended path; its endpoints and provenance remain.
- Missing edges are never treated as deletion events. Unmapped/open recreation paths prevent a
  COMPLETE working-copy certification rather than being hidden.
- Before/latest/per-receipt exploration uses recorded transitions. Mobile retains readable node
  sizes and pan/zoom; selecting a node/edge exposes its records or supporting evidence.

Motion is event-driven: source arrivals, running-state pulses, verified-record transitions and ended
connections. Historical replay has its own explicit label. Reduced-motion users receive immediate
state changes. Pan, zoom, node/edge selection, identifier search, proof drawers and keyboard controls
remain available; source/identity/timeline detail is grouped inside the audit instead of separate
top-level dashboards.

## Actual execution scope

`code/slam/web/remediation.py` creates `working-copy.sqlite` per audited request. Static,
parameterized SQL mutates only this internal database. There are no external connection strings,
arbitrary SQL inputs, cloud credentials, file deletion tools or production connectors.

Supported actions are `DISABLE_DATA_FLOW`, `BLOCK_RESTORE`, `DELETE_RECORD`, `REDACT_RECORD` and
`ANONYMIZE_RECORD`. Control actions precede record changes according to the existing plan order.
Retention-protected resources are not accepted as delete targets. Non-deletion requests, unresolved
identity/evidence, conflicting actions and uncited/future-only resource states cannot be executed.
A failed control/read-back stops dependent actions. Repeating a verified plan skips completed actions.

Flow/restore controls here are materialized SQLite representations. They are not connections to
real synchronization workers or physical backup media. Payload anonymization is a scoped scrubbing
operation, not a claim about irreversible anonymization across an organization's other systems.

After actions, the verifier reads every imported resource again, writes a hashed JSON evidence
snapshot and calls the actual policy planner/validator with those new states. It keeps the original
identity/policy basis and unresolved coverage. Missing required retained records and remaining or
unmapped flow/restore paths prevent completion. This verifies **only the isolated imported scope**.

The original cutoff, CaseAnswer and challenge CSV remain immutable. A new result has its own
verification time, proof hash, receipts and execution report. Execution finishing and deletion being
COMPLETE remain separate concepts. This extension does not fix the previously measured 11/32 exact
public-sample correctness; it does not claim production deletion or autonomous self-healing.

## API and implementation map

| Endpoint | Purpose |
| --- | --- |
| GET /api/workflow/input | Installed input readiness and fingerprint |
| POST /api/workflow/input | One raw ZIP body, no multipart dependency |
| POST /api/workflow/runs | SSE audit of a registered input_id, all its requests |
| GET /api/workflow/runs/{run_id} | Recorded status, case summaries, copy IDs and export readiness |
| GET /api/workflow/runs/{run_id}/cases/{case_id} | The recorded case, no policy rerun |
| GET /api/workflow/runs/{run_id}/evidence/{id}[/raw] | Run-scoped original evidence |
| GET /api/workflow/runs/{run_id}/export | Original challenge-format CSV |
| POST /api/workflow/sandboxes | Prepare reviewed run_id + case_id |
| POST /api/workflow/sandboxes/{id}/execute | SSE actual SQLite actions + fresh verification |
| GET /api/workflow/sandboxes/{id} | Working-copy state, actions and receipts |
| GET /api/workflow/sandboxes/{id}/evidence/{proof_id} | Receipt/read-back proof for that copy |
| GET /api/workflow/sandboxes/{id}/export | Separate JSON execution report |

`frontend/src/workflow/Workflow.tsx`, `types.ts` and `workflow.css` own the four-step shell, stream
state, input/case selection, scoped evidence, action inspection and presentation. Existing Identity
and SystemGraph renderers remain their foundations. `frontend/src/LegacyApp.tsx` isolates the old
chapters for development-only regression tests. Shared engine contract 1.1.0 is unchanged.

## Run and validate

```powershell
# repository root; no API key is used
$env:SLAM_MODEL_PROVIDER = 'fake'
docker compose --profile web up -d --build aftertrace-api
cd frontend
npm ci
npm run dev -- --port 5173
```

Open http://127.0.0.1:5173. The same `dataset/` used by the CLI is the default input. A dataset ZIP
uses the same schema and parsers. No demo is substituted when input is missing.

```powershell
# repository root
docker compose run --rm -e SLAM_MODEL_PROVIDER=fake slam-dev pytest -q tests/web
docker compose run --rm -e SLAM_MODEL_PROVIDER=fake -e SLAM_DATASET_DIR=/workspace/dataset slam-dev pytest -q
docker compose run --rm slam-dev ruff check code tests scripts
docker compose run --rm slam-dev mypy code/slam code/main.py
# frontend
npm run build
npm run format:check
npm run test:e2e
```

New backend tests cover input pinning/traversal, actual DELETE/UPDATE, scrubbing, retention, scoped
proof, idempotence, blocking uncertain/non-deletion/uncited cases, failed-control ordering and missing
retained records during verification. Browser tests execute an independently supplied fictional ZIP
through the real API, inspect graph state/evidence, compare original CSV bytes, replay actual receipts,
exercise responsive layouts, stale-input recovery, refresh restore and reduced motion. Archived
graph/identity functionality still has its original browser regression checks.

The API remains localhost and unauthenticated, with an in-memory run registry and bounded SSE
transport. Public hosting, external execution connectors, durable distributed jobs, generalized
policy-condition evaluation and self-healing promotions are outside this increment.

## Verification on 5 November 2026

- Python: 649 passed / 18 skipped with participant-data tests enabled; final web subset: 24 passed.
- Frontend: 36 checks passed; final changed workflow subset: five passed.
- Production build, formatting, Ruff, mypy (66 source files), whitespace and delivery checks passed.
- The new run API processed all 518 requests and 94 evidence sources with no execution failures.
  Its original audit CSV exactly matched the earlier keyless CLI output.
- Executed case_33 (two actions) and case_54 (four actions, including a flow control) inside isolated
  working copies. Both received fresh COMPLETE verification within their materialized scope.
- Original CSV and all 103 downloaded participant files remained unchanged; zero API calls.

The original sample result remains 29/32 correct statuses and 11/32 exact answers. Successful UI
execution and sandbox verification do not fix those original audit coverage/policy limitations.
