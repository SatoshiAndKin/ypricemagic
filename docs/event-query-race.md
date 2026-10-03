# Concurrent event query construction

A complete native pricing run exposed a `KeyError` in Pony's
`Query._get_translator`: two event-page builders can read the same translator,
then both invalidate it when a fixed topic attribute changes. The second
unconditional dictionary deletion fails. The unmodified event-page builder on
current master reproduces this behavior with a deterministic two-thread test
using Pony's actual translator invalidation method.

Serialize only event-page query construction. Database reads and log decoding
remain outside the lock, with unchanged ordering, pagination, ranges and limits.
The regression fails before this repair and passes afterward. All 39 event
query/log-cache regressions pass against the native pricing environment. Strict
mypy passes all 246 files. The complete migration suite is rerun separately.
