const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time, setStorageAt, setBalance, impersonateAccount, stopImpersonatingAccount } =
  require('@nomicfoundation/hardhat-network-helpers');

const DAY = 24 * 60 * 60;
const YEAR = 365 * DAY;
const MAX_SUPPLY = 21_000_000n * 10n ** 18n;
const YEAR0_BUDGET = MAX_SUPPLY / 2n;
const YEAR1_BUDGET = YEAR0_BUDGET / 2n;
// Summing yearBudget(n) = YEAR0_BUDGET >> n over every year gives
// 2 * YEAR0_BUDGET - popcount(YEAR0_BUDGET). The schedule is integer-halved, so
// the discarded remainders leave exactly popcount(YEAR0_BUDGET) = 38 wei of
// headroom below MAX_SUPPLY. The invariant that matters is that the slack is
// strictly positive: the schedule alone can never mint past the cap.
const SCHEDULE_SLACK = 38n;

describe('RTM halving token and bounty vault', function () {
  let rtm, vault, owner, evaluator, attacker, outsider;

  beforeEach(async () => {
    [owner, evaluator, attacker, outsider] = await ethers.getSigners();
    const emissionStart = await time.latest();
    vault = await (await ethers.getContractFactory('BountyVault')).deploy(owner.address);
    rtm = await (await ethers.getContractFactory('RTMToken')).deploy(owner.address, vault.target, emissionStart);
    await vault.initializeRtm(rtm.target);
    await vault.setEvaluator(evaluator.address);
  });

  describe('halving schedule', function () {
    it('starts at half the cap and halves every year', async () => {
      expect(await rtm.MAX_SUPPLY()).to.equal(MAX_SUPPLY);
      expect(await rtm.YEAR0_BUDGET()).to.equal(YEAR0_BUDGET);
      expect(YEAR0_BUDGET).to.equal(10_500_000n * 10n ** 18n);
      expect(await rtm.yearBudget(0)).to.equal(10_500_000n * 10n ** 18n);
      expect(await rtm.yearBudget(1)).to.equal(5_250_000n * 10n ** 18n);
      expect(await rtm.yearBudget(2)).to.equal(2_625_000n * 10n ** 18n);
    });

    it('summing the schedule stays below the cap', async () => {
      let sum = 0n;
      for (let year = 0; year <= 30; year++) {
        sum += await rtm.yearBudget(year);
      }
      expect(sum <= MAX_SUPPLY).to.equal(true);

      // yearBudget(n) is zero from n = 256 on, so this is the complete series.
      let full = 0n;
      for (let year = 0; year < 256; year++) {
        full += await rtm.yearBudget(year);
      }
      expect(full).to.equal(MAX_SUPPLY - SCHEDULE_SLACK);
      expect(full < MAX_SUPPLY).to.equal(true);
      expect(await rtm.yearBudget(256)).to.equal(0n);
      expect(await rtm.yearBudget(1000)).to.equal(0n);
    });

    it('starts at year 0 with no premint', async () => {
      expect(await rtm.currentYear()).to.equal(0n);
      expect(await rtm.totalSupply()).to.equal(0n);
      expect(await rtm.remainingThisYear()).to.equal(YEAR0_BUDGET);
      expect(await rtm.name()).to.equal('REDTEAM');
      expect(await rtm.symbol()).to.equal('RTM');
      expect(await rtm.minter()).to.equal(vault.target);
    });

    it('rejects a zero emission start', async () => {
      const factory = await ethers.getContractFactory('RTMToken');
      await expect(factory.deploy(owner.address, vault.target, 0)).to.be.revertedWithCustomError(rtm, 'ZeroAmount');
    });

    it('requires a deployed BountyVault-bound minter', async () => {
      const factory = await ethers.getContractFactory('RTMToken');
      await expect(factory.deploy(owner.address, ethers.ZeroAddress, await time.latest()))
        .to.be.revertedWithCustomError(rtm, 'ZeroAddress');
      await expect(factory.deploy(owner.address, outsider.address, await time.latest()))
        .to.be.revertedWithCustomError(rtm, 'InvalidMinter');
    });
  });

  describe('minter authority', function () {
    it('mint is minter-only', async () => {
      await expect(rtm.connect(outsider).mint(attacker.address, 1n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
      // Ownership cannot change the immutable minter or mint through it.
      await expect(rtm.connect(owner).mint(attacker.address, 1n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
    });

    it('keeps the BountyVault as an immutable minter', async () => {
      expect(await rtm.minter()).to.equal(vault.target);
      expect(rtm.setMinter).to.equal(undefined);
      await expect(rtm.connect(outsider).mint(attacker.address, 1n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
      await expect(rtm.connect(owner).mint(attacker.address, 1n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
    });

    it('rejects zero recipients and zero amounts', async () => {
      await expect(rtm.connect(evaluator).mint(ethers.ZeroAddress, 1n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
      await expect(rtm.connect(evaluator).mint(attacker.address, 0n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
    });

    it('mints within budget only through a settled vault claim', async () => {
      const amount = 1_000n * 10n ** 18n;
      await vault.setMaxPerClaim(amount);
      await vault.connect(evaluator).configureClaim(ethers.id('direct-vault-mint'), attacker.address, amount);
      await expect(vault.connect(evaluator).settleClaim(ethers.id('direct-vault-mint')))
        .to.emit(rtm, 'EmissionMinted').withArgs(attacker.address, amount, 0n);
      expect(await rtm.totalSupply()).to.equal(amount);
      expect(await rtm.mintedByYear(0)).to.equal(amount);
      expect(await rtm.remainingThisYear()).to.equal(YEAR0_BUDGET - amount);
    });
  });

  describe('current-year reservations and explicit claim lifecycle', function () {
    it('keeps minted plus competing reservations within the year budget', async () => {
      const first = ethers.id('competing-first');
      const second = ethers.id('competing-second');
      const overflow = ethers.id('competing-overflow');
      const firstAmount = YEAR0_BUDGET * 3n / 5n;
      const secondAmount = YEAR0_BUDGET - firstAmount;
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await vault.connect(evaluator).configureClaim(first, attacker.address, firstAmount);
      await expect(vault.connect(evaluator).configureClaim(second, outsider.address, secondAmount + 1n))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable')
        .withArgs(0n, secondAmount + 1n, secondAmount);
      expect((await vault.claims(second)).configured).to.equal(false);
      expect(await vault.reservedByYear(0)).to.equal(firstAmount);
      await vault.connect(evaluator).configureClaim(second, outsider.address, secondAmount);
      expect(await vault.reservedByYear(0)).to.equal(firstAmount + secondAmount);
      expect(await rtm.mintedByYear(0) + await vault.reservedByYear(0)).to.equal(YEAR0_BUDGET);
      expect(await vault.availableCurrentYearBudget()).to.equal(0n);
      await expect(vault.connect(evaluator).configureClaim(overflow, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable').withArgs(0n, 1n, 0n);

      // Free capacity can be zero without preventing a reserved claim from settling.
      await vault.connect(evaluator).settleClaim(second);
      expect(await vault.reservedByYear(0)).to.equal(firstAmount);
      expect(await rtm.mintedByYear(0) + await vault.reservedByYear(0)).to.equal(YEAR0_BUDGET);
      expect(await vault.availableCurrentYearBudget()).to.equal(0n);
      await vault.connect(evaluator).cancelClaim(first);
      expect(await vault.availableCurrentYearBudget()).to.equal(firstAmount);
      await expect(vault.connect(evaluator).configureClaim(overflow, attacker.address, firstAmount + 1n))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable')
        .withArgs(0n, firstAmount + 1n, firstAmount);
      await vault.connect(evaluator).configureClaim(overflow, attacker.address, firstAmount);
      await vault.connect(evaluator).settleClaim(overflow);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await rtm.mintedByYear(0)).to.equal(YEAR0_BUDGET);
      expect(await rtm.balanceOf(attacker.address)).to.equal(firstAmount);
      expect(await rtm.balanceOf(outsider.address)).to.equal(secondAmount);
    });

    it('cancels exactly once without minting or consuming another claim reservation', async () => {
      const cancelled = ethers.id('cancel-release');
      const pending = ethers.id('cancel-retained');
      await vault.setMaxPerClaim(10n);
      await vault.connect(evaluator).configureClaim(cancelled, attacker.address, 3n);
      await vault.connect(evaluator).configureClaim(pending, attacker.address, 7n);
      await expect(vault.connect(evaluator).cancelClaim(cancelled))
        .to.emit(vault, 'ClaimCancelled').withArgs(cancelled, attacker.address, 3n, 0n);
      expect(await vault.reservedByYear(0)).to.equal(7n);
      expect(await vault.availableCurrentYearBudget()).to.equal(YEAR0_BUDGET - 7n);
      expect(await vault.claims(cancelled)).to.deep.equal([attacker.address, 3n, 0n, true, false, true]);
      expect(await vault.claims(pending)).to.deep.equal([attacker.address, 7n, 0n, true, false, false]);
      await expect(vault.connect(evaluator).cancelClaim(cancelled))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyCancelled');
      await expect(vault.connect(evaluator).settleClaim(cancelled))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyCancelled');
      await expect(vault.connect(evaluator).configureClaim(cancelled, attacker.address, 3n))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyConfigured');
      expect(await vault.reservedByYear(0)).to.equal(7n);
      expect(await rtm.balanceOf(attacker.address)).to.equal(0n);
      expect(await rtm.totalSupply()).to.equal(0n);
      expect(await rtm.mintedByYear(0)).to.equal(0n);
      expect(await vault.totalSettled()).to.equal(0n);
      await vault.connect(evaluator).settleClaim(pending);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await rtm.totalSupply()).to.equal(7n);
    });

    it('rejects settlement at rollover and cancels only the bound old-year reservation', async () => {
      const old = ethers.id('year0-expired');
      const fresh = ethers.id('year1-reserved');
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await vault.connect(evaluator).configureClaim(old, attacker.address, YEAR0_BUDGET);
      await time.setNextBlockTimestamp(await rtm.emissionStart() + BigInt(YEAR));
      await expect(vault.connect(evaluator).settleClaim(old))
        .to.be.revertedWithCustomError(vault, 'ClaimYearExpired').withArgs(0n, 1n);
      expect(await vault.reservedByYear(0)).to.equal(YEAR0_BUDGET);
      expect(await vault.availableCurrentYearBudget()).to.equal(YEAR1_BUDGET);
      expect(await vault.claims(old)).to.deep.equal([attacker.address, YEAR0_BUDGET, 0n, true, false, false]);
      expect(await rtm.totalSupply()).to.equal(0n);
      expect(await vault.totalSettled()).to.equal(0n);
      await vault.connect(evaluator).configureClaim(fresh, outsider.address, YEAR1_BUDGET);
      await expect(vault.connect(evaluator).cancelClaim(old))
        .to.emit(vault, 'ClaimCancelled').withArgs(old, attacker.address, YEAR0_BUDGET, 0n);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await vault.reservedByYear(1)).to.equal(YEAR1_BUDGET);
      expect(await vault.availableCurrentYearBudget()).to.equal(0n);
      await expect(vault.connect(evaluator).configureClaim(old, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyConfigured');
      await vault.connect(evaluator).settleClaim(fresh);
      expect(await rtm.mintedByYear(0)).to.equal(0n);
      expect(await rtm.mintedByYear(1)).to.equal(YEAR1_BUDGET);
      expect(await vault.reservedByYear(1)).to.equal(0n);
    });

    it('settles in the last second of a year and binds an exact-boundary configuration to the new year', async () => {
      const before = ethers.id('last-second');
      const after = ethers.id('first-second');
      const boundary = await rtm.emissionStart() + BigInt(YEAR);
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await time.setNextBlockTimestamp(boundary - 2n);
      await vault.connect(evaluator).configureClaim(before, attacker.address, 5n);
      await time.setNextBlockTimestamp(boundary - 1n);
      await expect(vault.connect(evaluator).settleClaim(before))
        .to.emit(vault, 'ClaimSettled').withArgs(before, attacker.address, 5n, 0n);
      await time.setNextBlockTimestamp(boundary);
      await expect(vault.connect(evaluator).configureClaim(after, attacker.address, YEAR1_BUDGET))
        .to.emit(vault, 'ClaimConfigured').withArgs(after, attacker.address, YEAR1_BUDGET, 1n);
      expect((await vault.claims(after)).emissionYear).to.equal(1n);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await vault.reservedByYear(1)).to.equal(YEAR1_BUDGET);
      expect(await rtm.mintedByYear(0)).to.equal(5n);
      expect(await rtm.mintedByYear(1)).to.equal(0n);
      expect(await vault.availableCurrentYearBudget()).to.equal(0n);
    });

    it('pause does not extend a claim year even when its amount fits the next year', async () => {
      const id = ethers.id('paused-rollover');
      await vault.setMaxPerClaim(15n);
      await vault.connect(evaluator).configureClaim(id, attacker.address, 15n);
      await vault.pause();
      await time.increaseTo(await rtm.emissionStart() + BigInt(YEAR));
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'EnforcedPause');
      await expect(vault.connect(evaluator).cancelClaim(id))
        .to.be.revertedWithCustomError(vault, 'EnforcedPause');
      expect(await vault.reservedByYear(0)).to.equal(15n);
      expect(await vault.availableCurrentYearBudget()).to.equal(YEAR1_BUDGET);
      await vault.unpause();
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimYearExpired').withArgs(0n, 1n);
      await vault.connect(evaluator).cancelClaim(id);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await vault.reservedByYear(1)).to.equal(0n);
      expect(await vault.availableCurrentYearBudget()).to.equal(YEAR1_BUDGET);
      expect(await rtm.totalSupply()).to.equal(0n);
    });

    it('rotation preserves reservations and moves every claim operation to the new evaluator', async () => {
      const paid = ethers.id('rotated-settle');
      const cancelled = ethers.id('rotated-cancel');
      await vault.setMaxPerClaim(10n);
      await vault.connect(evaluator).configureClaim(paid, attacker.address, 3n);
      await vault.connect(evaluator).configureClaim(cancelled, attacker.address, 7n);
      await vault.setEvaluator(outsider.address);
      expect(await vault.reservedByYear(0)).to.equal(10n);
      await expect(vault.connect(evaluator).configureClaim(ethers.id('stale-key'), attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      await expect(vault.connect(evaluator).settleClaim(paid))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      await expect(vault.connect(evaluator).cancelClaim(cancelled))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      await vault.connect(outsider).settleClaim(paid);
      expect(await vault.reservedByYear(0)).to.equal(7n);
      await vault.connect(outsider).cancelClaim(cancelled);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await vault.totalSettled()).to.equal(3n);
      expect(await rtm.totalSupply()).to.equal(3n);
    });

    it('does not promise a claim before RTM emission starts', async () => {
      const start = await time.latest() + DAY;
      const futureVault = await (await ethers.getContractFactory('BountyVault')).deploy(owner.address);
      const futureRtm = await (await ethers.getContractFactory('RTMToken'))
        .deploy(owner.address, futureVault.target, start);
      await futureVault.initializeRtm(futureRtm.target);
      await futureVault.setEvaluator(evaluator.address);
      await futureVault.setMaxPerClaim(1n);
      const id = ethers.id('future-start');
      // Preserve RTMToken's existing pre-start arithmetic guard, without changing its ABI.
      await expect(futureVault.availableCurrentYearBudget()).to.be.revertedWithPanic(0x11);
      await expect(futureVault.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithPanic(0x11);
      expect((await futureVault.claims(id)).configured).to.equal(false);
      expect(await futureVault.reservedByYear(0)).to.equal(0n);
      expect(await futureRtm.totalSupply()).to.equal(0n);
      await time.setNextBlockTimestamp(start);
      await expect(futureVault.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.emit(futureVault, 'ClaimConfigured').withArgs(id, attacker.address, 1n, 0n);
      await futureVault.connect(evaluator).settleClaim(id);
      expect(await futureRtm.totalSupply()).to.equal(1n);
    });

    it('rejects configuration in a zero-budget year without underflow or partial claims', async () => {
      const id = ethers.id('zero-budget');
      await vault.setMaxPerClaim(1n);
      await time.increaseTo(await rtm.emissionStart() + 256n * BigInt(YEAR));
      expect(await rtm.currentYear()).to.equal(256n);
      expect(await vault.availableCurrentYearBudget()).to.equal(0n);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable').withArgs(256n, 1n, 0n);
      expect((await vault.claims(id)).configured).to.equal(false);
      expect(await vault.reservedByYear(256)).to.equal(0n);
      expect(await rtm.totalSupply()).to.equal(0n);
    });

    it('rechecks the bound year budget before settlement and saturates availability safely', async () => {
      const id = ethers.id('budget-fault');
      await vault.setMaxPerClaim(5n);
      await vault.connect(evaluator).configureClaim(id, attacker.address, 5n);
      // Fault injection only: production cannot sign transactions as the vault.
      // Consume budget outside its reservation path to exercise the defensive check.
      await impersonateAccount(vault.target);
      try {
        await setBalance(vault.target, ethers.parseEther('1'));
        const vaultSigner = await ethers.getSigner(vault.target);
        await rtm.connect(vaultSigner).mint(outsider.address, YEAR0_BUDGET - 4n);
        await expect(rtm.connect(vaultSigner).mint(attacker.address, 5n))
          .to.be.revertedWithCustomError(rtm, 'YearBudgetExceeded').withArgs(0n, 5n, 4n);
      } finally {
        await stopImpersonatingAccount(vault.target);
        await setBalance(vault.target, 0n);
      }
      expect(await rtm.remainingThisYear()).to.equal(4n);
      expect(await vault.availableCurrentYearBudget()).to.equal(0n);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable').withArgs(0n, 5n, 4n);
      expect(await vault.claims(id)).to.deep.equal([attacker.address, 5n, 0n, true, false, false]);
      expect(await vault.reservedByYear(0)).to.equal(5n);
      expect(await vault.totalSettled()).to.equal(0n);
      expect(await rtm.balanceOf(attacker.address)).to.equal(0n);
      await vault.connect(evaluator).cancelClaim(id);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await vault.availableCurrentYearBudget()).to.equal(4n);
    });

    it('rolls back claim state, reservation, totals, and mint effects when RTM mint fails', async () => {
      const paid = ethers.id('mint-fault-baseline');
      const id = ethers.id('mint-fault');
      const other = ethers.id('mint-fault-other');
      await vault.setMaxPerClaim(20n);
      await vault.connect(evaluator).configureClaim(paid, attacker.address, 1n);
      await vault.connect(evaluator).settleClaim(paid);
      await vault.connect(evaluator).configureClaim(id, attacker.address, 10n);
      await vault.connect(evaluator).configureClaim(other, attacker.address, 20n);
      const before = await vault.claims(id);
      const otherBefore = await vault.claims(other);
      const supplyBefore = await rtm.totalSupply();
      const mintedBefore = await rtm.mintedByYear(0);
      const availableBefore = await vault.availableCurrentYearBudget();
      // Fault injection only. OpenZeppelin ERC20 uses slot 2 for _totalSupply
      // after balances/allowances. Assert the injected value, then restore it.
      // Year-budget checks still pass, so the revert is from the real RTM.mint.
      const totalSupplySlot = 2n;
      try {
        await setStorageAt(rtm.target, totalSupplySlot, MAX_SUPPLY);
        expect(await rtm.totalSupply()).to.equal(MAX_SUPPLY);
        await expect(vault.connect(evaluator).settleClaim(id))
          .to.be.revertedWithCustomError(rtm, 'MaxSupplyExceeded').withArgs(10n, 0n);
        expect(await vault.claims(id)).to.deep.equal(before);
        expect(await vault.claims(other)).to.deep.equal(otherBefore);
        expect(await vault.reservedByYear(0)).to.equal(30n);
        expect(await vault.availableCurrentYearBudget()).to.equal(availableBefore);
        expect(await vault.totalSettled()).to.equal(supplyBefore);
        expect(await rtm.mintedByYear(0)).to.equal(mintedBefore);
        expect(await rtm.balanceOf(attacker.address)).to.equal(supplyBefore);
        expect(await rtm.totalSupply()).to.equal(MAX_SUPPLY);
      } finally {
        await setStorageAt(rtm.target, totalSupplySlot, supplyBefore);
      }
      // The failed attempt did not consume the id or its reservation.
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.emit(vault, 'ClaimSettled').withArgs(id, attacker.address, 10n, 0n);
      expect(await vault.reservedByYear(0)).to.equal(20n);
      expect(await vault.totalSettled()).to.equal(supplyBefore + 10n);
      expect(await rtm.totalSupply()).to.equal(supplyBefore + 10n);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadySettled');
      expect(await vault.reservedByYear(0)).to.equal(20n);
    });
  });

  describe('bounty vault settlement against the emission schedule', function () {
    it('requires owner initialization and rejects rebinding', async () => {
      const uninitialized = await (await ethers.getContractFactory('BountyVault')).deploy(owner.address);
      const uninitializedRtm = await (await ethers.getContractFactory('RTMToken'))
        .deploy(owner.address, uninitialized.target, await time.latest());
      const id = ethers.id('before-init');
      await uninitialized.setEvaluator(evaluator.address);
      await uninitialized.setMaxPerClaim(1n);
      await expect(uninitialized.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(uninitialized, 'RtmNotInitialized');
      await expect(uninitialized.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(uninitialized, 'RtmNotInitialized');
      await expect(uninitialized.availableCurrentYearBudget())
        .to.be.revertedWithCustomError(uninitialized, 'RtmNotInitialized');
      await expect(uninitialized.initializeRtm(ethers.ZeroAddress))
        .to.be.revertedWithCustomError(uninitialized, 'ZeroAddress');
      await expect(uninitialized.initializeRtm(rtm.target))
        .to.be.revertedWithCustomError(uninitialized, 'ZeroAddress');
      await expect(uninitialized.connect(outsider).initializeRtm(uninitializedRtm.target))
        .to.be.revertedWithCustomError(uninitialized, 'OwnableUnauthorizedAccount');
      await uninitialized.initializeRtm(uninitializedRtm.target);
      await expect(uninitialized.initializeRtm(uninitializedRtm.target))
        .to.be.revertedWithCustomError(uninitialized, 'RtmAlreadyInitialized');
    });

    it('pays the configured claim to the beneficiary', async () => {
      const id = ethers.id('bounty-1');
      const amount = 1_000n * 10n ** 18n;
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, amount))
        .to.emit(vault, 'ClaimConfigured').withArgs(id, attacker.address, amount, 0n);
      const claim = await vault.claims(id);
      expect(claim.beneficiary).to.equal(attacker.address);
      expect(claim.amount).to.equal(amount);
      expect(claim.emissionYear).to.equal(0n);
      expect(claim.configured).to.equal(true);
      expect(claim.settled).to.equal(false);
      expect(claim.cancelled).to.equal(false);
      expect(await vault.reservedByYear(0)).to.equal(amount);
      expect(await vault.availableCurrentYearBudget()).to.equal(YEAR0_BUDGET - amount);
      expect(await rtm.balanceOf(attacker.address)).to.equal(0n);
      expect(await rtm.totalSupply()).to.equal(0n);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.emit(vault, 'ClaimSettled').withArgs(id, attacker.address, amount, 0n);
      expect(await rtm.balanceOf(attacker.address)).to.equal(amount);
      expect(await vault.totalSettled()).to.equal(amount);
      expect(await vault.reservedByYear(0)).to.equal(0n);
    });

    it('reserves the full current-year budget and rejects competing claims', async () => {
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      const full = ethers.id('claim-full-year0');
      await expect(vault.connect(evaluator).configureClaim(full, attacker.address, YEAR0_BUDGET))
        .to.emit(vault, 'ClaimConfigured').withArgs(full, attacker.address, YEAR0_BUDGET, 0n);
      expect(await vault.reservedByYear(0)).to.equal(YEAR0_BUDGET);
      expect(await vault.availableCurrentYearBudget()).to.equal(0n);

      const oneWei = ethers.id('claim-one-wei');
      await expect(vault.connect(evaluator).configureClaim(oneWei, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable')
        .withArgs(0n, 1n, 0n);
      expect(await rtm.totalSupply()).to.equal(0n);
      expect(await vault.totalSettled()).to.equal(0n);

      await expect(vault.connect(evaluator).settleClaim(full))
        .to.emit(vault, 'ClaimSettled').withArgs(full, attacker.address, YEAR0_BUDGET, 0n);
      expect(await rtm.balanceOf(attacker.address)).to.equal(YEAR0_BUDGET);
      expect(await rtm.totalSupply()).to.equal(YEAR0_BUDGET);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await rtm.remainingThisYear()).to.equal(0n);
      expect(await vault.availableCurrentYearBudget()).to.equal(0n);
      await expect(vault.connect(evaluator).configureClaim(oneWei, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable')
        .withArgs(0n, 1n, 0n);
      expect((await vault.claims(oneWei)).configured).to.equal(false);
      expect(await vault.totalSettled()).to.equal(YEAR0_BUDGET);
    });

    it('the next year restores a halved budget', async () => {
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      const year0 = ethers.id('y0-full');
      await vault.connect(evaluator).configureClaim(year0, attacker.address, YEAR0_BUDGET);
      await vault.connect(evaluator).settleClaim(year0);

      await time.increase(YEAR);
      expect(await rtm.currentYear()).to.equal(1n);
      expect(await rtm.remainingThisYear()).to.equal(YEAR1_BUDGET);

      // The token's new budget is available only to newly configured claims.
      const over = ethers.id('y1-over');
      await expect(vault.connect(evaluator).configureClaim(over, attacker.address, YEAR1_BUDGET + 1n))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable')
        .withArgs(1n, YEAR1_BUDGET + 1n, YEAR1_BUDGET);
      expect((await vault.claims(over)).configured).to.equal(false);
      expect(await vault.reservedByYear(1)).to.equal(0n);

      // ...while the exact remaining budget still settles.
      const exact = ethers.id('y1-exact');
      await vault.connect(evaluator).configureClaim(exact, attacker.address, YEAR1_BUDGET);
      await expect(vault.connect(evaluator).settleClaim(exact))
        .to.emit(vault, 'ClaimSettled').withArgs(exact, attacker.address, YEAR1_BUDGET, 1n);
      expect(await rtm.totalSupply()).to.equal(YEAR0_BUDGET + YEAR1_BUDGET);
      expect(await rtm.totalSupply() < MAX_SUPPLY).to.equal(true);
    });

    it('settles and releases a reservation exactly once without touching other claims', async () => {
      const id = ethers.id('one-shot');
      const other = ethers.id('one-shot-other');
      const amount = 5n;
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await vault.connect(evaluator).configureClaim(id, attacker.address, amount);
      await vault.connect(evaluator).configureClaim(other, attacker.address, 7n);
      expect(await vault.reservedByYear(0)).to.equal(amount + 7n);
      await vault.connect(evaluator).settleClaim(id);
      expect(await vault.reservedByYear(0)).to.equal(7n);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadySettled');
      await expect(vault.connect(evaluator).cancelClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadySettled');
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, amount))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyConfigured');
      expect(await vault.reservedByYear(0)).to.equal(7n);
      expect(await vault.totalSettled()).to.equal(amount);
      expect(await rtm.mintedByYear(0)).to.equal(amount);
      expect(await rtm.balanceOf(attacker.address)).to.equal(amount);
      expect(await vault.claims(id)).to.deep.equal([attacker.address, amount, 0n, true, true, false]);
    });

    it('configuration is one-shot and must exist before settlement or cancellation', async () => {
      const id = ethers.id('configured-once');
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimNotConfigured');
      await expect(vault.connect(evaluator).cancelClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimNotConfigured');
      await vault.connect(evaluator).configureClaim(id, attacker.address, 1n);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyConfigured');
      await vault.connect(evaluator).cancelClaim(id);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyConfigured');
      await expect(vault.connect(evaluator).cancelClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyCancelled');
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyCancelled');
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await rtm.totalSupply()).to.equal(0n);
      expect(await vault.totalSettled()).to.equal(0n);
    });

    it('configure, settle, and cancel are evaluator-only, not owner or beneficiary operations', async () => {
      const id = ethers.id('authz');
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      for (const caller of [outsider, owner, attacker]) {
        await expect(vault.connect(caller).configureClaim(id, attacker.address, 1n))
          .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      }
      await vault.connect(evaluator).configureClaim(id, attacker.address, 1n);
      for (const caller of [outsider, owner, attacker]) {
        await expect(vault.connect(caller).settleClaim(id))
          .to.be.revertedWithCustomError(vault, 'NotEvaluator');
        await expect(vault.connect(caller).cancelClaim(id))
          .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      }
      expect(await vault.reservedByYear(0)).to.equal(1n);
      expect(await vault.claims(id)).to.deep.equal([attacker.address, 1n, 0n, true, false, false]);
    });

    it('rejects zero ids, zero beneficiaries and zero amounts', async () => {
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await expect(vault.connect(evaluator).configureClaim(ethers.ZeroHash, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'ZeroAddress');
      await expect(vault.connect(evaluator).configureClaim(ethers.id('z'), ethers.ZeroAddress, 1n))
        .to.be.revertedWithCustomError(vault, 'ZeroAddress');
      await expect(vault.connect(evaluator).configureClaim(ethers.id('z'), attacker.address, 0n))
        .to.be.revertedWithCustomError(vault, 'ZeroAmount');
    });

    it('enforces the per-claim cap, including after it is lowered, while cancel still releases', async () => {
      const id = ethers.id('cap');
      await vault.setMaxPerClaim(10n);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, 11n))
        .to.be.revertedWithCustomError(vault, 'ClaimTooLarge');
      await vault.connect(evaluator).configureClaim(id, attacker.address, 10n);
      await vault.setMaxPerClaim(5n);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimTooLarge');
      expect((await vault.claims(id)).settled).to.equal(false);
      expect(await vault.reservedByYear(0)).to.equal(10n);
      await vault.connect(evaluator).cancelClaim(id);
      expect(await vault.reservedByYear(0)).to.equal(0n);
      await expect(vault.connect(owner).setMaxPerClaim(0n))
        .to.be.revertedWithCustomError(vault, 'ZeroAmount');
    });

    it('only the owner can rotate the evaluator or the cap', async () => {
      await expect(vault.connect(outsider).setEvaluator(outsider.address))
        .to.be.revertedWithCustomError(vault, 'OwnableUnauthorizedAccount');
      await expect(vault.connect(outsider).setMaxPerClaim(1n))
        .to.be.revertedWithCustomError(vault, 'OwnableUnauthorizedAccount');
      await expect(vault.setEvaluator(ethers.ZeroAddress))
        .to.be.revertedWithCustomError(vault, 'ZeroAddress');
      await expect(vault.setEvaluator(outsider.address))
        .to.emit(vault, 'EvaluatorUpdated').withArgs(evaluator.address, outsider.address);
      await expect(vault.setMaxPerClaim(42n))
        .to.emit(vault, 'MaxPerClaimUpdated').withArgs(0n, 42n);
      expect(await vault.maxPerClaim()).to.equal(42n);
    });

    it('pause blocks configure, settle, and cancel without releasing reservations', async () => {
      const id = ethers.id('paused');
      const cancelled = ethers.id('paused-cancel');
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await vault.pause();
      expect(await vault.paused()).to.equal(true);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'EnforcedPause');
      await vault.unpause();
      await vault.connect(evaluator).configureClaim(id, attacker.address, 1n);
      await vault.connect(evaluator).configureClaim(cancelled, attacker.address, 2n);
      await vault.pause();
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'EnforcedPause');
      await expect(vault.connect(evaluator).cancelClaim(cancelled))
        .to.be.revertedWithCustomError(vault, 'EnforcedPause');
      expect(await vault.reservedByYear(0)).to.equal(3n);
      expect(await vault.availableCurrentYearBudget()).to.equal(YEAR0_BUDGET - 3n);
      expect(await rtm.totalSupply()).to.equal(0n);
      expect(await vault.totalSettled()).to.equal(0n);
      await vault.unpause();
      await expect(vault.connect(evaluator).settleClaim(id)).to.emit(vault, 'ClaimSettled');
      await expect(vault.connect(evaluator).cancelClaim(cancelled)).to.emit(vault, 'ClaimCancelled');
      expect(await vault.reservedByYear(0)).to.equal(0n);
      expect(await rtm.totalSupply()).to.equal(1n);
      await expect(vault.connect(outsider).pause())
        .to.be.revertedWithCustomError(vault, 'OwnableUnauthorizedAccount');
      await expect(vault.connect(outsider).unpause())
        .to.be.revertedWithCustomError(vault, 'OwnableUnauthorizedAccount');
    });
  });
});
