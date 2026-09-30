# Cached Sushi comparison with the repaired requester

Both source runs finish with exit status zero. They use the same Python 3.12
image, dependency versions, frozen workload, and helpers. All ten configured
extensions load. Archive probes pass. Each source runs three timing samples
and a separate allocation profile.

| Measure | Before | After |
| --- | ---: | ---: |
| Median process peak RSS bytes | 424,853,504 | 276,234,240 |
| Median workload seconds | 2.638235577 | 2.639275379 |
| Python allocation peak bytes | 212,564,995 | 83,515,159 |

The workload retains 4,771 pools, 75 input pools, 4,128 historical blocks,
309,675 liquidity reads, and 4,131 quote calls. Peak discovery operations remain
64. Final market and result caches contain 4,096 and 2,048 entries. Exact USD,
input/output amount, independent-path, and cached-child assertions pass on both
sources. Each comparison collects garbage at matching measurement boundaries.
It does not clear caches or restart the process within a workload.

This is controlled cached topology work. It does not measure real-node pricing
latency or cold event discovery. The [full suites](../requester-full-suites/README.md)
still reach the unchanged 8 GiB limit. These results do not resolve that failure.
Source SHAs and all measured values appear in [comparison.json](comparison.json).
