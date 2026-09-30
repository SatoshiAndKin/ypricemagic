# Task wrapper ownership

The task mapper's weak-key cache stored each plain callable as its own strong
value. Each entry therefore kept its key and captured state alive. The async
function object already owns its cached modified and async wrappers; the extra
module cache was redundant.

Three unprofiled runs each create 1,000 callables with 65,536 bytes of captured
state. Before repair, all 1,000 callables remain live. After repair, none remain
live. Median process RSS falls from 98,754,560 to 32,763,904 bytes; median elapsed
time falls from 0.008429 to 0.001194 seconds. A separate allocation run changes
retained Python memory from 65,982,172 to 89,600 bytes. No forced collection or
within-workload restart occurs. This probe makes no RPC calls.

The comparison isolates wrapper ownership. It does not measure full pricing or
claim a successful full-suite memory target. Both sides use the repaired native
Brownie compiler image; the changed image adds the owning a-sync source repair.
The dependency image build report records the exact owner source archive.

The first focused owning comparison passes 46 of 58 cases before repair and
57 after repair. The remaining cancellation case exposes a separate defect in
exception-result wrapping. The final expanded tests preserve that assertion and
check caller cancellation as well. Final owning tests and application integration
remain pending.

The actual runtime manifests (`dependencies-after.txt`) show one extra build tool,
Cython 3.2.5, in the changed image. The image's original build manifest predates
that install. A final controlled repeat will include that same tool on both sides.
The shared runner now records the actual installed environment before each command
and retains the image's build manifest separately. The original probe records stay
intact and do not stand in for that final repeat.
