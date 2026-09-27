# PR 43 timeout investigation and mergeability

Validation is in progress. PR remains draft until the remaining checks complete.

- [x] Fetch and fast-forward the assigned branch; preserve the generated C file.
- [x] Resolve conflicts with master 2ebf9c56, retaining bounded event/write ownership and adopting startup/cache repairs.
- [x] Identify successful cold calls exceeding the old deadline: 912.15, 914.76, and 922.89 seconds in the prior three unprofiled public-pricing repetitions.
- [x] Run the 1,800-second deadline probe, then set final deadlines to 3,600 seconds after a completed full run records 1,792.82-second success and two timeouts; retain concurrency 100 and container limits.
- [x] Reproduce interference between a cooperative global decoder mock and the live Gearbox test; serialize the affected mock tests.
- [x] Skip unavailable V3 balances explicitly, without swallowing unexpected errors.
- [x] Avoid loading V2/V3 indexes when the factory has no code at the historical block.
- [x] Treat empty Chainlink feed data as unavailable decoding, preserving unexpected-error and cancellation propagation.
- [x] Correct the stablecoin test to reflect the explicit USDC-only fixed valuation policy.
- [x] Measure the native steCRV gauge's zero LP backing and correct its unavailable-quote expectation.
- [x] Finish isolated Compound measurement: the old source returns `InvalidFEOpcode` after 1,796.86 seconds; no deadline success is claimed.
- [x] Reproduce and repair infinite singleton multicall bisection in Dank Mids; 7 red regressions become 158 passing native unit tests.
- [x] Repair xPREMIA detection by correcting its deployment address checksum; add equivalent-form regression.
- [x] Skip V2 pool code probes when cached factory metadata already proves the pool was created after the requested block; preserve exact-boundary and unknown-date reads.
- [x] Preserve oracle priority when a lower-priority structural bucket was cached at an older block; regress feed addition/removal and unexpected-error propagation without a cache migration.
- [x] Recognize the exact Reth `ValueError` payload for legacy invalid opcode `0xfe`; keep unsupported VM opcodes, missing historical state, decoder errors and cancellation visible.
- [x] Compare numeric Uniswap prices at one resolved block instead of comparing structured paths through `pytest.approx`.
- [x] Apply existing first-hop factory/protocol restrictions before discovery reads excluded inventories; partition bounded market caches and retain unrestricted descendant routing.
- [x] Preserve the empty V2 output guard and exact-amount fallback behavior.
- [x] Preserve V2 index address normalization, deployment/exclusion filtering and dictionary copy isolation.
- [x] Preserve V3 entry-point normalization and inherited Slipstream routing options.
- [x] Retain the original review repairs' 26-red/431-green compiled regression evidence in the previous report directory.
- [x] Reproduce the additional empty-feed, missing-balance, factory-boundary, checksum, and cached-oracle failures: 25 red cases in `repairs-before`.
- [x] Guard the newly exposed V1 decoded-empty result before integer conversion; keep unexpected errors visible.
- [x] Verify the original six V1 cases on the repaired source; three empty-result cases fail on the pre-fix source.
- [x] Handle the independently observed exact Reth InvalidJump contract failure through the V1 optional-read boundary.
- [x] Verify the expanded nine V1 cases, execution-error lookalikes, and historical native exchange check against both sources.
- [x] Complete the expanded pre-fix reproduction, including the exact legacy-opcode error and restricted-discovery assertions.
- [x] Pass the same expanded assertions and focused regressions on Python 3.11–3.13 against all ten compiled extensions.
- [x] Compare Python 3.12 configured mypy diagnostics: 1,804 versus 1,827, with no additions after normalizing positional line references. Configured formatting passes; final source/matrix checks remain below.
- [x] Finish the required Python 3.12 full suite at 1,800 seconds and retain all exact failures.
- [x] Commit and push the source repairs and master integration; pass the committed-source focused rerun.
- [x] Pass all nine final sequential native adapter checks; retain eight additional passing redemption checks with their separate source hash.
- [x] Repair Windows dependency checkout paths and verify all nine CI jobs reach mypy.
- [x] Finish the required 3,600-second full suite at commit `5936a496` and classify every failure.
- [x] Prove and repair the live Chainlink fixture failure for legacy feeds without `aggregator()`.
- [x] Rerun the 102 live feed cases: 97 pass and five stale feeds skip.
- [ ] Finish the final Python 3.11–3.13 focused runs and mypy comparisons after helper import repairs.
- [x] Recheck the two remaining ERC20 timeouts sequentially at the same blocks and deadline.
- [ ] Compare the same cold checks with the previous 10,000-block log range.
- [ ] Finish the mainnet audit with both reports and memory measurements.
- [ ] Commit and push the remaining scoped changes; rerun focused checks on that commit.
- [ ] Verify remote alignment and the preserved generated C hash; update PR Summary/Rationale/Details and assess ready status.

