# PR 43 zero-failure follow-up

This follow-up addresses the remaining full-suite and static-check failures.
Final committed-source validation passed: **2,132 full-suite tests passed,
22 intentionally skipped, and zero failures**. The focused matrix passed all
667 tests on each of Python 3.11–3.13, and all 15 sequential native checks passed.

The earlier 68-case investigation, timeout experiments, audit OOM, and interrupted
supervisor reports remain in the dated directories beside this one. A later
successful run does not change their outcomes.

## Repairs and regression coverage

- [x] Retry only the exact `-32000 historical state <64-hex hash> is not available`
  archive response, preserving the same requested block identifier on every call.
- [x] Cover native decoding after recovery, exhaustion, unrelated errors, and
  cancellation during a request or backoff. Ten attempts allow 121.5 seconds of
  bounded backoff; a persistent miss still raises its original error.
- [x] Forward `Contract.get_code(block=...)` as the RPC's `block_identifier`.
- [x] Cover the historical code-read keyword regression against original source.
- [x] Preserve typed sync/async execution modes, arguments, overloads, inherited
  descriptors, generator binding, and covariant method returns in the mypy plugin.
- [x] Check valid calls and deliberately invalid arguments, results, overrides,
  queue calls, and generator calls. Unused-ignore checking detects lost diagnostics.
- [x] Repair ERC20 decoding boundaries, empty balances, readable integer supplies,
  multicall return mappings, and synchronous timestamp persistence.
- [x] Cover exact native quantities, optional failure behavior, ordinary integers,
  batch holes, real ABI decoding, and both timestamp response representations.
- [x] Restore empty-iterator and dictionary-log decoding; restore immutable log
  topics even when Brownie's decoder fails.
- [x] Cover decoded Transfer values and metadata for both RPC log representations.
- [x] Resolve Saddle's pool before requesting its tokens; preserve Ellipsis reserves
  in native units until the existing balance wrapper applies token scaling.
- [x] Cover the Saddle call order, missing pools, and Ellipsis native reserves.
- [x] Make missing Aave markets, missing Synthetix resolver entries, and incomplete
  Curve balances explicit; preserve unexpected database integrity failures.
- [x] Cover those boundary failures with production methods active.
- [x] Correct trace-cache address fields, metadata keys, and nested action predicates.
- [x] Verify metadata extension, direction, block boundaries, and stored trace values
  against the real schema in an isolated SQLite database.
- [x] Fix CLI token-selection scoping and block deletion without loading lazy
  composite keys. Omit an absent network argument from the Curve debug command.
- [x] Verify exact retained database rows for address, symbol, and block selectors,
  and exact debug commands with and without a configured network.
- [x] Retain DEBUG-only `y.stuck?` diagnostics at the default five-minute interval;
  add the same decorator to refactored RPC helpers.

No resolved dependency versions or database schemas are changed. Click was already
present at version 8.5.0 in every frozen lock; it is now declared directly.
The mypy workflow installs the existing development requirements, including numpy.
Strict checking remains enabled, with explicit probes guarding against type erasure.
Four legacy subclass APIs in three classes intentionally differ from their parent signatures;
those individual overrides are documented without changing their public call shape.

- [x] Preserve Decimal results for Balancer V1 TVL and Mooniswap prices, and
  preserve configured V2 tuple paths; cover exact values and return shapes.

## Completed diagnostic evidence

The five-attempt retry snapshot completed the required full command with
**2,091 passed, one failed, and 22 skipped**. Its sole failure was an archive-state
miss after all five attempts. Twenty sequential replays of that exact hash and
address all returned the same 19,873-byte code payload. Those reports remain
`state-retry-full-312` and `exhausted-state-native-312`; neither is presented as a
passing full suite. The current retry window is tested beyond the old five-attempt
boundary.

`types-round40-312` and `types-round42-312` completed strict mypy with no diagnostics.
Later source snapshots must pass the same check as part of final validation.
Intermediate syntax errors, plugin failures, test-fixture failures, and unsuccessful
checks retain their own reports and exit codes.

The nine core native checks in `final-native-312` passed sequentially. At mainnet
block **10,100,000**, canonical hash
`0x5e1bf57830198afe8da55194b916982922cb923b80fb2b050fecb80ee183d1cc`,
the USDC/WETH pool `0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc` has
11,293 bytes of code and Router02 `0x7a250d5630b4cf539739df2c5dacb4c659f2488d`
has none. The adapter returned `None`; the later V2 quote also passed.

The earlier `zero2-full-312` snapshot has now completed the required command:
**2,124 passed, 22 skipped, zero failures**, plus **14/14 sequential native checks**.
Its peak cgroup memory was **3,988,103,168 bytes**, with no OOM, interruption, or
missing reports. The longest test passed in **2,799.631 seconds**, within the
unchanged 3,600-second deadline. This report retains its original archive hash
`7a78521199afde9a43479b265cfdfb77037bd3d9e01357c24ea7376bd38c1e38`.
It is historical evidence, separate from the final committed-source gates below.

## Reviewed-source checks

The focused matrix passed **661 tests on each of Python 3.11, 3.12, and 3.13**,
with zero strict-mypy diagnostics and all ten compiled extension paths verified.
The final cache-order preservation, Mooniswap stuck-call decorator, and native
Inverse assertion are included in commit `0771c206`. This earlier matrix retains
its own source/archive hashes; final acceptance uses the later source below.

The original-source helper control (`typed-negative2-312`) completed with
**16 expected failures and seven passes**. It restores seven modules' original
helper implementations while retaining byte-identical current regression files.
The Ellipsis counterexample is precisely **1.234567 versus 1,234,567 native units**.
The overlay manifest records restored functions, source hashes, and assertion-file
hashes. The earlier control is retained separately; its Ellipsis fixture did not
provide the old scale lookup and was strengthened before repeating the control.

