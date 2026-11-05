# Repository instructions

- Use Conventional Commits titles and messages. In PR descriptions, state the change
  and relevant validation.
- Use the repository's formatter, linter, dependency locks, and configured test runner.
  Keep mypy configuration in `pyproject.toml` and pytest settings in its owning config;
  workflows and hooks invoke those configured checks.
- When code is compiled with mypyc, run tests against the compiled extensions and report
  how that runtime was confirmed.

## Price lookups and tests

- For async RPC/price-fetch changes, retain `y._decorators.stuck_coro_debugger` so the
  `y.stuck?` DEBUG logger reports long-running calls at its five-minute interval.
  Keep related documentation consistent.
- Use Python 3.12 and
  `PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test`.
  Record baseline failures and compare the affected tests after the change; do not
  treat test execution alone as a pass or expand a documentation task into test repair.
- After a local `pip install .`, inspect generated `build/` output and remove only
  untracked artifacts owned by the task before closing its worktree.
- Target `SatoshiAndKin/ypricemagic` when opening PRs.
