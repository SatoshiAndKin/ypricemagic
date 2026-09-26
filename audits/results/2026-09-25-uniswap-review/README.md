# Uniswap review repairs

All four review findings are addressed:

- V3 and Slipstream event loaders construct pools with named fields. V3 preserves the event fee and tick spacing; Slipstream keeps its tick spacing and the dynamic-fee sentinel of zero.
- The multiplexer admits Slipstream first hops and normalizes all supported address inputs before routing.
- Restoring normalization exposed an existing integer converter defect under the frozen HexBytes dependency: `hex()` returns unprefixed text, so stripping two characters changed the address. The converter now removes only an actual `0x` prefix. Compiled tests cover every byte, zero, the maximum address, and out-of-range values.
- The former maximum-price test is replaced by deterministic public-multiplexer cases for deepest viable selection, revert/zero fallback, exclusions, exhaustion, and stable ties. Existing live V1/V3 tests remain.

Public pricing signatures, the fixed USDC policy, and DEBUG-only five-minute stuck-call diagnostics remain unchanged. No dependencies changed. The user's generated C modification is preserved and excluded.

## Reproductions

`baseline-312` uses pre-fix source `fdfaea7148380d8d026de83176282b191d930594` and the corrected regression inputs. It completes with **11 failures and 374 passes**, including all 370 prior focused cases passing. The failures demonstrate actual encoded V3/Slipstream key mismatches, Slipstream omission, integer/byte address regressions, invalid-address validation, and the old assertion rejecting the correct price of 2 because a shallower quote is 9. The old assertion reproducer is retained as text; it is not part of the final test suite.

`fixed-312` has the three routing/event fixes and corrected fixtures but predates the integer converter correction. Its **389 passes and one integer-address failure** expose that additional defect. All other new behavior passes there.

`before-312` and `after-312` are superseded intermediate reports: a malformed fixture address made all six address forms fail before reaching the behavior under test. Corrected fixtures and annotation fixes supersede those results; raw evidence is retained rather than represented as production regressions.

## Validation

**All 397 focused cases pass on Python 3.11–3.13**, with all ten compiled extensions verified, including `y.convert`. Each version retains **1,827 mypy diagnostics versus 1,834 before**, with none added and byte-identical installed dependencies to its baseline image. Mypy still fails overall. The three runs share the same source archive hash. Container peaks range from **1,165,869,056 to 1,368,010,752 bytes**, with no OOM events. Matrix results, compiled extension paths, configured mypy comparisons, frozen dependency checks, and memory measurements are indexed in `summary.json`. Formatting versions and results are recorded separately.

Committed source `065e6b527dff43f1681ecfb8f207717baba39af4` separately passes **all 397 tests**, loads all ten extensions, and passes the archive probe. It retains 1,827 mypy diagnostics with none added, peaks at **1,174,122,496 bytes**, and records no OOM. The live runs verify matching changed-source hashes in `source-comparison.json`.

Use only completed reports as completed evidence. Both native scripts complete sequentially, including the final Curve withdrawal and canonical-block check. All **14 rows exactly match** the prior baseline: **13 passes and one unchanged unavailable Curve steCRV gauge**. The native command exits 1 solely for that known unavailable case. The required Python 3.12 command `PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test` ran unchanged in Docker. After **3,003.53 seconds**, it was intentionally stopped with **1,500 of 1,900 cases completed: 1,171 passes, 308 failures, and 21 skips**. All **114 quote-repair and replacement selection cases passed** inside this run. A synchronous Compound case recorded its 600-second timeout and advanced to the next case before interruption; this is not evidence of a permanently hung process. The runner exits 125, the container exits 143, and `pytest-summary.json` is missing. Peak container memory is **3,507,015,680 bytes**, with no OOM events. All ten compiled extensions load, and the changed source hashes match source commit `065e6b52`.

Against the prior incomplete quote-repair full run, **219 failed case/phase pairs already failed**, and 96 have identical error messages. **39 previously passing cases now fail with timeout or cancellation errors**; 50 failures have no prior matching outcome. Their cause remains unresolved. `full-comparison.json` preserves the exact case IDs and errors. Both runs are incomplete and some historical samples depend on chain height, so this comparison does **not** establish absence of new failures. Collection changed from 1,957 to 1,900 cases because 84 live maximum-price variants were replaced by six deterministic selection cases, and 21 other regressions were added. Existing live V1/V3 assertions remain.

Earlier full-suite timeouts, the prior 32 newly observed timeout cases, and audit OOM evidence in the quote-repair reports remain unresolved and separate. PR #43 remains draft.

## Reproducibility and containment

The existing Docker runner keeps containers at 8 GiB, no swap, four CPUs, and 512 processes/threads, with one heavy job per approved profile. Raw reports include source archive hashes, Python/dependency versions, all ten compiled extension paths, limits, memory peaks, and OOM/interruption status. `source-files.json` identifies the final changed source files. No host project build was run.

Private endpoint/token values are redacted from published files. Per-run manifests hash the published artifacts and local bounded console logs; consoles remain outside the repository. Missing reports and interruptions never count as passing validation.
