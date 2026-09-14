# Final pinned full-suite and real-node validation

These runs use Python 3.12 and the same dependency image,
`sha256:5f67dfecf3085abd5cff6a15469e5bc36ea28fee0c557e05340cf7b181ac13bc`.
The image contains the committed pool-property, future-owner, and cooperative
scheduler repairs. Each revision builds its extensions in a separate Linux
workspace and uses a separate database. All jobs run in sequence in the
`colima-ypricemagic` profile.

The full-suite command is unchanged:

```sh
PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test
```

| Source | Revision | Terminal outcomes / collected | Run seconds | Container peak bytes | Result |
| --- | --- | ---: | ---: | ---: | --- |
| Original PR baseline | `476af288a520a30052668a8b3ad7e3e682cd101f` | 412 / 1,752 | 1,206.69 | 8,589,934,592 | OOM; incomplete |
| Before memory optimization | `61be7b520aba7f771a0bf96b326315e68767fae4` | 476 / 1,816 | 1,469.06 | 8,589,959,168 | OOM; incomplete |
| Pool ownership repair | `1a8023089c220ce4f1ae33497b70fb463fe582d3` | 1,464 / 1,865 | 3,929.25 | 4,348,043,264 | Interrupted; synchronous deadline unavailable |

Both baseline runs pass the historical archive probe and load all ten configured mypyc
modules from compiled extensions. Both record one cgroup OOM kill and Docker
`OOMKilled=true`. Neither produces a final pytest summary. The effective limit
remains 8,589,934,592 bytes; the second peak includes a small cgroup accounting
overshoot. The container settings remain 8 GiB, zero swap, four CPUs, and 512
processes or threads. The builder is stopped before each test run.

The original run records 289 passed calls, 111 failed calls, nine skipped calls,
and three setup failures. The pre-optimization run records 300 passed calls,
164 failed calls, nine skipped calls, and three setup failures. Full test
failure equivalence and coverage remain unverified. The
[partial comparison](partial-baseline-comparison.json) only compares terminal
outcomes that both runs recorded. It preserves exact errors and identifies
outcomes present on only one side. Installed dependencies are byte-identical.

The optimized run records 1,074 passed calls, 369 failed calls, 15 skipped calls,
and six setup skips. Its peak sampled process RSS is 3,154,800,640 bytes. It has
zero cgroup OOM events and Docker reports `OOMKilled=false`. It passes the archive
probe and loads all ten configured compiled modules. Its final pytest summary
is missing, so its 4.05 GiB container peak remains an incomplete measurement.

The run reaches synchronous Compound pricing after the cooperative tests. The
configured `timeout = 600` has no synchronous handler: `pytest-timeout` is absent
from the dependency image. The stack capture shows the call waiting in the
event loop; it does not prove a pricing deadlock. A separate USDC archive recheck
at block 16,830,000 returns six decimals in 0.02498 seconds. The run was
interrupted to repair the missing test dependency, and the remaining queue was
paused. The exact cause and stack remain in the optimized report. The
[deadline and owner repair](../sync-deadline/README.md) now passes its focused
Python 3.11–3.13 matrix. The old childless queue has been retired with all reports
preserved. Its replacement retains every pending workload and repeats the
three full revisions with the final dependency image.

Native quote checks, three public-pricing timing repeats, separate allocation
profiles, and the mainnet audit remain pending. Full failure equivalence and
coverage are unverified. The two full comparisons explicitly reject incomplete
reports. PR #43 remains draft.

Each run retains source and runner hashes, dependencies, command, elapsed time,
exit state, peak memory, cgroup OOM events, and Docker limits. Pytest events and
audit JSON/CSV reports remain separate from console output. Console logs rotate
at 100 MiB with five retained files. Neither baseline expires console output;
the bounded console files stay local. Published structured files remove private
RPC values and retain before/after file hashes in `published-files.json`.
