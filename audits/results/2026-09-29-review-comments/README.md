# PR 43 review-comment repairs

These checks address the three review findings on `c27864f0`. All final acceptance gates pass on committed source `7d5074c0`; native and
mutation controls use pricing-identical committed source `5e809224`.
Earlier passing suites did not detect the two false-green paths. Their historical
results remain unchanged and are not evidence that these review findings were safe.

## Repairs and regressions

- [x] Chainlink: determine availability from native registry phase mappings and
  deployed static aliases, independently of `Chainlink.get_feed` and its event
  cache. Pin mainnet reads to block 26,063,967 and its canonical hash. Reconstruct
  prices from native feed timestamps, answers, and decimals; prove removed
  aggregators independently instead of accepting a missing implementation result.
- [x] The reviewer's always-`None` discovery mutation causes 162 assertion failures
  (146 expected-unavailable cases pass), including known-active WETH/USD pricing.
- [x] V3: assert the two known unavailable tokens before branching. Require an
  actual connected swap or canonical WETH redemption path for every available
  token. Verify pool identity, native input/output amounts, decimals, and full-fill bounds. Independently
  reconstruct terminal USD value and compare both public and amount quotes.
- [x] The reviewer's constant-$123/empty-path mutation fails all 84 V3 cases,
  including the unavailable tokens.
- [x] Solidly and Velodrome V2: return `None` for empty decoded quote results before
  indexing. Keep the existing exception classifier and stuck-call decorator.
- [x] Reproduce 18 failures against the original adapter with production ABI
  decoding and routing active; 40 other cases pass. Cover empty RPC data, encoded
  empty arrays, decoded empty sequences, fallback to a later pool, both public
  exhaustion modes, and propagation of unexpected errors and cancellation.
- [x] Pass the same router assertions after repair, within the 691-test focused suite.

Fixed USDC valuation, native integer amounts and fees, public signatures, liquidity
ranking, and cache/schema policy are unchanged. Diagnostics remain DEBUG-only on
`y.stuck?`, at the default five-minute interval. No dependencies are changed.

## Validation and delivery

- [x] Frozen Python 3.11–3.13 focused matrix with all ten compiled imports verified.
- [x] All 450 targeted review cases pass on Python 3.12, within the required full run.
- [x] Committed-source mutation controls fail for the intended assertion reasons:
  162 Chainlink failures and all 84 V3 failures, all during assertion execution.
- [x] Sequential historical native checks pass: all 15 on committed `5e809224`.
- [x] Required Python 3.12 full command passes unchanged:
  `PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test`.
- [x] Configured formatting and strict mypy pass; scoped diff inspected.
- [x] Commit and push, verify source identity and remote alignment, update PR
  Summary/Rationale/Details, and check GitHub validation before marking ready.
- [x] Preserve generated C SHA256
  `099f4992d9c8404dc31bc761d0fcfb5aeef32cd9f582688dc1b9f73646104506`.

All jobs retain the 8 GiB/no-swap/four-CPU/512-process limits, with one heavy job
per Docker profile. Pytest deadlines remain 3,600 seconds. Failed harness attempts
and the explicitly interrupted exploratory V3 probe remain separate from final
acceptance reports; no interruption is counted as a completed validation run.

