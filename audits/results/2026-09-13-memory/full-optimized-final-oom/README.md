# Changed full suite with the same locked dependencies

The optimized pricing source `850d7506d554209738cc2c471f82fbb951845d29` also
hit the 8 GiB container limit. It used the same Python 3.12 image, direct NUC
Reth, command, and limits as the original PR comparison, with a separate database.
Docker recorded `OOMKilled: true`; cgroup counters record one OOM and one OOM kill.
The command exited 2 after 1,479.03 seconds. No final pytest summary exists.
This validation is incomplete.

The archive preflight passed and all ten configured modules loaded as native
extensions. Pytest collected 1,833 cases and recorded 422 terminal outcomes:
290 passed, 123 failed, and 9 skipped. The last Popsicle teardown had peak process
RSS of 8,456,155,136 bytes and 11,752 live tasks. Both full runs exceeded the
memory limit in this group. A separate allocation probe and native bytecode
regression identify a compiler ownership defect; these OOM records alone do not.

The additional Gearbox failure expected a DAI price of exactly one dollar at
block 16,980,000. The canonical historical feed returns 0.9997. The reference
record preserves the block hash, feed address, raw answer, and calculated value.
The revised test must retain the original diesel exchange ratio and the current
historical USD pricing behavior. Its validation follows separately.

The partial failures also contain different timeout case IDs in both directions.
Do not treat the two failure sets as equal. `full-suite-comparison.json` confirms
identical dependency records but rejects a complete comparison because both
pytest summaries are missing. The comparison tool now reports these two facts
independently; its regression test passes.

One brief historical-feed query ran inside the changed container. Use separate
controlled workloads for timing claims. The complete private report preserves
phase records and bounded console output. No console output expired.
