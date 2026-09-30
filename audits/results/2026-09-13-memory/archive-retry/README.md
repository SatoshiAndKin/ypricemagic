# Archive RPC retry

The archive check still fails after the requested retry. All calls use the same
private endpoint as the earlier checks. No endpoint, dependency, or resource
limit changed. The tested source is
`850d7506d554209738cc2c471f82fbb951845d29`; the Python 3.12 image is
`sha256:4ccb5b8063f29ecbd755ac2760da6364ee81d9f630af1a1f855ecfb83e34ae1b`.

The standard Docker probe again returned the chain ID and block 16,830,000 header,
then timed out after 30 seconds on USDC `decimals()` by canonical block hash.
Its process and reports completed, but `rpc-probe.json` has `complete: false`.
This is a failed archive check.

A separate diagnostic used a 90-second client timeout. The endpoint identifies
itself as `ski_web3_proxy/v2.0.0`. It returned HTTP 408 for historical calls after
60 seconds, before the client timeout. The host comparison uses two small
standard-library HTTP requests. It performs no project import, build, or test
on the Mac.

| Origin | Request | Result | Seconds |
|---|---|---|---:|
| Docker | USDC decimals at latest | 6 | 0.024 |
| Docker | Header at 16,830,000 | Returned | 14.043 |
| Docker | USDC decimals by number, 16,830,000 | HTTP 408 | 60.028 |
| Docker | USDC decimals by canonical hash, 16,830,000 | HTTP 408 | 60.033 |
| Docker | Header at 18,000,000 | HTTP 408 | 60.027 |
| Docker | USDC decimals by number, 18,000,000 | HTTP 408 | 60.025 |
| Mac | USDC decimals at latest | 6 | 0.045 |
| Mac | USDC decimals by canonical hash, 16,830,000 | HTTP 408 | 60.026 |

The block-hash request at 18,000,000 did not run because its header failed.
The diagnostic's exit code 0 and `complete: true` mean that it recorded all
attempts; they do not mean that historical RPC calls passed.

All calls target USDC `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` with
calldata `0x313ce567`. Block 16,830,000 uses hash
`0x6e65cf41a9208837f764d22dd0358f7d67f57cd71ec5ee975d98674e292322bd`
and `requireCanonical: true`.

The first diagnostic command had a string-escaping syntax error and made no RPC
calls. Its reports remain separate in `archive-recovery-diagnostic`; execution
is incomplete because its required report is missing. The corrected command is
in `archive-recovery-diagnostic-2`. The maximum container peak across all three
attempts was 141,176,832 bytes. No cgroup OOM event or Docker OOM kill occurred.
No console output expired.

These results exclude a Docker-only network failure. They do not identify which
proxy or backend component caused HTTP 408. The final application matrix, full
suites, scaling, native quotes, public pricing, and audit remain pending. PR 43
stays draft. The prior independent build, type-comparison, dependency, and
containment results remain unchanged.
