# CLI logging repair

CLI imports now preserve the configured logger level and handlers. Explicit
price debugging enables DEBUG and reuses an available handler. DEBUG-only
`y.stuck?` messages retain their five-minute interval.

The negative control uses the old runtime with only the five new cases and
centralized test target added. Four cases fail there. The repaired source passes
all 283 focused tests on Python 3.11–3.13, with every setup, call, and teardown
recorded. All ten configured compiled extensions load and archive probes pass.

| Run | Passed / failed | Peak bytes | Seconds |
| --- | --- | ---: | ---: |
| cli-logging-before-312 | 279 / 4 | 1283940352 | 190.98 |
| cli-logging-after-312 | 283 / 0 | 1171021824 | 183.57 |
| cli-logging-after-311 | 283 / 0 | 1316106240 | 186.85 |
| cli-logging-after-313 | 283 / 0 | 1358577664 | 178.03 |

The configured mypy checks retain 1,836 existing errors on each Python version,
with no added diagnostics and identical dependencies. No run has an OOM event
or expired console output. These focused checks do not complete the interrupted
full suites or the mainnet audit. Both mainnet audit revisions ended with OOM
and missing JSON/CSV reports. The full-audit memory gate remains unmet.
