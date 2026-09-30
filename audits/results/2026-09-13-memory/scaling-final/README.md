# Controlled Sushi comparison in the 10 GiB profile

Both revisions complete three timing samples and one separate allocation sample
with the same Linux ARM64 Python 3.12 image, dependency versions, helper hashes,
workload hashes, and resource limits. Every run loads all ten configured compiled
extensions. Neither container records an OOM event.

| Measurement | Before `61be7b52` | After `850d7506` |
| --- | ---: | ---: |
| Median workload peak RSS | 443,097,088 bytes | 294,731,776 bytes |
| Median workload time | 2.76070 s | 2.65251 s |
| Median historical phase time | 2.62673 s | 2.53667 s |
| Separate Python allocation peak | 212,561,486 bytes | 83,515,112 bytes |
| Python memory after workload teardown | 4,564,892 bytes | 4,596,090 bytes |
| Container peak, including build and profiler | 1,489,649,664 bytes | 1,242,202,112 bytes |

Median workload RSS falls 33.48%, and elapsed time falls 3.92%. The small increase
after teardown includes the shared address cache. At the end of the changed
workload, it has 155 entries, 155 misses, and 2,180,089 hits. Its configured
100,000-entry capacity stays unchanged.

All eight samples preserve 4,771 pools, 64 concurrent operations, 4,128 historical
blocks, 309,675 controlled state reads, and 4,131 quotes. The market and result
caches finish at their existing limits of 4,096 and 2,048 entries. No cache is
cleared during the historical turnover workload. Assertions preserve USD 1,994
for one token and output amount 997,000,000,000,000,000 base units.

The frozen workload uses the same small async fixtures on both revisions. This
comparison measures the production snapshot and address-sharing changes; the
earlier fixture-history reduction has separate evidence. The native RPC boundary
is controlled. These figures do not establish real-node pricing latency or resolve
the separate full-suite OOM. Profiler timings are excluded from the timing table.

The private reports retain phase output and bounded console logs. No console
output expired. `comparison.json` includes source and dependency provenance,
exact counters, and phase medians.
