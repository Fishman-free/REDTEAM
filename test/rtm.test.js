const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');

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

    it('requires a non-zero BountyVault-bound minter', async () => {
      const factory = await ethers.getContractFactory('RTMToken');
      await expect(factory.deploy(owner.address, ethers.ZeroAddress, await time.latest()))
        .to.be.revertedWithCustomError(rtm, 'ZeroAddress');
    });
  });

  describe('minter authority', function () {
    it('mint is minter-only', async () => {
      await expect(rtm.connect(outsider).mint(attacker.address, 1n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
      // The owner governs the minter role but does not mint through it.
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
        .to.emit(vault, 'ClaimConfigured').withArgs(id, attacker.address, amount);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.emit(vault, 'ClaimSettled').withArgs(id, attacker.address, amount, 0n);
      expect(await rtm.balanceOf(attacker.address)).to.equal(amount);
      expect(await vault.totalSettled()).to.equal(amount);
    });

    it('a full year-0 payout exhausts the year for everyone', async () => {
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      const full = ethers.id('claim-full-year0');
      await vault.connect(evaluator).configureClaim(full, attacker.address, YEAR0_BUDGET);
      await expect(vault.connect(evaluator).settleClaim(full))
        .to.emit(vault, 'ClaimSettled').withArgs(full, attacker.address, YEAR0_BUDGET, 0n);
      expect(await rtm.balanceOf(attacker.address)).to.equal(YEAR0_BUDGET);
      expect(await rtm.totalSupply()).to.equal(YEAR0_BUDGET);
      expect(await rtm.remainingThisYear()).to.equal(0n);

      const oneWei = ethers.id('claim-one-wei');
      await vault.connect(evaluator).configureClaim(oneWei, attacker.address, 1n);
      await expect(vault.connect(evaluator).settleClaim(oneWei))
        .to.be.revertedWithCustomError(rtm, 'YearBudgetExceeded')
        .withArgs(0n, 1n, 0n);

      // The budget check happens inside the token, so the whole call reverts
      // and the claim stays configured but un-settled: deferred, not lost.
      const claim = await vault.claims(oneWei);
      expect(claim.configured).to.equal(true);
      expect(claim.settled).to.equal(false);
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

      // One wei over the year-1 budget is refused...
      const over = ethers.id('y1-over');
      await vault.connect(evaluator).configureClaim(over, attacker.address, YEAR1_BUDGET + 1n);
      await expect(vault.connect(evaluator).settleClaim(over))
        .to.be.revertedWithCustomError(rtm, 'YearBudgetExceeded')
        .withArgs(1n, YEAR1_BUDGET + 1n, YEAR1_BUDGET);

      // ...while the exact remaining budget still settles.
      const exact = ethers.id('y1-exact');
      await vault.connect(evaluator).configureClaim(exact, attacker.address, YEAR1_BUDGET);
      await expect(vault.connect(evaluator).settleClaim(exact))
        .to.emit(vault, 'ClaimSettled').withArgs(exact, attacker.address, YEAR1_BUDGET, 1n);
      expect(await rtm.totalSupply()).to.equal(YEAR0_BUDGET + YEAR1_BUDGET);
      expect(await rtm.totalSupply() < MAX_SUPPLY).to.equal(true);
    });

    it('settlement is one-shot', async () => {
      const id = ethers.id('one-shot');
      const amount = 5n;
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await vault.connect(evaluator).configureClaim(id, attacker.address, amount);
      await vault.connect(evaluator).settleClaim(id);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadySettled');
      expect(await rtm.balanceOf(attacker.address)).to.equal(amount);
    });

    it('configuration is one-shot and must exist before settlement', async () => {
      const id = ethers.id('configured-once');
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimNotConfigured');
      await vault.connect(evaluator).configureClaim(id, attacker.address, 1n);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'ClaimAlreadyConfigured');
    });

    it('both configure and settle are evaluator-only', async () => {
      const id = ethers.id('authz');
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await expect(vault.connect(outsider).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      // The owner governs the evaluator role but is not the evaluator here.
      await expect(vault.connect(owner).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      await vault.connect(evaluator).configureClaim(id, attacker.address, 1n);
      await expect(vault.connect(outsider).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      await expect(vault.connect(owner).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
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

    it('enforces the per-claim cap, including after it is lowered', async () => {
      const id = ethers.id('cap');
      await vault.setMaxPerClaim(10n);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, 11n))
        .to.be.revertedWithCustomError(vault, 'ClaimTooLarge');
      await vault.connect(evaluator).configureClaim(id, attacker.address, 10n);
      await vault.setMaxPerClaim(5n);
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimTooLarge');
      expect((await vault.claims(id)).settled).to.equal(false);
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

    it('pause blocks configure and settle until unpaused', async () => {
      const id = ethers.id('paused');
      await vault.setMaxPerClaim(YEAR0_BUDGET);
      await vault.pause();
      expect(await vault.paused()).to.equal(true);
      await expect(vault.connect(evaluator).configureClaim(id, attacker.address, 1n))
        .to.be.revertedWithCustomError(vault, 'EnforcedPause');
      await vault.unpause();
      await vault.connect(evaluator).configureClaim(id, attacker.address, 1n);
      await vault.pause();
      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'EnforcedPause');
      await vault.unpause();
      await expect(vault.connect(evaluator).settleClaim(id)).to.emit(vault, 'ClaimSettled');
      await expect(vault.connect(outsider).pause())
        .to.be.revertedWithCustomError(vault, 'OwnableUnauthorizedAccount');
    });
  });
});