The unrelated generated C SHA256 is `099f4992d9c8404dc31bc761d0fcfb5aeef32cd9f582688dc1b9f73646104506`.

All heavy runs retain 8 GiB, no swap, four CPUs and 512 processes/threads, one heavy job per approved profile. Prior interrupted full suites and audit OOMs remain separate historical evidence.

The records below retain successive source snapshots. Later completed results supersede earlier pending statuses; each failed or interrupted attempt remains separate evidence.

The first 1,800-second application run recorded 70 explicit deadline failures.
It was stopped after the singleton loop and incorrect cached decimals were
identified; it remains incomplete, with 387 of 1,964 test outcomes (271 passed, 107 failed, 9 skipped) and a missing
pytest summary. A fresh-database run uses the repaired dependency.

Dependency source is `1f76d99a9e727de7a6ed795f1cad9dbeb3db6cfa`.
The native unit check compiles unchanged C from successful CI build 34794957700
for the matching pinned source; no generated dependency artifact is committed.
All 158 tests pass and the uninstrumented process exits zero. Instrumented runs
cover all six new statements but crash at shutdown on both versions; those
results remain separate. Raw historical RPC evidence shows direct USDC calls
succeed while injected Multicall2 returns `NotActivated` at block 6,100,000.

The dependency's macOS historical-HTTP fixture initially timed out while resolving
reverse DNS in `HTTPServer.server_bind`. Binding the explicit loopback listener
without DNS fixes the fixture. Native CI run 36260223536 passes 158 tests in each
of all 12 OS/Python jobs; build run 36260223537 and lint pass. The sampled current
Linux mypy job retains 80 errors in 11 files. Production code is unchanged from
the downstream pinned revision.

The superseded `full-singleton` attempt was interrupted after 7,970.58 seconds
to validate the repaired source. It completed 1,587 of 1,973 test calls:
1,418 passed, 153 failed and 16 skipped. The last active Compound case was
interrupted; `pytest-summary.json` is missing, the command exited 143, and the
supervisor returned 125. Its 5,258,190,848-byte memory peak had no OOM event.
This is incomplete evidence, not a full-suite pass or failure-equivalence proof.
`full-singleton/interruption.json` records why this source was superseded.

It passed 41 test calls exceeding the former 600-second deadline. The longest
was a 1,755.91-second historical Popsicle test; synchronous Compound tests
completed in 1,340.62, 1,243.86 and 1,209.86 seconds.
`successes-over-old-deadline.json` records the exact cases and frozen source hash.
The replacement focused run includes the historical-discovery optimizations;
the required unchanged full-suite command later completed in `full-optimized-312`, as recorded below.

The dependency's generated-artifact head `7f4d0df49d0dbec4391e6fee7ab6e49ef8237827`
also passes all 12 native unit jobs (158 tests each) in run 36260638431 and lint
run 36260638460. Its production Python matches the pinned `1f76d99a` source;
`dank-latest-native-ci.json` records each job.

`focused-optimized-312` completes with 687 passes, 10 skips and six stale
internal-call assertions after discovery gained protocol restrictions. All 97
previously timed-out classification cases pass. Updating those assertions to
check the exact forwarded restrictions yields `focused-validated-312`: **693
passed, 10 skipped**, all ten compiled extensions, no missing reports or OOM,
457.69 seconds, and a 1,173,868,544-byte peak. All 97 classification cases pass
again. The earlier cold Curve-loading timeout was not reproduced in these two
runs; its evidence remains separate. The repaired-source full suite subsequently completed; see its exact outcome below.

