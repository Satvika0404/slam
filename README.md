# SLAM — Ghost Data Still Exists

SLAM is the planned portable, AI-assisted deletion-audit agent for the HackerRank Orchestrate challenge. The latest approved architecture uses deterministic evidence and policy logic with bounded API-based structured extraction. It does not use Ollama, `llama.cpp`, local model weights, or a GPU-specific development path.

## Start here

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
