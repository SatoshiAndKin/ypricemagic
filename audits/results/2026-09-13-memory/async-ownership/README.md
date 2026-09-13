# Task argument, cancellation, and ownership repair

The [owning repair](https://github.com/SatoshiAndKin/ez-a-sync/pull/1) at
`000e4f24466ddc01abc6bb1a12cc429cbeea5813` binds constant arguments before mapped
keys, executes callable bodies once, and releases unused wrappers. The shared
exception-result wrapper uses standard asyncio cancellation behavior. No pricing
API or task-concurrency setting changes.

All 88 focused cases pass in the native Linux ARM64 Python 3.12 build. The complete
733-case suite changes 699 passes / 33 failures / one skip into 717 passes /
15 failures / one skip. The same 15 assertions fail on both sides. Fourteen contain
elapsed measurements; the comparison preserves their exact values and thresholds.
Sixteen fixed failures cover this repair. Two other passes come from upstream
mypy-plugin changes already present in the branch base.

Configured mypy changes 307 errors to 300, with no added rendered diagnostic.
The annotation repair describes the dynamic callable boundary and adds no ignore.
The test import probe confirms native function, bound-method, and completion
extensions. Full raw pytest XML and type output accompany the summaries.

Three unprofiled samples per side use the same helper hashes, commands, compiler,
Brownie, Cython, and supporting dependencies. Only the owning task package differs.
Each sample creates 1,000 callables with 65,536 bytes of captured state.

| Measurement | Before | After |
| --- | ---: | ---: |
| Median process RSS | 98,758,656 bytes | 32,768,000 bytes |
| Retained callables | 1,000 | 0 |
| Median elapsed time | 0.020863 s | 0.001234 s |
| Separate retained Python allocations | 65,982,172 bytes | 89,600 bytes |

No forced collection or within-workload restart occurs. This small ownership probe
makes no RPC calls; its short timings do not establish full pricing latency.
The weak-key cache previously stored each callable as its own strong value.
Async function objects already own their cached wrappers, so the extra cache was
redundant. Existing unwrap identity/reuse checks still pass.

`final/` contains the matched comparison and the final native build/tests.
`exploratory-notes.md` preserves the earlier probe's extra-build-tool limitation.
The shared runner now records actual installed dependencies before execution and
keeps the image's original build manifest separately. The full pricing matrix,
Popsicle allocation probe, and real-node checks remain separate gates.
