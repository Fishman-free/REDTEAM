// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Round-based commit–reveal layer for public attack submissions
/// (docs/references/ATTACK_INTERFACE_DESIGN.md §3, minimal prototype).
/// @dev Deliberately separate from the audited BountyVault: BountyRound only
/// fixes submission priority (first commit per material hash wins) and holds
/// pre-funded payouts for finalized findings in pull mode. Settling a winning
/// finding as an RTM claim still goes through the frozen evidence-reward
/// protocol (docs/EVIDENCE_REWARD_PROTOCOL.md) on the BountyVault. The verifier
/// is off-chain adjudication's single trusted writer; attackers can only
/// commit hashes and pull their own approved payouts.
contract BountyRound is Ownable {
    struct Round {
        bytes32 versionHash;   // frozen target version digest
        bytes32 specHash;      // task/authorization spec digest
        uint64 closeAt;        // submissions accepted until this time
        bool finalized;
        uint256 pool;          // pre-funded payout pool for this round
    }

    struct Commit {
        address attacker;
        bool valid;            // set by finalizeRound
        bool paid;             // set by claimPayout
        uint256 amount;        // approved payout; zero = rejected
    }

    uint256 public constant MAX_COMMITMENTS = 10_000;

    mapping(bytes32 => Round) public rounds;
    /// roundId => materialHash => commit state
    mapping(bytes32 => mapping(bytes32 => Commit)) public commits;
    /// roundId => materialHash => first committer (priority anchor)
    mapping(bytes32 => mapping(bytes32 => address)) public firstCommitter;
    /// roundId => material hashes in submission order
    mapping(bytes32 => bytes32[]) public roundMaterials;

    event RoundCommitted(bytes32 indexed roundId, bytes32 versionHash, bytes32 specHash,
                         uint64 closeAt);
    event MaterialSubmitted(bytes32 indexed roundId, bytes32 indexed materialHash,
                            address indexed attacker);
    event RoundFinalized(bytes32 indexed roundId, uint256 validCount, uint256 totalApproved);
    event PayoutClaimed(bytes32 indexed roundId, bytes32 indexed materialHash,
                        address indexed attacker, uint256 amount);

    error InvalidCloseAt();
    error RoundExists();
    error RoundUnknown();
    error RoundClosed();
    error RoundStillOpen();
    error RoundNotFinalized();
    error DuplicateMaterial();
    error TooManyCommitments();
    error NotPayable();
    error AlreadyPaid();
    error NotBeneficiary();
    error NothingToClaim();
    error InsufficientPool();

    constructor(address initialOwner) Ownable(initialOwner) {}

    /// @notice Open a submission round for a frozen target version.
    function commitRound(bytes32 roundId, bytes32 versionHash, bytes32 specHash,
                         uint64 closeAt) external onlyOwner {
        if (closeAt <= block.timestamp) revert InvalidCloseAt();
        Round storage round = rounds[roundId];
        if (round.closeAt != 0) revert RoundExists(); // ids are single-use
        round.versionHash = versionHash;
        round.specHash = specHash;
        round.closeAt = closeAt;
        emit RoundCommitted(roundId, versionHash, specHash, closeAt);
    }

    /// @notice Commit the hash of the full submission material before revealing it.
    /// @dev Priority is first-come per (roundId, materialHash): a later commit of
    /// the same material reverts, so sybil re-submissions cannot win the race.
    function submitClaim(bytes32 roundId, bytes32 materialHash) external {
        Round storage round = rounds[roundId];
        if (round.closeAt == 0) revert RoundUnknown();
        if (block.timestamp > round.closeAt) revert RoundClosed();
        if (round.finalized) revert RoundClosed();
        if (firstCommitter[roundId][materialHash] != address(0)) revert DuplicateMaterial();
        if (roundMaterials[roundId].length >= MAX_COMMITMENTS) revert TooManyCommitments();
        firstCommitter[roundId][materialHash] = msg.sender;
        roundMaterials[roundId].push(materialHash);
        commits[roundId][materialHash] = Commit({attacker: msg.sender, valid: false,
                                                 paid: false, amount: 0});
        emit MaterialSubmitted(roundId, materialHash, msg.sender);
    }

    /// @notice Adjudicate every committed material after the round closes.
    /// @param materialHashes Committed material hashes being adjudicated.
    /// @param validFlags Whether each committed material is a valid finding.
    /// @param amounts Payout amounts for valid findings; zero means rejected.
    function finalizeRound(bytes32 roundId, bytes32[] calldata materialHashes,
                           bool[] calldata validFlags, uint256[] calldata amounts) external onlyOwner {
        Round storage round = rounds[roundId];
        if (round.closeAt == 0) revert RoundUnknown();
        if (block.timestamp <= round.closeAt) revert RoundStillOpen();
        if (round.finalized) revert RoundClosed();
        if (materialHashes.length != validFlags.length
                || materialHashes.length != amounts.length) revert NotPayable();
        round.finalized = true;
        uint256 totalApproved;
        uint256 validCount;
        for (uint256 index = 0; index < materialHashes.length; ++index) {
            bytes32 materialHash = materialHashes[index];
            if (firstCommitter[roundId][materialHash] == address(0)) continue;
            if (!validFlags[index] || amounts[index] == 0) continue;
            commits[roundId][materialHash].valid = true;
            commits[roundId][materialHash].amount = amounts[index];
            totalApproved += amounts[index];
            ++validCount;
        }
        if (totalApproved > round.pool) revert InsufficientPool();
        emit RoundFinalized(roundId, validCount, totalApproved);
    }

    /// @notice Fund a round's payout pool (owner; pre-funded pull mode).
    function fundRound(bytes32 roundId) external payable onlyOwner {
        if (rounds[roundId].closeAt == 0) revert RoundUnknown();
        rounds[roundId].pool += msg.value;
    }

    /// @notice Pull an approved payout; only the committer can claim, to the
    /// address that committed (beneficiary binding for real rewards happens on
    /// the BountyVault via the frozen protocol, not here).
    function claimPayout(bytes32 roundId, bytes32 materialHash) external {
        Round storage round = rounds[roundId];
        if (round.closeAt == 0) revert RoundUnknown();
        if (!round.finalized) revert RoundNotFinalized();
        Commit storage commit = commits[roundId][materialHash];
        if (commit.attacker == address(0)) revert NotPayable();
        if (!commit.valid || commit.amount == 0) revert NotPayable();
        if (msg.sender != commit.attacker) revert NotBeneficiary();
        if (commit.paid) revert AlreadyPaid();
        commit.paid = true;
        (bool sent,) = payable(commit.attacker).call{value: commit.amount}("");
        if (!sent) revert NothingToClaim();
        emit PayoutClaimed(roundId, materialHash, commit.attacker, commit.amount);
    }
}
