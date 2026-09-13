# Direct Reth comparison

NUC Reth serves the required archive state. The same historical USDC calls
succeed directly through NUC Reth while Lambo Reth calls time out. The proxy
still returns HTTP 408. These results identify a working validation endpoint;
they do not establish the cause of Lambo's delay or the proxy's failure to
complete these requests.

The user confirmed that archive requests are split between the Reths. The local
deployment config maps Lambo Reth to port 8547 and NUC Reth to port 8545, with
both marked `archive`. Lambo Geth uses port 8545 with a 128-block limit. Its
expected historical-state error is a separate non-archive control, not evidence
about the archive route. The proxy's live status lists both Reths as connected.

The test used one Docker job with the unchanged 8 GiB, no-swap, 4-CPU, 512-task
limits. It sent identical USDC `decimals()` requests from the same container.
Both Reths returned client version `reth/v2.5.1-6dec1b9` and `eth_syncing: false`.

| Request | Lambo Reth | NUC Reth | Proxy |
|---|---|---|---|
| `latest` | Client timeout at 75 s | 6 in 10 ms | Not repeated |
| 16,830,000 by number | Client timeout at 75 s | 6 in 13 ms | Not repeated |
| 16,830,000 by canonical hash | Client timeout at 75 s | 6 in 13 ms | HTTP 408 at 60 s |
| 18,000,000 by number | Client timeout at 75 s | 6 in 11 ms | Not repeated |
| 18,000,000 by canonical hash | Not run: header timed out | 6 in 11 ms | HTTP 408 at 60 s |

Lambo returned the 16,830,000 header in 23 ms; its 18,000,000 header timed out.
NUC returned both headers. A separate two-request host check also returned the
16,830,000 canonical-hash result through NUC Reth in 21 ms. It used only the
standard library and ran no project imports or tests on the Mac.

The diagnostic completed all planned attempts. Its exit code 0 means that it
recorded the outcomes, including the timeouts. It does not mean every backend
passed. The separate rpc-tune profile had no running container during this
check. NUC Reth now supplies the private validation configuration for the final
focused matrix and sequential comparisons. Source, dependencies, concurrency,
and container limits remain fixed for those comparisons.
