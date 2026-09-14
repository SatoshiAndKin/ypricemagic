# Bound historical event work by the existing fetch capacity

The event loader now admits only the chunks that processing and persistence can
accept. It keeps the existing semaphore limit, refills each released slot,
processes out-of-order results in block order, and advances checkpoints after
the corresponding write. Cancellation and failure close owned fetches. An
already queued write remains owned by the filter and finishes before reuse.
A semaphore with zero permits keeps a waiter until a permit becomes available.
Verbose progress uses the existing logger. DEBUG-only five-minute stuck-call
diagnostics remain in place.

## Controlled memory comparison

The before and after runs use identical dependencies, helpers, and frozen
fixtures. Each source runs three timing samples and a separate allocation
profile. All ten configured application extensions load. The fixture fetches
512 chunks of 262,144 bytes, using 32 concurrent fetches and controlled in-process
fetch/write delays. It verifies the ordered payload digest and every checkpoint.
It performs no real RPC within the measured workload.

| Measure | Before | After |
| --- | ---: | ---: |
| Median process peak RSS bytes | 319,193,088 | 195,379,200 |
| Median workload seconds | 1.752524682 | 1.822884427 |
| Peak retained chunks, each timing run | 499 | 32 |
| Python allocation peak bytes | 131,755,799 | 8,530,993 |
| Retained chunks after completion | 0 | 0 |

Median time increases by about 4%. Fetch concurrency and work counts remain
unchanged. Both revisions produce digest
`51dfdc30539dad6b5e53e3fd51531483e0ea5f1151efa49aedf45a3f8968bf75` and final block
512. No forced collection, cache clearing, or process restart occurs within a
workload. See [the full comparison](profile/comparison.json) for source identity
and individual samples. These results do not establish real-node pricing latency.

## Regression and type checks

The original control passes 256 of 259 checks and fails three new regressions.
It fetches all 128 chunks behind a blocked consumer or writer, instead of keeping
four in that fixture. Caller cancellation leaves four fetches active. The final
suite adds ordering, failure, write ownership, reuse, and closed-semaphore cases.
The following matrix records the final source and its complete pytest results.

| Python | Focused passes | Configured type errors before / after | Status |
| --- | ---: | ---: | --- |
| 3.11 | 264 | 1,935 / 1,922 | Tests pass; existing type failures remain |
| 3.12 | 264 | 1,935 / 1,922 | Tests pass; existing type failures remain |
| 3.13 | 264 | 1,935 / 1,922 | Tests pass; existing type failures remain |

The type-only commands and installed dependency records match the earlier
baseline exactly. The parser records 1,930 → 1,917 diagnostics: 13 removed,
none added. The combined native-test/type runs install the application editable;
their diagnostic maps match the type-only results. Raw records retain both
commands and their installation difference. Type checks still fail.

Development reports retain two test corrections. The first assertion incorrectly
forbids a completed raw database write while event processing waits; the corrected
assertion preserves this existing behavior. A later observer stores its current
task inside a cancelled coroutine and creates a task/traceback cycle. The small
standard-library diagnostic and the container reference graph identify that
cycle. The final observer stores task IDs, and release checks pass without
forced collection. Diagnostic collection is not used as a production repair or
as memory performance evidence.

## Remaining application validation

The 29-case historical profile before this repair finishes with 10 passes and
19 failures, at a 5,477,474,304-byte container peak. It retains roughly half a
million raw logs late in the run; pytest log capture remains empty. Profiling
adds overhead and the workload includes configured timeouts.

The [three full suites before this repair](../requester-full-suites/README.md)
all reach 8 GiB and remain incomplete. The
[committed historical profile](../event-historical/README.md) now finishes without OOM at 4,798,681,088 container bytes. Its ten passes and 19 failures
remain separate from the running full suite and remaining native/public pricing
and audit checks. Limits remain 8 GiB, no swap, four CPUs, and 512 processes/threads.
PR #43 remains draft.
