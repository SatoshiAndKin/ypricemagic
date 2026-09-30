# Historical pricing repair validation

Pricing repair commit: `17c08dda9796994ea755699032975dc4b91fd06e`. The subsequent bot commit changes generated C files only. The frozen focused matrix passed 613 tests on each of Python 3.11, 3.12 and 3.13; the committed-source recheck also passed 613. All ten compiled extensions were verified. Fourteen protocol-native checks and nine additional fixed-block public-price checks passed.

The final full workload recorded 2,059 passes, 23 provider-state failures and 22 skips, with no assertion failures, timeouts or OOM. The provider-affected pytest recheck recorded 29 passes and nine provider-state failures; those nine prices subsequently passed native calls at their exact failed canonical blocks. These failed pytest runs remain failures. PR 43 remains draft with full-suite RPC and baseline mypy validation gaps.

Every row is a separate immutable source snapshot. A completed command is not necessarily a passing or complete test run. Negative controls use original production source with the documented regression-test/configuration overlay.

The original 68-failure run, older deadline experiments, master diagnostic, and audit OOM remain in `../2026-09-26-mergeability/`; they are not merged into these results.

| Attempt | Passed / failed / skipped | Test report complete | Interrupted | Peak GiB |
| --- | ---: | --- | --- | ---: |
| [before-312](before-312/run.json) | 0 / 20 / 0 | True | False | 1.084 |
| [committed-312](committed-312/run.json) | 613 / 0 / 0 | True | False | 1.089 |
| [complete-regressions-before-312](complete-regressions-before-312/run.json) | 9 / 61 / 0 | True | False | 1.085 |
| [expanded-after-312](expanded-after-312/run.json) | 45 / 0 / 0 | True | False | 1.085 |
| [expanded-before-312](expanded-before-312/run.json) | 3 / 4 / 0 | False | False | 1.092 |
| [expanded-before-retry-312](expanded-before-retry-312/run.json) | 4 / 39 / 0 | True | False | 1.093 |
| [final-regressions-before-312](final-regressions-before-312/run.json) | 9 / 58 / 0 | True | False | 1.085 |
| [first-312](first-312/run.json) | 563 / 0 / 0 | True | False | 1.095 |
| [full-312](full-312/run.json) | missing summary | False | True | 3.298 |
| [full-complete-312](full-complete-312/run.json) | 2055 / 23 / 22 | True | False | 4.153 |
| [full-final-312](full-final-312/run.json) | missing summary | False | True | 1.098 |
| [full-guarded-312](full-guarded-312/run.json) | 2008 / 65 / 22 | True | False | 4.091 |
| [full-latest-312](full-latest-312/run.json) | 2059 / 23 / 22 | True | False | 4.215 |
| [full-repaired-312](full-repaired-312/run.json) | 64 / 1 / 0 | True | False | 1.094 |
| [late-complete-312](late-complete-312/run.json) | 613 / 0 / 0 | True | False | 3.087 |
| [latest-matrix-311](latest-matrix-311/run.json) | 613 / 0 / 0 | True | False | 1.047 |
| [latest-matrix-313](latest-matrix-313/run.json) | 613 / 0 / 0 | True | False | 1.080 |
| [latest-negative-312](latest-negative-312/run.json) | 9 / 65 / 0 | True | False | 1.083 |
| [matrix-311](matrix-311/run.json) | missing summary | False | True | 1.040 |
| [matrix-complete-311](matrix-complete-311/run.json) | 609 / 0 / 0 | True | False | 1.039 |
| [matrix-complete-313](matrix-complete-313/run.json) | 609 / 0 / 0 | True | False | 1.083 |
| [matrix-final-311](matrix-final-311/run.json) | 604 / 0 / 0 | True | False | 1.041 |
| [matrix-final-312](matrix-final-312/run.json) | 606 / 0 / 0 | True | False | 1.096 |
| [matrix-final-313](matrix-final-313/run.json) | 604 / 0 / 0 | True | False | 1.090 |
| [matrix-repaired-311](matrix-repaired-311/run.json) | 603 / 1 / 0 | True | False | 1.047 |
| [native-provider-312](native-provider-312/run.json) | native 9 / 0 | n/a - native report | False | 3.102 |
| [provider-recheck-312](provider-recheck-312/run.json) | 29 / 9 / 0 | True | False | 3.389 |

Native-only commands have their own complete result report and do not request a pytest summary. The native pass/failure counts and completeness are also recorded in validation-summary.json.

Exact source/archive hashes, byte-level memory peaks, exit codes, and missing reports are recorded in [validation-summary.json](validation-summary.json). Each directory retains pytest events, compiled-extension verification, resource limits, and publication hashes. Full console logs and complete mypy output remain in the corresponding local `/private/tmp/yprice-repairs/` report; published mypy comparisons retain every changed diagnostic.

`full-repaired-312` stopped at its failing regression guard before the full-suite command ran. `expanded-before-312` encountered a pytest internal error and did not complete its tests. Manually stopped snapshots have a `diagnostic-stop.json`; they are explicitly incomplete even if a supervisor completed its shutdown reporting.

The host supervisor for `full-latest-312` did not finish reporting. Its exited container retained a complete pytest summary and command report; these were recovered intact. `run.json` keeps host completion false and records workload completion separately in `recovery.json`.

The latest focused runs retain 1,772 mypy diagnostics versus 1,788 in the baseline. The sole added diagnostic text replaces the existing Gelato decorator inference error after its return annotation gained `None`; the raw added/removed messages are retained. This is not a clean mypy result.

Native evidence includes canonical block hashes, integer quote outputs, historical oracle denominations, the BAND pool revert, wrapped-USDT inputs, and same-request replays of all eleven original provider-state failures in [native-diagnosis](native-diagnosis/).

All jobs use 8 GiB RAM, no swap, four CPUs, and 512 processes/threads, with one heavy job per Docker profile. The 3,600-second pytest and cooperative-task deadlines are unchanged.
