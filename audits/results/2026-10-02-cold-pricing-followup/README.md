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

Further fresh-cache validation exposed work that was absent from copied-cache
measurements. The follow-up now grows sparse log ranges only after a bounded
eight-range window commits, respecting known smaller provider limits and backing
off on latency or event density. Curve preloads its address-provider history
through the same raw disk cache. Token metadata consumers recheck completed
coverage between pages instead of repeatedly reading tiny ranges after the
shared owner has already filled a larger window. That paging regression was
introduced by #47. Historical ceilings, ordering, and candidate sets remain
covered by five protocol variants at pinned blocks.

A live Ethereum reorg during the complete suite exposed an orphaned canonical
hash. Native reads now report that exact provider error as a transient connection
failure, without changing hash or disabling `requireCanonical`. The Chainlink
comparison fixture uses one finalized block for its two independent reads;
production current-price checks remain separate. Four regressions reproduce on
`911a7a5` and all 100 tests in their modules pass after repair. The final scan
policy module adds 27 passing cases. Each auxiliary run has a separate database
and report directory.

The expanded focused native run passed 712 tests with five skips, strict typing
across 242 files, and all ten compiled extension imports. Its archive hash and
results are in `sparse-focused-native.json`. A complete run against the earlier
revision failed with six reorg comparisons and five synthetic cache assertions;
the latter were caused by an auxiliary process incorrectly sharing that run's
database. That failed run is retained, and the complete suite is being rerun
against an immutable final source snapshot with isolated auxiliary databases.

The newer truly empty-cache Base candidate became healthy in 33.44 seconds and
returned the exact historical USDC amount result in 247.90 seconds. SIGTERM
completed in 0.57 seconds with no OOM. Ethereum still failed cold readiness at
602.84 seconds. Those reports explicitly identify the runtime overlays and are
not production-image proof. Direct provider comparison then found that the
production proxy excluded Geth from historical logs through an explicit
128-block log-history setting. A separate infrastructure repair retains
Ethereum on web3-proxy and Geth's 128-block state limit while correcting log
eligibility, after matching nonempty pre-Merge event sets against Reth.

Independent router inventories now run concurrently and retain deterministic final
market ordering. Balancer V2 registration discovery uses compact, historically
bounded raw events instead of a live current-head loader. Real cold Base
historical WETH pricing passed in 217.26 seconds, preserving exactly
`1969.89808`. Ethereum, using the existing web3-proxy Fastest route on the same
production proxy host, completed required initialization in 488.92 seconds and
returned the historical USDC amount result in 237.18 seconds, exactly
`0.9989039883929369`. These are isolated interpreted-overlay candidate results,
not final-image or deployed-provider configuration proof.

Metadata cache pages now read up to 4096 events with explicit caller limits;
ordering, legacy/compact deduplication, historical ceilings, and empty results
are tested. Shared raw scans release their RPC permit before serialized disk
commits and stabilize dense windows around 8192 events instead of repeatedly
growing and splitting rejected ranges. Large-range timeouts split immediately;
ordinary reads and small-range timeouts retain one bounded retry.

The latest focused native run passed 401 tests and strict mypy across 242 files.
All ten configured modules resolved to native Python 3.12 extension files in
that isolated child source tree. Its per-file hashes are recorded in
`parallel-protocol-focused-native.json`. A fresh current-block Base request
still reached the single 300-second deadline with incomplete factory backfill;
that failure is retained. The server follow-up is measuring required Base
factory warmup against the unchanged 600-second startup grace. Complete native
validation, final production-image builds, merges, deployment, public matrix,
browser verification, and the 60-minute production soak remain acceptance gates.
