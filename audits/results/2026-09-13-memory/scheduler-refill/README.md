# Cooperative scheduler refill

The owning dependency now fills all free test slots after it reports a completed
batch. Previously it started only one queued test before it waited again. This
left available slots unused. The repair preserves FIFO order, cancellation
cleanup, the configured concurrency limit, and its default of 100.

Owner commit: `17677c7145d24c36917036877681eb83225ccdb3` in
[SatoshiAndKin/pytest-asyncio-cooperative PR #1](https://github.com/SatoshiAndKin/pytest-asyncio-cooperative/pull/1).
The plugin source SHA-256 is
`3faeeccf9979f3f15e60bcc963433b29bd2413c28e7fdbe02e41079c6df10cb7`.
The dependency owns the repair. Application code applies no scheduler patch.

Three new regressions require a second batch of three tests to reach a barrier
when the first batch has completed, failed, or been cancelled. All three fail
with the original plugin. All ten focused tests pass on Python 3.11, 3.12, and
3.13 after the repair. The one-second barrier guard detects a stalled batch;
it is not a performance gate.

| Full dependency suite | Collected | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Original, Python 3.12 | 100 | 82 | 2 | 16 |
| Repaired, Python 3.12 | 103 | 85 | 2 | 16 |
| Repaired, Python 3.11 | 103 | 85 | 2 | 16 |
| Repaired, Python 3.13 | 103 | 85 | 2 | 16 |

The two full-suite failures remain `example/hypothesis_test.py::test_a`
(Hypothesis function-fixture health check) and
`tests/test_fixture.py::test_tmp_path` (child-test stash failure). The rendered
count dictionary has a different field order on some versions. The test IDs and
failure causes match. Raw events and errors remain in each run directory.

Before and after Python 3.12 runs have byte-identical unit dependency freezes.
The unit lock is `tools/validation/cooperative-owner-dependencies.lock` at the
repository root. Each repaired owner run loads the source hash above. All runs
completed within the selected Docker limits without OOM. The [application pin matrix](../ownership-pinned/README.md) confirms the ordinary
installed dependency revision and plugin hash on all three Python versions.

This scheduling repair does not count as a production pricing memory reduction.
Earlier fixture-retention measurements retain their original source boundary.
See `comparison.json` for commands, source archives, exact outcomes, elapsed time,
and raw failure messages. Text normalization manifests record whitespace changes;
private endpoint values are removed from published evidence.
