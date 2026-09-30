// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title RewardSettlement
/// @notice Bounty payout authority for the local RSI experiment: it pays a
/// pre-funded ERC-20 reward to a beneficiary only when the request matches a
/// previously configured settlement exactly.
/// @dev Reward authority is deliberately separated from the payment authority
/// in `PaymentAgent`. The two contracts hold different balances, have different
/// owners (the host operates payments, the evaluator settles bounties), and
/// enforce independent caps, so an attacker who captures the payment path gains
/// nothing on the bounty path and vice versa. Only the evaluator -- the party
/// that independently judges whether an executed transfer violated the task --
/// can configure or fire a settlement, each settlement is one-shot, and total
/// payouts are capped by `cap`.
contract RewardSettlement {
    using SafeERC20 for IERC20;

    /// @notice ERC-20 asset rewards are paid in.
    IERC20 public immutable token;
    /// @notice Account allowed to configure and fire settlements.
    address public immutable evaluator;
    /// @notice Upper bound on a single reward and on `paid`.
    uint256 public immutable cap;
    /// @notice Cumulative reward amount paid out.
    uint256 public paid;

    /// @notice Settlement ids that have already been paid.
    mapping(bytes32 => bool) public settled;

    /// @notice A bounty authorisation configured in advance by the evaluator.
    /// @param beneficiary Recipient of the reward.
    /// @param reward Exact amount the settlement must use.
    /// @param configured Whether this settlement id has been configured at all.
    struct Settlement {
        address beneficiary;
        uint256 reward;
        bool configured;
    }

    /// @notice Configured settlements keyed by settlement id.
    mapping(bytes32 => Settlement) public settlements;

    /// @notice Emitted when a reward is paid.
    /// @param settlementId Settlement id that authorised this payout.
    /// @param recipient Beneficiary that received the reward.
    /// @param amount Amount transferred.
    event Reward(bytes32 indexed settlementId, address indexed recipient, uint256 amount);

    /// @notice Emitted when a bounty authorisation is created.
    /// @param settlementId Id of the configured settlement.
    /// @param beneficiary Recipient of the reward.
    /// @param reward Exact amount the settlement must use.
    event SettlementConfigured(bytes32 indexed settlementId, address indexed beneficiary, uint256 reward);

    /// @notice Restricts a call to the configured evaluator account.
    modifier onlyEvaluator() {
        require(msg.sender == evaluator, "not evaluator");
        _;
    }

    /// @notice Deploys the settlement and makes the deployer the evaluator.
    /// @dev The evaluator is immutable, so the judging authority of a deployed
    /// settlement cannot be reassigned after the fact.
    /// @param t ERC-20 asset rewards are paid in; the contract must be funded
    /// separately, since the constructor transfers nothing.
    /// @param c Maximum amount for a single reward and for `paid`.
    constructor(IERC20 t, uint256 c) {
        token = t;
        evaluator = msg.sender;
        cap = c;
    }

    /// @notice Configures a bounty authorisation under `id`.
    /// @dev Configuration is one-shot per settlement id, mirroring
    /// `PaymentAgent.configureInvoice`: a mistaken configuration must be
    /// replaced with a fresh id rather than edited.
    /// @param id Settlement id, must be non-zero and unused.
    /// @param beneficiary Recipient of the reward, must be non-zero.
    /// @param reward Exact amount the payout must use; must be within `cap`.
    function configureSettlement(bytes32 id, address beneficiary, uint256 reward)
        external
        onlyEvaluator
    {
        require(id != bytes32(0) && beneficiary != address(0), "zero address");
        require(reward > 0 && reward <= cap, "cap");
        require(!settlements[id].configured, "settlement configured");
        settlements[id] = Settlement(beneficiary, reward, true);
        emit SettlementConfigured(id, beneficiary, reward);
    }

    /// @notice Pays the reward authorised by `id`.
    /// @dev The recipient and amount are checked against the stored settlement
    /// rather than trusted from the caller, and `id` is consumed, so a bounty
    /// cannot be paid twice. State is updated before the transfer
    /// (checks-effects-interactions) and `SafeERC20` tolerates non-standard
    /// ERC-20 implementations.
    /// @param id Settlement id to fire; must be configured and unsettled.
    /// @param recipient Must equal the beneficiary recorded on the settlement.
    /// @param amount Must equal the reward recorded on the settlement.
    function settle(bytes32 id, address recipient, uint256 amount) external onlyEvaluator {
        Settlement memory s = settlements[id];
        require(s.configured && s.beneficiary == recipient && s.reward == amount, "settlement mismatch");
        require(!settled[id], "already settled");
        require(paid + amount <= cap, "cap");
        settled[id] = true;
        paid += amount;
        token.safeTransfer(recipient, amount);
        emit Reward(id, recipient, amount);
    }
}
