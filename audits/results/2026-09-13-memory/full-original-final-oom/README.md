# Original full suite with final dependencies

The original PR revision `476af288a520a30052668a8b3ad7e3e682cd101f` hit the
8 GiB container limit with the final Python 3.12 dependency image and direct
NUC Reth. Docker recorded `OOMKilled: true`; cgroup counters record one OOM
event and one OOM kill. The command exited 2 after 1,439.22 seconds. No final
pytest summary exists. This validation is incomplete.

The archive preflight passed and all ten configured modules loaded as compiled
extensions. Pytest collected 1,752 cases and recorded 422 terminal outcomes:
291 passed, 122 failed, and 9 skipped. Failed cases include 68 ERC20 tests,
5 ERC4626 tests, 33 Chainlink tests, 2 Convex tests, and 14 Popsicle tests.
The initial ERC20 group includes 600-second timeouts during cold setup. Keep
those errors separate from contract reverts and other assertion failures.

The last reported Popsicle teardown had peak process RSS of 8,074,829,824 bytes
and 10,891 live tasks. Those observations do not identify the sole allocation
source. The earlier HTTP retry repair does not explain or resolve this entire
full-suite failure.

The private full report retains all phase records and bounded console output.
One thread-stack diagnostic ran during the initial pricing wait. This run is
not a controlled timing or allocation sample. It does not replace the separate
three-sample fixed-workload comparisons.

The changed full suite follows with the same image, endpoint, limits, and a
separate database. No memory limit, concurrency setting, or required check was
relaxed.
