// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title PaymentAgent
/// @notice Payment execution authority for the local RSI experiment: it moves a
/// pre-funded ERC-20 balance to a participant only when the operator's request
/// matches a previously configured invoice exactly.
/// @dev The contract enforces *mechanical boundaries only*: an allowlist of
/// merchants and participants, an exact match against a configured invoice,
/// single use of both the operation id and the invoice id, and a total cap on
/// everything the agent may ever pay. It deliberately performs no policy
/// judgement about whether a payment is "right" -- deciding that a transfer
/// violated the user's authorisation is the independent evaluator's job, and
/// keeping that judgement out of the contract is what keeps the local
/// attack/defence experiment meaningful. The boundary contract only guarantees
/// that a manipulated or compromised operator can never move more than the
/// pre-funded balance, never pay an unlisted counterparty, never pay an
/// unconfigured or already-spent invoice, and never exceed `maxPayment` in
/// aggregate -- and that every movement leaves an attributable on-chain log.
contract PaymentAgent {
    using SafeERC20 for IERC20;

    /// @notice ERC-20 asset this agent pays with.
    IERC20 public immutable token;
    /// @notice Account allowed to configure invoices and trigger payments.
    address public operator;
    /// @notice Upper bound on a single payment and on `totalPaid`.
    uint256 public immutable maxPayment;
    /// @notice Cumulative amount paid out by this agent.
    uint256 public totalPaid;

    /// @notice Whether `account` is allowed to appear as merchant or participant.
    mapping(address => bool) public allowlisted;
    /// @notice Operation ids and invoice ids that have already been consumed.
    mapping(bytes32 => bool) public used;

    /// @notice A payment authorisation configured in advance by the operator.
    /// @param merchant Merchant the payment is attributed to.
    /// @param participant Recipient of the funds.
    /// @param amount Exact amount the payment must use.
    /// @param configured Whether this invoice id has been configured at all.
    struct Invoice {
        address merchant;
        address participant;
        uint256 amount;
        bool configured;
    }

    /// @notice Configured invoices keyed by invoice id.
    mapping(bytes32 => Invoice) public invoices;

    /// @notice Emitted when a payment is executed.
    /// @param operationId Caller-supplied operation id, consumed to make the call single-use.
    /// @param invoiceId Invoice id that authorised this payment, also consumed.
    /// @param merchant Merchant recorded on the invoice.
    /// @param participant Recipient of the funds.
    /// @param amount Amount transferred.
    event Payment(
        bytes32 indexed operationId,
        bytes32 indexed invoiceId,
        address indexed merchant,
        address participant,
        uint256 amount
    );

    /// @notice Emitted when the allowlist entry of `account` is set to `allowed`.
    /// @param account Address whose allowlist status changed.
    /// @param allowed New allowlist status.
    event AllowlistUpdated(address indexed account, bool allowed);

    /// @notice Emitted when a payment authorisation is created.
    /// @param invoiceId Id of the configured invoice.
    /// @param merchant Merchant the payment is attributed to.
    /// @param participant Recipient of the funds.
    /// @param amount Exact amount the payment must use.
    event InvoiceConfigured(
        bytes32 indexed invoiceId,
        address indexed merchant,
        address indexed participant,
        uint256 amount
    );

    /// @notice Restricts a call to the configured operator account.
    modifier onlyOperator() {
        require(msg.sender == operator, "not operator");
        _;
    }

    /// @notice Deploys the agent and makes the deployer the operator.
    /// @dev The operator is set to `msg.sender` and is not rotatable afterwards,
    /// so the authorisation surface of a deployed agent cannot be reassigned.
    /// @param t ERC-20 asset the agent will pay with; the agent must be funded
    /// separately, since the constructor transfers nothing.
    /// @param cap Maximum amount for a single payment and for `totalPaid`.
    constructor(IERC20 t, uint256 cap) {
        token = t;
        operator = msg.sender;
        maxPayment = cap;
    }

    /// @notice Adds or removes `a` from the allowlist.
    /// @dev Both sides of a payment (merchant and participant) must be
    /// allowlisted at configuration time and again at payment time, so revoking
    /// an entry also disables invoices that were configured earlier.
    /// @param a Address to update.
    /// @param ok Whether `a` may take part in payments.
    function setAllowlisted(address a, bool ok) external onlyOperator {
        require(a != address(0), "zero address");
        allowlisted[a] = ok;
        emit AllowlistUpdated(a, ok);
    }

    /// @notice Configures a payment authorisation under `id`.
    /// @dev Configuration is one-shot per invoice id: an operator mistake
    /// cannot be corrected in place, it must use a fresh id. This is what makes
    /// the invoice an immutable commitment that `pay` later checks against.
    /// @param id Invoice id, must be non-zero and unused.
    /// @param merchant Merchant the payment is attributed to; must be allowlisted.
    /// @param participant Recipient of the funds; must be allowlisted.
    /// @param amount Exact amount the payment must use; must be within `maxPayment`.
    function configureInvoice(bytes32 id, address merchant, address participant, uint256 amount)
        external
        onlyOperator
    {
        require(id != bytes32(0), "zero id");
        require(allowlisted[merchant] && allowlisted[participant], "not allowlisted");
        require(amount > 0 && amount <= maxPayment, "cap");
        require(!invoices[id].configured, "invoice configured");
        invoices[id] = Invoice(merchant, participant, amount, true);
        emit InvoiceConfigured(id, merchant, participant, amount);
    }

    /// @notice Executes the payment authorised by `invoice`.
    /// @dev Every parameter is re-checked against the stored invoice rather than
    /// trusted from the caller, and both `op` and `invoice` are consumed, so a
    /// replayed or reworded call cannot pay twice. State is updated before the
    /// token transfer (checks-effects-interactions); `SafeERC20` tolerates
    /// non-standard ERC-20 implementations that return no value.
    /// @param op Operation id chosen by the operator; must be unused.
    /// @param invoice Invoice id authorising this payment; must be configured and unused.
    /// @param merchant Must equal the merchant recorded on the invoice.
    /// @param participant Must equal the participant recorded on the invoice.
    /// @param amount Must equal the amount recorded on the invoice.
    function pay(bytes32 op, bytes32 invoice, address merchant, address participant, uint256 amount)
        external
        onlyOperator
    {
        Invoice memory i = invoices[invoice];
        require(
            i.configured && i.merchant == merchant && i.participant == participant && i.amount == amount,
            "invoice mismatch"
        );
        require(!used[op] && !used[invoice], "duplicate");
        require(allowlisted[merchant] && allowlisted[participant], "not allowlisted");
        require(totalPaid + amount <= maxPayment, "cap");
        used[op] = true;
        used[invoice] = true;
        totalPaid += amount;
        token.safeTransfer(participant, amount);
        emit Payment(op, invoice, merchant, participant, amount);
    }
}
