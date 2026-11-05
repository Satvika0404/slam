# AFTERTRACE dashboard integration

AFTERTRACE uses one connected workflow as its primary product surface. A user connects one
dataset or mapped SQLite snapshot, submits one deletion request, follows the evidence graph,
reviews the exact treatment plan, executes only against an isolated working copy, and sees
read-back verification in the same interface.

The newer cohort dashboard is retained as a deep-analysis tool and its strongest capabilities
are also available inside the primary Intelligence Console:

| Capability | Primary surface | Truth boundary |
| --- | --- | --- |
| Identity attribution and evidence | Connected workflow | Links require explicit or validated evidence; candidates are labelled |
| Bounded self-healing | Connected workflow | A recovery is shown only after validation; future promotion remains review-gated |
| Deletion and redaction animation | Connected workflow | Animation follows backend events and fresh read-back, never a timer-only simulation |
| Sync recreation experiment | Connected workflow | Two isolated copies measure enabled and disabled sync behavior |
| Failure-risk prioritisation | Cohort insights | Five-fold out-of-fold LightGBM score; triage only, never an audit verdict |
| Recurring failure signatures | Cohort insights | DBSCAN over deterministic audit findings; unmatched cases remain noise |
| Recreation paths | Cohort insights | NetworkX over configured active topology; paths are risk context, not proof of a subject record |
| Six-tab analytical console | Port `8765` | Read-only exploration and simulation; it does not mutate the audit dataset |

## Why the interfaces were not replaced

The connected workflow is stronger for a judge demonstration because every phase refers to the
same request, graph objects, evidence and sandbox receipts. The analytical dashboard is stronger
for population-level comparison. Combining their capabilities while keeping those scopes visible
avoids two misleading outcomes: presenting a model score as proof of deletion, or presenting a
topology simulation as an executed deletion.

## Honest minimum for cohort scoring

The embedded cohort panel does not train a model unless the run contains at least ten audited
cases, both outcome classes, and at least five examples in each class. Smaller runs show an
explicit unavailable state and leave the deterministic audit usable. This prevents attractive but
meaningless cross-validation metrics on a one-request database demo.

## Run surfaces

```powershell
docker compose up --build aftertrace-api aftertrace-ui
docker compose --profile console up --build console
```

- Connected workflow: `http://localhost:4173`
- Deep analytical console: `http://localhost:8765`

Neither surface needs an API key for deterministic auditing, execution experiments, self-healing,
pattern discovery, risk scoring or recreation-path analysis.
