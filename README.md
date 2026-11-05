# SLAM — Ghost Data Still Exists

SLAM is the planned portable, AI-assisted deletion-audit agent for the HackerRank Orchestrate challenge. The latest approved architecture uses deterministic evidence and policy logic with bounded API-based structured extraction. It does not use Ollama, `llama.cpp`, local model weights, or a GPU-specific development path.

## Start here

- [AFTERTRACE contributor reference — current frontend, live backend flow, graphs and boundaries](docs/AFTERTRACE_CONTRIBUTOR_REFERENCE.md)
- [Revised implementation plan](docs/REVISED_SLAM_PLAN.md)
- [Four-person handoff index](team_handoff/README.md)
- [Shared build contract](team_handoff/SHARED_BUILD_CONTRACT.md)
- [Official participant problem statement](team_handoff/reference/problem_statement.md)

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
(`code/slam/pipeline.py`); the frozen `plan(context)` stays a stub, and the pipeline calls the
additive `plan_case(context, bundle)` instead. See "Run the pipeline" below.

## Run the pipeline

Everything runs offline with the default `fake` provider: no API key, no network, no spend. The
pipeline makes no model call, and the 11 screenshots are read with Tesseract OCR, which is
installed in the Docker image (a plain Windows/macOS Python run cannot OCR them).

1. Put the participant files in `dataset/` (`deletion_requests.csv`, `user_identities.csv`,
   `user_audit_log.csv`, `system_activity.csv`, `deletion_rules.csv`, `evidence_files.csv`,
   `evidence/`). `dataset/` is gitignored and is not part of `code.zip`.
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

The eight-scene local evidence workspace includes the Identity Constellation, Time Machine and
Decision Chamber, backed by Python reconstruction and planning. Start its API with
`docker compose --profile web up -d --build aftertrace-api`, then run `npm ci` and
`npm run dev -- --port 5173` from `frontend/`. Open http://127.0.0.1:5173.

See [AFTERTRACE setup, design and testing](docs/AFTERTRACE.md). Fictional demo data is labelled;
the separate dataset mode reads the ignored participant `dataset/` folder.

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
