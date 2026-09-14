# Contained memory validation

## Synchronous deadline and interruption cleanup

The [deadline and owner repair](sync-deadline/README.md) activates the existing
600-second synchronous test deadline and rejects a missing handler before
collection. The pinned ez-a-sync repair releases its created request task after
a caller interruption while preserving the original error and independent
shared requests. All 278 application tests, 52 owner checks, and two deadline
checks pass on Python 3.11–3.13. All ten application extensions and four owner
extensions load native code. Type diagnostics remain unchanged at 1,836.
The [replacement full-suite and real-node queue](deadline-node-validation/README.md)
remains separate from this focused validation. With the final dependencies,
the original and pre-optimization baselines reach 8 GiB after 1,203.63 and
1,525.52 seconds. They record 412 of 1,752 and 486 of 1,816 terminal outcomes.
Both pass the archive probe and load ten compiled modules, but their missing
final summaries keep validation incomplete. The optimized run records 1,467 of
1,865 terminal outcomes and peaks at 4,401,676,288 bytes without OOM. It stops
after a synchronous case emits its timeout but does not report a result after
2,114.65 seconds. A native sample shows the original pending request at block
7,720,755, not the new cancellation cleanup. The cause remains unresolved.
All three full runs remain incomplete. The native quote, public pricing, and
audit stages continue in the existing queue.

## Latest pool ownership repair

The [pool-index comparison](property-ownership/README.md) uses the same 524,288
seeded pools in three unprofiled runs per stage. Shared descriptor access and
owning dependency repairs reduce median peak process RSS from 6,796,603,392 to
1,291,739,136 bytes and index time from 29.1073 to 7.1822 seconds. Exact metadata
and independent returned dictionaries match. Both sides make zero RPC calls.
A separate allocation sample measures retained Python memory. No forced
collection, cache clearing, expiry, or restart occurs within these workloads.

All 278 focused application checks pass with the final dependency build. All
ten configured mypyc modules load compiled extensions, and the archive probe
passes. The same-dependency type comparison removes three diagnostics, adds
none, and retains all 1,836 reported diagnostics. The owning dependency's full
747-case comparison removes all 13 ownership failures and passes both metaclass
checks; the same 15 baseline failures remain. The application now pins the
committed repair. The [ordinary pinned Python 3.11–3.13 matrix](ownership-pinned/README.md)
passes all 278 application tests and 47 owner tests on each version. All ten
compiled application modules, the three native owner modules, and archive
probes pass. Application container peaks range from 1,158,004,736 to
1,197,735,936 bytes. Each installed source revision matches its lockfile.

The [cooperative scheduler repair](scheduler-refill/README.md) fills available
slots after a batch finishes. It retains the default concurrency of 100 and
passes all three new barrier regressions. Its Python 3.11–3.13 owner checks keep
the same two existing full-suite failures. This scheduling repair does not count
as a production pricing memory reduction.

The [final pinned baseline runs](final-node-validation/README.md) both reach the
8 GiB limit and remain incomplete. The original revision records 412 of 1,752
terminal outcomes; the pre-optimization revision records 476 of 1,816. Both load
all ten compiled modules and pass the archive probe with identical dependencies.
The optimized run records 1,464 of 1,865 terminal outcomes and peaks at
4,348,043,264 container bytes without OOM. It is interrupted after confirming
that the configured synchronous test deadline has no installed handler. Its
final pytest summary is missing. The native quote, public pricing, and audit
gates remain pending in the replacement queue with the repaired deadline
dependency and request cleanup. All interrupted and OOM reports remain incomplete.
PR #43 remains draft. The controlled pool reduction does not establish a full
pricing memory result.

## Previous historical profile

The shared-topic revision reached the 8 GiB limit in the
historical Uniswap allocation profile. It records 130 terminal outcomes from
171 collected cases, then ends with OOM after 1,915.68 seconds. All ten native
modules and the archive probe pass. The final pytest summary is missing.
[Exact errors and retained-state samples](topic-historical/README.md) preserve
the incomplete run and the unresolved final memory increase. The controlled
40% topic-lookup RSS reduction does not establish a full pricing memory result.

[Fixture and timing-helper checks](validation-harness/README.md) register the
existing V1 fixture and remove profiling work from the public timing helper.
All three V1 cases now execute; their pricing calls still reach the configured
timeout. The type check adds no diagnostics.

