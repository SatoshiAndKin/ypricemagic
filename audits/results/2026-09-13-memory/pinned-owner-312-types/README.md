# Configured types with the published dependency pins

Both checks execute `python -m mypy` with each source revision's central
`pyproject.toml` configuration and the same Python 3.12 dependency image. The
installed dependency manifests match. Both executions complete and exit 1.

The pre-optimization source reports 1,959 errors; the changed source reports
1,940. The complete output contains 1,954 and 1,935 rendered diagnostic headers,
respectively. The comparison preserves both counts. No rendered diagnostic is
added. Nineteen logger-related diagnostics disappear. No type-check pass is
claimed.

The first changed run exposed one new nullable-result error in the Gearbox test.
The final test asserts a non-null result before checking the exact historical
price and child path. This fixes the type error without weakening the checks.
The Popsicle task cleanup and profiler add no rendered type diagnostic.

Python 3.11 and 3.13 checks remain separate gates.
