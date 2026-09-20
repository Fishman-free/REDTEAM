// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";

import "./RTMToken.sol";

/// @title BountyVault
/// @notice Settlement authority of the attack bounty mechanism: it turns an
/// independently verified attack into a one-shot RTM payout. The evaluator --
/// the party that reproduces an attack and judges it valid -- configures a
/// claim, and settlement mints the reward to the attacker's address.
/// @dev This contract holds no balance. It is the *only* minter of `rtm`, and
/// the token's halving schedule remains the outer bound on everything it can
/// ever pay out, so vault authority and issuance authority stay separated: the
/// vault can choose winners, but it cannot mint outside the published schedule.
///
/// Why there is no `ReentrancyGuard`: `settleClaim` makes exactly one external
/// call, `rtm.mint(...)`, on the RTMToken bound once during initialization. `rtm`
/// cannot be rebound after initialization, and its `mint` performs a plain ERC-20
/// balance update with no callback into the beneficiary or any other untrusted
/// contract, so no reentrant path into this vault exists. The
/// reasoning is safe independently of that assumption too: the claim is marked
/// settled *before* the mint (checks-effects-interactions), and a re-entrant
/// `settleClaim` would revert with `ClaimAlreadySettled` -- so even a
/// misbehaving token could not pay a claim twice. Add a guard only if a future
/// version starts calling an arbitrary or upgradeable token.
contract BountyVault is Ownable, Pausable {
    /// @notice Bounty asset minted on settlement; also this vault's only minter role.
    /// @dev Bound exactly once by `initializeRtm`; the token immutably points
    /// to this vault as its sole minter.
    RTMToken public rtm;

    /// @notice Account allowed to configure and settle claims.
    address public evaluator;

    /// @notice Current ceiling on a single claim.
    uint256 public maxPerClaim;

    /// @notice Cumulative amount settled through this vault.
    uint256 public totalSettled;

    /// @notice A bounty award configured in advance by the evaluator.
    /// @param beneficiary Attacker address that receives the reward.
    /// @param amount Amount of RTM to mint on settlement.
    /// @param configured Whether this claim id has been configured at all.
    /// @param settled Whether this claim has already been paid.
    struct Claim {
        address beneficiary;
        uint256 amount;
        bool configured;
        bool settled;
    }

    /// @notice Configured claims keyed by claim id.
    mapping(bytes32 => Claim) public claims;

    /// @notice Emitted when the evaluator account is rotated.
    /// @param oldEvaluator Previous evaluator, zero on first configuration.
    /// @param newEvaluator Newly authorised evaluator.
    event EvaluatorUpdated(address indexed oldEvaluator, address indexed newEvaluator);

    /// @notice Emitted when the per-claim ceiling changes.
    /// @param oldMax Previous ceiling.
    /// @param newMax New ceiling.
    event MaxPerClaimUpdated(uint256 oldMax, uint256 newMax);

    /// @notice Emitted when an award is configured.
    /// @param id Claim id.
    /// @param beneficiary Attacker address that will receive the reward.
    /// @param amount Amount of RTM reserved for this claim.
    event ClaimConfigured(bytes32 indexed id, address indexed beneficiary, uint256 amount);

    /// @notice Emitted when an award is paid.
    /// @param id Claim id.
    /// @param beneficiary Recipient of the minted reward.
    /// @param amount Amount minted.
    /// @param year Emission year the amount was charged against.
    event ClaimSettled(bytes32 indexed id, address indexed beneficiary, uint256 amount, uint256 year);

    /// @notice Caller is not the configured evaluator.
    error NotEvaluator();
    /// @notice A required address (or, following the existing settlement
    /// contract's convention for a zero id, an id) was zero.
    error ZeroAddress();
    /// @notice A required amount argument was zero.
    error ZeroAmount();
    /// @notice A claim with this id already exists.
    error ClaimAlreadyConfigured();
    /// @notice The vault is already bound to an RTM token.
    error RtmAlreadyInitialized();
    /// @notice The vault has not yet been bound to an RTM token.
    error RtmNotInitialized();
    /// @notice No claim has been configured under this id.
    error ClaimNotConfigured();
    /// @notice This claim has already been paid.
    error ClaimAlreadySettled();
    /// @notice The amount exceeds `maxPerClaim`.
    error ClaimTooLarge();

    /// @notice Restricts a call to the configured evaluator account.
    modifier onlyEvaluator() {
        if (msg.sender != evaluator) revert NotEvaluator();
        _;
    }

    /// @notice Deploys the vault before its RTM token is bound.
    /// @dev Deployment is intentionally two-step: deploy the vault first, then
    /// deploy RTMToken with the vault address as `minter_`, and finally call
    /// `initializeRtm` once. There is no post-deploy role handoff.
    /// @param initialOwner Owner allowed to rotate the evaluator and the cap.
    constructor(address initialOwner) Ownable(initialOwner) {}

    /// @notice Binds the vault to its RTM token exactly once.
    /// @dev The token must already have this vault as its immutable minter.
    function initializeRtm(RTMToken rtm_) external onlyOwner {
        if (address(rtm) != address(0)) revert RtmAlreadyInitialized();
        if (address(rtm_) == address(0) || rtm_.minter() != address(this)) revert ZeroAddress();
        rtm = rtm_;
    }

    /// @notice Rotates the evaluator account.
    /// @param newEvaluator New evaluator; must be non-zero.
    function setEvaluator(address newEvaluator) external onlyOwner {
        if (newEvaluator == address(0)) revert ZeroAddress();
        address oldEvaluator = evaluator;
        evaluator = newEvaluator;
        emit EvaluatorUpdated(oldEvaluator, newEvaluator);
    }

    /// @notice Sets the ceiling applied to new and unsettled claims.
    /// @dev Lowering the cap does not silently cancel existing claims, but
    /// `settleClaim` re-checks against the *current* cap, so a lowered ceiling
    /// blocks settlement of oversized claims until they are reconfigured.
    /// @param newMax New ceiling; must be non-zero.
    function setMaxPerClaim(uint256 newMax) external onlyOwner {
        if (newMax == 0) revert ZeroAmount();
        uint256 oldMax = maxPerClaim;
        maxPerClaim = newMax;
        emit MaxPerClaimUpdated(oldMax, newMax);
    }

    /// @notice Configures an award under `id` for `beneficiary`.
    /// @dev One-shot per id, mirroring `PaymentAgent.configureInvoice`: a wrong
    /// beneficiary or amount must be re-issued under a fresh id, so an
    /// already-reviewed award cannot be silently rewritten between review and
    /// payout.
    /// @param id Claim id; must be non-zero and unused.
    /// @param beneficiary Attacker address that receives the reward; non-zero.
    /// @param amount Amount of RTM to mint on settlement; within `maxPerClaim`.
    function configureClaim(bytes32 id, address beneficiary, uint256 amount)
        external
        onlyEvaluator
        whenNotPaused
    {
        if (address(rtm) == address(0)) revert RtmNotInitialized();
        if (id == bytes32(0)) revert ZeroAddress();
        if (beneficiary == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        if (amount > maxPerClaim) revert ClaimTooLarge();
        if (claims[id].configured) revert ClaimAlreadyConfigured();
        claims[id] = Claim(beneficiary, amount, true, false);
        emit ClaimConfigured(id, beneficiary, amount);
    }

    /// @notice Pays the award configured under `id`.
    /// @dev The amount is re-checked against the *current* `maxPerClaim`, so
    /// lowering the cap restricts previously configured claims too. State is
    /// finalised before the mint (checks-effects-interactions), which makes a
    /// second settlement of the same id impossible.
    ///
    /// Exhausted-budget behaviour: if the current year's emission budget is
    /// already spent, `rtm.mint` reverts with `YearBudgetExceeded` and the whole
    /// call reverts -- the claim stays configured and unsettled, and the
    /// evaluator simply retries after the year rolls over. Rewards are therefore
    /// deferred, never lost or re-based. This is a deliberate consequence of the
    /// halving schedule: the vault cannot pay out faster than the token emits.
    /// @param id Claim id; must be configured and unsettled.
    function settleClaim(bytes32 id) external onlyEvaluator whenNotPaused {
        if (address(rtm) == address(0)) revert RtmNotInitialized();
        Claim storage c = claims[id];
        if (!c.configured) revert ClaimNotConfigured();
        if (c.settled) revert ClaimAlreadySettled();
        if (c.amount > maxPerClaim) revert ClaimTooLarge();
        c.settled = true;
        totalSettled += c.amount;
        rtm.mint(c.beneficiary, c.amount);
        emit ClaimSettled(id, c.beneficiary, c.amount, rtm.currentYear());
    }

    /// @notice Pauses claim configuration and settlement.
    /// @dev Owner-only. Existing claims are retained and can be settled after
    /// `unpause()`; pausing is a circuit breaker on the evaluator's ability to
    /// award, not a way to seize funds -- the vault holds none.
    function pause() external onlyOwner {
        _pause();
    }

    /// @notice Resumes claim configuration and settlement.
    function unpause() external onlyOwner {
        _unpause();
    }
}
