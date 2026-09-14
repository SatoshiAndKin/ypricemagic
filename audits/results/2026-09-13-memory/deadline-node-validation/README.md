# Final deadline-aware node validation

These runs use the final Python 3.12 dependency image after the
[deadline and request ownership repair](../sync-deadline/README.md).
Each run has its own Linux source workspace and database. The original,
pre-optimization, and optimized full suites execute the required command:

```sh
PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test
```

All builds and tests run in sequence in `colima-ypricemagic`. The container
limits remain 8 GiB, zero swap, four CPUs, and 512 processes or threads.
The builder stops before tests. An OOM, interruption, or missing report keeps
validation incomplete. A complete execution can still contain failed tests.
The target peak remains below 7 GiB.

Dependency image: `sha256:d0eb8585a747730516769a0223fa674ef9ffbc602ff32e801b0ca1e5e9136e48`.

| Run | Source | Terminal / collected | Seconds | Container peak bytes | Complete execution | Exit |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| [full-deadline-original](full-deadline-original/run.json) | `476af288a520a30052668a8b3ad7e3e682cd101f` | 412 / 1752 | 1203.63 | 8589934592 | no | 2 |
| [full-deadline-preoptimization](full-deadline-preoptimization/run.json) | `61be7b520aba7f771a0bf96b326315e68767fae4` | 486 / 1816 | 1525.52 | 8589996032 | no | 2 |
| [full-deadline-optimized](full-deadline-optimized/run.json) | `c16d43e0c6b38e146834f0cd8d75090bb25222c7` | 1467 / 1865 | 6465.46 | 4401676288 | no | 130 |
| [native-deadline-before](native-deadline-before/run.json) | `61be7b520aba7f771a0bf96b326315e68767fae4` | — / — | 242.84 | 1171931136 | no | 130 |
| [native-reviewed-deadline-before](native-reviewed-deadline-before/run.json) | `61be7b520aba7f771a0bf96b326315e68767fae4` | — / — | 363.29 | 1165611008 | no | 130 |
| [native-deadline-after](native-deadline-after/run.json) | `c16d43e0c6b38e146834f0cd8d75090bb25222c7` | — / — | 119.56 | 1165357056 | yes | 0 |
| [native-reviewed-deadline-after](native-reviewed-deadline-after/run.json) | `c16d43e0c6b38e146834f0cd8d75090bb25222c7` | — / — | 333.08 | 1164902400 | yes | 1 |
| [public-deadline-before-timing-1](public-deadline-before-timing-1/run.json) | `61be7b520aba7f771a0bf96b326315e68767fae4` | — / — | 745.57 | 8589950976 | no | 137 |
| [public-deadline-before-timing-2](public-deadline-before-timing-2/run.json) | `61be7b520aba7f771a0bf96b326315e68767fae4` | — / — | 883.55 | 8589971456 | no | 137 |
| [public-deadline-before-timing-3](public-deadline-before-timing-3/run.json) | `61be7b520aba7f771a0bf96b326315e68767fae4` | — / — | 714.51 | 8589946880 | no | 137 |
| [public-deadline-before-allocations](public-deadline-before-allocations/run.json) | `61be7b520aba7f771a0bf96b326315e68767fae4` | — / — | 652.56 | 8589934592 | no | 137 |
| [public-deadline-after-timing-1](public-deadline-after-timing-1/run.json) | `c16d43e0c6b38e146834f0cd8d75090bb25222c7` | — / — | 1357.36 | 3222843392 | yes | 0 |
| [public-deadline-after-timing-2](public-deadline-after-timing-2/run.json) | `c16d43e0c6b38e146834f0cd8d75090bb25222c7` | — / — | 1374.31 | 3111694336 | yes | 0 |

`full-deadline-original` records 291 passed calls, 109 failed calls, 9 skipped calls, 3 setup failures, and 0 setup skips. Its final pytest summary is missing.
It records 1 cgroup OOM kills and Docker `OOMKilled=true`. It loads 10 compiled modules; the archive probe passes. Expired console bytes: 0.