The changed timeout harness passes both tests in the frozen Python 3.12 image:
the 1,800-second central setting, explicit one-second interruption, cleanup and
continued execution, and all 100 cooperative slots are verified in
`timeout-1800.json`.

During `full-optimized-312`, live reads encountered a real reorg at block
26,063,974. `live-block-canonical-check.json` confirms that the requested hash
is orphaned; rejecting those reads preserves the canonical-block contract.
A separate CRV oracle-comparison failure is independently reproduced by the
native V3 quoter: at block 26,063,944 the selected pool returns exactly 269,190
USDT base units for one CRV. The terminal USD conversion exactly equals the
reported $0.2691348483528. `crv-native-quote.json` contains the pool state and
raw responses; no tolerance or liquidity-ranking change is made.

The full run also exposed an empty decoded Uniswap V1 quote for old sUSD at
block 10,836,738. The raw RPC returns `InvalidJump`; the existing Dank decoding
path presents unavailable output as `None`. The V1 adapter now explicitly
returns unavailable before integer conversion. Six controlled regressions cover
later-pool fallback, both public exhaustion modes, and unexpected errors or
cancellation. A ninth sequential native check records the original RPC error
and the unavailable adapter result. These changes were made after the completed
full suite's frozen snapshot and require separate final focused/native evidence.

`mln-native-quote.json` independently reproduces the selected V3 pool's output
at block 26,063,967 and its $0.010301160542674576 USD value. The alternative
public price follows another DEX path. The native output is equal for 0.01 and
1 MLN; this evidence verifies the returned output and does not establish full
input consumption. `failed-block-canonical-checks.json` distinguishes orphaned
heads from canonical blocks, and `archive-state-recheck.json` records a later
successful raw request for an earlier provider archive-state error.

`full-optimized-312` completes the exact required command with **1,684 passed,
88 failed and 221 skipped** (1,993 collected). Pytest exits 1 and make exits 2.
The supervisor records completion, no missing reports or OOM, 5,955.01 seconds,
and a 4,339,249,152-byte peak. All ten compiled extensions were verified.
The failures include 18 orphaned-block errors, 14 provider historical-state
errors, two deadlines, eight V3 alternate-path comparisons, the V1 unavailable
result and stale Chainlink fixture repaired after the snapshot, and 44 other
assertion, contract or pricing failures. `failure-analysis.json` preserves
every message and per-case earlier observations without claiming a complete
baseline comparison. The older baseline full run remains incomplete.

This completed run passes 43 calls beyond 600 seconds, reaching 1,792.82
seconds. The final central deadline is therefore 3,600 seconds for headroom;
a final full run remains required on that configuration. The constructor-only
PieDAO check reproduces its tuple-argument failure without RPC; the source is
identical to master, recorded in `piedao-call-shape.json`.

The final 3,600-second timeout harness passes both tests in the frozen Python
3.12 image (`timeout-3600.json`), preserving cleanup and all 100 cooperative
slots. A subsequent focused run also exposed the direct-revert variant of a
removed Chainlink aggregator. `removed-chainlink-native.json` independently
confirms a zero aggregator and a reverting timestamp call at one canonical
block. The live test now checks removal before querying its timestamp; active
aggregators must still provide a valid timestamp or fail.

A direct RPC replay isolated a provider log-scan delay: the 10,000-block
request exceeded a 45-second client deadline, while the head, one-block and
1,000-block requests took 0.05, 0.26 and 3.01 seconds. The existing
`YPRICEMAGIC_GETLOGS_BATCH_SIZE=1000` setting applies to subsequent validation
jobs. `rpc-log-wait-recheck.json` records measurements and
`provider-log-range.json` identifies the environment boundary. The already
running focused check and audit retain their original 10,000-block ranges;
no improvement is claimed until the tuned runs complete.

