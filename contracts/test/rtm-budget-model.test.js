const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');

const YEAR = 365 * 24 * 60 * 60;
const YEAR0_BUDGET = 10_500_000n * 10n ** 18n;

describe('RTM reservation accounting against an independent state model', () => {
  it('preserves yearly budgets and claim terminal states across mixed operations and rollovers', async () => {
    const [owner, evaluator, beneficiary] = await ethers.getSigners();
    const vault = await (await ethers.getContractFactory('BountyVault')).deploy(owner.address);
    const start = await time.latest();
    const token = await (await ethers.getContractFactory('RTMToken'))
      .deploy(owner.address, vault.target, start);
    await vault.initializeRtm(token.target);
    await vault.setEvaluator(evaluator.address);
    await vault.setMaxPerClaim(YEAR0_BUDGET);

    const claims = [];
    const minted = [0n, 0n, 0n];
    let seed = 0x5eed;
    const next = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed;
    };
    const reserved = year => claims
      .filter(claim => claim.year === year && claim.state === 'pending')
      .reduce((sum, claim) => sum + claim.amount, 0n);
    const check = async () => {
      let total = 0n;
      for (let year = 0; year < minted.length; year++) {
        const pending = reserved(year);
        expect(await vault.reservedByYear(year)).to.equal(pending);
        expect(await token.mintedByYear(year)).to.equal(minted[year]);
        expect(minted[year] + pending <= (YEAR0_BUDGET >> BigInt(year))).to.equal(true);
        total += minted[year];
      }
      expect(await token.totalSupply()).to.equal(total);
      expect(await token.balanceOf(beneficiary.address)).to.equal(total);
      expect(await vault.totalSettled()).to.equal(total);
      const currentYear = Number(await token.currentYear());
      expect(await vault.availableCurrentYearBudget()).to.equal(
        (YEAR0_BUDGET >> BigInt(currentYear)) - minted[currentYear] - reserved(currentYear));
      for (const claim of claims) {
        const onchain = await vault.claims(claim.id);
        expect(onchain.emissionYear).to.equal(BigInt(claim.year));
        expect(onchain.configured).to.equal(true);
        expect(onchain.amount).to.equal(claim.amount);
        expect(onchain.settled).to.equal(claim.state === 'settled');
        expect(onchain.cancelled).to.equal(claim.state === 'cancelled');
      }
    };

    for (let year = 0; year < minted.length; year++) {
      if (year) await time.increaseTo(start + year * YEAR);
      expect(await token.currentYear()).to.equal(BigInt(year));
      for (const expired of claims.filter(claim => claim.year < year && claim.state === 'pending')) {
        await expect(vault.connect(evaluator).settleClaim(expired.id)).to.be.reverted;
        await check();
        await vault.connect(evaluator).cancelClaim(expired.id);
        expired.state = 'cancelled';
        await check();
      }
      const budget = YEAR0_BUDGET >> BigInt(year);
      for (let step = 0; step < 18; step++) {
        const pending = claims.filter(claim => claim.year === year && claim.state === 'pending');
        if (pending.length && step % 3 !== 2) {
          const claim = pending[next() % pending.length];
          if (step % 3 === 0) {
            await vault.connect(evaluator).cancelClaim(claim.id);
            claim.state = 'cancelled';
          } else {
            await vault.connect(evaluator).settleClaim(claim.id);
            claim.state = 'settled';
            minted[year] += claim.amount;
          }
          await expect(vault.connect(evaluator).settleClaim(claim.id)).to.be.reverted;
          await expect(vault.connect(evaluator).cancelClaim(claim.id)).to.be.reverted;
          await expect(vault.connect(evaluator).configureClaim(claim.id, beneficiary.address, 1n))
            .to.be.reverted;
        } else {
          const available = budget - minted[year] - reserved(year);
          const amount = step % 5 === 0 ? available + 1n : budget / BigInt(8 + next() % 9);
          const id = ethers.id(`model-${year}-${step}`);
          if (amount > available) {
            await expect(vault.connect(evaluator).configureClaim(id, beneficiary.address, amount))
              .to.be.reverted;
            expect((await vault.claims(id)).configured).to.equal(false);
          } else {
            await vault.connect(evaluator).configureClaim(id, beneficiary.address, amount);
            claims.push({ id, year, amount, state: 'pending' });
          }
        }
        await check();
      }
    }
    for (const claim of claims.filter(claim => claim.state === 'pending')) {
      await vault.connect(evaluator).cancelClaim(claim.id);
      claim.state = 'cancelled';
    }
    await check();
    expect(claims.some(claim => claim.state === 'settled')).to.equal(true);
    expect(claims.some(claim => claim.state === 'cancelled')).to.equal(true);
  });
});
