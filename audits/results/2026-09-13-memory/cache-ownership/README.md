# Cache ownership and native dependency repair

The controlled cache workload uses 92% less peak RSS after the repair. The
original wrapper retains every cache key through an idle per-key lock. The
repaired wrapper releases each lock after its last registered caller exits.
Cache eviction, cached values, independent result copies, shared failures, and
cancellation isolation pass the owning regression tests.

This result covers cache ownership. Full pricing validation remains incomplete.
The application pins the owning repair at
`10be25afe46afb32c8135db4d1b8e2d94431b9c1`. The remaining full-suite and
real-node comparisons are pending.
The separate unbounded topic-result cache remains visible in the diagnosis.

## Diagnosis

The Uniswap profile at production revision
`1657cdcf4c00072178cd9828341bdf3dd7e8f215` reached the 8 GiB container limit after
2,191.19 seconds. It collected 171 cases and recorded 146 call failures and three
setup failures before the OOM kill. It produced no final pytest summary.
Docker recorded `OOMKilled=true`; the cgroup recorded one OOM and one kill.

The last of 32 allocation samples shows 505,406 completed cache tasks with integer
results. The `get_hash_dbid` value cache held 10,000 entries while its lock table
held 514,022 entries, including 513,959 idle locks. The final cache-owner name for
the completed integer tasks is obscured by Pony's wrapper around a native
callable. This report does not infer a confirmed owner from that wrapper name.

The earlier bulk-write and event-buffer repairs remain effective: this profile
shows no growing SQL text cache and no persistent database write backlog.
[Raw diagnosis and OOM records](diagnosis/summary.json) retain the partial result.
The allocation run includes profiler overhead and is not a final timing result.

## Why repair the current dependency

