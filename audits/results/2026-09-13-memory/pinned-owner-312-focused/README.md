# Integration built from the published repair commits

All 246 focused tests pass at `9d32c001094b8b7c640a1377e4c0342cd81084a0` with the source-pinned Python
3.12 Linux ARM64 dependency image `sha256:27ffa2884a5bf1a6538184ec79af495dc0d45839a5b20317e2526bdc5e7be46b`. All ten configured pricing
modules load as compiled extensions. Direct NUC Reth passes both archive blocks
by number and canonical hash. No OOM event occurs.

The exact compiler, Brownie, and a-sync VCS revisions appear in the installed
manifests. Native Brownie and a-sync wheels build through the ordinary isolated
package build. Brownie uses the repaired compiler to generate its C extension.
The compiler distribution itself is Python source; this does not change the
native status of its compiled application and Brownie outputs.

BuildKit peak: 3,309,588,480 bytes. Test-container peak:
1167736832 bytes. The container command takes
269.252 seconds, including the editable pricing build and cold
real-node Gearbox request. This is a correctness check, not a controlled timing
comparison. BuildKit stops before the tests start.

This image is the common dependency input for the next baseline and changed
Python 3.12 validation runs. Python 3.11 and 3.13 integration, complete pricing
suites, native quote comparisons, the mainnet audit, and fixed-block public
pricing measurements remain separate gates.
