# Release test-owned historical tasks

The Popsicle test now closes its own task mapping in a `finally` block. It keeps
all 18 tokens, 25 selected blocks per token, assertions, concurrency, and the
600-second test deadline. The existing dependency `close()` method cancels the
mapping's remaining work when the test finishes, fails, or is cancelled.

All 19 outcomes and teardown complete. The same two tests pass and the same
17 tests reach the configured timeout as in the preceding diagnostic. There
are zero pending mapped price tasks at session finish, compared with 425 before
cleanup. Shared cache-owned tasks remain visible in the census; this change
does not cancel work that other pricing requests can reuse.

The native Linux ARM64 Python 3.12 run uses the published source-pin image and
loads all ten configured application extensions. Archive preflight passes.
Container peak is 1,212,628,992 bytes, with no OOM event. Python allocations at
session finish are 179,208,312 bytes; their peak is 236,649,340 bytes.

These figures describe a profiled correctness run, not controlled performance.
The preceding run used the owner probe image, and historical block selection
uses the current chain height. The matching test outcomes and explicit task
census verify the cleanup. The 17 pricing timeouts remain unresolved.
