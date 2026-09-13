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
now has 12 GiB of memory and 5 CPUs.

The dependency repair is pinned at
`3089b3ddd393a45655b5231e6a67b54dd5529196` in
[SatoshiAndKin/pytest-asyncio-cooperative PR 1](https://github.com/SatoshiAndKin/pytest-asyncio-cooperative/pull/1).
Its full Python 3.12 suite has 80 passes, 16 skips, and the same two failures as
the unchanged revision (75 passes). Five new ownership checks pass. Three
controlled runs at concurrency 100 reduce median peak RSS from 716,128,256 to
186,753,024 bytes, with zero completed fixtures retained instead of 4,000.

The 238 focused application tests pass on Linux ARM64 Python 3.12.14 with all ten
configured compiled extensions. The scaling check preserves 64 operations,
4,771 cached pools, 4,128 historical blocks, 309,675 state reads, and 4,131 quotes.
The type check remains non-green: 1,940 errors versus 1,959 on the unchanged
revision with the same dependency image. No rendered diagnostic was added.

Docker containment, real runner cancellation, atomic duplicate prevention, and
report persistence pass. A deliberate 64 MiB OOM exits 137 with `OOMKilled=true`.
The log test writes 600 MiB, retains five 100 MiB files, and reports 100 MiB of
expired output. The locked Python 3.12 BuildKit run peaks at 1,053,081,600 bytes
with no OOM event, then stops before the archive probe. Both archive probe blocks
pass. Complete application suites, audits, public pricing comparisons, and
Python 3.11/3.13 validation remain pending. PR 43 remains draft.
