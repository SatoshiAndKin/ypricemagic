# Full suite after the event-loader repair

The full suite at `5f1e9476e7f5452691d378fc351e1807c5119f3f` remains incomplete.
It reaches the unchanged 8 GiB limit after 1,707.35 seconds. Docker records
`OOMKilled=true`, and the cgroup records one OOM kill. There is no final pytest
summary. The runner preserves all available reports before container removal.

The command uses the same Python 3.12 dependency image as the preceding full
runs, a fresh database, and direct Reth archive access:

```sh
PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test
```

The archive probe passes, and all ten configured application extensions load.
The suite collects 1,851 cases and records 433 terminal outcomes: 314 passed
calls, 107 failed calls, nine skipped calls, and three fixture setup failures.
The setup failures report the missing `async_uni_v1` fixture, also present in
earlier baseline evidence. The 107 call failures comprise 94 configured
timeouts, ten contract reverts, two zero-supply divisions, and one assertion.
Raw test IDs, input blocks, messages, and traces remain in the event report.

The run reaches the Uniswap tests after earlier pricing work. Its last recorded
case is the Curve gauge check, which times out. That late timeout does not
identify the owner of subsequent memory growth. The last process RSS sample
is 8,403,996,672 bytes; the final cgroup peak is 8,589,934,592 bytes. These
measurements describe different accounting scopes.

See [the summary](after/summary.json) for exact source identity, dependencies,
command, effective resource limits, memory/OOM counters, elapsed time, and
sampled descriptor counts. The earlier full runs remain in
[requester-full-suites](../requester-full-suites/README.md).

The event repair reduces historical raw-log and pending-write retention in its
controlled workload and diagnostic profile. It does not resolve the full-suite
OOM. A separate Uniswap allocation profile will identify the remaining growth.
PR #43 stays draft. Native/public pricing and mainnet audit validation remain
incomplete. Container limits stay at 8 GiB, no swap, four CPUs, and 512 threads
or processes.
