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

The three teammate modules intentionally raise `NotImplementedError` until their owners replace the
stubs. This is a dependency boundary, not a claim that the challenge solution is complete.

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
