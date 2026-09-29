# PR 43 zero-failure follow-up

This follow-up addresses the remaining full-suite and static-check failures.
Validation is still running; this report does not declare the branch ready.

The earlier 68-case investigation, timeout experiments, audit OOM, and interrupted
supervisor reports remain in the dated directories beside this one. A later
successful run does not change their outcomes.

## Repairs and regression coverage

- [x] Retry only the exact `-32000 historical state <64-hex hash> is not available`
  archive response, preserving the same canonical block identifier on every call.
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

## Reviewed-source checks

The focused matrix passed **661 tests on each of Python 3.11, 3.12, and 3.13**,
with zero strict-mypy diagnostics and all ten compiled extension paths verified.
The final cache-order preservation, Mooniswap stuck-call decorator, and native
Inverse assertion are included in commit `0771c206`; committed-source validation
is running separately. The matrix reports retain their own source/archive hashes.

The original-source helper control (`typed-negative2-312`) completed with
**16 expected failures and seven passes**. It restores seven modules' original
helper implementations while retaining byte-identical current regression files.
The Ellipsis counterexample is precisely **1.234567 versus 1,234,567 native units**.
The overlay manifest records restored functions, source hashes, and assertion-file
hashes. The earlier control is retained separately; its Ellipsis fixture did not
provide the old scale lookup and was strengthened before repeating the control.

## Final acceptance gates

- [ ] Python 3.11 focused suite, strict mypy, and ten compiled extensions.
- [x] Python 3.12 committed-source focused suite: 661 passed, strict mypy clean,
  and ten compiled extensions. The full phase of `committed-full-312` is active.
- [ ] Python 3.13 focused suite, strict mypy, and ten compiled extensions.
- [ ] Fourteen sequential historical native checks on the repaired source.
- [ ] Required Python 3.12 full command, with every test passing or intentionally skipped:
  `PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test`.
- [ ] Configured formatting and scoped diff review.
- [ ] Commit, push, committed-source focused recheck, and green GitHub checks.
- [ ] Update PR Summary, Rationale, and Details; verify remote alignment.
- [ ] Verify the preserved generated C SHA256:
  `099f4992d9c8404dc31bc761d0fcfb5aeef32cd9f582688dc1b9f73646104506`.

Each attempt in [validation-summary.json](validation-summary.json) records its
immutable source/archive identity, exact exit status, memory peak, elapsed time,
missing reports, and test/static-check completeness. Failed test tracebacks and
complete mypy output are retained per attempt. All jobs use 8 GiB RAM, no swap,
four CPUs, and 512 processes/threads, with one heavy job per Docker profile.
The configured 3,600-second pytest deadlines remain unchanged.
