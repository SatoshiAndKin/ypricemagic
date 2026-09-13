# Historical allocation check with repaired dependencies

The native Linux ARM64 Python 3.12 run completes all 19 test outcomes and teardown
without an OOM event. Container peak is 1,465,389,056 bytes, below the 7 GiB target.
Python allocations at session finish are 212,137,214 bytes, with a peak of
231,678,298 bytes. The sampler preserves collection, pending work, and teardown.
All ten configured application extensions load. The direct NUC Reth archive
preflight passes.

Two cases pass: the non-Popsicle case and pricing for
`0x989442D5cCB27E7931095B0f3165c75a6def9bc3`. The other 17 cases reach the unchanged
600-second timeout while pricing historical blocks. The run exits 1. It completes
execution and reporting, but it does not pass the pricing gate. The exact errors,
logical RPC counters, task counts, and allocation groups remain in these records.

The earlier run had 18 argument-binding failures before those price requests
executed. It retained 6,788,727,784 Python bytes and peaked at 7,922,294,784 container
bytes. The repaired run no longer shows the large intermediate bytecode-buffer
allocation group. These are diagnostic observations, not a controlled latency or
RPC comparison: dependencies and completed work differ, historical test blocks use the existing
selection up to the current chain height, and both runs include tracemalloc overhead. Separate owning regressions establish buffer and callable
release on identical inputs.

The full-suite comparison and final source-pinned builds remain separate gates.
No timeout, concurrency setting, or test assertion was reduced for this run.
