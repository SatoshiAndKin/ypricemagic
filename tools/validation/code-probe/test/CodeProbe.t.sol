// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;
import {CodeProbe} from "../src/CodeProbe.sol";

contract ExistingCode {}

contract CodeProbeTest {
    CodeProbe private probe = new CodeProbe();

    function testOrderedPresenceAndEmptyInput() public {
        ExistingCode deployed = new ExistingCode();
        (bool success, bytes memory output) =
            address(probe).call(abi.encode(address(0), address(deployed), address(1), address(deployed)));
        require(success);
        require(keccak256(output) == keccak256(abi.encode(false, true, false, true)));
        (success, output) = address(probe).call("");
        require(success && output.length == 0);
    }

    function testRejectMalformedInput() public {
        (bool success,) = address(probe).call(hex"01");
        require(!success);
    }

    function testFuzzNativeCodePresence(address target) public {
        (bool success, bytes memory output) = address(probe).call(abi.encode(target));
        require(success);
        require(abi.decode(output, (bool)) == (target.code.length > 0));
    }
}
