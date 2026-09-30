# Pricing integration with repaired native dependencies

All 246 focused tests pass in Linux ARM64 Python 3.12 with the repaired native
Brownie and a-sync distributions. All ten configured pricing modules load as
compiled extensions. The canonical archive probe passes through direct NUC Reth.
There is no OOM event. Container peak: 1139773440 bytes.

The Gearbox check preserves the original diesel exchange ratio and verifies the
historical DAI/USD value of 0.9997 at block 16,980,000, including its returned path.
The suite also covers request-owned logger cleanup, failed/cancelled work, cache
release and reuse, independent paths, database shutdown, and the existing quote
regressions. Its cold real-node Gearbox setup makes this a correctness run, not
a controlled performance comparison.

The dependency image was built from the exact owning source archives before their
commits. The owner reports map those archives to the published compiler, Brownie,
and a-sync repairs. Actual installed manifests and the image's original manifest
remain separate. The final revision-pinned builds and Python 3.11–3.13 matrix still
need to run. The Popsicle allocation probe and full-suite comparisons are separate
gates; this focused pass does not complete them.