`full-deadline-preoptimization` records 305 passed calls, 169 failed calls, 9 skipped calls, 3 setup failures, and 0 setup skips. Its final pytest summary is missing.
It records 1 cgroup OOM kills and Docker `OOMKilled=true`. It loads 10 compiled modules; the archive probe passes. Expired console bytes: 0.

`full-deadline-optimized` records 1076 passed calls, 370 failed calls, 15 skipped calls, 0 setup failures, and 6 setup skips. Its final pytest summary is missing.
It records 0 cgroup OOM kills and Docker `OOMKilled=false`. It loads 10 compiled modules; the archive probe passes. Expired console bytes: 0.

The optimized full suite is interrupted after its synchronous Compound case
`0x158079Ee67Fce2f58472A96584A73C7Ab9AC95c1` emits the 600-second timeout dump
but produces no call or teardown report after 2,114.65 seconds. The earlier
three synchronous cases report their timeouts and advance. A
[native stack sample](full-deadline-optimized/deadline-native-stack.txt)
shows the original pending request at block 7,720,755 and
`a_sync/a_sync/_helpers.pyx:83`; it is not the cancellation cleanup gather.
The cause of this unpropagated timeout remains unresolved. The
[failure record](full-deadline-optimized/deadline-failure.json) preserves the
last state, diagnostic tool hash, and the diagnostic container's 128 MiB limit.
This read-only diagnostic does not change application dependencies.

The [active RPC route check](full-deadline-optimized/application-rpc-route.json)
confirms that the pytest process uses the requested archive route: 33 established
connections match it, and none use another host at the RPC port. This proves
route selection, not the cause of slow pricing. Private endpoints remain omitted.
All three full-suite executions remain incomplete, so the comparison cannot
establish full coverage or absence of new failures. The existing queue continues
the independent native quote, public pricing, and audit checks.

A reported peak can include a small cgroup accounting overshoot. The effective memory limit remains 8,589,934,592 bytes; no limit was raised.

Installed dependency lists for the persisted runs are byte-identical.

### Partial full-suite observations

These are exact-ID observations from incomplete runs. They do not establish
full coverage or attribute a changed result to an implementation change.
Some test bodies also use dynamic historical samples when their IDs match.
Missing tests remain unmatched and never become passes.

| Baseline | Common observed terminal IDs | Pass to fail | Fail to pass | Both pass | Both fail | Both skip |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [original](partial-full-observations/original.json) | 364 | 28 | 27 | 263 | 40 | 6 |
| [preoptimization](partial-full-observations/preoptimization.json) | 429 | 23 | 25 | 282 | 93 | 6 |

All 23 pass-to-fail changes against the pre-optimization run are cooperative
Chainlink feed timeouts. The comparison against the original PR baseline also
includes ten `int(None)` errors in latest-feed cases. Exact errors, unmatched
IDs, source and dependency hashes, and the analysis helper remain in the linked
reports. The final full-suite comparison stays incomplete.


### native-deadline

| Revision | Cases | Passed | Failed | Complete execution | Exit |
| --- | ---: | ---: | ---: | --- | ---: |
| [before](native-deadline-before/native.json) | 6 | 6 | 0 | no | 130 |
| [after](native-deadline-after/native.json) | 6 | 6 | 0 | yes | 0 |

All recorded case rows match exactly, including fixed block identity, output amounts, quote steps where recorded, and errors.

The `before` process needs intervention after its final workload report because an idle SQLite worker blocks interpreter exit. Its run stays incomplete. [Shutdown evidence](native-deadline-before/post-report-shutdown-failure.json).

Run elapsed time and container peaks include extension preparation and process shutdown; they do not measure native quote latency alone.

### native-reviewed-deadline

| Revision | Cases | Passed | Failed | Complete execution | Exit |
| --- | ---: | ---: | ---: | --- | ---: |
| [before](native-reviewed-deadline-before/native-reviewed.json) | 8 | 7 | 1 | no | 130 |
| [after](native-reviewed-deadline-after/native-reviewed.json) | 8 | 7 | 1 | yes | 1 |

All recorded case rows match exactly, including fixed block identity, output amounts, quote steps where recorded, and errors.

