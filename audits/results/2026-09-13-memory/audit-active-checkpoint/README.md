# Active mainnet audit checkpoint

At 2026-09-15T17:35:07.709186+00:00, the optimized audit remained active. Validation
is incomplete: neither audit JSON nor CSV exists, and the process has no final
exit status or final container state. Do not use request progress as passing
price rows, failure counts, or full audit coverage.

The frozen source is `c16d43e0c6b38e146834f0cd8d75090bb25222c7`. The command, image, source archive
hash, installed dependencies at command start, and all ten compiled-module
checks are saved here. The archive probe passes. Limits remain 8 GiB, no swap,
four CPUs, and 512 processes or threads in the dedicated Colima profile.

| Measurement at checkpoint | Bytes |
| --- | ---: |
| Container peak | 6,485,475,328 |
| Container current memory | 6,310,502,400 |
| Audit process RSS | 5,137,027,072 |
| Audit process peak RSS | 5,316,431,872 |
| Cgroup anonymous memory | 5,113,356,288 |
| Cgroup file memory | 1,106,796,544 |

Elapsed execution is 67,351.70 seconds. The container peak is 6.04 GiB,
below the 7 GiB target at this sample.
No cgroup OOM or limit-hit event has occurred. This sample does not establish
bounded retention for the complete historical workload.

The latest retained diagnostic identifies WETH at block 19,557,288, the end of
the first quarter of 2024. Exact address, amount, block hash, and request messages
remain in `request-progress.jsonl`. The audit has advanced through earlier
requests; their final result rows are not yet available.

`earlier-archive-probe.json` records a direct Reth check at block 13,000,000.
The canonical-hash USDC decimals call returns the expected 32-byte value six.
This one successful archive call does not prove all archive data is available
or explain the earlier Compound test timeout. No Geth failure provides archive
evidence for this check.

The read-only stack observation records one 63,702,722-byte DEBUG message. Raw
local-variable output remains private; the safe record preserves its hash.
Sparse OS-counter reads and the recorded stack and archive checks add diagnostic
overhead to this audit. The completed public pricing timing repetitions remain
separate. These counters do not identify individual retained Python or native
objects.

The checkpoint contains 42 sparse samples. The last seven add process RSS and
cgroup memory categories; earlier samples contain the total cgroup counters.
The first two samples do not record audit-report presence. Later samples do.

The CLI logging repair and its regression matrix remain pending. This checkpoint
contains the existing audit runtime. PR #43 remains draft until required
validation is complete.
