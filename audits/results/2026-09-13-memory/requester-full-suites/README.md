# Full suites with the repaired HTTP requester

These runs use the same Python 3.12 dependency image,
`sha256:0fb5880df36df7c1c86b5772a5cb426fca4770df349007a069bea09bd4b8529d`,
direct Lambo Reth, and separate databases. The image contains dank-mids source
repair `c9b17b58bb7908b46bf20e35ba7c262e3750105d` through native artifact pin
`9a58cd91b4a652ac10d41cc5862c7b2770727632`. No resource limit increases.

The runner executes the required command for each committed source:

```sh
PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test
```

| Source | Execution | Terminal outcomes / collected | Peak bytes | Elapsed seconds |
| --- | --- | ---: | ---: | ---: |
| original | OOM; incomplete | 415 / 1752 | 8,589,934,592 | 1521.86 |
| preoptimization | Pending | Pending | Pending | Pending |
| optimized | Pending | Pending | Pending | Pending |

Execution completion is separate from test success. OOM, interruption, and
missing final reports remain incomplete. Partial test records do not establish
full coverage or failure equivalence. All raw test errors remain in the streamed
event reports. The final Docker state and cgroup counters remain separate from
the last live measurement.

The original revision reaches 8 GiB and records one cgroup OOM kill.
It records 305 passed calls, 101 failed calls, and nine skips before that event.
No final pytest summary exists. The last completed test is the Gearbox price
test, with 6,906 live tasks; subsequent work reaches the memory limit before
another test report. The final process RSS sample totals 8,602,505,216 bytes.
Process RSS and cgroup accounting measure different quantities.

The descriptor census samples every 120 seconds. The original run's maximum
sampled process count is 116 descriptors; its last sample records 83. Both
are below the soft limit of 1,024. This
sampling does not establish the exact descriptor count at the later OOM.
The source archive, dependencies, archive probe, all ten compiled extension
paths, command, elapsed time, log retention, and final state remain recorded.

Earlier OOM and descriptor failures use separate reports and dependency images.
They are not relabeled as runs of the new requester repair.
