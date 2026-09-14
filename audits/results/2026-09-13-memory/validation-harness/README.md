# Fixture registration and timing boundaries

The existing `tests.fixtures` module now registers through `tests/conftest.py`.
All three original Uniswap V1 cases pass setup and teardown. Their unchanged
pricing calls still fail at the configured 600-second deadline. The complete
731.23-second container execution records no OOM. These are fixture-registration
checks; they are not three passing price checks.

The public pricing helper now takes allocation snapshots only in its separate
allocation run. It records elapsed time and peak process memory before the final
snapshot, and it does not force garbage collection. The 99-call workload and
its exact-result assertions remain unchanged. The real-node timing comparison
still needs to run.

Python 3.12 uses the normal pinned dependency image, a fresh database, and the
direct archive route. Both checks load all ten configured compiled modules and
pass the archive probe. Configured mypy reports 1,922 existing errors; its 1,917
rendered diagnostics have no additions or removals. The type-check execution
finishes in 137.34 seconds with no OOM.

[Source and diagnostic comparison](comparison.json) records the common validated
worktree archive and current hashes of the three changed source files. Raw
fixture outcomes, type output, dependencies, commands, limits, final container
state, and log-retention records remain in the two report directories. Copied
text removes trailing whitespace under the recorded normalization manifest.
