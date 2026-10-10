// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/Base64.sol";
import "@openzeppelin/contracts/utils/Strings.sol";
import "@openzeppelin/contracts/utils/introspection/IERC165.sol";

interface IERC5192 is IERC165 {
    event Locked(uint256 tokenId);
    event Unlocked(uint256 tokenId);
    function locked(uint256 tokenId) external view returns (bool);
}

/// @notice Recipient-consented, non-transferable recognition, not a payout asset.
/// @dev Contribution IDs and ownership are public on chain, but omitted from metadata.
/// EOAs must sign the exact policy-bound consent; ERC1271/contract recipients are unsupported.
contract ContributionFlower is ERC721, Ownable, EIP712, ReentrancyGuard, IERC5192 {
    using Strings for uint256;

    bytes32 public constant POLICY_VERSION = keccak256("redteam-flower-policy-v1");
    bytes32 public constant CONSENT_TYPEHASH = keccak256(
        "Consent(address recipient,bytes32 contributionId,uint8 category,uint256 nonce,uint256 deadline,bytes32 policyVersion)"
    );

    struct Consent {
        address recipient;
        bytes32 contributionId;
        uint8 category;
        uint256 nonce;
        uint256 deadline;
        bytes32 policyVersion;
    }

    address public issuer;
    uint256 public nextTokenId = 1;
    mapping(address => uint256) public nonces;
    mapping(bytes32 => bool) public contributionUsed;
    mapping(uint256 => bytes32) public contributionIds;
    /// @notice 0: model finding; 1: system finding; 2: research contribution.
    mapping(uint256 => uint8) public categories;
    mapping(uint256 => uint256) public issuedAt;
    mapping(uint256 => bool) public revoked;

    event IssuerUpdated(address indexed previousIssuer, address indexed newIssuer);
    event FlowerMinted(uint256 indexed tokenId, address indexed recipient, bytes32 indexed contributionId, uint8 category);
    event FlowerRevoked(uint256 indexed tokenId);

    error NotIssuer();
    error ZeroAddress();
    error ZeroContributionId();
    error ContractRecipient();
    error ConsentExpired();
    error InvalidPolicyVersion();
    error InvalidCategory();
    error InvalidNonce();
    error InvalidSignature();
    error ContributionAlreadyUsed();
    error AlreadyRevoked();
    error NonTransferable();
    error ApprovalsDisabled();

    // Fixed artwork: no wallet, contribution digest, external URI, or user-provided SVG.
    string private constant FLOWER_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400"><rect width="400" height="400" rx="32" fill="#faf8f5"/><path d="M200 225V340" stroke="#497655" stroke-width="12" stroke-linecap="round"/><path d="M200 300Q145 300 140 255Q190 255 200 300M200 275Q255 275 260 235Q210 235 200 275" fill="#497655"/><g fill="#bc4053"><ellipse cx="200" cy="132" rx="38" ry="58"/><ellipse cx="200" cy="132" rx="38" ry="58" transform="rotate(60 200 190)"/><ellipse cx="200" cy="132" rx="38" ry="58" transform="rotate(120 200 190)"/><ellipse cx="200" cy="132" rx="38" ry="58" transform="rotate(180 200 190)"/><ellipse cx="200" cy="132" rx="38" ry="58" transform="rotate(240 200 190)"/><ellipse cx="200" cy="132" rx="38" ry="58" transform="rotate(300 200 190)"/></g><circle cx="200" cy="190" r="34" fill="#e5b54b"/></svg>';

    constructor(address initialOwner, address initialIssuer)
        ERC721("REDTEAM Flower", "FLOWER")
        Ownable(initialOwner)
        EIP712("REDTEAM Flower", "1")
    {
        if (initialIssuer == address(0)) revert ZeroAddress();
        issuer = initialIssuer;
        emit IssuerUpdated(address(0), initialIssuer);
    }

    modifier onlyIssuer() {
        if (msg.sender != issuer) revert NotIssuer();
        _;
    }

    function setIssuer(address newIssuer) external onlyOwner {
        if (newIssuer == address(0)) revert ZeroAddress();
        address previousIssuer = issuer;
        issuer = newIssuer;
        emit IssuerUpdated(previousIssuer, newIssuer);
    }

    /// @notice Issue one recognition after verifying an EOA recipient's EIP712 consent.
    /// @dev A deadline equal to the current timestamp is valid. IDs remain used forever.
    function mint(Consent calldata consent, bytes calldata signature)
        external onlyIssuer nonReentrant returns (uint256 tokenId)
    {
        if (consent.recipient == address(0)) revert ZeroAddress();
        if (consent.recipient.code.length != 0) revert ContractRecipient();
        if (consent.contributionId == bytes32(0)) revert ZeroContributionId();
        if (block.timestamp > consent.deadline) revert ConsentExpired();
        if (consent.policyVersion != POLICY_VERSION) revert InvalidPolicyVersion();
        if (consent.category > 2) revert InvalidCategory();
        if (consent.nonce != nonces[consent.recipient]) revert InvalidNonce();
        if (contributionUsed[consent.contributionId]) revert ContributionAlreadyUsed();

        bytes32 digest = _hashTypedDataV4(keccak256(abi.encode(
            CONSENT_TYPEHASH,
            consent.recipient,
            consent.contributionId,
            consent.category,
            consent.nonce,
            consent.deadline,
            consent.policyVersion
        )));
        if (ECDSA.recover(digest, signature) != consent.recipient) revert InvalidSignature();

        tokenId = nextTokenId++;
        nonces[consent.recipient]++;
        contributionUsed[consent.contributionId] = true;
        contributionIds[tokenId] = consent.contributionId;
        categories[tokenId] = consent.category;
        issuedAt[tokenId] = block.timestamp;
        // Contract receivers are rejected above, so there is no receiver callback.
        _mint(consent.recipient, tokenId);
        emit Locked(tokenId);
        emit FlowerMinted(tokenId, consent.recipient, consent.contributionId, consent.category);
    }

    /// @notice Permanently mark recognition revoked; never burn or release its ID.
    function revoke(uint256 tokenId) external onlyIssuer {
        _requireOwned(tokenId);
        if (revoked[tokenId]) revert AlreadyRevoked();
        revoked[tokenId] = true;
        emit FlowerRevoked(tokenId);
    }

    function locked(uint256 tokenId) external view returns (bool) {
        _requireOwned(tokenId);
        return true;
    }

    function supportsInterface(bytes4 interfaceId) public view override(ERC721, IERC165) returns (bool) {
        return interfaceId == type(IERC5192).interfaceId || super.supportsInterface(interfaceId);
    }

    function approve(address, uint256) public pure override {
        revert ApprovalsDisabled();
    }

    function setApprovalForAll(address, bool) public pure override {
        revert ApprovalsDisabled();
    }

    function transferFrom(address, address, uint256) public pure override {
        revert NonTransferable();
    }

    // OZ's non-virtual three-argument overload delegates to this overload.
    function safeTransferFrom(address, address, uint256, bytes memory) public pure override {
        revert NonTransferable();
    }

    /// @dev Bottom-level invariant blocks transfers, self-transfers and burns even
    /// through internal ERC721 paths. Not virtual: extensions cannot weaken it.
    function _update(address to, uint256 tokenId, address auth) internal override returns (address) {
        if (to == address(0) || _ownerOf(tokenId) != address(0)) revert NonTransferable();
        return super._update(to, tokenId, auth);
    }

    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        _requireOwned(tokenId);
        string memory category = categories[tokenId] == 0 ? "model finding"
            : categories[tokenId] == 1 ? "system finding" : "research contribution";
        string memory status = revoked[tokenId] ? "revoked" : "active";
        bytes memory json = abi.encodePacked(
            '{"name":"REDTEAM Flower #', tokenId.toString(),
            '","description":"Non-transferable recognition of a REDTEAM contribution. Revocation changes recognition status only.",',
            '"image":"data:image/svg+xml;base64,', Base64.encode(bytes(FLOWER_SVG)),
            '","attributes":[{"trait_type":"Token number","value":', tokenId.toString(),
            '},{"trait_type":"Category","value":"', category,
            '"},{"trait_type":"Status","value":"', status, '"}]}'
        );
        return string.concat("data:application/json;base64,", Base64.encode(json));
    }
}
