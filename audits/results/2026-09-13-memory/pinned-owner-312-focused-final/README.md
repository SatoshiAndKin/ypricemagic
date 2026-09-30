# Final Python 3.12 focused checks

All 246 focused tests pass after the explicit Gearbox non-null assertion and
Popsicle cleanup change. All ten configured pricing extensions load. The archive
preflight passes. This run reuses the published source-pin image from the earlier
build and tests the exact worktree archive recorded in `run.json`.

The command completes in 279.168 seconds. Container peak is 1,166,548,992 bytes,
with no OOM event. The separate historical cleanup run preserves 19 outcomes
and releases its test-owned mapped tasks. The configured type comparison adds
no rendered error. Complete full suites and real-node gates remain pending.
