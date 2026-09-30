// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";

import "./RTMToken.sol";

/// @title BountyVault
/// @notice Settlement authority for independently verified attack bounties.
/// Claims reserve capacity in the RTM emission year in which they are configured;
/// a claim must be settled in that same year or explicitly cancelled.
/// @dev This contract holds no balance. It is the only minter of `rtm`, and the
/// token's halving schedule remains the outer bound on everything it can pay out.
///
/// There is deliberately no ReentrancyGuard: `settleClaim` calls only the
/// immutably bound RTMToken, whose `mint` performs a balance update with no
/// callback. The claim is also marked settled and its reservation released before
/// that call; a re-entrant settlement would therefore revert. State changes still
/// roll back if `mint` reverts.
contract BountyVault is Ownable, Pausable {
    /// @notice Bounty asset minted on settlement; also this vault's only minter role.
    /// @dev Bound exactly once by `initializeRtm`; the token immutably points to
    /// this vault as its sole minter.
    RTMToken public rtm;

    /// @notice Account allowed to configure, settle, and cancel claims.
    address public evaluator;

    /// @notice Current ceiling on a single claim.
    uint256 public maxPerClaim;

    /// @notice Cumulative amount settled through this vault.
    uint256 public totalSettled;

    /// @notice Amount reserved by configured-but-not-finalised claims in each year.
    mapping(uint256 => uint256) public reservedByYear;

    /// @notice A bounty award configured in advance by the evaluator.
    /// @param beneficiary Attacker address that receives the reward.
    /// @param amount Amount of RTM to mint on settlement.
    /// @param emissionYear RTM emission year reserved by this claim.
    /// @param configured Whether this claim id has ever been configured.
    /// @param settled Whether this claim has already been paid.
    /// @param cancelled Whether this claim was explicitly cancelled.
    struct Claim {
        address beneficiary;
        uint256 amount;
        uint256 emissionYear;
        bool configured;
        bool settled;
        bool cancelled;
    }

    /// @notice Configured claims keyed by claim id.
    mapping(bytes32 => Claim) public claims;

    /// @notice Emitted when the evaluator account is rotated.
    event EvaluatorUpdated(address indexed oldEvaluator, address indexed newEvaluator);

    /// @notice Emitted when the per-claim ceiling changes.
    event MaxPerClaimUpdated(uint256 oldMax, uint256 newMax);

    /// @notice Emitted when an award is configured and its year's capacity reserved.
    event ClaimConfigured(
        bytes32 indexed id,
        address indexed beneficiary,
        uint256 amount,
        uint256 indexed year
    );

    /// @notice Emitted when an award is paid.
    event ClaimSettled(bytes32 indexed id, address indexed beneficiary, uint256 amount, uint256 year);

    /// @notice Emitted when an unsettled award is explicitly cancelled.
    event ClaimCancelled(bytes32 indexed id, address indexed beneficiary, uint256 amount, uint256 year);

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
    /// @notice This claim has already been cancelled.
    error ClaimAlreadyCancelled();
    /// @notice The claim's bound year is no longer the current RTM year.
    error ClaimYearExpired(uint256 claimYear, uint256 currentYear);
    /// @notice The amount exceeds `maxPerClaim`.
    error ClaimTooLarge();
    /// @notice The requested amount is not available after minted and reserved RTM.
    error YearBudgetUnavailable(uint256 year, uint256 requested, uint256 available);
    /// @notice A reservation was unexpectedly smaller than the claim being released.
    error ReservationInvariantBroken(uint256 year, uint256 reserved, uint256 required);

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
    /// `settleClaim` re-checks against the current cap, so oversized claims stay
    /// reserved until the cap is raised or the evaluator explicitly cancels them.
    /// @param newMax New ceiling; must be non-zero.
    function setMaxPerClaim(uint256 newMax) external onlyOwner {
        if (newMax == 0) revert ZeroAmount();
        uint256 oldMax = maxPerClaim;
        maxPerClaim = newMax;
        emit MaxPerClaimUpdated(oldMax, newMax);
    }

    /// @notice Returns current-year capacity not already minted or reserved.
    /// @dev The subtraction is saturated in two steps, so malformed or exhausted
    /// accounting cannot underflow while reporting availability.
    function availableCurrentYearBudget() public view returns (uint256) {
        if (address(rtm) == address(0)) revert RtmNotInitialized();
        return _availableYearBudget(rtm.currentYear());
    }

    /// @notice Configures and reserves an award under `id`.
    /// @dev The claim is bound to the current RTM year. Its full amount must fit
    /// after both minted and previously reserved capacity are deducted. There is
    /// no future-year guarantee and no partial payment path.
    /// @param id Claim id; must be non-zero and unused.
    /// @param beneficiary Attacker address that receives the reward; non-zero.
    /// @param amount Amount of RTM to reserve and mint on settlement.
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

        uint256 year = rtm.currentYear();
        uint256 available = _availableYearBudget(year);
        if (amount > available) revert YearBudgetUnavailable(year, amount, available);

        claims[id] = Claim({
            beneficiary: beneficiary,
            amount: amount,
            emissionYear: year,
            configured: true,
            settled: false,
            cancelled: false
        });
        reservedByYear[year] += amount;
        emit ClaimConfigured(id, beneficiary, amount, year);
    }

    /// @notice Pays the award configured under `id`.
    /// @dev Settlement is valid only in the claim's bound year. The current
    /// year's minted budget is checked again before releasing the reservation.
    /// Reservation release and the settled mark happen before `mint`; if mint
    /// fails, EVM revert semantics restore the claim and reservation atomically.
    /// @param id Claim id; must be configured, unsettled, and uncancelled.
    function settleClaim(bytes32 id) external onlyEvaluator whenNotPaused {
        if (address(rtm) == address(0)) revert RtmNotInitialized();
        Claim storage c = claims[id];
        if (!c.configured) revert ClaimNotConfigured();
        if (c.settled) revert ClaimAlreadySettled();
        if (c.cancelled) revert ClaimAlreadyCancelled();

        uint256 year = rtm.currentYear();
        if (c.emissionYear != year) revert ClaimYearExpired(c.emissionYear, year);
        if (c.amount > maxPerClaim) revert ClaimTooLarge();

        uint256 remaining = _remainingYearBudget(year);
        if (c.amount > remaining) revert YearBudgetUnavailable(year, c.amount, remaining);
        uint256 reserved = reservedByYear[year];
        if (reserved < c.amount) revert ReservationInvariantBroken(year, reserved, c.amount);

        reservedByYear[year] = reserved - c.amount;
        c.settled = true;
        totalSettled += c.amount;
        rtm.mint(c.beneficiary, c.amount);
        emit ClaimSettled(id, c.beneficiary, c.amount, year);
    }

    /// @notice Explicitly cancels an unsettled claim and releases its old-year reservation.
    /// @dev Cancellation is required after an emission-year rollover. It never
    /// retargets a claim to a later year and cannot be performed twice.
    /// @param id Claim id; must be configured, unsettled, and uncancelled.
    function cancelClaim(bytes32 id) external onlyEvaluator whenNotPaused {
        Claim storage c = claims[id];
        if (!c.configured) revert ClaimNotConfigured();
        if (c.settled) revert ClaimAlreadySettled();
        if (c.cancelled) revert ClaimAlreadyCancelled();

        uint256 reserved = reservedByYear[c.emissionYear];
        if (reserved < c.amount) {
            revert ReservationInvariantBroken(c.emissionYear, reserved, c.amount);
        }
        reservedByYear[c.emissionYear] = reserved - c.amount;
        c.cancelled = true;
        emit ClaimCancelled(id, c.beneficiary, c.amount, c.emissionYear);
    }

    /// @notice Pauses claim configuration, settlement, and cancellation.
    /// @dev Existing claims are retained and can be settled or cancelled after
    /// `unpause()`; pausing is a circuit breaker, not a seizure mechanism.
    function pause() external onlyOwner {
        _pause();
    }

    /// @notice Resumes claim configuration, settlement, and cancellation.
    function unpause() external onlyOwner {
        _unpause();
    }

    function _remainingYearBudget(uint256 year) internal view returns (uint256) {
        uint256 budget = rtm.yearBudget(year);
        uint256 minted = rtm.mintedByYear(year);
        return budget > minted ? budget - minted : 0;
    }

    function _availableYearBudget(uint256 year) internal view returns (uint256) {
        uint256 remaining = _remainingYearBudget(year);
        uint256 reserved = reservedByYear[year];
        return remaining > reserved ? remaining - reserved : 0;
    }
}
