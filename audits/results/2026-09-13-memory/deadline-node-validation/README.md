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

`full-deadline-original` records 291 passed calls, 109 failed calls, 9 skipped calls, 3 setup failures, and 0 setup skips. Its final pytest summary is missing.
It records 1 cgroup OOM kills and Docker `OOMKilled=true`. It loads 10 compiled modules; the archive probe passes. Expired console bytes: 0.

`full-deadline-preoptimization` records 305 passed calls, 169 failed calls, 9 skipped calls, 3 setup failures, and 0 setup skips. Its final pytest summary is missing.
It records 1 cgroup OOM kills and Docker `OOMKilled=true`. It loads 10 compiled modules; the archive probe passes. Expired console bytes: 0.

A reported peak can include a small cgroup accounting overshoot. The effective memory limit remains 8,589,934,592 bytes; no limit was raised.

Installed dependency lists for the persisted runs are byte-identical.

Pending final reports: 15 of 17.

- `full-deadline-optimized`
- `native-deadline-before`
- `native-reviewed-deadline-before`
- `native-deadline-after`
- `native-reviewed-deadline-after`
- `public-deadline-before-timing-1`
- `public-deadline-before-timing-2`
- `public-deadline-before-timing-3`
- `public-deadline-before-allocations`
- `public-deadline-after-timing-1`
- `public-deadline-after-timing-2`
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