The `before` process needs intervention after its final workload report because an idle SQLite worker blocks interpreter exit. Its run stays incomplete. [Shutdown evidence](native-reviewed-deadline-before/post-report-shutdown-failure.json).

Run elapsed time and container peaks include extension preparation and process shutdown; they do not measure native quote latency alone.

### Public pricing workloads

The workload calls public pricing at fixed blocks with cold, warm,
repeated-amount, concurrent, and many-block requests. It requires 99 completed
calls. These rows include failed and incomplete repetitions.

| Run | Reported calls / 99 | Complete workload | Cgroup OOM kills | Docker OOMKilled | Final pricing summary |
| --- | ---: | --- | ---: | --- | --- |
| [public-deadline-before-timing-1](public-deadline-before-timing-1/run.json) | 0 / 99 | no | 1 | true | missing |
| [public-deadline-before-timing-2](public-deadline-before-timing-2/run.json) | 0 / 99 | no | 1 | true | missing |
| [public-deadline-before-timing-3](public-deadline-before-timing-3/run.json) | 0 / 99 | no | 1 | true | missing |
| [public-deadline-before-allocations](public-deadline-before-allocations/run.json) | 0 / 99 | no | 1 | true | missing |
| [public-deadline-after-timing-1](public-deadline-after-timing-1/run.json) | 99 / 99 | yes | 0 | false | present |
| [public-deadline-after-timing-2](public-deadline-after-timing-2/run.json) | 99 / 99 | yes | 0 | false | present |

An OOM before the first cold result supplies no completed price row or final
pricing summary. It cannot enter a 99-call timing median. A revision needs all
three complete timing repetitions for its median; allocation profiles remain
separate. Exact-row differences preserve missing and unmatched rows and do not
turn them into evidence of changed prices.

| Complete run | Pricing seconds | Workload peak RSS bytes | Live tasks at end | Market / result / state cache entries |
| --- | ---: | ---: | ---: | --- |
| [public-deadline-after-timing-1](public-deadline-after-timing-1/public-summary.json) | 1252.33 | 2087518208 | 53 | 33 / 35 / 16384 |
| [public-deadline-after-timing-2](public-deadline-after-timing-2/public-summary.json) | 1253.86 | 2078216192 | 53 | 33 / 35 / 16384 |

Pricing time excludes extension preparation and process shutdown. Workload RSS comes from `resource.getrusage`; sampled process RSS and total container memory remain separate in run metrics. Allocation-profile timings are excluded from performance medians. Logical RPC counters remain in each linked summary; they count adapter operations and batching, not necessarily physical requests.

Exact price, amount, block, path, and error rows within `after` match across 2 completed workloads. Timing and logical RPC counters are excluded from this semantic comparison. This does not establish equality against a baseline that returned no prices.

Pending final reports: 4 of 17.

- `public-deadline-after-timing-3`
- `public-deadline-after-allocations`
- `audit-deadline-before`
- `audit-deadline-after`

[Run metrics](runs.json) preserve exact outcomes, cgroup OOM events, Docker
`OOMKilled`, source and runner hashes, dependencies, and log retention.
[Comparisons](comparisons.json) contain completed pairs as they become available.
Full test errors, exact native quote rows, public pricing rows, and audit JSON/CSV
remain separate. Three unprofiled timing runs
produce medians only when all 99 calls complete; allocation profiles remain
separate from those timings.

Some existing full-suite cases derive historical samples from the current chain
height. Sequential runs can therefore collect different block-specific test
IDs. The comparison preserves those IDs and reports unmatched coverage. It
does not normalize away block identity. Native and public-pricing workloads
use fixed historical blocks for exact price and amount comparisons.

The preceding two OOM runs and interrupted optimized run remain separate in
[the previous node reports](../final-node-validation/README.md). They do not
become complete when a later run finishes. Console logs stay local and rotate
at 100 MiB with five retained files. Published inventories disclose private
value removal and retain original and published file hashes.

PR #43 remains draft until required validation is complete. Inspect incomplete
flags and exact failures before making full coverage or price-equivalence claims.
