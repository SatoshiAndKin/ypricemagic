# Immutable Web3 v7 native stack

This migration starts from fork master `073c7ac8`, retaining its indexed pool
inventory, bounded cold-state reads, historical state retries and pricing repairs.
It supports Web3 v7 exclusively.

The runtime/build pins are dank-mids `fa4b454fb8d33c2f412709da4daca522cd4f7e47`,
Brownie `7e529be8dfc1afa7bda2d6660c8a11c59a653a6e`, and evmspec
`f0df0d9d8e4e7a7000580054ce2c0b6b6193a14c`. The ez-a-sync, aiosqlite,
cachebox and mypy native repair pins are retained. cchecksum is pinned to
`fff7e1fe87f4679ec96de1cebb1cdd8f5e94be44`, which keeps the normalized address
buffer alive through scalar and bulk checksum conversion. Both published 0.4.4
and 0.4.5 expose a freed-buffer read with Python's debug allocator. The backport
retains the ABI stack's 0.4.4 requirement. Python 3.11–3.13 Linux ARM64
validation constraints were resolved anew for these immutable dependencies.

The code cache uses Web3 v7's middleware class interface, retaining the public
`getcode_cache_middleware` builder and the same latest-only cache/retry policy.
Historical, pending and hash/canonical selectors bypass the code cache as before.
POA uses `ExtraDataToPOAMiddleware` directly.

Bounded reserve/code/log reads use Web3 v7's request encoder/decoder and provider
HTTP configuration with one owned aiohttp session per attempt. They preserve
Web3's force-close connector policy, provider headers/auth/timeouts, exact IDs and
hash/canonical parameters. They avoid Web3 7.16's cancellation-unsafe session-cache
lock: cancelling a pending executor lock acquisition can leave the cache locked
and block unrelated later callers. Every completed, failed and cancelled attempt
closes its session. The existing pricing retry window and log-range splitter own
each attempt, without Web3's added automatic retry layer.

Block references normalize native integers/bytes and POA hex quantities/hashes,
retaining canonical hash identity on Base. The stale dict-item typing suppression
for historical multicall state overrides was removed; the required typed-dict
suppression remains. Pricing recognizes Dank's typed `ExecutionReverted`, including
legacy invalid opcode/jump responses, while propagating unrelated failures.

The configured focused native suite passed all 803 cases, including controlled
HTTP cancellation, timeout, recovery with a locked Web3 session cache, batch order,
exact retry counts, canonical selectors, archive-state retries and range splitting.
Strict mypy passed all 241 source files. The dependency image passed all 44 Brownie
compiled bytecode safety and memory regressions. A separate source coverage run
passed all 189 migration cases and covered all 31 changed executable runtime
statements (100%); this is independent of compiled-runtime verification. Live tests
admit eight cases concurrently, preserving the existing 30-second transport deadline.

The immutable Linux ARM64 server image passed health, historical spot prices,
ordered/duplicate batches, single/mixed amounts and spot-cache preservation on
Ethereum and Base. Independent native SDK checks preserved raw amounts 1,000,001
and 2,000,001 and canonical block hashes on both chains. All 333 server tests passed.
Base's first cold amount request hit the unchanged 300-second deadline while its
catalog loaded; the same request passed after catalog loading. These checks do not
prove that empty-cache Base amount requests always finish within that deadline.

The complete native pricing suite remains required. Earlier attempts encountered
validation-VM disk exhaustion and the original archive provider's exhausted monthly
capacity. An independent archive run completed 2,310 passing cases and 17 skips,
with one batch/individual price discrepancy for fOUSG at block 21,578,484. Three
full token-list replays at that exact block and all ten concurrent historical
batch/individual tests passed unchanged. A complete repeat captures that token's
bucket, oracle reads and DEX fallback without relaxing assertions or retry limits.
The independent run uses an encrypted loopback SSH connection to the operator's
archive Reth, a separate populated catalog snapshot, eight concurrent cases and a
1,000-call multicall limit. Default thresholds are verified by controlled SDK tests.
The repeat also exposed synthetic factory metadata retained by discovery tests
from earlier runs. Their fixture now clears only their three test factories before
and after each case; a regression verifies that unrelated metadata survives. All
23 native cases passed twice against the contaminated database, and strict mypy
passed 241 files. The final SDK pin passed all 37 hosted native matrix jobs under
the debug allocator. A fresh Linux ARM64 pricing rebuild and complete original
suite are running against the repaired immutable dependencies, with passive
full-value/path failure reporting and no runtime wrappers.
These archive runs do not establish empty-cache startup performance. Deployment
is separate; this migration remains draft pending full acceptance.
