# PR 43 historical pricing repair checklist

The completed pre-repair full run collected 2,034 tests: 1,745 passed, 68 failed,
and 221 skipped. None of those 68 failures were timeouts. The comparison against
another PR snapshot did not establish that they were all pre-existing.

The investigation accounted for every reported failure:

| Cause                                                  |  Cases |
| ------------------------------------------------------ | -----: |
| Missing V1 native ETH continuation                     |      9 |
| MLN partial V3 fills                                   |      4 |
| CRV/YFI sale-versus-oracle assertions                  |      8 |
| Unsupported or uninitialized historical samples        |      7 |
| Popsicle zero supply                                   |      2 |
| Compound unavailable-feed exception representations    |      7 |
| Historical Synthetix resolver / stable synth fallback  |      2 |
| GUNI metadata and missing child valuation              |      2 |
| Retired ATOM feed                                      |      1 |
| Unverified Aave wrapper implementation                 |      1 |
| Wrapped USDT fixed-dollar expectation                  |      1 |
| Aave async dispatch                                    |      2 |
| Standalone Compound historical oracle / initialization |      4 |
| Native Compound exchange-rate underflow                |      1 |
| Optional sense-check metadata                          |      1 |
| Yearn Decimal-versus-float expectations                |      2 |
| Balancer and Curve literals                            |      2 |
| PieDAO call encoding                                   |      1 |
| Historical-state provider errors                       |     11 |
| **Total**                                              | **68** |

The original full-run evidence is retained in
`results/2026-09-26-mergeability/full-v3-inventory-312/`. The twelve-case master
diagnostic used current frozen dependencies and a documented build configuration
overlay; it was not a clean full-suite baseline. Its timeout and shutdown
termination do not establish that the PR's failures were pre-existing.

## Repairs

- [x] Retain empty V2 quote fallback, including empty RPC decoding.
- [x] Retain V2 index and V3 entry-point address normalization, including Slipstream.
- [x] Restore V1 native ETH-to-USDC discovery and fee-inclusive swaps.
- [x] Require V3 and Slipstream quotes to prove the full input can be sold.
- [x] Resolve standalone Compound controllers at the requested block.
- [x] Recognize six verified unavailable Compound oracle revert reasons, including
      request-context and Brownie exception representations.
- [x] Verify Inverse's retired zero-aggregator feed before treating its blank
      oracle revert as unavailable; preserve unexplained blank reverts.
- [x] Convert the verified legacy Cream ETH-denominated oracle to historical USD.
- [x] Treat unavailable Compound exchange rates as unavailable candidates.
- [x] Resolve Synthetix keys and ExchangeRates through the historical synth resolver.
- [x] Allow stable synth spot pricing after an unavailable stablecoin feed.
- [x] Recognize both GUNI interfaces and value actual underlying balances.
- [x] Dispatch Aave reserve lookups asynchronously and drain owned work.
- [x] Detect and price Aave wrappers without explorer verification.
- [x] Preserve parent fallback and failure policy when a child price is unavailable.
- [x] Handle zero-supply Popsicle pools.
- [x] Repair PieDAO call encoding and pool/token batch arguments.
- [x] Keep missing optional sense-check metadata from aborting a valid price.

## Regression coverage

- [x] Initial 20 assertions fail against original production source.
- [x] Expanded baseline: 39 failures and four passing propagation checks.
- [x] Expanded repaired run: 45 passed, including unexpected errors/cancellation.
- [x] Eight sequential native checks passed with canonical hashes and exact outputs.
- [x] Further expanded original-source control: 58 failures and nine passing checks.
- [x] Final original-source control: 65 failures and nine passing checks, 74 total.
- [x] Eleven sequential native checks passed, adding both legacy Cream oracle
      denominations and IronBank EUR.
- [x] Final fourteen sequential native checks passed, including Venus, Inverse's
      verified retired feed and successful fallback, and PieDAO's reconstructed value.
- [x] Replay all three unique requests behind the eleven provider-state failures
      successfully at their original canonical block hashes.
- [x] Correct Yearn Decimal expectations and independently verified Balancer/Curve values.
- [x] Reconstruct PieDAO's historical value from native balances and feeds.
- [x] Enable the 199 previously unmarked Compound async cases.
- [x] Collect all individual batch-pricing failures before asserting.
- [x] Verify explicit supported, uninitialized, retired, and unavailable historical cases.

