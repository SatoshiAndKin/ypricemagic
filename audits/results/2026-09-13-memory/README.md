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

The dependency repair is pinned at
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
