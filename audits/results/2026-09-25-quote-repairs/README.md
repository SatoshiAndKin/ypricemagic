# Quote-path repairs

The implementation uses 1 USDC = $1 for curated/configured spot and terminal valuations at every block. Amount inputs still execute real sales. Band remains USDC-denominated. Curve iterates lazy withdrawal candidates until their complete outputs can be valued, isolating rejection state and exclusions while sharing exact native observations. Missing/reverted input decimals use the public failure policy; empty output metadata is unavailable. V3 amount quotes and the existing property share the verified-ABI/unverified fallback initializer.

The user's generated `build/__native_ypricemagic.c` change is excluded. No dependencies or validation limits changed. Containers retain 8 GiB, no swap, four CPUs, and 512 processes/threads, with one heavy job per approved profile. All tests run against the ten configured compiled extensions; their exact paths are recorded.

## Controlled regressions and matrix

- `baseline-312`: before production repairs, 29 new regression failures and 294 passes (including all 283 existing focused cases). The failures cover fixed USDC valuation, Band source descriptions, Curve exit fallback, decimals errors/batches, and unverified V3/Slipstream quoters.
- `empty-before-312b`: 366 passes and two additional failures demonstrate that an actual empty RPC response decodes to `None` and previously escaped as `TypeError` in both public failure modes.
- `repaired-311`, `repaired-312`, `repaired-313`: **370 passes on each Python version**, all ten extensions verified, no OOM. The 3.12 run preceded a test-only import annotation correction; `types-final-312` checks that correction on 3.12. The final 3.11/3.13 sources include it.
- Final configured mypy comparisons retain **1,834 pre-existing diagnostics**, down from 1,836, with no added diagnostics. Mypy still exits nonzero. Baseline reports use the exact same dependency images and byte-identical installed dependencies. The intermediate `repaired-312` mypy report's one test-only import diagnostic is superseded by `types-final-312`.
- Black 25.9.0, isort 7.0.0, autoflake 2.2.1, and diff whitespace checks pass; see `formatting.json` and `source-files.json`.

## Native checks

`native-312` runs both scripts sequentially and completes both final reports and the final canonical-block check. All **14 case rows exactly match** the earlier results: **13 passes and one unchanged unavailable Curve steCRV gauge**. This known unavailable case makes the command exit 1. `native-comparison.json` identifies the exact baseline reports. The pending Curve 3crv case eventually completed successfully; its diagnostic stack capture is retained and is not a failure result.

## Full-suite status

The required Python 3.12 command is run unchanged inside Docker:

```sh
PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test
```

The final-source rerun is still in progress when this initial evidence is committed. Its result will be recorded separately before updating PR #43. Full validation is not claimed complete.

`full-final-312` was **prematurely interrupted** after an outdated stall assessment. Its final checkpoint actually shows resumed progress: 389 / 1,957 terminal cases, comprising 270 passes, nine skips, and 110 failures. Of those failures, 100 are 600-second cooperative timeouts and ten are `TypeError` in unchanged Chainlink `latest_timestamp`; all ten Chainlink IDs/messages also fail identically in the earlier optimized full-suite report. This partial run does not establish coverage or absence of new failures. Its corrected checkpoint explicitly records the interruption error.

The other early `full-*` runs and `final-313` were superseded during implementation; missing reports/interruption are preserved as incomplete. `before-312` was stopped to correct focused-test selection. Names beginning `final-` reflect intermediate run names, not final validation claims. The summary JSON records each source archive hash, command status, and available memory/OOM evidence. A supervisor interruption prevented final counters for the superseded `final-313` build; stopped-container reports were recovered only after verifying no runner remained.

Earlier full-suite timeout and mainnet-audit OOM results remain independent unresolved results in the September 13 evidence. They are not resolved by these focused repairs. Keep PR #43 draft.

## Artifact handling

`summary.json` indexes completed and interrupted runs. `published-files.json` records hashes of published artifacts and the bounded console retained in `/private/tmp/yprice-quote-repairs`. Endpoint/token values are redacted before publishing. Raw console files are kept locally; structured failures, dependency freezes, compiled module paths, resource limits, and source identities are published here. Missing summaries never count as passing checks.
