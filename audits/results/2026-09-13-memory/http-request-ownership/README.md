# HTTP request ownership

The repair resides in dank-mids, source commit
`c9b17b58bb7908b46bf20e35ba7c262e3750105d`. The application pins
`9a58cd91b4a652ac10d41cc5862c7b2770727632`, which adds the successful CI-generated
native artifacts without changing Python source. Full application validation
with this pin remains incomplete.

The requester now uses the standard cross-thread future bridge. Cancelling a
caller cancels its HTTP operation on the session's event loop. RPC and JSON
batch races close their remaining owned attempts after success, failure, or
cancellation. Completed batch tasks leave the registry, and log records retain
the rendered diagnostic instead of its task. Request IDs, retry rules, the two
timeout-race winners, and independent callers remain covered.

## Controlled measurements

Each revision runs three unprofiled samples and one separate allocation sample.
Each sample sends the same 256 HTTP bodies, with 64 concurrent callers and
128 KiB payloads. Measurements precede final cleanup. Both revisions use the
same dependency image, frozen helper, and cancellation-settlement interval.
There is no forced collection, cache clearing, or process restart within a
sample. The [comparison](comparison.json) retains all exact request hashes.

| Measurement | Before | After |
| --- | ---: | ---: |
| Median process peak RSS, bytes | 203,718,656 | 169,242,624 |
| Median elapsed seconds | 6.416846 | 6.454716 |
| Open server connections after the workload | 256 | 0 |
| Pending requester tasks after the workload | 256 | 0 |
| Process file descriptors after the workload | 539 | 27 |
| Python allocations retained, bytes | 38,666,620 | 336,629 |
| Python allocation peak, bytes | 39,075,173 | 10,466,554 |

The RSS reduction is 16.9%; elapsed time increases 0.6% in this local workload.
This measures source modules on Linux ARM64. It does not measure real-node
latency or establish the sole cause of the earlier application descriptor failure.

The [turnover run](turnover-100/summary.json) completes 6,400 calls in 100 rounds
in one process. Across rounds 21–100, RSS stays between 172,404,736 and
173,281,280 bytes. Every round records zero open server connections, zero pending
requester tasks, and 27 file descriptors. Python's normal cyclic collector stays
enabled. The raw report retains both `/proc` RSS and `getrusage` peak measurements;
these Linux counters use different accounting and are reported separately.

## Behavior, coverage, and native checks

The complete local source suite uses 150 identical cases and dependencies:
97 passed, 51 failed, and two skipped before; 117 passed, 31 failed, and two
skipped after. Twenty failures are fixed and no failed test ID is added.
The 31 remaining terminal errors match after replacing only object addresses.
They include required native-extension and source/native class-identity checks.
All 29 focused ownership cases pass within this run.

The complete source coverage run covers all 56 changed statements and 17 of
18 changed branches. The remaining branch exhausts a nonempty `as_completed`
loop that returns its first result. Both configured type checks report 205
errors in 19 files. Two raw messages change only a referenced source line and
union-member order. The comparison retains those raw differences and reports
no added semantic diagnostic. No local type-check pass is claimed.

[Native unit CI](https://github.com/SatoshiAndKin/dank_mids/actions/runs/34794957696)
passes all 150 tests in each of 12 jobs on Linux, macOS, and Windows with Python
3.10–3.13. Each job compiles the current checkout before testing.
[Native build CI](https://github.com/SatoshiAndKin/dank_mids/actions/runs/34794957700)
passes all 15 platform/Python builds and artifact aggregation. Lint passes.
The twelve CI type-check jobs report 80 existing errors in 11 files each.
[Job records and artifact provenance](native-ci/source-and-artifacts.json)
remain separate from the local ARM64 source evidence.

## Preserved failed attempts

- `first-repair-failures` records four failures in the first repair: local
  cleanup variables retained the final failed payload, and logging arguments
  retained completed tasks. Production cleanup fixed them; assertions stayed.
- `batch-control` records three failing JSON batch cleanup cases before repair.
- `incomplete-profile-harness` records an interrupted first profile. Python
  3.12 server shutdown waited for leaked control connections before the harness
  wrote its report. The final harness writes measurements before cleanup, then
  closes the server. The interrupted attempt is not a memory sample.
- `native-global-version-failure` records a source version override that made
  an ez-a-sync dependency build report version 0.0.0. The runner now scopes its
  override to ypricemagic. `native-abi-build-failure` records the subsequent
  existing faster-eth-abi 5.2.26 source-build type failures. Neither local
  attempt reached native dependency tests. Hosted native results are separate.

Every run retains its command, source archive hash, dependencies, helper hashes,
elapsed time, exit status, cgroup counters, Docker final state, and console
retention record. No OOM occurs. The `.py.txt` files preserve exact source without
letting repository formatters alter historical evidence.
