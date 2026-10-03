# Immutable Web3 v7 native stack

This migration starts from fork master `073c7ac8`, retaining its indexed pool
inventory, bounded cold-state reads, historical state retries and pricing repairs.
It supports Web3 v7 exclusively.

The runtime/build pins are dank-mids `2a5a4d21fc8aa1d12a9146043871ade23084323c`,
Brownie `7e529be8dfc1afa7bda2d6660c8a11c59a653a6e`, and evmspec
`f0df0d9d8e4e7a7000580054ce2c0b6b6193a14c`. The ez-a-sync, aiosqlite,
cachebox and mypy native repair pins are retained. Python 3.11–3.13 Linux ARM64
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

The complete native pricing suite is being repeated after the session-lock repair.
Server Ethereum price/batch/amount/cache scenarios passed with the native v7 stack;
Base scenarios passed after the POA repair. Final immutable server-image acceptance
and the complete pricing run remain required. Deployment is separate.
