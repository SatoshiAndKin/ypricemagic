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

Large persisted factory catalogs exposed another #47 regression: without SQLite
optimizer statistics, rare-token pages used the factory-wide block index instead
of the existing token index. The deployed `073c7ac8` source reproduces the wrong
index selection while returning the same event. Bounded index samples repair
the planner choice without changing filters, schemas, raw events, or ordering.
On an exclusively owned Base diagnostic cache, all four query variants returned
the same 1,255 events and ordered digest. A warm unoptimized query took 0.723 s;
the sampled query took 0.0036 s. Sampling took 0.0014–0.0136 s. Exact normalized
topic parameters and query plans are recorded in
`sqlite-token-index-reproduction.json`.

Static factory decoding now follows the registered protocol-specific ABI and
preserves strict validation, with the generic decoder retained for other ABIs.
Immutable decoded pages are reused across blocks with both a 65,536-row budget
and a 128-page limit. Keys include the factory, ABI, and every ordered event word;
changed data and ABIs cannot reuse stale metadata. Raw events stay on disk, and
pool state and quotes still use the exact canonical block hash. The latest
focused native run passed 413 tests, mypy across 244 source files, and all ten
compiled-module imports, with 14 source hashes matched to the isolated child
tree. Its evidence is in `index-metadata-focused-native.json`.

An earlier larger disk-commit experiment reduced fetch/write overlap and was
discarded at that revision. The latest candidate revisits bounded eight-range
commits after repairing writer cache churn and canonical event encoding; failed
and cancelled windows retain prior coverage and never publish an incomplete
window. Failed startup measurements remain in the archive. The uncapped CPU
diagnostic matches production's CPU policy and retains 8 GiB without swap; its
container reached readiness just after 600 seconds, so the acceptance harness
rejected it. Neither that run nor recovery using its completed test cache counts
as a passing cold-cache result.

The complete required native suite at preceding revision `82a0543e` finished
successfully: 2,389 passed, 17 skipped, all ten compiled modules verified, peak
cgroup memory 3,603,099,648 bytes, and no OOM. The full run took 87.39 minutes.
`complete-native-preceding-revision.json` preserves its revision and boundaries;
newer changes still require a complete native run.

The copied-cache current WETH failure persisted after index sampling. Static
factory ABI decoding now reads validated words directly and retains the primary
codec for unsupported or malformed fields. Numeric boundaries, truncation, and
padding retain exact values and exception classes. A host Python 3.12 replay of
80,000 real events took 1.10–1.11 s with the general codec and 0.047 s with direct
validated words. Complete protocol inventories and the final candidate ordering
are unchanged.

The next trace exposed sequential Curve/Balancer work after the dense V2/V3
inventories. That ordering predates #47 and exists in `69dda57e`. All independent
protocol inventories now start together under owned cancellation. The expanded
controlled test requires V2, V3, Curve, and Balancer to enter, verifies exact
combined depth order, and checks that failures and cancellation drain all four
producers. All 452 focused native tests, strict typing across 244 files, and ten
compiled imports passed against an archive reproduced from the current worktree.
The intermediate missing local set annotation is retained as a failed run.

The copied-cache Base WETH amount `0.1` at current block 52,109,406 then returned
HTTP 200 in 284.00 s, at price `2668.1196`, using the unchanged native V3 quote.
Peak cgroup memory was 7,129,616,384 bytes under the 8 GiB cap, swap was zero,
there was no OOM, and real SIGTERM completed in 1.64 s. The earlier word-only
candidate's 300-second failure remains recorded. This is interpreted-overlay
diagnostic recovery, not empty-cache, final-image, new-block, or production
acceptance. Those checks and the final complete native rerun remain required.

The next two truly empty-cache candidates still failed the unchanged 600-second
startup grace. Neither OOMed. Range logs account for about 570 seconds of
serialized raw-event writes. A single factory writer now bounds the enlarged
SQLite page cache to 64 MiB instead of multiplying it across filter connections.
The real schema, JSON event format, journal mode, and full synchronous durability
remain intact. Scratch and full-size catalog write profiles are retained, with
their timing variance and shared validation VM scope. A WAL experiment did not
show a consistent independent write benefit and is not part of the change.

