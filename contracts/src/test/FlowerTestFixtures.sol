// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../ContributionFlower.sol";
import "@openzeppelin/contracts/token/ERC721/IERC721Receiver.sol";

/// @dev Test-only entry points prove that the bottom ERC721 hook is fail-closed.
contract FlowerHarness is ContributionFlower {
    constructor(address initialOwner, address initialIssuer) ContributionFlower(initialOwner, initialIssuer) {}

    function exposedBurn(uint256 tokenId) external {
        _burn(tokenId);
    }

    function exposedTransfer(address to, uint256 tokenId, address auth) external {
        _update(to, tokenId, auth);
    }

    function exposedMint(address to, uint256 tokenId) external {
        _mint(to, tokenId);
    }

    function injectApproval(address operator, uint256 tokenId) external {
        _approve(operator, tokenId, address(0));
    }

    function injectOperator(address holder, address operator) external {
        _setApprovalForAll(holder, operator, true);
    }
}

/// @dev Deliberately accepts ERC1271 signatures and would reenter if called.
/// Production must reject it as a recipient regardless of those interfaces.
contract FlowerMaliciousReceiver is IERC721Receiver {
    ContributionFlower public immutable flower;
    bool public callbackCalled;

    constructor(ContributionFlower flower_) {
        flower = flower_;
    }

    function attemptMint(ContributionFlower.Consent calldata consent, bytes calldata signature) external {
        flower.mint(consent, signature);
    }

    function isValidSignature(bytes32, bytes calldata) external pure returns (bytes4) {
        return 0x1626ba7e;
    }

    function onERC721Received(address, address, uint256 tokenId, bytes calldata) external returns (bytes4) {
        callbackCalled = true;
        flower.revoke(tokenId);
        return IERC721Receiver.onERC721Received.selector;
    }
}
