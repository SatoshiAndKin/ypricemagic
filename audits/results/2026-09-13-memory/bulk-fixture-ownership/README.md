# Bulk fixture ownership

The historical bulk-price tests now close the price and deployment mappings in
`finally`. They retain their token lists, block-selection rules, assertions,
600-second deadline, and test concurrency.

Four controlled cases exercise the actual fixture functions and task mapping.
Before cleanup, a child failure leaves two sibling requests active; caller
cancellation leaves all three requests active. Both price and deployment phases
fail these release assertions. The changed fixture cancels every owned request
and preserves the original failure object or caller cancellation.

| Python | Passed | Container peak bytes | Elapsed seconds |
| --- | ---: | ---: | ---: |
| control | 247 | 1,172,873,216 | 289.43 |
| 312-focused | 251 | 1,162,887,168 | 255.77 |
| 311-focused | 251 | 1,127,145,472 | 257.59 |
| 313-focused | 251 | 1,166,450,688 | 290.16 |

The control has four expected failures; each changed focused run has 251 passes.
Every run checks all ten configured compiled application modules and passes the
historical archive probe. All have zero OOM events. These are correctness checks,
not repeated performance measurements. The full-suite result remains separate.

The first type check exposed missing helper annotations. Subsequent checks use
explicit address/result types and the established dynamic ez-a-sync call
boundary. Initial and final diagnostics remain separate. Final comparisons use
the same dependency image per version and report added and removed diagnostics;
no passing type check is claimed while existing errors remain.
All three final configured checks report 1,935 errors, compared with 1,959
before optimization. The rendered comparisons show 24 removed diagnostics and
no added diagnostics. They preserve both the CLI totals and rendered counts.

The control and focused runs record development source archives. Later type-only
edits retain the same cleanup behavior. The final full suite uses a committed
source revision. Public evidence replaces private environment values and omits
ordinary console output. Raw mypy output retains its original whitespace.

During these checks, host disk pressure prevented a script write. Five completed
rotation-test logs now use verified, lossless gzip archives; their byte counts
and content hashes remain recorded. Eight unused, superseded development images
were removed after their identities were saved. Current and matched comparison
images remain available. No Colima profile was removed or restarted.
