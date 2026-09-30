# Historical profile after the shared topic cache

This run is incomplete. The container reached its 8 GiB limit and recorded one
OOM kill after 1,915.68 seconds. Docker reports `OOMKilled=true`. The final
pytest summary and session-finish allocation report are missing. No limits were
raised.

The source is commit `8d1964f6dfe2e5a39164c2d51a426b21dfeaae59`, with the normal
Python 3.12 dependency image that pins the cachebox owner repair. It uses a fresh
SQLite database, the direct Reth archive route, and the unchanged 100-test
cooperative limit. All ten configured compiled modules load, and the archive
probe passes. The selected file contains 171 cases. The run records 130 terminal
outcomes: 122 configured timeouts, five `InvalidFEOpcode` failures, and three
missing-fixture setup failures. No pricing call passes before OOM.

[Exact outcomes and run state](summary.json) remain separate from the
[controlled topic lookup comparison](../topic-cache/README.md). This profile
includes allocation overhead. It cannot establish full-suite peak memory,
completed coverage, failure equivalence, or unprofiled pricing latency.

## Retained state and the final increase

The last complete sample contains 513,802 Uniswap V2 pool instances and 514,327
cached-property state objects. Those states hold 1,027,615 values, two pending
tasks, and two locks. Python retains 819,579,572 bytes and peaks at 867,416,389
bytes in that sample. Process peak RSS is 3,984,863,232 bytes.

The shared topic cache remains at 50,000 IDs. The hash cache remains at 10,000
entries. Their samples contain active owners but no idle locks or stored
exceptions. There is no separate topic result-task cache. Persistent database
write queues remain empty, and the raw historical buffers remain bounded.

Memory then rises beyond the last completed allocation sample. The final
process sample records 7,856,615,424 bytes of RSS; the cgroup subsequently reaches
8,589,934,592 bytes and kills the process. The saved samples do not identify the
allocation that causes this final increase. Further measurement must distinguish
pool-discovery materialization from profiler overhead before selecting another
production repair.

All 33 periodic allocation samples are preserved. No sampler error was reported.
Console output contains 33,098 bytes, with no expired output. The original
private reports remain available; copied text removes trailing whitespace under
the recorded normalization manifest.

## Reth method-probe errors

The GNO `currencyKey()` probe returns JSON-RPC code `-32003` and message
`EVM error: InvalidFEOpcode` at both block 18,000,000 and `latest`. GNO's
`decimals()` call succeeds at block 18,000,000 with the exact value 18.
[Three direct diagnostic requests](reth-method-probe.json) retain IDs, parameters,
and complete responses. They run outside the pricing process and its logical
RPC counters. They do not demonstrate an archive-access failure.

Both `has_method` and `call_reverted` have the same function bodies in the
original PR baseline, the pre-optimization revision, and this run.
[Source comparison](method-probe-source-comparison.json) records that boundary.
It does not establish complete test-failure equivalence.

## Next checks

Validate the existing V1 fixture registration, retain the unchanged test
assertions, and isolate the final memory increase. Full-suite, native quote,
fixed-block public pricing, and mainnet audit comparisons remain required.
PR #43 remains draft.