`focused-final-validated-312` completes with **601 passed, 98 failed and
10 skipped** (709 collected), 2,498.65 seconds, no missing reports or OOM,
and a 1,173,565,440-byte peak. All six new V1 cases pass against compiled
extensions. Its 97 bucket failures reach the frozen 1,800-second deadline
waiting for Curve initialization; the other failure is the removed-aggregator
fixture corrected afterward. This run retains the original 10,000-block
log range. Its 1,804 mypy diagnostics add none to the prior validated run.

The first expanded native check exposed a second V1 representation: the direct
call preserves Reth's exact `EVM error: InvalidJump` payload. The V1 adapter
now uses the existing optional-read boundary for known contract execution
failures, and the classifier recognizes that exact ValueError payload alongside
`InvalidFEOpcode`. New assertions cover both native error and decoded-empty
fallback, exhaustion, and non-ValueError lookalikes. A final negative/native
recheck is required; the preceding native failure remains preserved.

Final interpreter-matrix targets retain all controlled repair regressions and
compiled-extension checks. The 204 live Chainlink/latest and bucket-registry
cases remain in the unchanged full-suite command, rather than repeating their
shared historical-registry initialization for each interpreter. Their earlier
timeouts remain recorded. The final native rerun covers the nine affected
checks; the eight additional redemption checks are retained separately with
their frozen source and will be rerun if their current run exposes a failure.

`native-optimized` completes all 17 sequential native cases: **16 pass and
one fails** on the already-recorded V1 InvalidJump payload, before the final
optional-read repair. All eight additional redemption checks pass, including
the final Curve 3crv LP exit and canonical-block verification. The run takes
2,287.05 seconds, peaks at 1,164,144,640 bytes, and has no missing reports or
OOM. Its exact source archive is `df86368cc0ff9210f9a29084043d65d80687e6b6c3f833de6975f7be80c04858`.
The final nine-case adapter rerun remains pending.

`compound-optimized-cold` completes its cold measurement before the 1,800-second
diagnostic limit: 1,239.02 seconds for cBAT at block 7,720,735, returning the
normal `yPriceMagicError: PriceError` for the unavailable BAT valuation. This
is **not a successful price**. The full command takes 1,363.16 seconds and
peaks at 1,174,085,632 bytes, with no OOM or missing reports. Its sampler records
no RPC-request timeout retries, only native multicall out-of-gas retries. The
provider range setting differs from the old measurement, so no controlled
performance-comparison claim is made.

`focused-validated-311` passes all **514** focused cases against all ten compiled
extensions, with no skips or failures. The command completes in 308.51 seconds
with a 1,122,136,064-byte cgroup peak, no OOM and no missing reports. Configured
mypy retains 1,804 diagnostics versus 1,827 in the recorded Python 3.11 baseline;
none are added. The source archive is
`3293448a5ff200d3b8825aab86ef737317b901a79894090e4e0fe0088c73b52e`.

`focused-validated-313` passes the same **514** cases against all ten compiled
extensions, with no skips or failures. The command takes 292.56 seconds and
peaks at 1,170,464,768 bytes, with no OOM or missing reports. Its configured mypy
comparison is also 1,804 versus 1,827 diagnostics with no additions, using the
same source archive as Python 3.11.

`focused-final-3600-312` passes all **514** cases and the timeout harness.
The command takes 296.78 seconds and peaks at 1,173,168,128 bytes, without OOM
or missing reports. All three interpreters execute identical test IDs from the
same source archive and verify all ten compiled extensions; see
`final-focused-matrix.json`. Configured Python 3.12 mypy has 1,804 diagnostics
versus 1,834 in the original baseline, with no additions. These are diagnostic
comparisons, not clean mypy runs.

`repairs-before-execution-errors` completes **171** controlled cases: 41 fail
and 130 pass on the pre-fix source. Every one of those test IDs passes in the
final interpreter matrix, including all nine V1 assertions and error lookalikes.
The same pre-fix run passes seven native cases and fails the two expected legacy
execution-error cases. The command takes 136.29 seconds (supervisor 137.25),
with no OOM or missing reports. `final-red-to-green.json` preserves exact errors
and distinguishes targeted regression proof from full-suite equivalence.

