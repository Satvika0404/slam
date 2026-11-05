# Reconstruction fixtures

The reconstruction tests build small participant-visible contract objects in
`tests/reconstruction/conftest.py`. They cover historical identity, cutoff
filtering, contradictory replicas, data-flow recreation, restore risk, cycles,
provider failure and input-order determinism. Expected results are declared in
the tests rather than derived by production reconstruction code.
