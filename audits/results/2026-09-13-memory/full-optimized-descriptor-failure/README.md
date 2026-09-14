# Full suite ended after descriptor exhaustion

The optimized full run at `368a6e79fa7226cb0f7f92be27a90c80d5a649b7` is
incomplete. It records 410 terminal outcomes: 281 passes, 121 call failures, and
eight skips. Pytest then raises `OSError: [Errno 24] Too many open files` while
rendering the Convex failure and writing its session report. No final pytest
summary exists. The exact exit traceback accompanies the partial event stream.

The container peaks at 1,173,213,184 bytes, with no cgroup OOM or Docker OOM kill.
Execution lasts 2,371.61 seconds and exits 2 through `make test`. This lower peak
does not establish full-suite memory success because execution stopped early.
The last event reports 7,259 live tasks.

The run uses the final source-pinned dependency image, a new database, and the
required Python 3.12 `make test` command. All ten application extensions load at
pytest startup, and the initial archive probe succeeds. Repeated historical-log
attempts later reach their local timeouts. These records do not establish the
cause of each pricing timeout.

A separate startup census with the same image and unchanged Docker defaults
finds a soft file-descriptor limit of 1,024 and a hard limit of 524,288. The failed
full process had no descriptor census, so its final open-socket count is unknown.
No file, memory, CPU, process, thread, or swap limit was raised after this failure.

The subsequent [archive probes](../archive-after-full-failure/README.md) fail on
direct NUC Reth. Controlled HTTP socket and task ownership regressions can run
without a node while archive access is unavailable.