`native-final-execution-errors` passes all **nine** sequential native cases on
the final matrix source, including the historical Router02 deployment boundary,
V1 failed quote and legacy BAT selector. The command takes 120.29 seconds
and peaks at 1,166,856,192 bytes, with no OOM or missing
reports. The eight additional native redemption cases passed in
`native-optimized`; their separate source hash remains explicit.

Published text reports normalize trailing whitespace for repository formatting;
raw report hashes remain in each publication manifest alongside the published
hashes. Private raw originals are retained separately.

The committed-source rerun at `5936a4969bb0ed4e70cf057cce97c758f409db4c`
passes all **514** focused cases, with identical test IDs, all ten compiled
extensions and no added mypy diagnostics. It takes 283.53 seconds and peaks
at 1,163,137,024 bytes, with no OOM or missing reports. Its source
archive is `efe6bf996d0e0bb62a42c07ab2c0ad291c801c28040b2befb05725a48d4251d2`.
The required full-suite command is running against that same commit.

The follow-up `f689b2c6` changes only Windows CI setup: Git long-path support
is enabled before installing nested dependency submodules. The preceding Windows
CI failure occurred before mypy; `windows-ci-checkout.json` records its cause.

GitHub compile and lint pass on `f689b2c6` (runs 36280880213 and 36280880186).
All nine mypy jobs reach type checking after the Windows checkout repair but
remain failing: 1,807 diagnostics on Linux/macOS and 1,838–1,840 on Windows.
Compared with the frozen Linux Docker report, Linux/macOS add three diagnostics
for missing click/numpy, and Windows 3.12 adds 34 including platform-specific APIs.
This cross-environment comparison is not a source-regression baseline; see
`ci-mypy-final.json` and `ci-vs-frozen-mypy.json`.

The compile workflow pushes generated-only commit `2172c19f`; its application
Python is identical to the locally tested `5936a496` source. The local branch
fast-forwards to it while restoring the user's generated C bytes exactly.
The bot-triggered follow-up workflows require GitHub action approval; these are
not represented as successful checks.

`full-committed-3600-312` completes the exact required command at `5936a496`:
**1,717 passed, 72 failed and 216 skipped** (2,005 collected). Pytest exits 1
and make exits 2; the supervisor records completion, no missing reports or OOM,
8,150.72 seconds and a 3,838,300,160-byte memory peak. The archive hash remains
`efe6bf996d0e0bb62a42c07ab2c0ad291c801c28040b2befb05725a48d4251d2`.

There are two configured deadline failures (GHO at block 17,708,470 and PYUSD
at block 18,465,234), five legacy-feed fixture failures, four provider
historical-state errors, 16 V3 unavailable/native-versus-alternate-price
comparisons, and 45 other assertion or contract/pricing failures. Thirty failures
have the same test ID and exact error message as the prior completed repaired-source
probe. That comparison is not a pristine full-suite baseline. All failures are
retained in `full-committed-3600-312/failure-analysis.json`.

The completed run passes **162** calls exceeding 600 seconds and **65** exceeding
1,800 seconds, reaching **3,591.42 seconds**. This demonstrates that the old
limits rejected successful work. The two remaining timeout cases require the
queued sequential check before another timeout adjustment is justified.

The initial `fixture-before-312` attempt fails before building or running tests
because the extracted negative-control snapshot lacks Git metadata. It is recorded
as incomplete; no regression outcome is claimed. The snapshot now has local Git
metadata and the retry is queued under the same resource limits. Positive fixture
validation is running separately.

`fixture-focused-312` and `fixture-live-312` both stop before pytest collection:
the installed legacy TOML parser rejects the mixed string/integer arrays added
for sequential timeout cases. Both attempts are incomplete with a missing pytest
summary. The configuration now uses tables; both `toml` and `tomllib` parse the
same settings. No dependency or timeout setting changes for this repair.

`fixture-focused-311` passes all **523** cases against all ten compiled extensions,
with no OOM or missing reports, 320.12 seconds and a 1,172,873,216-byte peak.
Mypy exposes one new test-only diagnostic for an implicitly re-exported
`ZERO_ADDRESS`. The test now imports the same constant directly from Brownie;
the final matrix will rerun this source rather than claiming the diagnostic was
absent from the preceding run.

