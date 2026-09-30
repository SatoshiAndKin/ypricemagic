# Pinned pool ownership and scheduler matrix

The application installs both owning repairs from committed Git revisions.
Each Python version uses an ordinary dependency image built from the version
lockfile. The before/after application type checks share byte-identical runtime
dependencies and use separate source workspaces and databases.

| Python | Application passes | Owner passes | Container peak bytes | Command seconds |
| --- | ---: | ---: | ---: | ---: |
| 3.12 | 278 | 47 | 1,166,749,696 | 174.93 |
| 3.11 | 278 | 47 | 1,158,004,736 | 182.01 |
| 3.13 | 278 | 47 | 1,197,735,936 | 175.07 |

All ten configured application mypyc modules load compiled extensions on each
version. The native property, cached-property, and smart-future modules also
load `.so` files. The archive probes and exact runtime cache/factory assertions
pass. Source proof checks both installed Git revisions and the cooperative
plugin source hash. The scheduler retains its configured concurrency.

No application type diagnostic is added. The configured type checks still fail
with existing diagnostics; matrix.json records each version and every removed
message. The owner configured type checks also retain their existing errors.
All builds and tests stay inside the selected 8 GiB/no-swap/four-CPU limits, and
all containers record no OOM. Console retention and final cgroup data remain
separate from structured pytest and type reports.

The original full owner suite keeps 15 baseline assertion failures; see the
[747-case comparison](../property-ownership/owner-full-comparison.json). The
application full-suite, native quote, public pricing, and audit gates remain
separate. These focused checks do not make the draft PR ready for merge.
