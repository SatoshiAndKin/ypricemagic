# Published dependency matrix on Python 3.11 and 3.13

Both Linux ARM64 versions pass all 246 focused tests at pricing source
`ffb225a80b4b3584be1d88619b17daa6cedea5af`. Each imports all ten configured pricing
modules as compiled extensions and passes the direct NUC Reth archive preflight.
The ordinary isolated builds use the published compiler, Brownie, and a-sync
source pins. No build or test OOM event occurs.

| Python | BuildKit peak bytes | Test peak bytes | Focused passes |
| --- | ---: | ---: | ---: |
| 3.11 | 3,451,871,232 | 1,148,137,472 | 246 |
| 3.13 | 2,203,672,576 | 1,210,519,552 | 246 |

Configured `python -m mypy` reports 1,959 errors before optimization and 1,940
after it on both versions. The runtime dependency manifests match within each
comparison. No rendered diagnostic is added. The raw output and normalized
comparisons remain separate from the passing pytest reports. No type-check pass
is claimed. All build and test peaks remain below the 7 GiB target.

The separate Python 3.12 source-pin checks also pass 246 cases. The later
logging-handler cleanup regression was added after these frozen source runs;
it requires its own validation. Full suites and the real-node audit/native/public
pricing gates remain separate work.
