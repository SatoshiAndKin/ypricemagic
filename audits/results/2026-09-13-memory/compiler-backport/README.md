# Compatible compiler ownership repair

The [owning compiler backport](https://github.com/SatoshiAndKin/mypy/pull/1)
at `18a37e099bba69872e38adaee3319c125c97048e` applies upstream commit
`db331b44ac2b4ef35b138cd5ecba7731c656ca4c` to mypy 1.19.1. The compiler no longer
declares that byte concatenation consumes its first operand. Generated callers
release intermediate byte buffers correctly.

All 64 reference-count tests pass. Native compiler and Brownie wheels build in
the approved Linux ARM64 Python 3.12 container, with a peak of 6,601,424,896 bytes
and no OOM event. BuildKit stops before the test containers start.

Brownie's caching module loads its `.so` extension. All 33 bytecode checks pass,
including every PUSH1–PUSH32 size, truncated push data, and repeated-scan release.
The unchanged sixteen-scan workload returns the same opcodes. Python memory
after collection falls from 4,467,732 to 3,540 bytes, including the diagnostic's
own records. The old build retains 4,464,096 bytes in intermediate byte buffers;
the repaired build no longer has that allocation group.

Published mypy 2.2.0 and 2.3.1 already contain the upstream fix, but native Brownie
builds made with those releases fail to import a typed dictionary. The compatible
backport keeps the existing Web3 6 and Brownie contract. No scanner algorithm or
application runtime patch was added. The source pin and scanner regressions live
in [Brownie's owning maintenance PR](https://github.com/SatoshiAndKin/brownie/pull/3)
at `c986066ddd9ae10906a470008d786faab2355cc5`.

The first Brownie test invocation reported 33 passes but omitted the requested
JSON summary because the application reporter intentionally excludes nested
pytest roots. That run remains incomplete. The completed repeat preserves pytest's
standard XML report. Compiler tests likewise preserve their explicit result file.
Private bounded build logs retain the rejected compiler attempts separately.

Full pricing suites, the Python 3.11–3.13 integration matrix, and real-node quote
comparisons still need to run with the final dependency pins. This local native
regression does not establish a complete pricing pass or the full-suite RAM target.