The cold run also exposed a gap in the initial index-statistics repair: updating
one SQLite connection leaves existing readers with their old query plans.
An isolated native two-connection reproduction selected the primary index on
the existing reader after the analyzing connection selected the token index.
Reloading persisted statistics selected the token index on both. The permanent
regression fails against the committed original statistics owner and passes with
connection-local generation tracking. This follows SQLite's documented
[statistics reload behavior](https://www.sqlite.org/lang_analyze.html).
Each reader reloads only when its connection or the statistics generation changes.
Generated Pony SQL was also inspected: the factory projection already omits
`DISTINCT`, so removing it would have no effect.

The two changed files matched the isolated auxiliary control source hashes;
454 focused Python 3.12 tests, strict typing across 244 files, and the ten
unchanged compiled extensions passed. These are scoped controls in the prior
native validation container, not a final image build. The fresh empty-cache run
with connection-local statistics is still in progress; startup, subsequent
quotes, latest full-native validation, and production acceptance remain gates.


The full required native suite at `4569534b` completed with 2,440 passed and
17 skipped in 86.95 minutes, strict typing across 244 files, and all ten compiled
imports. The later bounded-window, canonical event encoding, and supported
2,048-getter V3 batches passed 476 focused native tests and strict typing, with
an independently reproduced source archive. These controls precede the newest
batch decoder and do not establish its validation.

On the physical production host, the latest truly empty-cache candidate became
healthy in 552.53 seconds, inside the unchanged 600-second grace. Canonical raw
event preparation accounted for 78.40 seconds across 4,986,684 events. Its first
current Base WETH amount `0.1` still returned HTTP 504 at 300.009 seconds with
incomplete dense inventories. The cgroup reached its 8 GiB ceiling, recorded
407 limit events, and recorded no OOM or OOM kill; clean cancellation exited zero.
The failed report is retained as `ypm-followup-base-remote-empty55.json`. This
proves cold startup improvement, but fails quote acceptance. Production images,
providers, and cache volumes were not changed. Further profiling separates
anonymous memory from file pages and measures quote CPU costs before delivery.


Checked canonical aggregate encoding and decoding passed 541 focused native
controls, strict typing across 244 files, and all ten compiled imports. One
intermediate test wrongly treated prefixless addresses as invalid; its failed
run is retained, and the corrected regression preserves the native support.
The whole-request replay still timed out after 300 seconds, at only 1.997 GiB
peak and without memory-limit events. Component speedups alone did not establish
quote recovery.

The subsequent phase trace records 896 individual Balancer vault inventory
reads competing with dense scans for the same eight native RPC slots. Their
transport durations total 1,625.30 seconds including overlapping semaphore
queueing. The trace and independent same-hash balance-batch probe are in
`current-base-rpc-phase-profile.json`. Balancer's
[primary vault source](https://github.com/balancer/balancer-v2-monorepo/blob/master/pkg/vault/contracts/PoolTokens.sol)
confirms that `getPoolTokens` reads registered pool state independently of the
caller. The next candidate batches only that getter, in at most 128-pool windows,
retains deployment checks, checks aggregate block and result count, and falls
back to native individual getters for unavailable members or provider limits.
This latest change still needs scoped and whole-request verification.


The provider-sized getter and code batches, bounded HTTP 413 splitting, Balancer
vault batches, and ordinary-byte RPC decoding passed 563 focused native tests,
strict typing across 244 files, and all ten compiled imports. The underlying
native ABI bytes and values match at the measured limits: 7,500 reserve getters,
6,250 balance getters, and 8,192 code checks. Payloads for getter aggregates stay
around 2.4 MB including hexadecimal calldata. Larger getter requests were
rejected and are not adopted; smaller provider limits still split boundedly at
the same hash. Ordinary-byte slicing also preserves the native payload type and
avoids constructing a HexBytes wrapper for every ABI word.

Current Base replays with these changes still reached the single deadline.
Failures 64, 72 and 74 remain recorded, with no OOM or memory-limit events.
The last replay used about one CPU core throughout, with no CPU throttling.
An isolated direct-SQLite comparison returned identical ordered event digests,
but its gain over the ORM was modest and it is not adopted. Focused per-thread
profiles are separating event-read and static-metadata CPU costs. These scoped
passes do not establish end-to-end quote recovery, final-image readiness,
production deployment, or a successful soak.
