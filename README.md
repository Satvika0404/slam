# SLAM — Ghost Data Still Exists

SLAM is the portable deletion-audit agent for the HackerRank Orchestrate challenge. AFTERTRACE provides a single-dataset workflow for auditing, inspecting evidence, executing remediation in isolated SQLite copies, and verifying the result. The current workflow is keyless; the existing optional API adapters remain available separately. It does not require Ollama, local model weights, or a GPU.

## Start here

- [Connected database workflow, record deletion graph and reliability panels](docs/AFTERTRACE_CONNECTED_WORKFLOW.md)
- [Why and how the connected workflow and cohort dashboard are combined](docs/AFTERTRACE_DASHBOARD_INTEGRATION.md)
- [Current AFTERTRACE workflow — one dataset, audit, execution console and final report](docs/AFTERTRACE_WORKFLOW.md)
- [AFTERTRACE contributor reference — current frontend, live backend flow, graphs and boundaries](docs/AFTERTRACE_CONTRIBUTOR_REFERENCE.md)
- [Revised implementation plan](docs/REVISED_SLAM_PLAN.md)
- [Four-person handoff index](team_handoff/README.md)
- [Shared build contract](team_handoff/SHARED_BUILD_CONTRACT.md)
- [Official participant problem statement](team_handoff/reference/problem_statement.md)

## Run the console on your machine

The console is the dashboard plus a live analysis you can run after deleting systems in the graph.
It needs **Docker** (Docker Desktop on Windows or macOS) and the participant files in `dataset/`
(see "Run the pipeline" below). One command does the rest:

| System | Command |
|---|---|
| Windows (PowerShell or cmd) | `scripts\run_console.cmd` |
| macOS, Linux, Git Bash | `scripts/run_console.sh` |
| Any | `docker compose --profile console up` (needs the `.env` lines below first) |

The launcher creates `.env` from `.env.example` if it is missing, gives Neo4j a random local password,
starts Neo4j and the console, waits until it answers and opens **http://127.0.0.1:8765**. The first
start builds the Docker image and audits all 518 cases (about a minute); later starts take under a
minute. It builds only the dashboard files that are missing, and the console listens on this machine
only. Options: `-Port 9000` / `--port 9000`, `-Refresh` / `--refresh` (rebuild the data files),
`-NoBrowser` / `--no-browser`, `-Stop` / `--stop`.

Model-written explanations in live runs are optional and cost API tokens. Without a key the console
explains cases with rules and spends nothing. To enable them add `GROQ_API_KEYS`, `SLAM_API_MAX_CALLS`,
`SLAM_CONSOLE_PROVIDER=groq` and `SLAM_CONSOLE_MODEL=<model id>` to `.env` (see `.env.example`).

If something fails: `docker compose --profile console logs console`. "Docker is not running" means
Docker Desktop has to be started first. A busy port is changed with `-Port`. The Python run without
Docker cannot read the 11 screenshots (no Tesseract), so the console is Docker-only.

## Repository layout

| Path | What it is | How it gets there |
|---|---|---|
| `code/` | The solution: ingestion, reconstruction, planning, evaluation, runtime, insight layer | written by hand |
| `dataset/` | The official participant data (never part of `code.zip`) | provided |
| `docs/` | Plans, integration notes, `INSIGHT_LAYER.md` | written by hand |
| `evaluation/` | `evaluation_report.md`, `usage_report.md`, side-by-side sample report | `python code/main.py --dataset dataset --evaluate` |
| `results/` | `run_summary.json`, `sample_scores.json`, `insight_summary.json` | written by the run, see `results/README.md` |
| `scripts/` | Packaging, smoke test, delivery gate, console launchers | written by hand |
| `tests/` | Offline test suite | written by hand |
| `output.csv` | The 518 answers | `python code/main.py --dataset dataset` |
| `log.txt` | The agent log required by `AGENTS.md` | appended by the coding agents |
| `AGENTS.md`, `CLAUDE.md` | Agent instructions (`CLAUDE.md` points to `AGENTS.md`) | provided |
| `problem_statement.md`, `agent_trace_instructions.md` | The official statement and trace instructions | provided |

`Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, `contracts/`, `dashboard/`, `db/`, `docker/`
and `team_handoff/` support running the code and stay where they are.

## Team split

| Owner | Workstream |
|---|---|
| Ashish | Evidence ingestion, parsing, normalization, provenance ledger |
| Manya | Request intent, historical identity, temporal state, dependency graph |
| Satvika | Policy, decision, ordered remediation and verification, output export |
| Lalith | Contracts, API adapter, Docker, evaluation, orchestration, integration |

## Implemented foundation

Contract version `1.1.0` is now executable rather than only documented. Lalith's baseline provides:

- frozen Pydantic cross-team models and generated JSON Schema;
- typed ownership boundaries for `ingest`, `reconstruct`, and `plan`;
- offline fake-provider and OpenAI Responses API adapters;
- content-addressed cache keys and usage metering;
- an explicit orchestration boundary that refuses to fabricate missing results;
- locked Python 3.11 dependencies and offline contract/runtime tests.

Ingestion, reconstruction and a first planner are implemented and wired end to end
(`code/slam/pipeline.py`); the frozen `plan(context)` remains a conservative compatibility API,
and the pipeline calls `plan_case(context, bundle)`. See "Run the pipeline" below.

## Run the pipeline

Everything runs offline with the default `fake` provider: no API key, no network, no spend. The
pipeline makes no model call, and the 11 screenshots are read with Tesseract OCR, which is
installed in the Docker image (a plain Windows/macOS Python run cannot OCR them).

1. Put the participant files in `dataset/` (`deletion_requests.csv`, `user_identities.csv`,
   `user_audit_log.csv`, `system_activity.csv`, `deletion_rules.csv`, `evidence_files.csv`,
   `evidence/`). `dataset/` is tracked in the repository (it is the official participant data) and is not part of `code.zip`.
2. Build once, then generate `output.csv` at the repository root:

   ```bash
   docker compose build
   docker compose run --rm slam-dev python code/main.py --dataset dataset
   ```

   The run ingests the evidence once, then per request reconstructs the case at `audit_at`, applies
   the deletion rules, orders the steps and validates the answer. A failing case is isolated and
   reported, never guessed; the command exits non-zero until all 518 cases have a supported answer.
3. Add `--evaluate` to also score the 32 public samples against `dataset/sample_output.csv` and
   write `code/evaluation/evaluation_report.md` and `code/evaluation/usage_report.md` (the
   locations the submission rules require; mirrored to `evaluation/`):

   ```bash
   docker compose run --rm slam-dev python code/main.py --dataset dataset --evaluate
   ```

   The reports alone, without writing `output.csv`: `python code/evaluation/main.py --dataset dataset`.
4. Build the submission archive (`code.zip`; never contains `dataset/`, `.env`, `output.csv` or
   `log.txt`) and self-check it against the packaging rules:

   ```bash
   docker compose run --rm slam-dev python scripts/build_submission.py
   ```

Without Docker: `uv sync --frozen`, install Tesseract, then `python code/main.py --dataset dataset`.

### Optional: measure a real model (Groq, several keys)

The pipeline never needs a model: rules and OCR answer every case, so a normal run makes 0 model
calls. To call the two model fallbacks on purpose and get a measured usage report:

1. Copy `.env.example` to `.env` (gitignored) and set `GROQ_API_KEYS=key_one,key_two,...` and a
   positive `SLAM_API_MAX_CALLS` (optionally `SLAM_API_MAX_TOKENS`). With Docker, do **not** put
   `SLAM_MODEL_PROVIDER` or `SLAM_MODEL` in `.env`: Compose copies both into every container,
   including the default offline test run, which would stop being offline. Pass them on the
   command line as below. Without Docker they may live in `.env`.
2. `docker compose run --rm -e SLAM_MODEL_PROVIDER=groq -e SLAM_MODEL=<model id> slam-dev python
   code/main.py --check-keys` probes every key and the model name without spending tokens.
3. The same command with `--dataset dataset --model-check` instead of `--check-keys` runs the
   normal pipeline, then sends the 11 screenshots and a sample of request texts
   (`--model-check-requests N`, default 60) to the model, compares them with OCR and the rules, and
   writes the real counts into `code/evaluation/usage_report.md`.

Keys are tried in the order listed. The first usable one is kept until it is rejected (401/403) or
runs out (429); then the next takes over. A short rate limit cools a key down and it comes back
afterwards; if every key is gone the check stops with a clear error. Groq applies rate limits per
organization, so extra keys add capacity only when they belong to different organizations. Hard
ceilings stop the run (`SLAM_API_MAX_CALLS` is exact and counts logical calls, one per request to
the model; the HTTP attempts a call makes while failing over between keys are listed per key in the
usage report. `SLAM_API_MAX_TOKENS` and a priced `SLAM_API_BUDGET_USD` can overshoot by one call).
Key values are never printed or logged, and the model never changes `output.csv`.

Pipeline stages and owners: `slam.ingestion` (Ashish) -> `slam.reconstruction` (Manya) ->
`slam.planning` (Satvika) -> `slam.evaluation` validator and scorer (Lalith) -> `output.csv`.
Known limits and open decisions are in `docs/integration/deliveries/integration.md`.

### Optional: insight layer and console

Failure-risk model (LightGBM), failure patterns (DBSCAN), recreation paths (Neo4j with NetworkX),
model-written explanations (Groq) and the six-tab Ghost Data Console. It reads what the pipeline
decided and never changes `output.csv`. Run it with
`python code/main.py --dataset dataset --insight` and see [docs/INSIGHT_LAYER.md](docs/INSIGHT_LAYER.md)
for the steps, the exact prompt, the measured numbers and the limits.

With `--serve` the console runs the analysis live on a what-if deletion (Neo4j delete, re-audit,
LightGBM retrain, DBSCAN, model explanations) instead of showing preprocessed data.

The strongest cohort capabilities are also embedded in AFTERTRACE's Intelligence Console. They
require enough audited cases for honest five-fold scoring and are always labelled as triage, not
as evidence that a deletion completed. The connected workflow remains the authoritative surface
for request evidence, working-copy execution, database read-back and receipts.

## Development environment

Docker and Compose provide the shared, locked toolchain.

```bash
docker compose build
docker compose run --rm slam-dev
docker compose run --rm slam-dev ruff check code tests scripts
docker compose run --rm slam-dev mypy code/slam code/main.py
```

The default Compose command synchronizes `uv.lock` with `--frozen` and runs all offline tests. To
verify the baseline without starting teammate-owned work, run:

```bash
docker compose run --rm slam-dev python code/main.py --foundation-status
```

## AFTERTRACE frontend

The default interface is **Dataset -> Audit -> Intelligence Console -> Final report**. Identity,
source and timeline inspection share the same recorded run. The console performs real mutations
only in isolated working copies and records fresh read-back evidence. Original challenge inputs
and audit CSV remain unchanged. Start its API with
`docker compose --profile web up -d --build aftertrace-api`, then run `npm ci` and
`npm run dev -- --port 5173` from `frontend/`. Open http://127.0.0.1:5173.

See the [current workflow, scope and testing guide](docs/AFTERTRACE_WORKFLOW.md). Use the ignored
participant `dataset/` folder or upload one compatible dataset ZIP. Earlier scenes are kept in a
development-only archive for regression tests; they do not supply demo data to the main workflow.

## Teammate start point

Each teammate should branch from the published `dev` baseline (currently contract 1.1.0), then edit only their owned module:

```bash
git fetch origin
git switch <your-name>
git merge --ff-only origin/dev
docker compose run --rm slam-dev pytest -q tests/contracts
```

If a named branch already has independent commits, merge `origin/dev` normally instead of using
`--ff-only`, resolve only owned-file conflicts, and rerun the contract suite. The canonical schema
hash is stored in `contracts/SCHEMA_SHA256`; interface drift requires team review.

The default provider is `fake`, so normal tests cannot spend money or require credentials. For a deliberately authorized API run, copy `.env.example` to `.env`, set an explicit provider/model and positive budget, and add the API key locally. Never commit `.env`.

No implementation accuracy or hidden-set performance is claimed by the planning artifacts in this repository.