Validation is incomplete. PR #43 remains draft. Earlier full suites reach the
unchanged 8 GiB limit. Event loading now bounds historical chunks and pending
writes. The [storage repair](storage-retention/README.md) removes retained
SQL payload strings and defers unused reserve-call handles. Controlled memory
checks, the 270-case Python matrix, and PostgreSQL persistence checks pass.
The [repaired full suite](storage-full-suite/README.md) records 1,240 of 1,857
cases before another OOM. The subsequent [topic-cache repair](topic-cache/README.md)
passes 274 focused tests on Python 3.11–3.13. Its historical and full pricing
checks, plus the remaining real-node checks, still need completion.

## Current evidence

The [topic-ID comparison](topic-cache/README.md) reduces median peak process RSS
from 353,050,624 to 210,583,552 bytes. Median lookup time increases from 18.508328
to 21.496016 seconds. Exact persisted IDs match; one evicted-topic revisit adds
one database lookup and no RPC calls. All 274 focused tests pass on each of
Python 3.11–3.13, all ten compiled modules load, and no type diagnostic is added.

The [cache ownership repair](cache-ownership/README.md) releases idle per-key
locks and prevents a native garbage-collection deadlock. The controlled cache
workload reduces median peak RSS from 318,275,584 to 24,641,536 bytes with exact
results and unchanged cache hits. All 303 owning tests pass on Python 3.11–3.13.
The application pins that repair. The subsequent topic-cache change bounds
completed topic IDs in one shared cache. The cache-only reduction does not establish a full pricing memory result.

The [storage comparison](storage-retention/README.md) reduces median process peak
RSS from 528,093,184 to 190,730,240 bytes for identical bulk writes, and from
366,612,480 to 330,182,656 bytes for identical unused pool construction. Both
workloads also run faster. All 270 focused checks pass on Python 3.11–3.13;
all ten compiled extensions load. Type errors stay at 1,922 with no added
semantic diagnostics. The exact SQLite data and pool metadata digests match.

The [HTTP ownership repair](http-request-ownership/README.md) reduces median
process peak RSS from 203,718,656 to 169,242,624 bytes in the identical 256-call
local workload. Retained connections and requester tasks fall from 256 to zero.
The 6,400-call turnover check keeps zero of each and 27 file descriptors after
every round. All 150 dependency tests pass in each of 12 native CI jobs; all 15
native builds pass. The application now pins their generated artifacts. The
local source comparison fixes 20 failures with no added failed test IDs.

The [earlier event-loader matrix](event-backlog/README.md) passes all 264
focused tests on Linux ARM64 Python 3.11, 3.12, and 3.13. Every run loads all ten
configured compiled extensions and passes the historical archive probe. No OOM
occurs. Type checks report 1,922 errors per version, compared with 1,935 before
this repair under identical dependencies. No rendered diagnostic is added; 13
are removed. These type checks still fail. The earlier
[251-case dependency matrix](requester-owner-matrix/README.md) remains separate.

| Python | Focused passes | Container peak bytes | Run elapsed seconds |
| --- | ---: | ---: | ---: |
| 3.11 | 264 | 1,120,059,392 | 198.59 |
| 3.12 | 264 | 1,172,852,736 | 206.75 |
| 3.13 | 264 | 1,158,500,352 | 219.83 |

The [same four fixture release checks](bulk-fixture-ownership/README.md) fail
before cleanup and pass afterward.
They cover child failure and caller cancellation during price and deployment
mapping. The fixtures retain their token lists, historical blocks, assertions,
600-second deadline, and existing concurrency.

The [logger and builder checks](logging-and-build-cleanup/README.md) also cover
a logging handler that raises before pricing starts. The request still closes
its diagnostic task. A real interrupted BuildKit job preserves its final state
and memory counters, then stops. Five standard-library supervisor tests pass,
including build OOM and interruption cases.

[Configured source checks](configured-format-checks/README.md) pass Black,
isort, and autoflake for the changed Python files. Recorded source fixtures use
`.py.txt` names so formatters cannot change historical evidence; their hashes
and original names remain recorded.

## Full suites and source identity

The [storage-repair full run](storage-full-suite/README.md) records 893 passed
calls, 330 failed calls, 14 skips, and three setup failures before Docker stops
it for OOM at 3,639.60 seconds. It has no final pytest summary and misses the
7 GiB memory target. The source, dependency image, partial failure comparisons,
and final cgroup state remain recorded. Further cache ownership work is required.

