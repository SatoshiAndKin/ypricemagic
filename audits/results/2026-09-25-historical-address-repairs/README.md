# Historical V2 quotes and address normalization

The three review repairs are implemented and pushed. Focused and native evidence validates the changes; **full-suite validation remains incomplete and PR #43 remains draft**.

## Repair and regression checklist

- [x] Empty V2 `getAmountsOut` results return unavailable before indexing, allowing later pools to be tried. Exact native amounts and fees remain intact; unexpected errors and cancellation still propagate.
- [x] V2 `all_pools_for` normalizes addresses before looking up the cached checksummed index and returns an independent dictionary. Router `check_liquidity` also normalizes before forwarding to pool reserve comparisons, which cannot compare bytes with an ERC20 instance.
- [x] V3 `get_price` normalizes before liquidity routing, including Slipstream markets. Factory restrictions, block selection, exclusions and cache options remain intact.
- [x] Twelve empty-quote cases cover real RPC decoding, decoded empty sequences, exact fallback output/steps, both public failure modes, unexpected errors and cancellation.
- [x] Four V2 address forms exercise the real index, pool metadata, reserve-based liquidity, exclusions, deployment boundaries and copy isolation with the factory helper disabled.
- [x] Eighteen V3 entry cases exercise address forms, real routing, selected factories/pools, forwarded options, Slipstream and invalid-input rejection.

Public signatures, result types, liquidity ordering, the fixed USDC policy, and DEBUG-only five-minute `y.stuck?` diagnostics are preserved. No dependencies or cache formats change.

## Reproduction and validation checklist

- [x] The corrected pre-fix run (`reproduced-312`, production commit `0b553dfa819e418df7cbd85b77464eb26d748bd4`) completes with **26 failures and 405 passes**. All 397 existing focused cases pass. The same regression-file hash then passes all 431 assertions after repair; `regression-comparison.json` confirms preserved coverage and zero new failures. The earlier `baseline-312` contains one additional fixture error (missing router address) and is retained as superseded evidence.
- [x] **All 431 focused cases pass on Python 3.11–3.13** with frozen third-party dependencies. All ten configured mypyc modules import from compiled extensions, including `y.convert`. Interpreter-specific installed packages match their baseline images; command-time freezes differ only by the editable ypricemagic installation. Raw mypy output retains 1,827 diagnostics: only an embedded source-line reference shifts from 809 to 810. The raw difference and normalized comparison are both recorded. Configured Black 25.9.0, isort 7.0.0, autoflake 2.2.1 and whitespace checks pass.
- [x] Sequential native checks finish with every required report, including final canonical-block verification. At block **10,100,000**, pool `0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc` has 11,293 bytes of code; Router02 `0x7a250d5630b4cf539739df2c5dacb4c659f2488d` has none. The adapter returns `None`, and canonical hash `0x5e1bf57830198afe8da55194b916982922cb923b80fb2b050fecb80ee183d1cc` verifies. All 14 prior rows match exactly: 13 passes and the unchanged unavailable Curve steCRV gauge. Including the new row gives 14 passes and one known failure; exit 1 is retained. At block 18,000,000, the V2 quote remains exactly 604341080120514628 WETH base units for 1000000000 USDC base units.
- [x] Run the required Python 3.12 command unchanged: `PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test`. All ten compiled extensions load and all 34 new regressions pass inside this run.
- [ ] Complete the full suite and establish failure equivalence. This run was deliberately stopped after **3,124.07 seconds**, with **1,534 of 1,934 cases completed: 1,201 passes, 312 failures and 21 skips**. The configured synchronous Compound timeout fired and the next case started. This is not evidence that the process permanently hung. The command exits -15, the supervisor records interruption/exit 130 and returns 125, and `pytest-summary.json` is missing. `interruption.json` preserves the reason. No interrupted result counts as passing validation.

Against the prior incomplete full run, 237 failing case/phase pairs were already failing and 106 error messages are identical. **21 previously passing cases now fail**, and 54 failures have no matching prior outcome. Live historical samples differ and both runs are incomplete; the exact IDs/errors are in `full-comparison.json`. No absence-of-new-failures claim is made. The observed V3 discovery `int(None)` failure comes from a missing `balanceOf` response before quoting; the discovery source is byte-identical to the pre-fix commit, but the prior matching case timed out. `v3-balance-failure.json` preserves that distinction. Prior timeout and audit OOM evidence remains separate and unresolved.

## Resource and source evidence

Containers retain **8 GiB, no swap, four CPUs and 512 processes/threads**, with one heavy job per approved profile. Matrix peaks are 1126576128 bytes (3.11), 1173401600 bytes (3.12), and 1168658432 bytes (3.13). The sequential native peak is 1173082112 bytes. Committed-source verification peaks at 1356513280 bytes. The full-suite peak is **3994030080 bytes**. No run records an OOM event. Required reports are complete except for the interrupted full suite's pytest summary.

The matrix, native and full runs use source archive SHA256 `0f050399a080b97a49529cc2708d2fc4de50c29f4d85a4c3a0752061fa6c4fe4`. `source-commit.json` verifies that all six source files match implementation commit `a7c7545d121b4ec5ecb5830f1e7363d4073ca68d`. Per-run manifests retain exact source identity, dependency versions, compiled extension paths, effective limits, errors and memory measurements. Private credentials are redacted; bounded console logs remain local and their hashes are preserved.

## Delivery checklist

- [x] Commit and push scoped implementation as `a7c7545d121b4ec5ecb5830f1e7363d4073ca68d`.
- [x] Verify committed source: all 431 focused tests, ten compiled extensions and archive probe pass; mypy diagnostics remain unchanged apart from the positional reference.
- [x] Publish final evidence and update PR #43's Summary, Rationale and Details while keeping it draft.
- [x] Verify final remote alignment and preserved generated C hash.

The unrelated `build/__native_ypricemagic.c` modification is excluded. Its SHA256 remains `099f4992d9c8404dc31bc761d0fcfb5aeef32cd9f582688dc1b9f73646104506`.
