# Historical pricing profile after bounded event loading

This diagnostic profile uses the committed event repair and the same
Python 3.12 dependency image as the earlier 29-case Magic/Popsicle profile.
Each run uses a separate database and the existing test concurrency.
It includes allocation profiling and configured timeouts. Some fixtures
query latest state. It does not establish unprofiled pricing latency.

| Measure | Before | After |
| --- | ---: | ---: |
| Container peak bytes | 5477474304 | 4798681088 |
| Maximum sampled Python allocation peak bytes | 1121031591 | 857044735 |
| Python bytes at session finish | 1013244357 | 814117846 |
| Run seconds | 817.8793578147888 | 769.0462410449982 |
| Peak sampled pending insert tasks | 1827 | 3 |
| Peak sampled `evmspec.structs.log.Log` | 519924 | 17733 |
| Peak sampled `evmspec.structs.log.Topic` | 1562088 | 151011 |
| Peak sampled `_asyncio.Task` | 113483 | 157202 |
| Peak sampled `y.prices.dex.uniswap.v2.UniswapV2Pool` | 75781 | 104047 |

Source, commands, dependencies, cgroup events, final execution state,
RPC counts, allocation samples, and exact test/error changes appear in
[the comparison](comparison.json). The before records remain in
[event-backlog/combined-before](../event-backlog/combined-before).

Before pytest summary: `{"collected": 29, "counts": {"call:failed": 19, "call:passed": 10, "setup:passed": 29, "teardown:passed": 29}, "exit_code": 1}`.
After pytest summary: `{"collected": 29, "counts": {"call:failed": 19, "call:passed": 10, "setup:passed": 29, "teardown:passed": 29}, "exit_code": 1}`.

Execution complete: `True`. Docker OOM killed: `False`.
Both runs have ten passes, two zero-supply divisions, and 17 configured
timeouts. Nine Magic block values move with `chain.height`, so only 20
test IDs match. Ten common cases pass in both; two division messages
match; eight timeout messages differ only in elapsed seconds. The
helper hashes differ for run.py, repeat_events.sh, and event_profile.py.
The two event benchmark helpers do not execute in this command; the
runner adds the frozen event fixture. The comparison records all hashes.
The unchanged case count does not establish identical historical input.

The changed profile executes more logical work: 101,346 → 101,911
calls, 3,801 → 4,363 multicalls, 1,471 → 2,407 requester operations,
and 1,786 → 2,651 JSON-RPC batches. Task and processed-pool peaks also
increase. Lower raw-log retention does not imply all retained state is
bounded; the full suite must verify total application memory.

PR #43 stays draft while full-suite and remaining native/public pricing
and mainnet audit validation remain incomplete. Limits stay at 8 GiB,
no swap, four CPUs, and 512 processes/threads.
