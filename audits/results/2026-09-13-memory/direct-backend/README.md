# Direct Geth control

The requested direct check reached Geth on Lambo port 8545. Geth returned USDC
decimals `6` at `latest` and reported `eth_syncing: false`. Calls by number and
canonical hash at blocks 16,830,000 and 18,000,000 returned JSON-RPC error
`-32000`, stating that the requested historical state is not available.

This result is expected for this Geth backend. It does not test the archive
route or explain the proxy timeout. The user confirmed that the proxy splits
archive requests between its two Reth backends. The local deployment config
labels both Reths as archive nodes and gives Geth a 128-block limit. Subsequent
validation must use the Reth results.

The standard probe failed. The broader diagnostic completed its attempts and
recorded the RPC errors; its process exit code 0 does not mean archive access
passed. These records remain as an expected non-archive control, separate from
archive validation. No endpoint setting or production code changed.