## Validation

- [x] Fetch and fast-forward assigned remote branch before implementation.
- [x] First repaired focused run: 563 passed, all ten compiled extensions verified.
- [x] Latest Python 3.12 focused run: 613 passed, with all ten compiled extensions.
- [x] Final frozen focused matrix: 613 passed on each of Python 3.11, 3.12, 3.13;
      all ten compiled extensions verified on every version.
- [x] Configured formatting and mypy diagnostic comparison: 1,772 diagnostics
      versus 1,788 baseline on each version. The sole added message replaces the
      existing Gelato decorator diagnostic after its return annotation gained None.
      GitHub's Ubuntu/Python 3.13 job similarly records 1,775 versus 1,791 baseline;
      the three diagnostics beyond the frozen local count concern unchanged missing
      click/numpy imports and their consequence. CI remains failing.
- [x] Required Python 3.12 full command, unchanged; record provider failures explicitly.
- [x] Same-block provider replays and subsequent public-price validation: 29
      affected pytest cases passed; all nine remaining provider-failed prices passed
      sequential native calls at their exact failed canonical blocks. Preserve the
      failing pytest runs separately.
- [x] Record source/archive hashes, memory peaks, missing reports and interruptions.

All heavy jobs use 8 GiB RAM, no swap, four CPUs and 512 processes/threads,
with one heavy job per profile. Configured 3,600-second deadlines remain active.
Prior timeout, audit OOM and incomplete baseline results remain separate evidence.

The expanded full run also exposed repair mistakes that the final checks must
cover: Popsicle's private scale helper does not accept `sync=False`, and GUNI's
readable supply is a float. Corrected regressions now exercise the real scale
helper and use the actual readable-supply return type. BAND's pinned V3 pool
rejects native quotes with `SPL`; the test verifies that revert. Wrapped USDT's
native inputs confirm its expected value, with only one ULP of final float
rounding permitted by the assertion.

Enabling the previously skipped Compound async tests exposed fifteen Venus
`invalid resilient oracle price` reverts. Sequential native replay reproduced
all fifteen, and the proxy's historical implementation confirms that this is
the terminal result when its oracle sources cannot supply a validated price.
The exact reason is covered in all three exception representations. It is not
classified as a timeout, provider-state error, or one of the original 68 cases.

The complete intermediate diagnostic run recorded 2,008 passes, 65 failures,
and 22 skips, with no timeout, OOM, or missing reports. Its last cases also exposed
Inverse's retired feed and PieDAO's stale expected value. All 65 failures are
classified in `results/2026-09-27-historical-repairs/full-guarded-312/failure-analysis.json`;
that failed intermediate snapshot is not final-source validation.

The latest Python 3.12 focused/native run completed with 613 focused passes and
14 native passes, no OOM or missing reports, and a 3,314,966,528-byte memory peak.
Its archive hash is
`cd0f94e4be0fc0e426d68bc490440be9fc30d3613d74d3ae296b112097f61bd8`.
The Inverse fallback returned `0.0014653492066322037`; PieDAO returned exactly
`1.0002097895742665`.

The final-source full workload collected 2,104 tests: 2,059 passed, 23 failed
with provider historical-state errors, and 22 skipped. There were no assertion
failures, timeouts, or OOM. Peak cgroup memory was 4,526,096,384 bytes and workload
duration was 4,197.005 seconds. Archive hash:
`079400b6a3ff82771bb837837f696495cdde9bdf2641ae886b3c65d2f2040af3`.
Its longest individual test passed in 2,692.870 seconds. The preceding full run's
longest test passed in 2,436.113 seconds. Both fit the unchanged 3,600-second
per-test deadline; neither run had a timeout failure.
The host supervisor did not finish reporting; complete command and pytest reports
were recovered intact from the exited container. Host completion remains false,
with workload completion recorded separately in `full-latest-312/recovery.json`.

