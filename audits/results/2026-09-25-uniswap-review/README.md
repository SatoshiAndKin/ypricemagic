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

Use only completed reports as completed evidence. The full suite and native checks have not yet been recorded for this revision. Earlier full-suite timeouts, 32 newly observed timeout cases, and audit OOM evidence in the quote-repair reports remain unresolved and separate. PR #43 remains draft.

## Reproducibility and containment

The existing Docker runner keeps containers at 8 GiB, no swap, four CPUs, and 512 processes/threads, with one heavy job per approved profile. Raw reports include source archive hashes, Python/dependency versions, all ten compiled extension paths, limits, memory peaks, and OOM/interruption status. `source-files.json` identifies the final changed source files. No host project build was run.

Private endpoint/token values are redacted from published files. Per-run manifests hash the published artifacts and local bounded console logs; consoles remain outside the repository. Missing reports and interruptions never count as passing validation.
