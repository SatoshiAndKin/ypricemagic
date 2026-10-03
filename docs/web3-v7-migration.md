# Immutable Web3 v7 native stack

This follow-up retains merged pricing master
`9fdfeb101751a1d82eb41dccb87c8c06fbac9e75`, including its latest pricing,
discovery, canonical log pagination, indexed inventory and cold-state repairs.
Web3 v7 is the only supported Web3 major version.

## Immutable dependencies

Original migration acceptance used pricing
`8c8387ec15f4f8a119214df5971f10b79cfb6962`. Current dependency pins are:

| Dependency | Revision |
| --- | --- |
| dank-mids | `33d64a962a2ff2a60f4ddb0d1d17e6b0fbbd89c0` |
| Brownie | `7e529be8dfc1afa7bda2d6660c8a11c59a653a6e` |
| evmspec | `31c8540a14228ca49c77c19d565a6aaee3d0079f` |
| cchecksum | `fff7e1fe87f4679ec96de1cebb1cdd8f5e94be44` |
| mypy/mypyc | `18a37e099bba69872e38adaee3319c125c97048e` |

Existing immutable ez-a-sync, aiosqlite and cachebox native repairs are retained.
The cchecksum backport owns its normalization buffer through scalar/bulk conversion
while retaining the ABI stack's 0.4.4 requirement. Evmspec retains optional
transaction `blockTimestamp` and replaces unavailable isolated-build requirements.
Python 3.11–3.13 Linux ARM64 constraint files record the immutable native graph.

## Runtime behavior

The code cache uses Web3 v7's middleware class interface and retains the public
`getcode_cache_middleware` builder and latest-only cache/retry behavior.
Historical, pending and hash/canonical selectors bypass the cache. POA uses
`ExtraDataToPOAMiddleware`.

Bounded reserve/code/log reads use Web3 v7's request encoder/decoder and provider
configuration with one owned aiohttp session per attempt. Headers, authentication,
timeouts, force-close connections, exact IDs and hash/canonical parameters are
preserved. Completed, failed and cancelled attempts close their sessions. This
avoids Web3 7.16's cancellation-unsafe session-cache lock. Existing pricing retry
windows and log-range splitting continue to control attempts.

Block references normalize integer/bytes and POA hex quantities/hashes while
retaining canonical hash identity. Pricing recognizes Dank's typed
`ExecutionReverted`, including legacy invalid opcode/jump errors, and propagates
unrelated failures. Synthetic discovery fixtures clear only their three test
factories; unrelated metadata survives.

Compound oracle reads use Dank's existing `no_multicall` policy. Simulating
IronBank interest accrual before a Curve-backed oracle read changes its exact
result inside a multicall. The regression reproduces that drift before the repair.
The fix retains JSON-RPC batching, block selectors and retry/error handling; three
complete exact-block token-list replays pass unchanged. The DEBUG-only `y.stuck?`
logger retains its default five-minute interval.

A separate [Pony repair](https://github.com/SatoshiAndKin/ypricemagic/pull/50)
serializes event-page query construction around translator-cache invalidation.
Database reads and decoding remain parallel, with unchanged pagination and ranges.
Its two-thread regression reproduces the same failure on unmodified current master.

## Validation

- Complete freshly compiled Linux ARM64 pricing suite: **2,664 passed, 17 skipped**,
  with `PYTHONMALLOC=debug` and fault handling enabled. All ten declared pricing
  native modules were rebuilt; compiled imports are checked separately from source.
- Separate extension-free source profile: **308 passed**, covering **40/40 changed
  executable runtime statements (100%)** against current master. Coverage spans
  the complete cooperative pytest lifetime, including work after pytest-cov teardown.
- Strict mypy: **246 source files**; all 13 hosted pricing checks pass, including
  Linux/macOS/Windows Python 3.11–3.13 typing, build, lint and CodeQL.
- SDK: **33 archive integration cases** passed. Its runtime repair also passed all
  37 hosted native build/unit/import jobs on Linux/macOS/Windows Python 3.10–3.13,
  including the repaired macOS 3.10 shutdown crash and debug-allocator checks.
- Existing Brownie fork: **77 native bytecode-memory/explorer-timeout regressions**
  passed. cchecksum's native owned-buffer regressions passed all **22 cases**.
- Fresh isolated evmspec wheels on macOS and Linux ARM64: **365 passed, two existing
  trace-enum failures** on each. The original compiled schema revision reproduces
  exactly those two failures; transaction timestamp, block and data repairs pass.
- Final locked Linux ARM64 server image: **346 passed plus four subtests**, mypy,
  Ruff, formatting, deptry and lock checks. All eight real Ethereum HTTP scenarios
  passed, including ordered duplicate batches, single/mixed amounts and spot-cache
  preservation. Native exact-amount calls retain raw amounts 1,000,001 and 2,000,001
  with Ethereum block 18,000,000's canonical hash.

The full archive suite uses a populated catalog snapshot, eight concurrent cases,
unchanged assertions/retries and the default 10,000-call multicall limit. The SDK's
archive batching workload separately caps groups at 1,000; controlled HTTP tests
verify default thresholds. These runs do not establish empty-cache startup timing.
Final Base acceptance is deferred at the user's explicit request after provider
quota exhaustion. The SDK and original pricing/server migration PRs have been
merged. This follow-up does not deploy the applications; original draft branches
remain available.

## Merged SDK dependency

Build requirements, runtime requirements and Python 3.11–3.13 native constraints
now use merged dank-mids master `33d64a962a2ff2a60f4ddb0d1d17e6b0fbbd89c0`.
This retains the reviewed synchronization and hash-header RPC error repair,
preserving provider error code, message, arbitrary data and request context.
Current pricing master, including the merged concurrent event-query repair,
is retained. Existing native repair pins and pricing behavior are unchanged.
The acceptance counts above describe the original migration. This follow-up
passes the complete freshly rebuilt Linux ARM64 suite (**2,664 passed, 17 skipped**),
strict mypy (**246 files**) and all **11 hash-header error cases** through the
installed native SDK controller. Compiled import audits verify all ten pricing
extensions, the SDK controller and vendored aiolimiter, Brownie, evmspec and
ez-a-sync. Direct-URL metadata verifies the immutable SDK and native repair pins.
The debug allocator and the same archive/cache/concurrency boundaries apply.
