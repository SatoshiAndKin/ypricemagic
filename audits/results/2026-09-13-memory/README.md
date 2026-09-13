# Contained memory validation

Validation is incomplete. This directory records the transition and will receive
completed Docker comparison results before PR #43 can leave draft state.

The original PR baseline is `476af288a520a30052668a8b3ad7e3e682cd101f`.
The pre-optimization revision is `61be7b520aba7f771a0bf96b326315e68767fae4`.
Each Docker report records the tested revision or worktree archive hash.
Implementation and validation reports use separate commits as checks finish.

The four existing host checks were stopped after evidence capture. They ignored
SIGTERM and required SIGKILL. Treat all four executions as incomplete, including
any native case results written before the processes exited. `transition.json`
records original log paths and sizes. The original files remain in
`/private/tmp/yprice-pr43-repairs/`. The audit console log exceeded 16 GB. No
successful full-suite, native-run, or audit completion is inferred from partial
output.

The prior generated C diff remains saved at
`/private/tmp/yprice-memory-host-generated-c.patch`. It is separate from the
Python source changes. Colima's existing data disk remains intact; its profile
was first resized to 12 GiB of memory and 5 CPUs. After approval of parallel limits,
that idle default profile was stopped with its disk preserved. New `ypricemagic`
and `rpc-tune` profiles each have 10 GiB and 5 CPUs: 20 GiB combined on this
36 GiB Mac. Each profile permits one heavy job with the unchanged 8 GiB, no-swap,
4-CPU, 512-process/thread container limits. See `colima-profiles.json`.

