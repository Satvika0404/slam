# AI interview preparation

**What it is.** The submission has four parts: `code.zip`, `output.csv`, the `chat_transcript`
(`log.txt`) and an **AI interview**, described in the official README as a *live explanation of your
architecture, approach, and evaluation*. You explain the solution and answer questions; nothing
here can do that for you. Per the README the AI interviewer reads the code and Markdown in
`code.zip` but **not** `.csv`/`.json`/`.sql`/`.log` files, so the evidence for every claim below is in
`.py`/`.md` files (`docs/integration/RCA_ACCURACY.md`, `code/evaluation/evaluation_report.md`).

## 60-second pitch

A deletion audit is a *claims vs evidence* problem. Workflows say "COMPLETE"; the data says
otherwise. The pipeline never trusts a reported status: it rebuilds what was true at `audit_at`
from observations, applies the deletion rules, and only certifies COMPLETE when every copy has the
required treatment and nothing can recreate prohibited data. It is deterministic and makes no model
call; accuracy on the 32 published answers: status 29/32, **0 false COMPLETE**, step F1 0.70.

## Architecture (follow the flowchart)

| Stage | Module | One-line job |
|---|---|---|
| Loaders + ingestion | `slam.ingestion` | 94 files (CSV, JSON, logs, text, SQL, PDF, screenshots via OCR) -> one `EvidenceBundle` with provenance; failures are explicit issues, never "nothing found" |
| Intent | `reconstruction/request_intent.py` | does the text authorize deletion? multilingual, negation and marketing aware; a model may only propose, citing exact text |
| Identity + timeline | `identity.py`, `timeline.py` | current and historical identifiers as of `audit_at`; evidence after the cutoff never changes the answer |
| Relevant records | `ownership.py`, `linking.py`, `absence.py`, `graph.py` | which records belong to the person, which processes can recreate data |
| Policy + steps | `planning/engine.py` | rules -> findings, remediation, verification in the specified order |
| Validate / collect / export | `planning/validation.py`, `pipeline.py`, `evaluation/validator.py` | per-case failure isolation; uncertain never becomes COMPLETE |

## Investigation approach (the story to tell)

1. Run it on the real corpus, not only fixtures; diff every case against HackerRank's answers.
2. Root-cause each difference with data (probes), then fix the cause, never the case.
3. Test hypotheses and reject them with numbers (time proximity, id numbering, ordering).

## Remediation planning

Order is fixed by the spec: operation order of the table, then `system_id`, then `resource_id`.
That gives "disable flows and block restores before changing records" for free. Remediation and
future verification carry an empty `evidence_id`; findings and COMPLETE verification cite a
`file_id`/`activity_id`/`audit_id` captured at or before the cutoff.

## Evaluation (be precise)

- Scored on the 32 public answers only: status 0.906, F1 0.701, exact 11/32, 161/193 steps, evidence
  id right on every matched step. **No answers exist for the 518**, so say so.
- Byte-identical output on a fresh CRLF clone; deterministic under row shuffling.
- Progress was measured step by step: F1 0.335 -> 0.441 (spec order) -> 0.456 (linking) -> 0.701.

## Hard questions, honest answers

| Question | Answer |
|---|---|
| Is the linking overfit to this dataset? | Nothing is hard-coded. Timing windows are learned per (activity type, target system) from explicitly-owned pairs, enabled only after held-out validation with zero wrong, and tested on an invented world. The 32 samples are a proxy; some of their timing differs. |
| Why not use an LLM? | Identity, state and policy must be explainable and reproducible. A model can only propose intent for ambiguous text. The data lacks the link for some records; a model would guess. |
| What are you least sure of? | The 153 COMPLETE answers among the 518 are unverified, and about 17% of expected steps in the samples are still missing (7 teaching cases, 7 ambiguous, 2 delete-vs-redact). |
| Where did you get it wrong? | Invented step order (3% sequence accuracy), a parser that ignored explicit states, and a formatter pass that touched files I did not own; all found, fixed and documented. |
| What would you do next? | A confirmed account-to-owner link from the organizers, or accept status as the main score. |