The [new full-suite sequence](requester-full-suites/README.md) uses the repaired
requester image and direct Lambo Reth. The original revision records 415 terminal
outcomes out of 1,752 cases, then reaches 8 GiB after 1,521.86 seconds. The
pre-optimization revision records 416 outcomes out of 1,816 cases and reaches
the same limit after 1,510.30 seconds. The optimized revision records 416 outcomes
out of 1,838 cases and reaches the limit after 1,525.53 seconds. All three record
one cgroup OOM kill and Docker `OOMKilled=true`. None has a final pytest summary.
They use the same image, source runner, and separate databases.

The following reports precede the HTTP cancellation repair:

| Source | Revision | Status before the HTTP ownership repair |
| --- | --- | --- |
| Original PR baseline | `476af288a520a30052668a8b3ad7e3e682cd101f` | OOM; incomplete |
| Before memory changes | `61be7b520aba7f771a0bf96b326315e68767fae4` | Archive probe timeout; pytest did not start |
| Optimized behavior | `368a6e79fa7226cb0f7f92be27a90c80d5a649b7` | File-descriptor exhaustion; incomplete |

The [original full run](full-original-owner-pinned-oom/README.md) collected
1,752 cases and recorded 438 terminal outcomes before reaching the 8 GiB limit.
Docker records `OOMKilled=true` and the cgroup records one OOM kill. It has no
final pytest summary. Its partial outcomes cannot establish failure equivalence
or preserved full coverage.

The [changed full run](full-optimized-descriptor-failure/README.md) records
410 terminal outcomes out of 1,838 collected cases. It peaks at 1,173,213,184 bytes
with no OOM, but has no final pytest summary. Its early exit prevents a full
memory or failure comparison. [Later archive probes](archive-after-full-failure/README.md)
time out on the required USDC call through direct NUC Reth. A subsequent
[direct Lambo Reth probe](archive-lambo-restored/README.md) passes. The remaining native,
public pricing, and audit checks still need completion with the repaired image.

Those three earlier suite commands select image
`sha256:27ffa2884a5bf1a6538184ec79af495dc0d45839a5b20317e2526bdc5e7be46b`,
separate databases, and the required command:

```sh
PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test
```

Each report records the source archive hash, helper and workload hashes,
installed dependencies, command, exit status, elapsed time, and resource data.
The focused development runs record their exact worktree archive. The full
suite uses committed source. Later import formatting changes preserve the
behavior recorded at `368a6e79`; their AST comparison is recorded separately.

## Controlled memory measurements

These workloads isolate specific repairs. They do not replace a complete
application run or prove real-node pricing latency. Each RSS figure is the
median of three unprofiled samples per revision; allocation profiles remain
separate. Each before/after pair preserves its own dependencies and workload.
Different rows use different dependency builds.

| Workload | Before RSS bytes | After RSS bytes | Preserved work and result |
| --- | ---: | ---: | --- |
| [Pool token index](property-ownership/README.md) | 6,796,603,392 | 1,291,739,136 | 524,288 identical pools; exact metadata; independent copies; zero RPC |
| [Bulk persistence](storage-retention/README.md) | 528,093,184 | 190,730,240 | 4,096 rows; 64 MiB of exact ordered data; 128 batches |
| [Unused pool construction](storage-retention/README.md) | 366,612,480 | 330,182,656 | 131,072 identical pools; unused reserve handles 131,072 to zero |
| [Historical event chunks](event-backlog/README.md) | 319,193,088 | 195,379,200 | 512 identical chunks; 32 concurrent fetches; every ordered write and checkpoint |
| [Cached Sushi topology, current requester](scaling-requester/README.md) | 424,853,504 | 276,234,240 | 309,675 reads; 4,131 quotes; 4,128 historical blocks; 64-operation bound |
| [Request diagnostics](logger-comparison.json) | 215,588,864 | 183,836,672 | 10,000 requests; retained loggers and tasks fall from 10,000 to zero |
| [Callable ownership](async-ownership/README.md) | 98,758,656 | 32,768,000 | 1,000 callables; all captured owners released |
| [HTTP retry ownership](dank-retry/comparison.json) | 295,972,864 | 227,442,688 | 64 concurrent requests; 1,088 attempts; unchanged request IDs and retry rules |
| [HTTP cancellation ownership](http-request-ownership/comparison.json) | 203,718,656 | 169,242,624 | 64 concurrent requests; 256 identical HTTP bodies; connections and requester tasks fall to zero |

