# Repaired requester dependency matrix

The application pins dank-mids native artifact commit
`9a58cd91b4a652ac10d41cc5862c7b2770727632`. Its parent source repair passes all
150 owning dependency tests in each of 12 native CI jobs. Each local version
builds one fixed dependency image, then reuses it for both configured type checks.
Every run has its own source directory and database.

| Python | Focused passes | Compiled modules | Container peak bytes | Elapsed seconds |
| --- | ---: | ---: | ---: | ---: |
| 312 | 251 | 10 | 1,169,694,720 | 247.19 |
| 311 | 251 | 10 | 1,132,236,800 | 226.68 |
| 313 | 251 | 10 | 1,172,312,064 | 219.23 |

Every completed focused run passes the direct Lambo Reth historical probe,
loads all ten configured ypricemagic extensions, and reports no OOM. BuildKit
stops before tests start. Build and test containers retain the approved 8 GiB,
zero-swap, four-CPU, and 512-process/thread limits. These are correctness checks;
three-sample performance measurements remain separate.

Each complete type comparison reports 1,959 CLI errors before optimization and
1,935 after. The raw diagnostic parser counts 1,954 and 1,930 rendered records;
all raw console output remains available. No rendered diagnostic is added and
24 are removed. The type checks still fail. Complete full suites and real-node
pricing/audit checks remain separate gates.
