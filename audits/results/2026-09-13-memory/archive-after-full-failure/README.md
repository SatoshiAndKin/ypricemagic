# Archive startup after the descriptor failure

Two contained archive probes time out on direct NUC Reth at the USDC decimals
call for block 16,830,000. Chain ID and the historical header return. Each state
request has the unchanged 30-second deadline. Earlier successful probes remain
separate evidence; these new failures do not erase them or identify the node's
failure mechanism. Geth is not used as an archive control here.

The first probe prevents the pre-optimization full suite from starting. That
execution lasts 31.89 seconds and remains incomplete, with no test collection or
compiled-module report. The cached Sushi comparison then cannot finish its
archive-dependent module startup. A second valid probe fails at the same state
call, so the owned scaling runner is stopped and its partial evidence is saved.
It has no scaling result and remains incomplete. The native, public-pricing,
and audit queue stops before starting those checks.

The first diagnostic probe used a missing report subdirectory and could not
write its result. That invalid attempt is disclosed in the attempt note. The
corrected repeat creates the directory first and preserves the actual timeout.

The scaling startup census records 22 descriptors in the import process,
including four sockets. Its soft/hard descriptor limits are 1,024/524,288. This
is separate from the earlier full process, whose final descriptor count was
not measured. Selected resource limits remain unchanged.