The new Sushi comparison uses the current dependency image. Its median elapsed
time changes from 2.63824 to 2.63928 seconds. Exact amount, quote output, and
independent-path assertions pass. The older [Sushi comparison](scaling-final/README.md)
remains separate. Sushi and logger workloads collect garbage at matching
measurement boundaries. They do not clear caches or restart the process within
a workload. The callable and retry workloads use normal cyclic collection only.

The [historical discovery profile](discovery-allocations/README.md) identifies
large raw log buffers, processed Uniswap pool state, and pending database insert
coroutines. The 19-case run finishes with 10 passes and nine failures at a
6,399,762,432-byte container peak. Allocation overhead remains separate from
performance results. The 29-case combined profile finishes with 10 passes and
19 failures at a 5,477,474,304-byte peak. The [event-loader repair](event-backlog/README.md)
keeps 32 raw chunks instead of 499 in the controlled workload. Median elapsed
time increases about 4%, from 1.75252 to 1.82288 seconds. Ordering, failure,
cancellation, pending-write reuse, and zero-permit semaphore checks pass. The
[committed historical profile](event-historical/README.md) finishes without OOM
at 4,798,681,088 container bytes, down from 5,477,474,304. Peak sampled raw logs
fall from 519,924 to 17,733 and pending insert tasks from 1,827 to three. Both
runs record ten passes and 19 failures. Nine Magic block values change with the
chain tip; RPC, task, and pool counts increase. This diagnostic run does not
establish identical-input performance or complete full-suite validation.

The [native quote control](native-requester-before/README.md) records six passing
cases. Its process exit remains incomplete because the old application waits
for an idle SQLite worker after reporting. The saved stacks establish the exit
failure before the supervisor stops the process.

The [compiler and Brownie check](compiler-backport/README.md) returns identical
opcodes from sixteen native bytecode scans. Retained Python allocations after
collection fall from 4,467,732 to 3,540 bytes. All 64 compiler reference-count
checks and 33 native scanner checks pass. The fix resides in the compiler's
owning repository; Brownie pins that repair.

The [historical fixture profile](popsicle-owned-cleanup/README.md) releases all
425 previously pending mapped tasks. Its two passes and 17 existing timeouts
remain unchanged. This profile includes allocation overhead and does not serve
as a timing comparison.

## Containment and archive access

The approved `ypricemagic` and `rpc-tune` Colima profiles each use 10 GiB and
5 CPUs, for 20 GiB combined. The previous default profile remains stopped with
its data preserved. Each heavy job uses an 8 GiB container, no swap, four CPUs,
and a limit of 512 processes and threads. Only one heavy job runs per profile.
BuildKit stops before tests start. Limits do not increase after failures.

The [runner verification](final-independent/runner/verification.json) covers
actual cancellation, duplicate prevention, and report persistence. A deliberate
64 MiB OOM confirms containment. Console output rotates at 100 MiB with five
files retained; the 600 MiB fixture discloses 100 MiB of expired output. Structured
pytest results and audit JSON/CSV remain separate from console logs.

The [latest direct Reth checks](archive-lambo-restored/README.md) establish archive
access through Lambo Reth. The Docker probe returns USDC decimals 6 at blocks
16,830,000 and 18,000,000, including canonical hash selection. Direct NUC Reth
times out in the new host retries. [Earlier observations](reth-backends/README.md)
remain recorded separately. The expected Geth archive failure remains a separate
control. These checks do not establish the cause of individual pricing timeouts.

The [archive version check](archive-version-scope/README.md) verifies that the
runner applies its source version override only to ypricemagic. Dependency
source builds keep their own versions.

## Earlier evidence

[Earlier progress notes](earlier-results.md) retain the previous index without
changing its bytes. Its pending statements describe earlier stages; use this
index for current status. [Provenance](earlier-results-provenance.json) records
the original commit, size, and hash. Earlier OOM runs, rejected build attempts,
incomplete reports, and dependency comparisons remain available in their
original directories. No partial run is relabeled as complete validation.