## Final acceptance gates

All current-source acceptance jobs use commit `619e23a2`, archive SHA256
`92b467579d47fa63a9a09e4ec2f381b70ee769f1c5fc30c9964378013be4a438`.

- [x] Python 3.11: 667 focused passes, strict mypy clean, ten compiled extensions,
  and ten runner unit tests.
- [x] Python 3.12: 667 focused passes, strict mypy clean, ten compiled extensions,
  and ten runner unit tests.
- [x] Python 3.13: 667 focused passes, strict mypy clean, ten compiled extensions,
  and ten runner unit tests.
- [x] Fifteen sequential historical native checks on the repaired source.
- [x] Required Python 3.12 full command: 2,132 passed, 22 intentionally skipped,
  zero failures, exit 0:
  `PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test`.
- [x] Configured formatting and scoped diff review.
- [x] Repair commits pushed; committed-source focused matrix and 13 GitHub checks pass.
- [x] Publish final reports and verify their hashes and committed-source identity.
- [x] Prepare final PR Summary, Rationale, and Details for delivery.
- [x] Verify the preserved generated C SHA256:
  `099f4992d9c8404dc31bc761d0fcfb5aeef32cd9f582688dc1b9f73646104506`.

Each attempt in [validation-summary.json](validation-summary.json) records its
immutable source/archive identity, exact exit status, memory peak, elapsed time,
missing reports, and test/static-check completeness. Failed test tracebacks and
complete mypy output are retained per attempt. All jobs use 8 GiB RAM, no swap,
four CPUs, and 512 processes/threads, with one heavy job per Docker profile.
The configured 3,600-second pytest deadlines remain unchanged.

| Final attempt | Result | Elapsed seconds | Peak cgroup bytes |
| --- | --- | ---: | ---: |
| `release-focused-311` | 667 focused passes | 285.453 | 1,135,165,440 |
| `release2-full-312` | 667 focused; 2,132 full passes, 22 skips | 4,527.075 | 4,536,238,080 |
| `release-focused-native-313` | 667 focused; 15 native passes | 938.661 | 3,482,857,472 |

All three jobs completed with exit 0, no OOM, and no missing reports. Each
compiled-module manifest lists all ten imported `.so` paths. Strict mypy reports
zero diagnostics across 230 files on every Python version. The full command
ran unchanged after the focused checks; the longest full-suite test passed in
**3,044.269 seconds**, below its 3,600-second deadline. The 22 skips cover
chain-specific tests, deprecated or uninitialized contracts, stale feeds, and
inapplicable bucket checks. No failures were converted into skips for acceptance.
The machine-checked gate report is [release-gates.json](release-gates.json).

All 13 GitHub checks passed at the validated source: nine mypy platform/version
jobs, compilation, formatting, and both CodeQL checks. The final delivery commit
adds documentation and evidence only; it does not change validated Python source.

## CI follow-up

The configured formatting tools now converge without changes. Workflow formatting
is committed locally, avoiding the GitHub App's denied workflow push. Captured
audit artifacts and chain fixtures retain their original bytes and hashes.
The two shared pytest fixture imports are explicitly retained for discovery.

Windows exposed 33 Linux-harness diagnostics per Python version. Resource reads,
process-group signals, stack dumps, and diagnostic alarms now have explicit Linux
platform guards; unsupported hosts fail clearly instead of reporting fabricated
measurements. The runner's ten unit tests cover the preserved units and signal
behavior. A subsequent three-diagnostic unit-test re-export issue was corrected
by patching `sys` directly. No mypy flags or ignores were relaxed.

## Compound direct-call follow-up

The older committed full run exposed an archive-state error in Compound's direct
`exchangeRateCurrent` call, which bypassed the existing bounded retry helper.
The exchange-rate call, contract fallback, and underlying-oracle reads now use the
same narrow retry classifier without changing the requested block, normal revert
handling, return values, or cancellation behavior.

The pre-fix control `release-compound-negative-312` ran real multicall encoding
and decoding with controlled RPC responses: four expected failures and 15 passes.
The same six new regression cases are included in the repaired 667-test focused
suite. The control records exact source and assertion-file hashes.

Native replay at block 26,081,277 returned the exact raw exchange rate
`200000000000000000000000000` (scaled `200000000.0`). The provider's error hash is
the state root `0x1235ab32b37a553df2f44b445c29c8f2a78643797af9791f1df1e8b0f07dc0f3`;
the canonical block hash is
`0x81c7c1b4feb7b185ea4592be62622b8cc34b70c405247cfadde7c946d6d7401d`.
The initial replay incorrectly compared the state root with the canonical hash;
that assertion failure is recorded separately from the successful native replay.
The native acceptance script now includes this case, for 15 sequential checks.

The first formatted-source focused run (`release-full-312`) stopped with 659
passes and two failures before its full phase. Both were stale test monkeypatch
targets exposed by removed unused imports: Aave's Contract reference and the
batch price lookup's RPC object. They now target the defining Contract class and
active `dank_eth` object. The failed run and missing full-phase report remain
explicitly recorded; it is not a completed full-suite result.

The completed `committed-full-312` pytest phase recorded **2,124 passed, two
failed, and 22 skipped**. The failures were the repaired Gearbox cache-path
assertion and Compound archive read. `make` exited 2; the following native phase
did not run, so `native-historical.json` is explicitly missing and the overall
job remains incomplete. Peak cgroup memory was **4,522,295,296 bytes**, with no
OOM. Final acceptance of the repaired source `619e23a2` is recorded separately
above; successful later checks do not relabel this older failed run.
