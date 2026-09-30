# Native quote control with an incomplete process exit

All six recorded checks pass: V2, V3, Curve, ERC4626 sDAI, and two historical
Curve int128 getter cases. The report preserves the exact block hash, amounts,
and contract addresses. All ten compiled application extensions load.

Execution remains incomplete. After the final result, the old application waits
for its idle aiosqlite worker during interpreter shutdown. The registered stack
diagnostic confirms both frames. The supervisor then stops the owned process
and records interruption, exit status 143, and no OOM. The final state and
failure record remain separate from the six successful quote checks.

The changed native run and reviewed native cases still need completion after
the historical allocation repair.