The independent registry reference follows the phase storage getters in the
[published Chainlink registry contract](https://github.com/smartcontractkit/feed-registry/blob/master/contracts/FeedRegistry.sol).

## Native-path reference corrections

The first complete targeted run passed 442 cases and failed four WETH address
variants plus four NU variants because the new assertion required every path
to contain only V3 swaps. WETH's existing canonical 1:1 ETH redemption is valid. The corrected test pins WETH9
runtime-code Keccak256
`0xd0a06b12ac47863b5c7be4185c2deaad1c61557033f56c7d4ea74429cbb25e23`,
requires exact input/output amounts and withdrawal metadata, verifies native ETH
backing against total supply, and reconstructs USD value from the independent
ETH feed. The final full suite rechecks all 450 targeted cases with these corrections.

WETH validation was corrected in `a29f6dfb`; a later correction also validates
NU's V2 leg through native factory identity, router exact-input output, and
exact-output bounds. Earlier checks remain separately identified. No pricing
implementation changed for these reference corrections. The corrected committed source passed all 450 targeted cases on Python 3.13, including all four
address variants for both WETH and NU.

## Development attempts retained separately

Final pricing and native controls use committed source `5e809224`; the full suite
and focused matrix use `7d5074c0`, whose only additional changes isolate the
diagnostic timer and add its regression test. Earlier attempts remain in `validation-summary.json`, with their exact assertions, source
identities, exit status, memory measurements, and missing-report lists.

| Attempt | Recorded result and resolution |
| --- | --- |
| `router-negative-312` | Original production adapter: 18 expected regression failures, 40 passes. The positive suite uses the same test AST. |
| `chainlink-312` | Four mypy diagnostics in the initial reference helper; fixed imports and types before tests ran. |
| `chainlink2-312`, `chainlink3-312` | Each passed 246 and failed 62 cases. The initial log-filter reference encountered malformed-topic RPC errors and HTTP 400 responses. Replaced it with direct registry phase-storage queries. |
| `review-positive-312`, `review-mutations-313` | A missing local type annotation stopped mypy before tests; corrected. |
| `review-positive2-312`, `review-mutations2-313` | Each passed 682 and failed nine focused cases. Updated old fixtures to control the new native RPC boundary while keeping actual encoding/decoding active. |
| `review-positive3-312`, `review-mutations3-313` | Mypy rejected an implicitly re-exported registry import; used its defining module. |
| `review-mutations4-313` | Focused 691 passed. Mutation child collection failed because the harness imported Brownie before pytest network setup. Deferred mutation installation until after collection; the missing child summary remains recorded. |
| `review-positive4-312` | Focused 691 passed; targeted 442 passed and eight failed: four WETH variants and four NU variants. Corrected the independent reference to validate canonical redemption and later V2 swaps as described above. |
| `review-mutations5-313` | Completed expected-negative controls: 162 Chainlink and 84 V3 assertion failures. This worktree snapshot predates the native-path reference corrections. |
| `v3-probe-313` | Exploratory probe explicitly interrupted after five of 21 public prices, exit 143, incomplete. No native path validation completed; excluded from acceptance. |
| `review-final2-full-312` | Committed `a29f6dfb`: 2,157 passed, 17 skipped, four NU reference assertions failed; pytest exit 1, make exit 2. The diagnostic sampler also hit its unchanged 3,600-second timeout. Completed without interruption, OOM, or missing reports; excluded from acceptance. |
| `review-final2-focused-311`, `review-final2-native-313` | Committed `a29f6dfb` focused checks passed 691 each, and all 15 native checks passed on 3.13. These precede the later V2-leg reference correction. |
| `review-final-focused-311`, `review-final-native-313` | Committed `03df6cdf` focused checks passed 691 each, and all 15 native checks passed on 3.13. Retained separately from the final `7d5074c0` matrix. |

The initial `v3-probe-312` launch used an image absent from that Docker profile;
no tests ran. A proposed full-suite job after `review-positive4-312` never started
because its prerequisite rejected the eight reference-assertion failures. Neither
is a completed full-suite run. Prior timeout and audit OOM results remain in their original audit
directories and are not combined with these review-control results.

## Diagnostic sampler isolation

The `a29f6dfb` full run exposed a separate harness defect after 1,747 passes and
the four known NU reference failures. The retry-boundary test patches
`asyncio.sleep` with an immediate mock. If the optional wait sampler wakes while
that patch is active, its loop stops yielding. A live registered stack dump
confirmed execution inside the sampler's `asyncio.all_tasks` loop. This is not
an RPC timeout or a pricing defect.

Commit `7d5074c0` captures the real diagnostic sleep independently of test patches.
The new runner regression fails against the old sampler and passes with the fix;
all 11 runner unit tests pass. The old run reached its configured 3,600-second
deadline without interruption. The signal stopped the background sampler, and
pytest then recorded the retry test as passed after 3,599.999 seconds. That outcome
is not accepted as a healthy check: the timeout and live stack evidence are
retained in `sampler-control/`. A fresh full run uses the same frozen Python
3.12 image and resource limits on the other profile. No pricing code or pricing
test changes follow `5e809224`.

The corrected full run passed the same retry-boundary test in 0.000553 seconds.
Its exact event is retained in `sampler-control/repaired-full-event.json`.

The old full attempt completed in 8,234.205 seconds, with peak cgroup memory
5,868,748,800 bytes. Its four assertions, 3,600-second diagnostic stall, and
nonzero exit remain separate from the corrected full-suite result.

## Final acceptance

The required full command was run unchanged, with diagnostics enabled and the
sampler clock isolated from mocked retry sleeps. No final acceptance job timed
out, was interrupted, was OOM-killed, or omitted a required report.

| Job | Result | Peak cgroup bytes | Elapsed seconds |
| --- | --- | ---: | ---: |
| `review-final4-focused-311` | 691 passed | 1,300,099,072 | 236.616 |
| `review-final4-full-312` | 2,161 passed, 17 skipped; focused 691 passed | 4,513,456,128 | 4772.368 |
| `review-final4-focused-313` | 691 passed | 1,322,848,256 | 245.350 |
| `review-final3-native-313` | 691 focused and 450 targeted passed; 15 native checks passed | 3,487,809,536 | 1476.861 |
| `review-final3-mutations-313` | 162 Chainlink and 84 V3 intended assertion failures | 1,200,291,840 | 175.698 |

All three final matrix jobs passed 11 runner tests, strict mypy with zero
diagnostics across 231 files, and imported all ten configured extensions from
CPython-specific `.so` paths. The full suite includes all 450 review-specific
cases. Its longest test passed in 3257.994 seconds, below the unchanged
3,600-second deadline. All 13 GitHub checks passed on `7d5074c0`.

`review-gates.json` verifies source/archive identity, native and mutation controls,
compiled imports, exact resource caps, complete test accounting, and the preserved
generated C hash. The only source changes between the native/mutation controls
and the final matrix are the diagnostic timer and its runner regression test.
`published-files.json` files hash the retained artifacts for each attempt.

The final delivery commit adds only audit evidence and documentation. Earlier
failed, incomplete, timed-out, and interrupted attempts retain their recorded
statuses; none is substituted for final acceptance.
