# Insight layer and console

Status: built 2026-11-05 on `main` 21a90f7. Everything here reads what the deterministic pipeline
already decided. It never changes `output.csv` (sha256 `55fabff2...edb81` before and after), a normal
run still makes 0 model calls, and no model decides a status or a step.

## What it does

| Stage | Tool | Question | Code |
|---|---|---|---|
| 1. Audit | the existing pipeline | What is true at `audit_at`? | `code/slam/pipeline.py` (`audit_cases`) |
| 2. Predict | LightGBM | From the workflow's claims alone, which deletions will fail? | `insight/predict.py` |
| 3. Discover | DBSCAN | Which failure patterns recur, and which are unseen? | `insight/patterns.py` |
| 4. Connect | Neo4j and NetworkX | Which active links can write data back into a cleaned system? | `insight/graph.py` |
| 5. Explain | Groq language model | Why did it fail and how is it fixed? | `insight/explain.py` |
| 6. Show | `dashboard/` | The Ghost Data Console, six tabs | `dashboard/*` |

The System graph tab also has a deletion simulation panel: delete systems in the graph and it recomputes every case's answer in the browser, showing output.csv before and after and the flagged-record database as an original and a modified table. Deleting a retained store (rule 12 to 14) is flagged as a retention break and turns affected cases INCOMPLETE. It is a simulation: nothing is written and Neo4j is not queried from the page.

Isolation Forest is not used: the audit labels are exact, so there is no unlabelled-anomaly problem.

## Run it

```bash
python dashboard/build_data.py                      # topology and activity statistics (host Python with pandas, scipy)
docker compose --profile graph up -d neo4j          # optional; without it NetworkX answers the same queries
docker compose run --rm -T -e SLAM_MODEL_PROVIDER=groq -e SLAM_MODEL=qwen/qwen3.8-27b slam-dev python code/main.py --dataset dataset --insight --insight-llm 80
python dashboard/build_page.py                      # writes dashboard/ghost-data-console.html
```

Without `SLAM_MODEL_PROVIDER=groq` the insight stage still runs and every explanation is rule-based.
Neo4j needs `NEO4J_URI=bolt://neo4j:7687` and `NEO4J_PASSWORD` (8+ characters) in the uncommitted `.env`.
Replies are cached in `.slam-cache/insight_explain.json`, so a rerun costs no tokens.

## Live mode

The published artifact is a static page: it shows preprocessed data and cannot run Python, Neo4j or
a model. For live numbers run the local server, which serves the same page and re-runs the real
stages for whatever you delete in the graph:

```bash
scripts\run_console.cmd      # Windows
scripts/run_console.sh       # macOS, Linux, Git Bash
```

The launcher prepares `.env`, starts Neo4j and the console container (which builds any missing
dashboard file, audits the cases once and serves everything) and opens http://127.0.0.1:8765. The
README section "Run the console on your machine" lists the options. The same console can be started
by hand with `python code/main.py --dataset dataset --console --serve-host 0.0.0.0` inside the
container, or `--serve` when the dashboard files already exist.

Delete systems in the System graph tab, then press **Run live analysis** in the simulation panel.
The server, in order: re-audits every case for the deletion (`facts.apply_deletion`), runs
`DETACH DELETE` for those systems in Neo4j and re-queries every recreation path (cross-checked with
NetworkX), retrains LightGBM on the new labels, re-clusters with DBSCAN, and asks the language model
to explain the cases whose answer changed (you choose 0 to 40 cases). Progress streams to the page,
then Failure risk, Pattern discovery, the graph paths, the Case explorer and the prompt panel all
show the live results under a banner. "Back to preprocessed data" returns to the stored view.

Example, measured 2026-11-05 after deleting `search_service` and `integration_service`: 281 answers
change (268 incomplete, 240 complete), 383 of 720 flagged records go, the model is retrained
(AUC 0.71 on the new labels, 0.78 before), DBSCAN finds 8 patterns, and the run takes about 2 seconds
plus about 1 second per model explanation. The in-browser simulation gives the same status counts.

Safety: the server listens on loopback unless a host is given, handles one run at a time, caps the
model calls per run (at most 40 cases and the `.env` ceilings), validates every system id, and
refuses any request whose `Origin` is not itself, because a run can spend API tokens. The held-out
check against the 32 published answers is not shown in live mode: a what-if deletion changes the
labels it would compare with.

## What the prompt is

The exact text is generated into `dashboard/insight_prompt.md` on every run: the system message the
Groq adapter adds (it embeds the reply schema), the user prompt template (`explain.USER_PROMPT`,
version `insight-explain-v1`), the reply schema, and two real prompt and reply pairs.

- The model receives the audited case as compact JSON: findings with evidence ids, the ordered
  plan, the failure score with its top drivers, the pattern, and the recreation paths. It never
  receives `request_text`, an email, a name or a phone number.
- It returns `why_failed`, `risk_drivers`, `recreation_risk`, a `runbook` (one entry per
  remediation step, with an action, a precondition and the risk if skipped) and a
  `verification_note`. Temperature 0, JSON mode.
- Every reply is checked before use: the runbook must contain exactly the audit's remediation step
  numbers in order, and every evidence, resource and system id in the text must appear in the case
  facts. A reply that fails is replaced by rule-based text from the same facts and the case is
  marked as such.

## Measured on the real data (2026-11-05)

Predictor, 508 audited cases, labels = the audit's verdicts, 5-fold out of fold:

| | accuracy | recall | AUC |
|---|---|---|---|
| always predict failure | 69.9% | 100% | n/a |
| trust the reported status | 55.7% | 54.1% | n/a |
| LightGBM | 72.2% | 83.4% | 0.78 |

Held out, the 32 public samples (never trained on, scored against HackerRank's published answers):
LightGBM 71.9% accuracy against 53.1% for trusting the report; the audit itself agrees with the
published answers on 90.6%.

Of 254 cases the workflow reported COMPLETE, 163 (64%) are incomplete.

Language model (`groq:qwen/qwen3.8-27b`): 80 incomplete cases explained, all 80 passed the grounding
check; the other 275 incomplete cases use rule-based text. The full batch used 77 live calls (3 came
from cache), 93,486 input and 30,212 output tokens, 93 rate-limit events absorbed by the four-key
rollover, ceilings 120 calls and 150,000 tokens. Neo4j 5.26 and NetworkX returned identical paths for
all 12 graph queries.

## Limits

- The predictor is a triage signal, not a verdict. Claims carry limited information, and its labels
  are the audit's own, so every number above is agreement with the audit, not accuracy on hidden
  answers. Four date-arithmetic features were dropped after repeated cross-validation showed they
  only added variance; that choice was made by looking at the CV scores, so the held-out samples are
  the unbiased check.
- Failure type cannot be predicted from claims: it is right 80% of the time against 82% for always
  guessing "record still present". RESTORE_RISK scores below chance (AUC 0.42, 26 cases).
- Recreation paths come from the system topology. They are risks to check, not findings, and never
  appear in `output.csv`.
- The topology in `dashboard/build_data.py` is a curated list of observed and inferred links.
- Only 80 of 355 incomplete cases have a model-written explanation. More needs a higher call and
  token ceiling in `.env`.
