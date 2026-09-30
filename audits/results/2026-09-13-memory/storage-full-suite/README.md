# Full suite after the storage repair

Validation is incomplete. The required Python 3.12 `make test` run reaches the
unchanged 8 GiB limit. Docker records `OOMKilled=true`, and the cgroup records one
OOM kill. The runner preserves the final container state and reports. It does
not start the native, public pricing, or audit sequence after this failure.

Source: `1657cdcf4c00072178cd9828341bdf3dd7e8f215`.
The source archive is
`dabe88d53f8100dc016d4b9e4d0c5cd393d45afd8dabe879ad6bd0f56cb700bd`.
The dependency image is
`sha256:0fb5880df36df7c1c86b5772a5cb426fca4770df349007a069bea09bd4b8529d`.
The run uses direct archive Reth, a fresh database, and the same image as the
prior original, pre-optimization, and event-repair full suites.

```sh
PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test
```

| Measure | Result |
| --- | ---: |
| Collected cases | 1,857 |
| Recorded terminal outcomes | 1,240 |
| Passed calls | 893 |
| Failed calls | 330 |
| Skipped calls | 14 |
| Failed setup phases | 3 |
| Elapsed seconds | 3,639.603956 |
| Cgroup peak bytes | 8,591,007,744 |
| Cgroup OOM kills | 1 |
| Command exit status | 2 |
| Maximum sampled file descriptors in one process | 122 |

The cgroup peak includes brief accounting above the configured hard limit of
8,589,934,592 bytes. Swap remains disabled, CPU quota remains four CPUs, and the
process/thread limit remains 512. The run misses the target of less than 7 GiB.
All ten configured native extensions load, and the archive probes pass before
pytest starts. No final pytest summary exists. More observed cases than in the
prior OOM run do not establish complete coverage or successful validation.

The 333 observed failed call/setup outcomes contain 139 configured timeouts,
71 TypeErrors, 110 assertion failures, three ContractLogicErrors, two division
by zero errors, three missing-fixture errors, and five yPriceMagicErrors.
[Raw events](pytest-events.jsonl) retain full failure text. The
[summary](summary.json) classifies cooperative cancellation messages containing
`Test took too long` as configured timeouts. Pytest's rewritten `assert` messages
remain assertion failures even when their text omits the exception class name.

The [failure comparisons](failure-comparisons.json) use test IDs and exact error
messages. Of 385 common observed IDs against the event-repair OOM run, 18 change
from pass to fail and 18 from fail to pass. The pre-optimization comparison has
368 common observed IDs, with 15 pass-to-fail and 17 fail-to-pass changes. The
original baseline has 367 common observed IDs, with 20 pass-to-fail and 17
fail-to-pass changes. The reports also list IDs observed on only one side.
None of these incomplete baselines can prove full failure equivalence.

The console contains 284,629 bytes, with zero expired output. Structured reports
remain separate. The private console also retains one registered SIGUSR1 stack
dump during memory pressure; the supervisor did not interrupt the suite.
See [run metadata](run.json), [command and cgroup state](command.json),
[container state](container-state.json), [log retention](console.retention.json),
and [file-descriptor samples](fd-samples.jsonl).
