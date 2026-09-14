# Synchronous deadline and request ownership

The full optimized run stopped after confirming that its configured
`timeout = 600` had no installed synchronous handler. The cooperative plugin
enforced its own deadline, but `pytest-timeout` was absent. The interrupted
run remains incomplete in [the node reports](../final-node-validation/README.md).
Its waiting stack does not prove a pricing deadlock.

The application now requires `pytest-timeout==2.2.0` and declares it in the
central pytest `required_plugins` setting. This version supports the pinned
pytest 6.2.5. The newer inspected releases require pytest 7 or 8.4. The
[registry metadata](pytest-timeout-selection) preserves that selection.
The 600-second deadlines and cooperative concurrency of 100 remain unchanged.
Missing the synchronous plugin now stops collection before a test can run.

Two Docker integration checks verify the missing-plugin error and a real
synchronous timeout. The second check keeps 100 cooperative requests active
together, interrupts a marked synchronous test after one second, executes its
`finally` and fixture teardown, and then runs the next test. The child records
one expected failure and 101 passes. Both outer checks pass on Python 3.11,
3.12, and 3.13. The earlier negative helper and its failed output remain separate.

A separate native probe confirmed an ez-a-sync ownership defect. A signal
interruption outside `run_until_complete` left the created request task pending
and skipped its async `finally`. The original probe records one pending task;
the repaired probe records zero and completed cleanup. Both preserve the exact
original exception instance.

The application pins ez-a-sync
`ed3459ee74abec91c7675f57fee4b75595edbfdc`. Its synchronous bridge creates and
owns the request task, cancels and settles it after a caller interruption, and
then raises the original error. A cleanup error does not replace that error.
Pre-existing futures and independent shielded requests retain their ownership.
The repair lives in the dependency; the application adds no runtime patch.

The five signal regressions cover two interruption types, successful and failed
cleanup, and independent shared-request survival. All five fail against the
original native helper. All 52 focused owner checks pass after repair on
Python 3.11–3.13. Four owner modules load native extensions, including `_helpers`.
The same-source 752-case owner comparison changes 745 passes, six failures,
and one skip into 750 passes, one failure, and one skip. It adds no failed IDs.
The existing `test_create_task_skip_gc_until_done` failure remains. The 14
semaphore timing failures from the earlier property comparison pass on both
sides of this comparison; this repair does not claim to fix them.

The owner CI includes Windows. A separate test-only follow-up replaces POSIX
signal injection with a test-owned event loop that raises the same caller
errors outside the request task. It retains all five cases and every cleanup,
exception, next-request, and shared-request assertion. Its matched controls
are recorded separately from the real Linux signal probe.

The portable full comparison also records 745 passes, six failures, and one skip
before repair, then 750 passes, one failure, and one skip after repair. All 52
portable focused checks pass on each of Python 3.11–3.13. Test-only commit
`03bf8d4aabd80ee538ee5ee03f0010c65246f63d` contains the portable fixture and its
documentation. It leaves runtime sources unchanged, so the application retains
the tested `ed3459e` runtime pin. The GitHub dependency PR has no CI runs;
Windows execution remains unverified. [Exact full comparisons](full-comparisons.json)
and [source identities](source-artifacts/source-proof.json) preserve both controls.

| Python | Application passes | Deadline checks | Owner passes | Application container peak bytes | Type diagnostics before / after |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3.11 | 278 | 2 | 52 | 1,163,370,496 | 1,836 / 1,836 |
| 3.12 | 278 | 2 | 52 | 1,166,147,584 | 1,836 / 1,836 |
| 3.13 | 278 | 2 | 52 | 1,200,775,168 | 1,836 / 1,836 |

The ordinary pinned application matrix passes the archive probe and loads all
ten configured mypyc extensions on each version. Installed Git revisions,
cooperative plugin bytes, and timeout version match the declared inputs.
The type comparison uses identical installed dependencies on each side and
adds no diagnostics. Owner type checks retain 304 existing diagnostics on
Python 3.11 and 300 on Python 3.12/3.13. Cache and factory runtime assertions
pass. These type checks remain failing checks.

All runs use Linux ARM64 in the dedicated Colima profile. Builds and tests run
sequentially with 8 GiB memory, zero swap, four CPUs, and 512 processes or
threads. The builder stops before tests. Completed reports preserve command,
source hashes, dependencies, elapsed time, exit state, cgroup and process memory,
OOM state, and log retention. Private RPC values are removed from published
files; their inventories retain original and published hashes.

The full-suite, native quote, public-pricing, and audit replacement queue uses
the final Python 3.12 image with separate databases. Its results remain separate
from these focused checks. PR #43 remains draft until required validation is
complete.
