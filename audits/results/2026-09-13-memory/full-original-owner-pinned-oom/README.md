# Original full suite with repaired dependencies: incomplete

The required Python 3.12 `make test` run at
`476af288a520a30052668a8b3ad7e3e682cd101f` uses dependency image
`sha256:27ffa2884a5bf1a6538184ec79af495dc0d45839a5b20317e2526bdc5e7be46b`.
It passes the historical archive probe and loads all ten configured native
extensions. Its database is separate from every other run.

The container reaches its unchanged 8 GiB limit after 2,419.34 seconds.
Docker reports `OOMKilled=true`; the cgroup records one OOM and one kill.
The command exits 2. No final pytest summary exists, so validation is incomplete.

The event stream records 1,752 collected cases and 438 terminal outcomes:
310 passed calls, 116 failed calls, 9 skipped calls, and 3 setup failures.
The last reported case is the bulk price test at block 13,994,236. Its teardown
reports 134,679 live tasks. That count identifies a workload for further
ownership analysis; it does not identify every retained task's owner.

Keep this run separate from earlier OOMs with the old compiler and dependency
image. The repaired compiler lets this run pass Popsicle cases that previously
failed before reaching bulk pricing. Incomplete event streams cannot establish
full failure equivalence or a completed before/after performance comparison.