The initial dependency ownership repair was validated at
`3089b3ddd393a45655b5231e6a67b54dd5529196` in
[SatoshiAndKin/pytest-asyncio-cooperative PR 1](https://github.com/SatoshiAndKin/pytest-asyncio-cooperative/pull/1).
Its full Python 3.12 suite has 80 passes, 16 skips, and the same two failures as
the unchanged revision (75 passes). Five new ownership checks pass. Three
controlled runs at concurrency 100 reduce median peak RSS from 716,128,256 to
186,753,024 bytes, with zero completed fixtures retained instead of 4,000.

All 239 focused application tests pass on Linux ARM64 Python 3.11.16, 3.12.14,
and 3.13.15 with all ten configured compiled extensions. The scaling check preserves 64 operations,
4,771 cached pools, 4,128 historical blocks, 309,675 state reads, and 4,131 quotes.
The type check remains non-green: 1,940 errors versus 1,959 on the unchanged
revision with the same dependency image. No rendered diagnostic was added.

Docker containment, real runner cancellation, atomic duplicate prevention, and
report persistence pass. A deliberate 64 MiB OOM exits 137 with `OOMKilled=true`.
The log test writes 600 MiB, retains five 100 MiB files, and reports 100 MiB of
expired output. The locked Python 3.12 BuildKit run peaks at 1,053,081,600 bytes
with no OOM event, then stops before the archive probe. Both archive probe blocks
pass. The new profile's 3.11 and 3.13 builds peak at 4,089,753,600 and
3,693,395,968 bytes, with no OOM events. All three application runs stay below
the 7 GiB target. Complete application suites, audits, public pricing comparisons,
and the dependency's 3.11/3.13 ownership checks remain pending. PR 43 remains draft.

Snapshot and fixture allocation follow-up: the allocator census found
490,162,455 bytes in unused mock call histories. The historical fixture now uses
small async functions while preserving all requests and exact counters. With
production unchanged, median process RSS falls from 968,015,872 to 425,013,248
bytes. Immutable slotted snapshots and shared lowercase address strings then
reduce it to 276,500,480 bytes on the same historical workload. The new string
cache holds 155 keys, with 2,180,089 hits and 155 misses; it uses the existing
address-cache size setting and retains no discovery objects. All 239 focused
tests pass. Historical median time changes from 2.581 to 2.628 seconds, with
unchanged read and quote counts. These exploratory comparisons used the same
12 GiB default VM before the approved profile split. Their workload hashes differ
because the latter adds address-cache statistics. A final comparison with the
identical recorded workload will run in the new 10 GiB profile.

Four small supervisor tests pass. They check bounded log retention, missing
reports, dependency drift, and an OOM in a build worker despite a successful
build exit. The last check also verifies BuildKit cleanup. The RPC profile's
independent cgroup probe confirms 8 GiB, no swap, four CPUs, and 512 tasks; it
does not run or claim a benchmark result.

The first contained original full suite collected 1,752 tests and produced 1,154
completed outcomes before the validation reporter failed. An import-guard fixture
replaced `dank_mids` with a stub that had no `instances` attribute. This was a
reporter defect. The run has no final pytest summary and remains incomplete in
`full-original-reporter-failure`. Its peak container memory was 1,552,637,952 bytes,
with no OOM event. The corrected reporter omits unavailable counters during that
fixture. A new original full-suite run uses the same image and a fresh database.

A separate child in that container completed a SQLite query but could not exit.
Its stack showed Python waiting for an idle, non-daemon aiosqlite worker. The
process-owned Brownie cursor now queues connection closure before Python joins
threads. It preserves connection reuse and queued SQL work. All 243 focused tests
pass on Python 3.11, 3.12, and 3.13, including compiled child-process checks with
open and closed event loops and both import-guard cases. All ten configured
extensions load in each run. See `shutdown-*-validation`.

The first shutdown matrix exposed one new type error in a supervisor test.
The test now patches the standard-library module directly. The final separate
type checks again report 1,940 existing errors on each Python version, with no
added rendered diagnostic against the baseline. See `shutdown-*-mypy-final` and
`shutdown-mypy-comparison.json`. Four supervisor tests, Black, and whitespace
checks pass. Complete full suites and real-node comparisons remain outstanding.

The corrected original full suite reached 1,351 completed outcomes out of 1,752
collected tests, then hit the 8 GiB cgroup limit. Docker recorded `OOMKilled=true`
and one cgroup OOM kill. The command exited 2 after 4,607.7 seconds and produced
no final pytest summary. The last phase was setup for the synchronous Compound
pricing case at `0x6C8c6b02E7b2BE14d4fA6022Dfd6d75921D90E4E`; its setup peak RSS
was 1,262,678,016 bytes before the subsequent rise to the limit. This is partial
evidence, not a complete baseline comparison. See `full-original-oom`. Small
dependency diagnostic processes also ran inside this container, so use separate
controlled runs for final performance comparisons.

The scheduler follow-up at `4b1ac302a000f27a9d80dc687ed03ac1a41f1cd1` removes
negative wait timeouts without changing concurrency or the 600-second deadline.
Seven focused dependency checks pass. The full dependency suite has 82 passes,
16 skips, and the same two existing failures. Three short I/O probes reduce
median wait calls from 25,848 to one and CPU time from 0.2065 to 0.00661 seconds.
Wall time stays near 0.207 seconds and median peak RSS stays at 36,044,800 bytes.
This change reduces allocation activity and CPU use; the earlier ownership
repair provides the retained-memory reduction.

The owning [aiosqlite repair](https://github.com/SatoshiAndKin/aiosqlite/pull/1)
drains queued SQL through closed-loop delivery races and releases idle worker
outcomes. Real database and weak-reference regressions fail against the prior
worker and pass after the repair. All 36 dependency tests pass locally in Linux
ARM64 Python 3.9.25 and 3.12.14; configured package mypy reports no issues in 11
files. The CI test, coverage, and type commands pass on Python 3.9–3.13 across
Linux, macOS, and Windows. The final test-only correction at
`b8265cce6f09bcc8015ea09036f5e05c4546d740` also passes the configured local tests,
83.6% coverage, type check, lint, wheel build, and source build. See
`sqlite-owner-configured`. Its final CI run passes all 15 platform/version jobs
and the package build. The final application integration matrix remains pending.
Both dependency PRs and PR 43 remain draft.

The runner now freezes helper files and workload inputs before a build. This
fixes a provenance gap when the checkout changes during dependency installation.
Five supervisor tests pass, including execution of the recorded helper after
the live checkout is edited. Subsequent comparison runs use these frozen inputs.

The Compound diagnostic on the original source was stopped after a controlled
regression confirmed retained HTTP retry failures in dank_mids. It completed no
pricing blocks. Its report remains incomplete, with no OOM recorded. During the
profile, Python TLS buffer allocations grew from 8,914,834 to 251,450,759 bytes.
The small regression then showed that eight failed HTTP 408 attempts remained
owned while their replacement waited. This confirms one retention defect; it
has not established the sole cause of the full-suite OOM. See
`compound-retry-profile`.

The owning [dank_mids repair](https://github.com/SatoshiAndKin/dank_mids/pull/9)
at `c4f8ad7fc62152f0017ee6a6b206e31b4fe03579` leaves each HTTP 408 exception
handler before it awaits the next attempt. Both release regressions now pass.
All ten new cases pass, including cancellation, unchanged IDs, non-408 errors,
and both local-timeout race winners. The full source unit comparison changes
96 passes / 33 failures / 2 skips into 98 passes / 31 failures / 2 skips. The 31
remaining failures are identical, including missing native extensions and class
identity checks. The changed method has 25/25 statements and 4/4 branches covered.
Configured mypy has the same 205 diagnostics before and after.

Three controlled Linux ARM64 samples preserve 64 concurrent requests and 1,088
attempts each. Median pending RSS falls from 295,972,864 to 227,442,688 bytes;
median elapsed time falls from 0.029021 to 0.020908 seconds. These runs use no
forced collection. The original retains all 1,024 failed payloads; the repaired
samples retain 194 / 258 / 258 until normal cyclic collection. Separate allocation
runs keep profiler overhead out of the timing figures. The weak-reference checks
confirm that pending retries no longer own earlier failures after collection.
See `dank-retry`. Native ARM64 dependency builds remain blocked by existing source
build/type errors. Updated hosted native unit CI passes all 12 platform/version
jobs, and all 15 native builds plus artifact aggregation pass. Final pricing
validation remains pending. All three owning PRs and pricing PR 43 remain draft.

The final dependency image for Python 3.12 built successfully, but the archive
probe timed out on USDC decimals at block 16,830,000. A second contained probe
failed at the same historical call. Chain ID and the historical header returned.
The separate rpc-tune profile had no running container during the second check.
The focused suite also remained in `eth_retry` during Multicall creation-block
lookup, before test collection. Its saved stack and two failed probes establish
an archive-access blocker. That startup was stopped and marked incomplete; no
focused test pass or compiled-load pass is claimed for this run. See
`archive-access-failure`. Containment, builds, type comparisons, and dependency
checks can continue without that archive state. Full suites, scaling startup,
and real-node price comparisons still require working archive access.

Final independent checks pass in the approved profiles. Dependency images and
application extension builds succeed on Python 3.11–3.13. BuildKit peaks are
1,038,311,424 / 1,336,922,112 / 3,330,588,672 bytes for Python 3.12 / 3.11 / 3.13,
with no OOM events. Application build containers stay at or below 1,242,468,352 bytes.
The configured type checks retain 1,940 errors and the same 1,935 rendered Python
diagnostic records on every version, with no added or removed records. The new
probe annotation error was fixed and its corrected check is recorded separately.
All seven cooperative ownership/deadline tests and all 36 SQLite tests pass in
Linux ARM64 Python 3.11 and 3.13; SQLite's configured types also pass. This extends
the earlier Python 3.12 dependency evidence. See `final-independent`.

The new-profile containment checks pass, including deliberate OOM, cancellation,
duplicate prevention, and report persistence. The actual runner's 600 MiB log
check retains five 100 MiB files and discloses 100 MiB expired output.

The retry probe's initial twelve rounds did not establish a plateau, so a
240-round check ran in one process with unchanged concurrency and normal cyclic
collection. It completes 261,120 attempts. Across rounds 41–240, pending RSS stays
between 249,974,784 and 304,013,312 bytes; every sample has 129 pending tasks and
normal collection reports no uncollectable objects. No forced collection or
process restarts occur. See `dank-retry/turnover-240`. These are controlled retry
results, not a replacement for complete public pricing or full-suite validation.
