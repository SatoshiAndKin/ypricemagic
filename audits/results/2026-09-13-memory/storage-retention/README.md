# Bound SQL payload retention and defer unused reserve handles

Bulk inserts now bind values through Pony's existing batch executor. One SQL
template serves all payloads and row counts, so the ORM caches retain only the
statement. The driver receives binary values without hex copies. SQLite keeps
its numeric conversion, dates keep their UTC representation, and both providers
keep their existing conflict rules. Failed batches roll back and allow reuse.
Empty batches preserve existing rows.

Uniswap V2 pool discovery now creates a reserve-call handle only on first use.
Repeated requests reuse that handle. ABI verification can still replace its
return signature. Existing async RPC methods retain their DEBUG-only five-minute
`y.stuck?` messages. Pricing inputs, ranking, fees, exclusions, block identity,
and the 64-operation discovery bound remain unchanged.

## Allocation diagnosis

The isolated Uniswap test module also reaches the 8 GiB limit before these
repairs. Its final allocation sample contains 501,581 pool instances, 498,404
tasks, and 508,711,575 characters of SQL retained by Pony's statement cache.
The largest allocation sites include bulk SQL construction and eager reserve
calls. The property-state census finds only two pending property tasks; it does
not identify property tasks as the owner of the completed task population.

This profile collects 171 tests and records 121 failed calls and three failed
setups. It ends with exit 137, one cgroup OOM kill, and Docker OOMKilled. It has
no final pytest summary or session-finish allocation report. Treat it as
incomplete diagnostic evidence. Profiling overhead prevents using its memory
figures as an unprofiled performance result. See [the diagnostic summary](diagnosis/summary.json).

## Controlled comparisons

Each revision runs three timing samples and a separate allocation profile in
Linux ARM64 Python 3.12. Dependencies, helper hashes, and frozen fixture hashes
match exactly. All ten configured compiled extensions load. Each workload uses
one process without forced collection, cache clearing, or a restart within that
workload. The measured code makes no real RPC requests.

Bulk persistence writes 4,096 rows of 16,384 bytes in 128 batches. A streaming
read verifies every field and the exact ordered data digest. Pool construction
creates 131,072 unused pools with the same addresses, token pair, and deployment
block. It verifies every pool's metadata and the ordered digest.

| Workload | Median process peak RSS bytes before / after | Median seconds before / after |
| --- | ---: | ---: |
| Bulk persistence | 528,093,184 / 190,730,240 | 0.557022989 / 0.285285109 |
| Unused pool construction | 366,612,480 / 330,182,656 | 1.760052011 / 1.403289541 |

Bulk SQL retention falls from 134,349,962 to 224 characters. Its Python allocation
peak falls from 136,047,310 to 578,195 bytes; retained Python allocations fall
from 134,468,837 to 35,793 bytes. The pool allocation profile creates zero unused
reserve handles, compared with 131,072 before. Its Python allocation peak falls
from 163,326,019 to 128,197,307 bytes. Python tracing covers only the separate
allocation runs; total process RSS remains a separate measurement.

Both revisions produce bulk digest
`9a0553e7efe82e2120f797715abb6daf540bbf7f8220bd0fdbc55e828f3d385c`
and pool metadata digest
`65fd7180d8667fba9cf382c179ddc43d2a139eaa38cbd9595b28fbfa118d70a4`.
See [all samples and source identities](profile/comparison.json). These controlled
results do not establish full-suite memory use or real-node pricing latency.

## Regression and database checks

The SQLite control completes with 266 of 270 cases passing. Four new checks fail:
128 writes retain more than one million SQL characters; dollar-containing quoted
text raises NameError; an empty batch raises SQLError; and an unused pool creates
a reserve-call object. Atomic rollback and subsequent reuse already pass. The
reserve ABI override also passes. See [exact failures](control/summary.json).

The changed matrix passes all 270 checks on each Python version. It tests binary
and quoted Unicode values, signed 64-bit boundaries, nulls, Decimal values,
UTC dates, duplicate keys, atomic failure, reuse, and lazy reserve-handle reuse
with ABI replacement. Every run loads all ten configured compiled extensions
and passes archive probes at blocks 16,830,000 and 18,000,000.

| Python | Focused passes | Container peak bytes | Run elapsed seconds |
| --- | ---: | ---: | ---: |
| 3.11 | 270 | 1,126,633,472 | 185.61 |
| 3.12 | 270 | 1,161,596,928 | 177.53 |
| 3.13 | 270 | 1,168,547,840 | 167.46 |

Configured mypy still reports 1,922 errors per version. The parser records 1,917
rendered diagnostics before and after. One diagnostic references a definition
that moves from line 801 to line 806; raw differences remain recorded. With only
that source-line reference normalized, no diagnostic is added or removed.
Installed dependency records match each baseline exactly. See [matrix details](matrix-summary.json).
The final matrix uses one identical source archive on all three Python versions
and includes the PostgreSQL helper and corrected binary-content test reader.

The separate PostgreSQL check starts a temporary server inside the same bounded
container as installation and tests. It uses PostgreSQL 15 and the existing Pony
driver, [psycopg2-binary 2.9.10](https://pypi.org/project/psycopg2-binary/2.9.10/),
as a test-only installation. Application dependency pins remain unchanged. The
final packaging moves this same tested driver pin into a dedicated lockfile;
[verification](postgres-lock-verification.json) confirms that it matches both
installed environments.
The server uses a local Unix socket and no host port. Both revisions use identical
recorded Python and system packages. The four persistence regressions use the
same test functions as the SQLite checks.

PostgreSQL before: 1 passed, 3 failed.

PostgreSQL after: 4 passed, 0 failed.

The first PostgreSQL checks failed because their readback helper compared a
format-`c` memoryview directly with bytes. The [diagnostic run](development/postgres-storage-diagnostic/postgres-bulk.json)
records the correct binary content and the driver's false equality result.
The test reader now compares the exact bytes of binary buffers and preserves
all other column values and assertions. The writer needs no repair for that
test-reader error. Initial failures and the corrected controls remain separate.
The controlled performance pair uses its original identical fixture; the
[frozen fixture](profile/frozen_bulk_fixture.py.txt) matches its recorded hash.
That benchmark reads the cursor directly and never calls the corrected reader.

See [PostgreSQL results and exact errors](postgres/comparison.json). These are
behavior checks. PostgreSQL batch performance, including remote round-trip cost
of driver executemany, is not measured here.

## Remaining validation

The repaired full suite and remaining native quotes, fixed-block public pricing
comparisons, and mainnet audit still need completion. Earlier full suites remain
incomplete after OOM. Limits stay at 8 GiB, no swap, four CPUs, and 512 processes
or threads, with one heavy job per profile. PR #43 stays draft.
