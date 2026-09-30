// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title ExperimentalToken
/// @notice Synthetic ERC-20 ("XEXP") used only inside the local experiment to
/// stand in for a payment asset.
/// @dev The entire supply is minted to the deploying host account and there is
/// no mint function afterwards, so the asset cannot be inflated mid-run and
/// carries no value outside the in-process chain. Balances are fully visible to
/// the host, which is what lets the evaluator compare on-chain state before and
/// after a run.
contract ExperimentalToken is ERC20 {
    /// @notice Mints the whole `supply` to the deployer.
    /// @param supply Amount minted to `msg.sender`, in wei-denominated units.
    constructor(uint256 supply) ERC20("Experimental Token", "XEXP") {
        _mint(msg.sender, supply);
    }
}
