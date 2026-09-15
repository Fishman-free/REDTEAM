// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
contract ExperimentalToken is ERC20 {
    constructor(uint256 supply) ERC20("Experimental Token", "XEXP") { _mint(msg.sender, supply); }
}