All 22 unique requests behind the 23 failures reached historical state when
replayed at their original canonical hashes. Responses include both data and
native EVM rejections from selector probes. The preceding full snapshot recorded
2,055 passes, 21 provider-state failures, the two subsequently repaired
Inverse/PieDAO failures, and 22 skips. The 38 distinct provider-failed public tests
from both runs were rerun with unchanged production and test source; only the
centrally configured test selection differed. That recheck completed with 29
passes and nine provider-state failures at newly selected blocks, with no
assertion failures or timeouts. Its four unique failed requests now reach state
at their exact original hashes. A separate sequential native check passed all
nine affected public prices at blocks 26,076,808 and 26,076,809, verifying each
canonical hash before and after pricing. All ten compiled extensions were
verified. The native-only runner, inputs, source identity proof, exact prices,
and resource measurements are retained in `native-provider-312/`. Neither failed
full run nor the failed pytest recheck is relabelled as passing.

## Earlier delivery checkpoint

- [x] Inspect scoped diff and preserved generated C hash:
      `099f4992d9c8404dc31bc761d0fcfb5aeef32cd9f582688dc1b9f73646104506`.
- [x] Commit and push scoped changes: `17c08dda9796994ea755699032975dc4b91fd06e`.
- [x] Rerun focused checks against committed source: 613 passed on Python 3.12,
      all ten compiled extensions verified. The following bot commit `bd1302d1`
      changes only generated C files; Python source and tests are identical.
- [x] Update PR Summary, Rationale and Details; keep draft while gaps remain.
- [x] Verify remote alignment and preserved generated C hash; the local C file
      remains the sole unrelated working-tree change. Retain the bot's generated C
      commit separately from the pricing repair and validation evidence commits.

At this checkpoint, the repairs were pushed and the PR remained draft. The
full-suite provider failures, baseline mypy failures, and earlier source-specific
audit limitations remain visible; later successful checks do not make those
historical runs green.

## Zero-failure follow-up

The remaining provider and static-check failures are repaired through `619e23a2`,
including Compound direct-call retries and portable validation-harness typing.

- [x] Required Python 3.12 full command: **2,132 passed, 22 intentionally skipped,
      zero failures**, exit 0.
- [x] Frozen focused matrix: **667 passed on each of Python 3.11, 3.12, and 3.13**.
- [x] All ten compiled extensions verified and strict mypy clean on each version.
- [x] All 15 sequential historical native checks passed.
- [x] All 13 GitHub checks passed on the validated source.
- [x] Preserve exact failed controls, earlier incomplete runs, source/archive
      identities, resource limits, peak memory, and report hashes.
- [x] Preserve the unrelated generated C hash shown above.

The final full run used 4,536,238,080 peak cgroup bytes. Its longest test passed
in 3,044.269 seconds; the 3,600-second deadline was not increased. All final jobs
completed without OOM or missing reports. Final delivery adds evidence and
documentation without changing the validated source.

The [follow-up checklist and evidence](results/2026-09-28-zero-failures/README.md)
track each repair, original-source regression control, immutable validation
attempt, and final acceptance gates. Earlier failed and interrupted results
above retain their original status; they are not relabelled as passing.

## Review-comment follow-up

All three review findings are repaired and independently verified. Chainlink
availability and USD values come from pinned native state; V3 prices require an
actual native swap/redemption path and independent terminal valuation; empty
Solidly and Velodrome V2 results now allow routing fallback.

- [x] Original adapter control: 18 failures reproduced; the same assertions pass
      after repair, with exact native amounts and failure propagation preserved.
- [x] All 450 review cases pass on Python 3.12 and Python 3.13.
- [x] The always-None Chainlink mutation causes 162 assertion failures; the
      constant-$123/empty-path V3 mutation fails all 84 cases.
- [x] Required Python 3.12 full command: **2,161 passed, 17 skipped,
      zero failures**, exit 0.
- [x] Frozen Python 3.11–3.13 matrix: **691 focused tests passed per version**,
      all ten compiled imports verified, strict mypy clean across 231 files,
      and all 11 runner unit tests passed.
- [x] All 15 sequential historical native checks passed.
- [x] Fix and regress the diagnostic sampler's collision with mocked retry sleeps;
      preserve the old configured-timeout result separately.
- [x] All 13 GitHub checks passed on validated source `7d5074c0`; preserve the
      unrelated generated C hash and keep delivery changes scoped to audit docs.

The [review repair evidence](results/2026-09-29-review-comments/README.md) records
source identities, exact failures, resource measurements, report completeness,
negative controls, and final acceptance gates. Production pricing is identical
between `5e809224` and `7d5074c0`; the latter adds only the sampler fix and its
regression. No deadline or resource limit was increased.
