// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// Synthetic ERC-20 used only in the local experiment. Minted entirely to the
/// deploying (host) account; carries no value outside the in-process chain.
contract ExperimentalToken is ERC20 {
    constructor(uint256 supply) ERC20("Experimental Token", "XEXP") {
        _mint(msg.sender, supply);
    }
}
