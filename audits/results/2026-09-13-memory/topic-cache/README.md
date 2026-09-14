# Shared topic-ID cache

One bounded cache now stores completed topic IDs for both synchronous and
asynchronous callers. The controlled lookup workload uses 40% less peak process
RAM. Its median lookup time increases by 16%. Full pricing validation remains
incomplete; this result covers topic-ID lookup and cache turnover.

## Ownership and behavior

The original function has an unbounded synchronous LRU and an unbounded
asynchronous task cache. A direct probe loads 8,192 normalized topics and
identifies `y._db.utils.logs.get_topic_dbid` as the owner of both caches.
Each retains all 8,192 entries after the requests finish.
[Direct owner evidence](diagnosis/topic-owner.json) accompanies the allocation
census. The earlier full census used an ambiguous Pony wrapper name; this
controlled probe establishes the function's behavior directly.

The repair uses the existing cachebox dependency and
`YPRICEMAGIC_DEFAULT_CACHE_MAXSIZE` setting, whose default is 50,000 entries.
The existing executor still serves asynchronous calls. Both call modes share
the same immutable IDs and per-key cache owner. The existing database-session
retry helper handles misses; the outer retry/commit boundary remains active on
cache hits. The public function and its `sync` argument keep their behavior.

No pricing API, topic normalization, database schema, discovery concurrency,
quote amount, fee, exclusion, or block identity changes. Price diagnostics keep
their DEBUG-only five-minute interval.

Four regressions use a separate SQLite database and the existing cache-size
setting at 32 entries. They check synchronous and asynchronous object release,
exact IDs after eviction, warm reuse across call modes, retry after a database
failure, and a cancelled caller with a surviving caller. The original code
fails both object-release cases and passes the failure and cancellation cases.
The repair passes all four. No test clears the cache or forces collection to
make these release assertions pass.
[Original outcomes](controls/before/pytest-summary.json) retain the exact errors.

## Matched lookup workload

Each run first stores 131,072 normalized topics with exact, predetermined
64-bit database IDs. The lookup phase uses 128 batches of 1,024 topics and 64
concurrent requests. Every cold lookup has a warm repeat. A recurring topic
stays hot throughout turnover. The workload also revisits an old topic and
checks both public call modes.

Three unprofiled repetitions measure process RSS and lookup time. A separate
run measures Python allocations. Each repetition has a separate database.
No process restart, cache clear, or forced collection occurs within turnover.
The lookup phase makes no RPC calls; connection setup and the archive probe
remain outside its timer.

| Measure | Before | After |
|---|---:|---:|
| Median peak process RSS, bytes | 353,050,624 | 210,583,552 |
| Median lookup seconds | 18.508328 | 21.496016 |
| Python allocation peak, bytes | 142,201,688 | 9,849,016 |
| Python retained bytes | 141,951,137 | 9,606,616 |
| Synchronous cached IDs | 131,072 | 50,000 |
| Separate cached result tasks | 131,072 | 0 |
| Database lookup executions, including final revisit | 131,072 | 131,073 |

The extra database lookup reloads the evicted topic's existing ID. Warm lookup
results and exact IDs stay unchanged. Both sides produce SHA-256
`eb707143e27626a7c35fa07442b96a2877ded8da6c20e1cd122143558e6000f5`.

The repaired cache stays at 50,000 entries after it fills. Across the remaining
samples, current RSS spans at most 1,335,296 bytes per repaired timing run,
compared with more than 95 million bytes before. This measures retained state;
it does not claim completely flat allocator RSS.

[All repetitions and allocation records](profile/comparison.json) preserve the
memory and time tradeoff together. Both sides use the same dependency image,
installed packages, frozen runner files, and frozen workload files.
The baseline is commit `0b16d2fab24ca98637d0a9862a58a61bfec37eeb`.
Its command also copies the recorded measurement helper into the old source
tree for the centralized type check. The changed runs use one source archive:
`ed327097f9c520397c1fc69f1c1e9b0d4c1d4b0f468fa52df32eab68562ae048`.

## Application checks

| Python | Focused passes | Container peak bytes | Run seconds |
|---|---:|---:|---:|
| 3.11 | 274 | 1,119,916,032 | 181.26 |
| 3.12 | 274 | 1,165,672,448 | 307.41 |
| 3.13 | 274 | 1,168,818,176 | 181.27 |

The Python 3.12 run also includes all four controlled measurements. Every run
loads all ten configured compiled modules and passes the archive probe.
Configured mypy still reports 1,922 existing errors. Its 1,917 rendered
diagnostics have no additions or removals.
[The complete matrix](matrix/comparison.json) records the source, exact test
outcomes, dependencies, commands, limits, elapsed time, and final cgroup state.
All runs stay below the 7 GiB target and record no OOM.

## Preserved development results

The first probe stored padded hexadecimal keys instead of using the production
`Topic.strip()` normalization. That probe is incomplete. The corrected probe
uses the same normalized keys as bulk persistence and passes.

The first measurement helper and test helpers had constructor/import type
errors. The initial production version also exposed an untyped direct Pony
decorator. The final code uses the existing database-session retry helper.
These earlier failures remain in the development records.

The first changed report labelled copied `cache_info` metadata as a second
cache. The allocation census showed no topic task cache. The final helper
identifies the actual async LRU type and records metadata forwarding separately.
The final matched comparison reruns both sides with that corrected helper.

Copied text reports remove trailing whitespace. The
[normalization manifest](text-normalization.json) records their hashes before
and after formatting. Private original reports remain preserved.

## Remaining validation

Run the historical allocation profile and full suites with this committed
repair. Then complete the local native quote checks, fixed-block public pricing
comparisons, and mainnet audit. The controlled reduction does not establish the
peak memory, failure equivalence, or timing of a full pricing run.
