# Local Docker validation

Use this runner for full suites, memory profiles, audits, and native quote checks.
It needs Docker with Linux ARM64 support and a host Python 3.12 interpreter. The
host interpreter runs only the standard-library supervisor. Project imports,
dependency installation, compilation, and expensive checks run inside Docker.

The approved parallel budget uses two named Colima profiles: `ypricemagic` and
`rpc-tune`. Each VM has 10 GiB and 5 CPUs; together they use at most 20 GiB of VM
memory. The Mac has 36 GiB. Keep the previous default profile stopped and preserve
its data disk. Do not raise limits to make a failed check pass.

```sh
colima start ypricemagic --cpu 5 --memory 10 --activate=false
colima start rpc-tune --cpu 5 --memory 10 --activate=false
```

The runner defaults to Docker context `colima-ypricemagic`. Use
`--docker-context` to select another explicit context. It never changes the
user's active Docker context. The RPC benchmark must use `colima-rpc-tune` and
its own 8 GiB/no-swap, 4-CPU, 512-process/thread container limits. Run at most one
heavy job per profile. A benchmark and pricing validation can then run in parallel.

```sh
make test-docker PYTHON=env/bin/python REVISION=HEAD \
  REPORT=/private/tmp/yprice-validation/full-suite \
  DOCKER_ARGS='--env-file /private/tmp/yprice-validation.env'
```

Set `VALIDATION_RPC_URL` and, if needed, `ETHERSCAN_TOKEN` in the private env file.
Use an endpoint that Docker can reach. The runner writes the endpoint only to the
container's private Brownie configuration. Keep the env file outside the repo.
The runner does not copy host Brownie databases, environments, or credentials.
Each run uses a new database and source directory inside its container.

The runner accepts a Git revision, a new report directory, and a command after
`--`. Use `--revision worktree` during development. Its report includes both the
parent SHA and the exact source archive SHA256. Commit and rerun the final checks
with the resulting Git SHA before delivery.

```sh
env/bin/python tools/validation/run.py --revision HEAD \
  --report /private/tmp/yprice-validation/probe \
  --env-file /private/tmp/yprice-validation.env \
  --require-report rpc-probe.json -- python /runner/probe.py
```

A successful probe checks chain ID, historical state, and canonical block-hash
calls at blocks 16,830,000 and 18,000,000. Run it before full tests. It is a sample
of archive access, not proof that all historical state is available.

The first run builds a reusable image from the checked-in interpreter-specific
dependency constraints. Python 3.11 uses NumPy 2.4.6; 3.12 and 3.13 use 2.5.3. Use the exact
`image` ID in its `run.json` as `--image` for baseline and changed runs. The image
contains `dependencies.txt`, which each report copies. The runner also records the final freeze to detect
command-time dependency changes. Do not compare results
from different dependency images without identifying that difference. Python
3.11 and 3.13 checks use separate images selected with `--python`.

