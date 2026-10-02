# Read-only code-presence probe

The amount-pricing state loader checks every candidate pool's historical code.
`eth_getCode` batches still charge one provider request per pool. This helper
returns the same presence bits with `EXTCODESIZE` in one `eth_call`.

The RPC overrides only the helper account's code for that call. It does not
execute or modify any inspected account, send a transaction, or deploy anything.
The call uses the quote's exact block hash and `requireCanonical: true`. Paris
bytecode supports blocks before Shanghai. If a provider explicitly rejects state
overrides, the loader uses ordinary native code reads instead. Other failures
propagate; malformed output cannot become an unavailable-price result.

Reproduce the embedded runtime and validate it from this directory:

```sh
forge fmt --check
forge build
forge test
forge snapshot --check
forge inspect CodeProbe deployedBytecode
```

Compiler: Solidity 0.8.26, optimizer 200, Paris EVM, CBOR and bytecode metadata
hash disabled. `CodeProbe.t.sol` compares returned bits with native code length,
including zero, a deployed contract, a precompile, duplicate addresses, empty
input, malformed input, and 256 fuzz cases.