`fixture-focused-313` passes all **523** cases against all ten compiled extensions,
with no OOM or missing reports, 316.70 seconds and a 1,220,861,952-byte peak.
It uses the same source archive as the preceding Python 3.11 run and records the
same single test-import mypy diagnostic, fixed before the queued final reruns.
The sequential GHO/PYUSD recheck runs afterward on the same profile; the separate
audit still shares the RPC provider, so this is not an isolated provider-load
benchmark.

`fixture-before-retry-312` completes the negative control: **2 failed, 10 passed**,
with the two expected direct-revert errors for legacy feeds lacking `aggregator()`.
Its production code and original fixture match `2172c19f`; the regression assertions
match the repaired worktree. The run takes 132.64 seconds, peaks at
1,173,598,208 bytes, verifies all ten compiled extensions and has no missing
reports or OOM. `fixture-negative-provenance.json` records the exact source boundary.

`slow-erc20-312` produces both case records but reaches neither valid pricing
measurement: importing the test outside pytest captured a disconnected Brownie
provider in multicall. Both cases fail immediately with `endpoint_uri` attribute
errors. The helper now connects Brownie and applies the same source-fetching
setting as `conftest.py` before importing the synchronous collection fixture.
The recorded setup failures do not establish price availability or justify a
timeout change. A corrected sequential rerun is queued after the final matrix.

`fixture-focused-retry-312` passes all **523** cases, with no OOM or missing
reports, in 305.07 seconds. Its mypy comparison finds one helper-only implicit
re-export of Brownie's `connect` function. The helper now imports that same
function from its defining module; the final Python 3.12 type comparison runs
with the corrected sequential check before committing.

`fixture-live-retry-312` completes **97 passed, 5 skipped** across all 102 live
feed cases, with no failures, missing reports or OOM. It takes 422.89 seconds
and peaks at 1,164,873,728 bytes. The five full-suite legacy-feed failures map
to the five repaired skips. The event reporter does not store skip reasons;
the fixture's explicit skip branch is its stale-timestamp check, covered by
the controlled regressions. `fixture-red-to-green.json` records both that
limitation and the exact mapping. All 12 negative-control test IDs pass in
the repaired focused run; both expected pre-fix failures are reproduced.

`fixture-focused-retry-311` passes all **523** cases on the final helper/fixture
source, verifies all ten compiled extensions, and adds no configured mypy
diagnostics: **1,803 versus 1,827** in its recorded baseline. It takes
318.62 seconds, peaks at 1,113,001,984 bytes, and has no OOM or missing reports.
Its source archive is
`2d9ceec58ea71c2847886f7e484faaeda0d12662464d8d8f439d1f264ad7ae27`.

`fixture-focused-retry-313` passes all **523** cases on that same final source
archive, with all ten compiled extensions and no added mypy diagnostics:
**1,803 versus 1,827**. It takes 298.75 seconds and peaks at 1,170,538,496 bytes,
with no OOM or missing reports. The corrected sequential check now runs with
Python 3.12 configured mypy before its two pricing cases.

The corrected sequential job's completed Python 3.12 mypy phase records
**1,803 diagnostics versus 1,834**, with no additions. The pricing phase has
started real RPC work; its case outcomes remain pending. This static result
does not claim that the sequential measurements or audit have completed.

`slow-erc20-retry-312` passes both original full-suite timeout cases at the
unchanged 3,600-second deadline: GHO at block 17,708,470 in **3,286.11 seconds**,
then PYUSD at block 18,465,234 in **82.91 seconds**. Both canonical block hashes
are verified. The cold first case populates shared inventories; the second
case is not an independent cold-start measurement. The command completes in
3,534.49 seconds, peaks at 3,091,181,568 bytes, verifies all ten compiled
extensions, and records no OOM or missing reports. Source archive is the same
`2d9ceec58ea71c2847886f7e484faaeda0d12662464d8d8f439d1f264ad7ae27`.
The 10,000-block range comparison remains pending; no further deadline increase
is justified solely by the preceding concurrent full-suite timeouts.
