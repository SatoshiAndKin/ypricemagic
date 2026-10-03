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

Raw code batches use the provider's HTTP session manager in place of the removed
Web3 v6 helper. Bounded native reserve/code/log reads disable Web3 v7's added
provider retry layer so the existing pricing retry window and log-range splitter
continue to own each HTTP attempt. Hash/canonical parameters and batch IDs remain
unchanged. The stale dict-item typing suppression for historical multicall
state overrides was removed; the required typed-dict suppression remains.
Pricing recognizes Dank's typed `ExecutionReverted`, including legacy invalid
opcode/jump responses, while propagating out-of-gas and unrelated failures.

Migration-specific native checks passed 164 tests after a fresh extension rebuild,
covering typed contract reverts, the middleware cache,
real HTTP batch order and retry counts, canonical selectors, archive-state retries
and provider range splitting. The configured strict mypy check passed all 241
source files. The dependency image also passed all 44 Brownie compiled bytecode
safety and memory regressions. A separate source coverage run passed the same
164 cases and covered every changed runtime statement; it is independent of
compiled-runtime verification. Live pricing tests admit eight cases concurrently
to retain the existing 30-second transport deadline on bounded validation hosts.
Full native pricing and server acceptance remain
required before the migration is ready. Deployment is separate.
