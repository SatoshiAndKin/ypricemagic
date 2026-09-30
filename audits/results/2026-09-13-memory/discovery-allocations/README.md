# Historical discovery allocation diagnosis

The 19-case Popsicle profile finishes with 10 passes, two zero-supply division
errors, and seven configured 600-second timeouts. It records all ten compiled
extensions, successful archive probes, and no OOM. Container peak memory is
6,399,762,432 bytes. Allocation profiling adds overhead; these measurements are
not timing comparisons or proof of final memory performance.

The early samples retain about 200 MB of Python allocations. Later samples
first grow in decoded raw log data, then in processed pool objects and pending
database insert tasks. Sample 16 counts 194,927 UniswapV2Pool objects, 54,457
asyncio tasks, and 393 pending Filter.__insert_chunk tasks. Its raw log allocation
sites account for about 449 MB. The listed executor queues are empty, which does
not mean that the pending coroutine chain is empty.

The loader starts all historical chunk coroutines and allows the completed
fetch results and ordered database insert tasks to accumulate while processing
continues. A controlled backlog regression and the combined Magic/Popsicle
profile will test the repair. No full-suite memory success is claimed.
