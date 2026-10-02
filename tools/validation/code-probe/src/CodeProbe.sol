// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

// Installed only via eth_call's temporary code override. No calls or writes.
contract CodeProbe {
    fallback() external {
        assembly {
            let length := calldatasize()
            if mod(length, 32) { revert(0, 0) }
            for { let offset := 0 } lt(offset, length) { offset := add(offset, 32) } {
                mstore(offset, iszero(iszero(extcodesize(calldataload(offset)))))
            }
            return(0, length)
        }
    }
}
