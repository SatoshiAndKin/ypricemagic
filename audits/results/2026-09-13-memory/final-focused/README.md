# Final dependency integration

All 244 focused tests pass on Linux ARM64 Python 3.11.16, 3.12.14, and 3.13.15
with the final three dependency pins. Every run imports all ten configured
ypricemagic modules as compiled extensions. `compiled-modules.json` records
the loaded paths; this check tests imports, not artifact presence.

The tests use source `850d7506d554209738cc2c471f82fbb951845d29`, the previously
built exact dependency images, and direct NUC Reth. The archive preflight passes
at both required blocks. Each run has a separate database and uses the unchanged
8 GiB, no-swap, 4-CPU, 512-task container limits. No OOM event occurred.

| Python | Passed | Loaded compiled modules | Container peak, bytes | Total seconds |
|---|---:|---:|---:|---:|
| 3.12.14 | 244 | 10 | 1,232,060,416 | 59.81 |
| 3.11.16 | 244 | 10 | 1,176,903,680 | 63.86 |
| 3.13.15 | 244 | 10 | 1,221,279,744 | 76.06 |

Total time and container peak include the extension build and archive probe.
The full pytest phase records and rotated console logs remain at the private
report paths listed in `matrix.json`. No console output expired.

The first full baseline attempt stopped before collection because its old
Makefile runs pytest without building extensions. The compiled-import check
correctly rejected the interpreted module. That attempt remains incomplete in
`baseline-missing-build`; it is not a pricing or test regression. The shared
full-suite helper now builds each source revision in Docker before invoking the
required `PYTEST_ADDOPTS="-p no:pytest_ethereum" BROWNIE_NETWORK=mainnet make test`
command. The fresh baseline loaded all ten compiled modules and collected
1,752 tests. Complete full-suite and real-node price comparisons remain required.