The application previously used cachebox 5.2.3 under `>=5.2,<6`.
It now pins [the owning repair](https://github.com/SatoshiAndKin/cachebox/pull/1)
at a complete source revision in its runtime, build, and validation dependencies.
The owning control executes against the installed native distribution. The
latest published 6.2.7 release passes six of the first eight ownership cases. It
still retains a key after a shared failure and propagates one owner's
cancellation to a surviving waiter. Version 6 also changes cache APIs, including
the TTL constructor. The repair therefore preserves the version 5 contract.

The sources are the [5.2.3 release](https://pypi.org/project/cachebox/5.2.3/),
[6.2.7 release](https://pypi.org/project/cachebox/6.2.7/), and
[version 6 migration guide](https://awolverp.github.io/cachebox/migration).
Both releases use the MIT license. The
[published-version comparison](published-controls/comparison.json) includes all
exact failure messages. All eight cases execute; none is skipped.

## Python wrapper repair and initial tests

The owning repair registers each caller before it acquires the per-key lock.
A registry guard protects this operation across threads. The last caller removes
only its own state and drops the stored exception reference. An old caller
cannot remove a new owner that started after a cache clear. Cancellation while
waiting also releases the caller's registration.

The native comparison uses the same Rust compiler, build backend, and 35 locked
third-party Rust packages. The upstream tag contains a stale root package version
in `Cargo.lock`. `cargo update --workspace` corrects that version from 5.2.1 to
5.2.3. Both builds use that exact corrected lock. No third-party Rust dependency
changes. [Lock verification](build/cargo-lock-verification.json) and the
[shared lockfile](build/Cargo.lock) record this correction.

The initial wrapper-only comparison has the same native core SHA-256 in both builds:
`7e3beb62eedbd728639281dbc1b39c376ddfc62c1603f49b67c5c7d05e6b6a1f`.
Only the installed Python `utils.py` differs. The wheel hashes differ because
that file changed. All other installed application dependencies and all executed
comparison helpers match exactly.

| Python 3.12 check | Before | After |
|---|---:|---:|
| Ownership regressions | 2 pass, 8 fail | 10 pass |
| Full owning Python suite | 274 pass, 8 fail | 282 pass |
| Focused application suite | 270 pass | 270 pass |
| Configured mypy diagnostics | 1,922 | 1,922 |
| Compiled application modules | 10 of 10 | 10 of 10 |

[Native test results](native/comparison.json),
[application type comparison](application/type-comparison.json), and
[application reports](application/cache-application-focused/run.json) preserve
exit status and detailed evidence. Mypy remains nonzero because of existing
diagnostics; its 1,917 rendered diagnostics have no additions or removals.
The initial Python 3.11 run reached a native garbage-collection deadlock. That
run remains incomplete. The final repair below fixes that separate defect.

## Native collection repair and final tests

A cache insertion or equality check can call Python while it holds the native
cache mutex. If Python starts garbage collection in that callback, the original
`__traverse__` waits for the same mutex. The only thread cannot release it.
The recorded Python 3.11 stack shows this exact state during the existing suite.

The repair uses nonblocking traversal for all seven cache types. This follows
the owning version 6 design. A traversal skips a cache that already owns its
mutex. Idle cache cycles still collect. The regressions force collection from
size and equality callbacks and verify the exact stored value. Seven additional
cases prove that idle cache/value cycles release their objects.

| Final check | Python 3.11 | Python 3.12 | Python 3.13 |
|---|---:|---:|---:|
| Ownership and native GC regressions | 31 pass | 31 pass | 31 pass |
| Full owning Python suite | 303 pass | 303 pass | 303 pass |
| Focused application suite | 270 pass | 270 pass | 270 pass |
| Compiled application modules | 10 of 10 | 10 of 10 | 10 of 10 |
| Added configured mypy diagnostics | 0 | 0 | 0 |

[Source verification](native-gc/source-verification.json) confirms that all 43
committed dependency files match the source tested on each Python version.

All three native builds pass Rust formatting, `cargo check --locked`, and the
owning `make test-rs` command. All application runs pass the historical archive
probe. Mypy still reports 1,922 existing errors. The
[final matrix](native-gc/matrix.json) and
[type comparison](native-gc/type-comparison.json) preserve those limits.

The extended published controls run all 31 cases. Version 5.2.3 has 14 native
GC timeouts and eight ownership failures. Its seven idle-cycle cases pass.
Version 6.2.7 has three ownership failures. Nine further version 6 failures
come from changed TTL and size-callback APIs; they do not prove a GC defect.
[Exact control results](native-gc/controls/comparison.json) preserve this distinction.

The final repair includes native changes. Its core hash therefore differs from
the initial wrapper-only pair. Repeated measurements retain the same exact
results, 64 keys per function, 24,641,536-byte median peak RSS, and 709,728-byte
Python allocation peak. Median elapsed work is 0.215325 seconds. All application
dependency versions except the repaired cachebox wheel match the original
controlled run. [Final comparison](native-gc/turnover-comparison.json) records
all hashes, helper differences, cache hits, and zero RPC work.

## Pinned application builds

The shared runner builds the exact Git revision with Rust 1.98.1 and the pinned
maturin 1.15.0 backend. BuildKit retains the same 8 GiB memory, no-swap, four-CPU,
and 512-process limits, and stops before each application run.

| Python | Focused passes | Test container peak bytes | Total build/run seconds |
|---|---:|---:|---:|
| 3.11 | 270 | 1,127,157,760 | 250.58 |
| 3.12 | 270 | 1,176,743,936 | 228.64 |
| 3.13 | 270 | 1,170,767,872 | 237.99 |

Each run uses the same application source archive, passes its archive probe,
and loads all ten configured compiled modules. All other application package
versions match the earlier storage matrix. The configured type check has no
added or removed semantic diagnostics. These type checks still exit nonzero.

[The pinned matrix](pinned-application/comparison.json) records dependency
changes, effective limits, elapsed time, peak memory, source revision, and all
module paths. Separate installed-distribution probes verify the complete Git
commit ID, the native extension suffix and hash, and all Python source hashes.
The installed Python files match the owning 303-case test matrix exactly.

## Controlled memory comparison

Each function processes 32,768 distinct keys in 128 batches. Each key owns 4 KiB
of data. The synchronous and asynchronous caches each have capacity 64. Every
cold request has an immediate warm repeat. The workload checks the exact square
result and mutates each returned dictionary to prove that the cached child
result stays unchanged. Each function performs 32,768 computations and has
32,768 cache hits. The workload makes no RPC calls.

Three separate unprofiled runs measure process RSS and elapsed work time. A
separate run measures Python allocations. The workload does not clear caches,
force garbage collection, or restart during turnover. Its object observer uses
one live counter per function; it does not retain a weak-reference list for
every key.

| Measure | Before | After |
|---|---:|---:|
| Median peak RSS, bytes | 318,275,584 | 24,641,536 |
| Median elapsed seconds | 0.274174 | 0.213191 |
| Python peak allocation, bytes | 291,998,371 | 709,728 |
| Python retained allocation, bytes | 291,992,277 | 703,634 |
| Retained keys per function at the end | 32,768 | 64 |
| Cache values per function at the end | 64 | 64 |

The repaired cache retains exactly 64 keys after every batch. Across the last 96
batches, current RSS spans at most 45,056 bytes within each repaired timing run.
The observer's fixed 128-row report contributes to that small increase. The
result SHA-256 matches in every run:
`bb7e9477d87b41ac5e562f1cb5f4e838133612eabd95cf808d6faee130b9fcf6`.

[All timing and allocation samples](turnover/comparison.json) and
[dependency identity](turnover/dependency-comparison.json) accompany these
measurements. This controlled workload uses large keys to expose ownership; its
RSS reduction is not an estimate for a full pricing run.

## Incomplete development checks

The development records retain the first helper startup failure, two runs that
skipped async cases because the required plugin was missing, the first profiler
type error, and the native build that rejected the stale Cargo lockfile, the native Python 3.11
deadlock, and two Rust compile failures before the final iterator guard repair. These
runs are not passing validation. The final dependency controls use an isolated,
locked pytest environment with the required asyncio plugin. Each run records
console retention, effective resource limits, source identity, and final state.

Copied text reports remove trailing whitespace. The
[normalization manifest](text-normalization.json) records their hashes before
and after this formatting change. Private original reports remain preserved.
