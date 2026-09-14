# Contained memory validation

Validation is incomplete. PR #43 remains draft. The changed full suite ended
after file-descriptor exhaustion. The owning dependency now releases cancelled
HTTP requests and completed batch tasks. Its native tests pass on all supported
CI test platforms. Direct Lambo Reth archive access has recovered. The pricing
matrix passes with the repaired dependency. Both baseline full suites reach
the unchanged 8 GiB limit. The optimized full suite is now running.

## Current evidence

The [HTTP ownership repair](http-request-ownership/README.md) reduces median
process peak RSS from 203,718,656 to 169,242,624 bytes in the identical 256-call
local workload. Retained connections and requester tasks fall from 256 to zero.
The 6,400-call turnover check keeps zero of each and 27 file descriptors after
every round. All 150 dependency tests pass in each of 12 native CI jobs; all 15
native builds pass. The application now pins their generated artifacts. The
local source comparison fixes 20 failures with no added failed test IDs.

The [current dependency matrix](requester-owner-matrix/README.md) passes all 251
focused tests on Linux ARM64 Python 3.11, 3.12, and 3.13. Every run loads all ten configured
compiled extensions and passes the historical archive probe. No OOM occurs.
The final type checks report 1,935 errors on each version, compared with 1,959
before optimization under the same dependencies. No rendered diagnostic was
added; 24 were removed. These type checks still fail.

| Python | Focused passes | Container peak bytes | Run elapsed seconds |
| --- | ---: | ---: | ---: |
| 3.11 | 251 | 1,132,236,800 | 226.68 |
| 3.12 | 251 | 1,169,694,720 | 247.19 |
| 3.13 | 251 | 1,172,312,064 | 219.23 |

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

The [new full-suite sequence](requester-full-suites/README.md) uses the repaired
requester image and direct Lambo Reth. The original revision records 415 terminal
outcomes out of 1,752 cases, then reaches 8 GiB after 1,521.86 seconds. The
pre-optimization revision records 416 outcomes out of 1,816 cases and reaches
the same limit after 1,510.30 seconds. Both record one cgroup OOM kill and Docker
`OOMKilled=true`. Neither has a final pytest summary. The optimized revision now
uses the same image, source runner, and a separate database.

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
[direct Lambo Reth probe](archive-lambo-restored/README.md) passes. The native,
public pricing, and audit checks still need the newly repaired dependency image.

All three suite commands select image
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
| [Cached Sushi topology](scaling-final/README.md) | 443,097,088 | 294,731,776 | 309,675 reads; 4,131 quotes; 4,128 historical blocks; 64-operation bound |
| [Request diagnostics](logger-comparison.json) | 215,588,864 | 183,836,672 | 10,000 requests; retained loggers and tasks fall from 10,000 to zero |
| [Callable ownership](async-ownership/README.md) | 98,758,656 | 32,768,000 | 1,000 callables; all captured owners released |
| [HTTP retry ownership](dank-retry/comparison.json) | 295,972,864 | 227,442,688 | 64 concurrent requests; 1,088 attempts; unchanged request IDs and retry rules |
| [HTTP cancellation ownership](http-request-ownership/comparison.json) | 203,718,656 | 169,242,624 | 64 concurrent requests; 256 identical HTTP bodies; connections and requester tasks fall to zero |

The Sushi comparison uses the older locked dependency image. Its median elapsed
time changes from 2.761 to 2.653 seconds, with identical amounts and quote outputs.
A repeat with the final dependency image stopped during archive-dependent
startup and has no workload result. Sushi and logger workloads
collect garbage at the same measurement boundaries on both sides. They do not
clear caches or restart a process to produce the within-workload release result.
The callable and retry workloads use normal cyclic collection only.

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