The builder and test container have an 8 GiB memory limit, no swap, four CPUs,
and a 512-process/thread limit. A Docker name reservation excludes other validation
jobs across all checkouts using the same profile. The runner stops BuildKit before
it starts a test command. Build OOM events also make validation incomplete.
The target peak is below 7 GiB. Resource settings follow the Docker
[container limits](https://docs.docker.com/engine/containers/resource_constraints/)
and [BuildKit driver controls](https://docs.docker.com/build/builders/drivers/docker-container/).

Use Ctrl-C to stop a job. The runner stops its container, saves final state, and
marks the run incomplete. After a host crash, inspect
`ypricemagic-validation-job`, `ypricemagic-validation-lock`, and
the BuildKit container named in `run.json` before removing a stale lock. Never
remove a live lock or start a second heavy job in the same profile.

Reports contain source identity, command, dependency versions, elapsed time,
exit status, cgroup memory peak and OOM events, sampled process RSS, effective
limits, and Docker `OOMKilled`. The pytest reporter records collection, setup,
call, failure, and teardown data as scalar JSON records. It checks every mypyc
module's extension path. Set `VALIDATION_ALLOCATIONS=1` in the private env file
for a separate tracemalloc run. Do not use profiler timings as performance
measurements. RSS includes native memory; tracemalloc measures Python
allocations and some extension allocations, not all native memory.

Console output rotates at 100 MiB per file, with five files retained. The
retention report discloses expired byte counts. Docker uses the same limits for
its own log files. Pytest events, audit JSON/CSV, and other structured results
remain separate from console output. Use `--require-report` for every required
artifact. Missing reports, OOM events, and interrupted commands make validation
incomplete. A completed command can still have test failures; inspect its exit
status and compare failures by test and error.

`compare.py` checks that both pytest summaries and event streams account for
every collected test. It can compare complete test outcomes after a later
process-exit failure, while keeping overall execution marked incomparable.
Partial test reports never qualify for that comparison.

Price diagnostics and the `y.stuck?` logger serve separate purposes. Enable
`logging.getLogger("y.stuck?").setLevel(logging.DEBUG)` for "still executing"
messages every five minutes. These messages remain DEBUG-only.

The `repeat_logger.sh` workload builds extensions once, then runs three allocation
profiles and three timing measurements. Each child process performs 10,000
requests before measuring retained state. `repeat_cooperative.sh` performs three
4,000-fixture measurements at the existing 100-test concurrency. The original
implementations fail their object-release assertions after writing measurements.
Process boundaries separate independent repetitions; they do not provide the
object-release result within a repetition.

The `repeat_scaling.sh` command runs three timing measurements and one separate
allocation profile of the cached Sushi topology. The runner copies and hashes
the same current workload and topology into `/runner/workloads` for each source
revision; `workload-files.json` records this test input separately from production
source. The workload preserves 4,771 pools, 64 concurrent requests, exact amounts,
4,128 distinct historical blocks, and normal cache eviction. Controlled reads
and quotes have exact counters. Pytest's logical RPC counters follow the existing
audit counters; they count generated calls and batches, not HTTP wire requests.

Allocation censuses also record stored historical log/checkpoint counts and
queue sizes for database writes. They read existing storage slots and queues;
they do not load lazy caches or drain pending work. Queue counts describe waiting
operations, not work already executing in a thread. Keep these censuses out of
timing measurements.

Use `python /runner/native.py` and `python /runner/native_reviewed.py` after an
isolated editable build for the fixed-block native checks. Require `native.json`
for the first script. Require both `native-reviewed.json` and
`native-reviewed-summary.json` for the second; the summary confirms its final
canonical-block check finished. Run the mainnet audit with
`ypricemagic audit-prices audits/mainnet.json --json /reports/audit.json --csv /reports/audit.csv`
and require both report files. These real-node checks remain local.

`verify_runner.py --image IMAGE --report DIRECTORY` exercises actual runner
cancellation, duplicate exclusion, and 600 MiB of console output. The rotation
check retains five 100 MiB files and reports 100 MiB of expired test output.
`containment_check.py` uses a deliberate 64 MiB OOM fixture to prove Docker
containment without approaching the Mac's memory limit.

The runner records Python, ABI, architecture, and platform in `environment.json`.
The pytest and native check processes accept `SIGUSR1` for a thread-stack dump to
the bounded console log. Use this only on those registered processes when a
concrete failure needs diagnosis. The signal does not stop the check.

The lowercase-address cache uses `YPRICEMAGIC_CHECKSUM_CACHE_MAXSIZE`, the existing
address-cache setting. It holds strings only. Immutable pool snapshots use slots;
block-specific balances, fees, exclusions, and hash keys remain unchanged.

Ypricemagic owns one shared Brownie SQLite connection per process. It queues
connection closure before Python joins background threads. This preserves
connection reuse and drains queued SQLite work during process shutdown. The
compiled regression checks cover both an open default event loop and a loop
closed by `asyncio.run`.
