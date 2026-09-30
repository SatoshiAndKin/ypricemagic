# Popsicle allocation diagnostic

This isolated group kept all 19 tests, including the 18 tokens with 25 historical
blocks each. It used the locked Python 3.12 dependency image and direct NUC Reth.
The command completed with 18 failures and one pass. All ten configured pricing
modules loaded as native extensions. Container peak memory was 7,922,294,784 bytes;
no OOM occurred, but the run exceeded the 7 GiB target.

Python retained allocations grew from 241,310,697 bytes at collection to
6,788,727,784 bytes at session finish. The largest source accounted for
6,656,235,307 bytes at Web3's synchronous middleware call boundary. That location
calls native Brownie middleware; it does not establish that Web3 owns the leak.
The separate bytecode regression shows retained intermediate buffers from
Brownie's compiled scanner. Upstream mypy PR 21469 corrects the compiler's
ownership declaration. No pending database writes appeared in the final census.

All 18 pricing tests failed before completing their historical prices because
`a_sync.TaskMapping` passed both a positional key and a constant `token` keyword.
Its retry then used the wrapper's signature and leaked its internal recursion
keyword. Repair and validate this in a-sync. Keep the test cases and concurrency.

Profiler overhead is present. These numbers are diagnostic allocations, not
unprofiled performance results. Complete phase records and bounded console logs
remain in the private report; no console output expired.
