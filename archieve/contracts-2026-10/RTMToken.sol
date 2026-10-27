// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @title RTMToken
/// @notice "REDTEAM" (RTM): the fixed-supply bounty asset of the RSI attack
/// bounty mechanism. Emission follows a Bitcoin-style yearly halving so that
/// even a fully successful attacker can never drain the whole pool.
/// @dev The supply is fixed at `MAX_SUPPLY` for all time: there is no premint
/// (the deployer receives nothing) and no path that mints outside the halving
/// schedule.
///
/// Halving schedule. Each year `n` may mint at most `yearBudget(n)`:
/// `YEAR0_BUDGET = MAX_SUPPLY / 2` for year 0, then halved every year. Summing
/// the schedule over all years gives `2 * YEAR0_BUDGET - popcount(YEAR0_BUDGET)`,
/// which for the constants above is `MAX_SUPPLY - 38` wei -- strictly below
/// `MAX_SUPPLY`. So even if every year were minted down to its last wei, the
/// schedule alone can never reach, let alone exceed, the cap; `MAX_SUPPLY` is a
/// redundant second bound rather than the only defence.
///
/// Why the owner cannot exceed the schedule: ownership does not control `minter`.
/// It cannot mint, cannot edit `yearBudget`, and cannot move `emissionStart`.
/// `mint` is callable solely by `minter` and every call is checked against both
/// the current year's remaining budget and the remaining supply, so the
/// authority that configures bounties is never the authority that can inflate
/// the asset beyond the published schedule.
contract RTMToken is ERC20, Ownable {
    /// @notice Hard cap on the total supply, 21,000,000 RTM. Never minted in
    /// full: see the halving note in the contract documentation.
    uint256 public constant MAX_SUPPLY = 21_000_000 ether;

    /// @notice Emission budget of year 0: half of `MAX_SUPPLY`.
    uint256 public constant YEAR0_BUDGET = MAX_SUPPLY / 2;

    /// @notice Timestamp at which year 0 starts; fixed at deployment.
    uint64 public immutable emissionStart;

    /// @notice The only account allowed to call `mint`; permanently bound at deployment.
    /// @dev The address is immutable, so owner, evaluator, and former authorities
    /// cannot replace the BountyVault with a direct minter after deployment.
    address public immutable minter;

    /// @notice Amount minted so far in each year, indexed by year number.
    mapping(uint256 => uint256) public mintedByYear;

    /// @notice Emitted on every successful emission.
    /// @param to Recipient of the newly minted tokens.
    /// @param amount Amount minted.
    /// @param year Emission year the amount was charged against.
    event EmissionMinted(address indexed to, uint256 amount, uint256 indexed year);

    /// @notice Caller is not the configured minter.
    error NotMinter();
    /// @notice A required address argument was the zero address.
    error ZeroAddress();
    /// @notice The designated minter has no deployed contract code.
    error InvalidMinter();
    /// @notice A required amount argument was zero.
    error ZeroAmount();
    /// @notice The mint would exceed the current year's remaining budget.
    /// @param year Year the mint was charged against.
    /// @param requested Amount requested.
    /// @param remaining Amount still available in that year.
    error YearBudgetExceeded(uint256 year, uint256 requested, uint256 remaining);
    /// @notice The mint would push `totalSupply()` past `MAX_SUPPLY`.
    /// @param requested Amount requested.
    /// @param available Supply still mintable.
    error MaxSupplyExceeded(uint256 requested, uint256 available);

    /// @notice Deploys the token with no premint: `totalSupply()` starts at 0.
    /// @dev The minter is immutable and must be the BountyVault deployed for this
    /// token. Binding it during construction removes any owner-controlled minting
    /// or role-handoff window.
    /// @param initialOwner Owner retained for inherited administration; it cannot mint.
    /// @param minter_ BountyVault address permanently authorised to mint; non-zero.
    /// @param emissionStart_ Timestamp at which year 0 begins; must be non-zero.
    constructor(address initialOwner, address minter_, uint64 emissionStart_)
        ERC20("REDTEAM", "RTM")
        Ownable(initialOwner)
    {
        if (minter_ == address(0)) revert ZeroAddress();
        if (minter_.code.length == 0) revert InvalidMinter();
        if (emissionStart_ == 0) revert ZeroAmount();
        minter = minter_;
        emissionStart = emissionStart_;
    }

    /// @notice Mints `amount` new RTM to `to`, charged against the current
    /// year's emission budget.
    /// @dev Two independent bounds must both hold: the current year's remaining
    /// budget (which implements the halving) and the remaining supply. The year
    /// is derived from `block.timestamp`, not supplied by the caller, so the
    /// minter cannot choose a cheaper year to mint against. Reverts if the
    /// current year's budget is already exhausted -- callers such as
    /// `BountyVault` are expected to retry in a later year rather than force it.
    /// @param to Recipient of the minted tokens; must be non-zero.
    /// @param amount Amount to mint; must be non-zero and within budget.
    function mint(address to, uint256 amount) external {
        if (msg.sender != minter) revert NotMinter();
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();

        uint256 year = currentYear();
        uint256 budget = yearBudget(year);
        uint256 minted = mintedByYear[year];
        uint256 remaining = budget > minted ? budget - minted : 0;
        if (amount > remaining) revert YearBudgetExceeded(year, amount, remaining);

        uint256 available = MAX_SUPPLY - totalSupply();
        if (amount > available) revert MaxSupplyExceeded(amount, available);

        mintedByYear[year] = minted + amount;
        _mint(to, amount);
        emit EmissionMinted(to, amount, year);
    }

    /// @notice Year index of the current block, counting from `emissionStart`.
    /// @dev Years are fixed-length windows of `365 days`; they drift from the
    /// calendar but keep the schedule deterministic and independent of any
    /// off-chain clock. Reverts before `emissionStart` (the subtraction would
    /// underflow), so the schedule always starts at a known timestamp.
    /// @return The current emission year, 0-based.
    function currentYear() public view returns (uint256) {
        return (block.timestamp - emissionStart) / 365 days;
    }

    /// @notice Emission budget of `year`: `YEAR0_BUDGET >> year`.
    /// @dev The budget halves every year and is zero from year 256 on, so the
    /// schedule is finite by construction.
    /// @param year Emission year, 0-based.
    /// @return Maximum amount mintable during `year`.
    function yearBudget(uint256 year) public pure returns (uint256) {
        return YEAR0_BUDGET >> year;
    }

    /// @notice Amount still mintable in the current year.
    /// @return `yearBudget(currentYear())` minus what has already been minted.
    function remainingThisYear() external view returns (uint256) {
        uint256 year = currentYear();
        uint256 budget = yearBudget(year);
        uint256 minted = mintedByYear[year];
        return budget > minted ? budget - minted : 0;
    }
}
