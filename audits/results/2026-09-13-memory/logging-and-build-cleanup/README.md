# Logger and build cleanup

The same frozen 247-case workload fails one logging-handler case at
`c1f19e21ca7104eef9e8704ca5bd28c6dd35c5a2`. Moving the first price log inside
the existing cleanup block passes all 247 cases on Python 3.11, 3.12, and 3.13.
Each run checks all ten configured mypyc modules and the historical archive
probe. The source archive and test input hashes identify each worktree run.

| Python | Passed | Container peak bytes | Elapsed seconds |
| --- | ---: | ---: | ---: |
| 3.12 control | 246; 1 expected failure | 1,209,122,816 | 283.90 |
| 3.12 changed | 247 | 1,178,685,440 | 267.10 |
| 3.11 changed | 247 | 1,176,051,712 | 267.93 |
| 3.13 changed | 247 | 1,236,860,928 | 280.47 |

These are correctness checks, not repeated performance measurements. All runs
have zero OOM events. Each version uses its recorded frozen dependency image.

The initial type runs found a new duplicate annotation in the build supervisor.
The final runs include its repair. All three configured checks report 1,940
existing errors, compared with 1,959 at the pre-optimization revision. The
rendered diagnostic comparisons show 19 removed errors and no added errors.
The CLI totals exceed the rendered header totals by five on both revisions;
the comparisons retain both counts. The type checks still fail overall.

The real BuildKit fixture interrupts a small sleeping build with SIGTERM.
It preserves the available final state and cgroup counters, records no build
exit code, and stops the builder. Its peak is 105,734,144 bytes with zero OOM
events. The effective limits are 8 GiB memory, 8 GiB memory plus swap, four CPUs,
and 512 processes or threads. The interruption remains incomplete build
validation; the fixture's verification succeeds. Five standard-library runner
tests also pass, including six build failure scenarios.

Private console logs retain their recorded rotation limits. These public
reports omit ordinary console output and replace private environment values.
