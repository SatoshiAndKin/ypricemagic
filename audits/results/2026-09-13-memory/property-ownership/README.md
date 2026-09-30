# Pool index and cached-property ownership

The pool index now reads token metadata through the shared cached-property
objects. It no longer creates three hidden bound methods and their expiry
callbacks for each pool. The returned token pair, block identity, subclass
behavior, failed-request retry, and cancellation isolation keep their contracts.
Each public pool lookup still returns an independent dictionary. Discovery keeps
its 64-operation bound. The token getters retain the DEBUG-only `y.stuck?`
diagnostic at the default five-minute interval.

Two defects in ez-a-sync also retained unused objects. A Cython loader closure
kept its first instance. Completed SmartFuture and SmartTask awaits left cleanup
callbacks on a caller that continued to run. The shielding callbacks also formed
a Cython closure cycle. The repair belongs to ez-a-sync; ypricemagic has no
runtime patch for these defects.

## Matched measurements

[pool-comparison.json](pool-comparison.json) compares three unprofiled runs per
stage, with 524,288 actual seeded UniswapV2Pool objects and the production token
index. Each run checks three warm independent result copies and the exact
metadata hash. A separate 131,072-pool run measures Python allocations with
tracemalloc. The timing measurements contain no allocation profiler or object
census. The workload uses no forced garbage collection, cache clearing, expiry,
or RPC calls.

| Stage | Median peak process RSS (bytes) | Median index time (seconds) | Retained Python bytes (131,072 pools) |
| --- | ---: | ---: | ---: |
| Original index and dependency | 6,796,603,392 | 29.1073 | 1,503,254,888 |
| Shared properties and loader repair | 1,650,896,896 | 8.8926 | 265,754,351 |
| Shared properties, loader and future repairs | 1,291,739,136 | 7.1822 | 261,294,567 |

The final stage reduces median peak process RSS by 81% and index time by 75%.
Hidden bound methods fall from 1,572,864 to zero; scheduled callbacks fall from
1,572,869 to five. All stages produce metadata SHA256
`ea1f044d3da1bcf44e2796970d8b7667ff3f50abe87330527b6728a8c027b2a8`.
Logical RPC counts remain zero. These are pool-index measurements, not complete
pricing or mainnet-audit measurements. Each run retains its source archive hash,
image, dependency manifest, command, cgroup memory data, exit state, and timing.
The only runtime dependency difference between the original and final stage is
the owning ez-a-sync repair.

## Behavioral and static checks

The 13 new native ownership regressions fail on the original extension. The
repaired extension passes all 38 focused property and future tests. The
application passes all 278 focused tests, including actual pool release,
subclasses, failures, independent cancellation, and unchanged cached child
results. The checks confirm all ten configured application mypyc modules load
compiled extensions. The archive RPC probe also passes.

[complete-type-comparisons.json](complete-type-comparisons.json) compares the application
before and after with byte-identical dependency manifests. It removes three
diagnostics, adds none, and retains all 1,836 reported diagnostics. This
comparison is separate from changes in inference due to the dependency stub.
The earlier static descriptor controls pass their runtime assertions on Python
3.11, 3.12, and 3.13 and remove two diagnostics without adding any.

## Preserved development failures

The reports include the initial failed ownership assertions, rejected stub MRO
approach, missing Cython build dependency, and the ambiguous diagnostic import.
They also retain the first full dependency comparison: 717 passed, 28 failed,
and one skipped before; 729 passed, 16 failed, and one skipped after. That run
removed all 13 ownership failures but exposed one new metaclass-plugin compiler
crash. Its traceback is preserved. The dependency plugin now preserves original
methods for analysis and resolves their signature types before creating the
descriptor types. The exact crash input passes in the repaired compiler probe.
The [replacement full comparison](owner-full-comparison.json) uses identical
test archives and has 747 cases: 716 passes, 30 failures, and one skip before;
731 passes, the same 15 baseline failures, and one skip after. No new failure
remains. The original metaclass input now requires resolved integer types, and
one added test checks that method and property bodies still report errors. No failed or incomplete development run counts as final validation.

The earlier historical allocation OOM remains incomplete. The [final pinned Python 3.11–3.13 matrix](../ownership-pinned/README.md) passes
all 278 application and 47 owner checks on each version. Full application,
public pricing, native quote, and audit gates remain separate and incomplete
before PR #43 can leave draft state.

The owning repair is committed and pushed as
[`ebb981bfaffd887048d1945eff29ab5dfe360e34`](https://github.com/SatoshiAndKin/ez-a-sync/commit/ebb981bfaffd887048d1945eff29ab5dfe360e34).
[dependency-source.json](dependency-source.json) proves that the three native
runtime source files match the final measured workload, full dependency suite,
and commit. The plugin and stub only received formatting after the full suite;
their syntax trees match. The final compiler-image application run also passes
all 278 tests. Its matched type comparison retains the same 1,836 diagnostics,
removes three, and adds none. Ordinary builds from the source pin are separate
from these development image controls.

The final formatting check sorts two newly added imports.
[import-formatting.json](import-formatting.json) records both source hashes and
confirms identical non-import syntax trees. The frozen measured helper is kept
as `pool_discovery_profile.py.txt`; its original hash remains in each measured
run. Final source formatting does not rewrite those workload reports.

Application Black, isort, and autoflake checks pass after the import cleanup.
The dependency Black check passes. Its configured default isort check reports
an existing import layout failure on both the baseline and committed plugin;
[owner-existing-isort.json](owner-existing-isort.json) preserves both outputs
and proves those imports are unchanged.

The old private type parser skipped seven empty `error:` header lines whose
messages wrapped to the next line. The shared comparison helper now reads those
messages and checks its count against mypy's final summary. The complete saved
Python 3.12 output compares 1,839 errors before with 1,836 after, with no added
message. The seven previously omitted messages also match. Earlier JSON files
keep their original partial parser counts; `complete-type-comparisons.json`
records the corrected totals. Exact errors remain unchanged in `mypy.txt`.

Final source checks run from identical frozen source archives. All seven runner
unit tests and the configured Black 25.9.0 check pass. The final source type
check retains exactly the same 1,836 complete diagnostics with byte-identical
dependencies, loads all ten compiled modules, and passes the archive probe.
[final-source-checks.json](final-source-checks.json) records the source hashes
and completed runs. The first three extra-check attempts remain incomplete:
one used the wrong container import path, one asserted the CLI version prefix,
and one omitted the required RPC environment file. Their passing intermediate
stages do not turn those incomplete runs into final validation. The final two
complete runs replace them. No application or node defect caused those setup
failures.
