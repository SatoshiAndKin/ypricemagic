# Cold pricing follow-up

The first repair deployment installed fork `073c7ac8` and server `be640a5b`.
Production acceptance failed when Base WETH at block 24,000,000, amount `0.1`,
returned HTTP 504 after 300.07 seconds. A fresh copy of the original production
SQLite backup reproduced the failure at 300.01 seconds. Separately, an isolated
candidate turnover run exposed an Ethereum read timeout after 35.88 seconds.
These failed runs remain in the companion server evidence and are not accepted
as a successful soak.

This follow-up carries immutable Solidly stable flags from factory events,
checks V3 input balances before code and companion balances, and retries one
transport timeout at the unchanged canonical block hash. Task cancellation and
persistent failures propagate. No candidate with usable input liquidity is
removed; zero companion balances remain valid. Quantity conversion, native
quotes, fees, ordering by input depth, and block identity remain unchanged.

Stable-flag reads and both-token V3 reads existed in the previous `69dda57e`
release (PR #46). The explicit native transport deadline was added in PR #47;
its timeout branch lacked a bounded recovery attempt. The historical scan
coverage repair remains intact. Current provider measurements returned identical
10,000-block event sets through web3-proxy, Geth, and Reth. Production providers
are preserved.

`initial-reproduction.json` records eight failures against the unrepaired
immutable metadata/timeout behavior. `v3-reproduction.json` records six failures
when companion reads touched empty or undeployed pools. The final focused run
passed all 232 tests, strict typing across 242 files, and all ten compiled-module
imports. Two intermediate infrastructure/fixture failures are retained: the
local validation disk filled during a build, and a new fixture initially
asserted insertion order rather than the existing depth order. Neither is
counted as passing validation.

Fresh copied-cache candidate results:

| Version | Base historical USDC first | Base historical WETH first |
| --- | ---: | ---: |
| Deployed fork, diagnostic candidate | 17.96 s | HTTP 504, 300.01 s |
| Stable flag reuse | 34.35 s | 291.30 s |
| Input balance first and stable flag reuse | 10.23 s | 273.72 s |

The middle run overlapped native compilation. These are local native ARM64
candidate timings, not production timings. Both repaired WETH results were
exactly `1969.89808`; the USDC result stayed exactly `0.990993596876513`.
The previously failing Ethereum parameters returned HTTP 200 in 11.02 seconds;
this proves recovery at those parameters, while controlled timeout tests prove
the retry behavior.

Full native validation, the complete candidate matrix, CI, follow-up merges,
server lock refresh, production deployment, corrected public and direct
Tailscale matrix/browser/timings, and a successful 60-minute production soak
remain required before acceptance.
