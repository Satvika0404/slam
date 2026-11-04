# Evidence pattern diagnostics

Detection-rule version: `1.0.0`

Findings: 1

Findings are advisory; heuristic reachability is not a probability.

## Findings

### INCOMPATIBLE_OBSERVATIONS (error)

Different states share system/resource/category/scope at 2026-01-01T00:00:00+00:00.
- Stable ID: `cb126be795491a2a3b93e389`
- Sources: synthetic-a
- Observations: 1111111111111111111111111111111111111111111111111111111111111111, 2222222222222222222222222222222222222222222222222222222222222222
- Resources: resource:accounts:synthetic-user

## Impact estimate

Direct cases: unknown
Direct resources: resource:accounts:synthetic-user
Potential systems: none
Potential resources: none
Coverage gaps: none

### Assumptions

- Reachability follows explicit active edges only.
- A finding is diagnostic evidence, not a policy or deletion decision.
- Identity validity uses change timestamps and current snapshot update times.

### Unknowns

- Case attribution requires supplied CaseContext objects.
- Unobserved systems and missing graph edges cannot be inferred.
