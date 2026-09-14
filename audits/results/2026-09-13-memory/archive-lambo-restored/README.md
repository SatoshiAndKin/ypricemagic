# Direct Lambo Reth archive access

The new host retries return USDC decimals 6 from Lambo Reth at block 16,830,000
by number and canonical hash. The same direct NUC Reth calls reach the
30-second timeout. Both observations remain in [host retries](host-retries.json).

The contained [archive probe](docker/rpc-probe.json) then passes USDC calls at
blocks 16,830,000 and 18,000,000, including canonical hash selection. It exits
zero with no OOM. Subsequent validation uses this direct Lambo Reth endpoint.
The endpoint and credentials remain private.

This supersedes the earlier backend availability observation. It does not
diagnose the proxy or prove that every historical pricing request will succeed.
