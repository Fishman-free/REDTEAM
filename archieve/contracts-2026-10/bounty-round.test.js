/**
 * BountyRound commit–reveal tests (ATTACK_INTERFACE_DESIGN §3, minimal prototype).
 *
 * Under test: commitment binding and timeout, first-come priority per material
 * hash, verifier-only finalization after close, and pull-mode payouts that only
 * the committer can claim. Red line: attackers cannot finalize, fund, or open
 * rounds.
 */
const { expect } = require('chai');
const { time } = require('@nomicfoundation/hardhat-network-helpers');
const { ethers } = require('hardhat');

const CLOSE_DELAY = 3600;

function materialHashOf(content) {
  return ethers.keccak256(ethers.toUtf8Bytes(content));
}

describe('BountyRound commit-reveal', function () {
  let owner, verifier, attackerA, attackerB;
  let round;

  beforeEach(async function () {
    [owner, verifier, attackerA, attackerB] = await ethers.getSigners();
    round = await (await ethers.getContractFactory('BountyRound'))
      .connect(owner).deploy(owner.address);
    await round.waitForDeployment();
  });

  async function openRound(roundId, closeDelay = CLOSE_DELAY) {
    await (await round.connect(owner).commitRound(
      roundId, ethers.id('target-v0'), ethers.id('spec-v1'),
      BigInt((await time.latest()) + closeDelay))).wait();
  }

  it('handles the full commit, finalize and pull-payout flow', async function () {
    const roundId = ethers.id('round-1');
    const material = materialHashOf(JSON.stringify({ actions: [1, 2, 3], mechanism: 'extra_fee' }));
    await openRound(roundId);
    await (await round.connect(attackerA).submitClaim(roundId, material)).wait();

    // Fund and finalize after the round closes.
    const reward = ethers.parseEther('1.5');
    await (await round.connect(owner).fundRound(roundId, { value: reward })).wait();
    await time.increaseTo((await time.latest()) + CLOSE_DELAY + 1);
    await expect(round.connect(verifier).finalizeRound(roundId, [material], [true], [reward]))
      .to.be.revertedWithCustomError(round, 'OwnableUnauthorizedAccount');
    await (await round.connect(owner)
      .finalizeRound(roundId, [material], [true], [reward])).wait();

    // Pull mode: only the committer, exactly once, to the committing address.
    await expect(round.connect(attackerB).claimPayout(roundId, material))
      .to.be.revertedWithCustomError(round, 'NotBeneficiary');
    const before = await ethers.provider.getBalance(attackerA.address);
    await expect(round.connect(attackerA).claimPayout(roundId, material))
      .to.emit(round, 'PayoutClaimed').withArgs(roundId, material, attackerA.address, reward);
    const after = await ethers.provider.getBalance(attackerA.address);
    expect(after).to.be.greaterThan(before);
    await expect(round.connect(attackerA).claimPayout(roundId, material))
      .to.be.revertedWithCustomError(round, 'AlreadyPaid');
  });

  it('gives first-come priority and rejects duplicate material', async function () {
    const roundId = ethers.id('round-2');
    const material = materialHashOf('same mechanism, same material');
    await openRound(roundId);
    await (await round.connect(attackerA).submitClaim(roundId, material)).wait();
    await expect(round.connect(attackerB).submitClaim(roundId, material))
      .to.be.revertedWithCustomError(round, 'DuplicateMaterial');
    expect(await round.firstCommitter(roundId, material)).to.equal(attackerA.address);
  });

  it('enforces the submission timeout and single-use round ids', async function () {
    const roundId = ethers.id('round-3');
    await openRound(roundId, 60);
    await time.increaseTo((await time.latest()) + 61);
    await expect(round.connect(attackerA).submitClaim(roundId, materialHashOf('late')))
      .to.be.revertedWithCustomError(round, 'RoundClosed');
    await expect(round.connect(owner).commitRound(
      roundId, ethers.id('v'), ethers.id('s'), BigInt((await time.latest()) + 60)))
      .to.be.revertedWithCustomError(round, 'RoundExists');
  });

  it('refuses finalization before the deadline and pays only valid findings', async function () {
    const roundId = ethers.id('round-4');
    const good = materialHashOf('good finding');
    const bad = materialHashOf('invalid finding');
    await openRound(roundId);
    await (await round.connect(attackerA).submitClaim(roundId, good)).wait();
    await (await round.connect(attackerB).submitClaim(roundId, bad)).wait();
    const reward = ethers.parseEther('0.5');
    await (await round.connect(owner).fundRound(roundId, { value: reward * 2n })).wait();

    await expect(round.connect(owner).finalizeRound(roundId, [good], [true], [reward]))
      .to.be.revertedWithCustomError(round, 'RoundStillOpen');
    await time.increaseTo((await time.latest()) + CLOSE_DELAY + 1);
    await (await round.connect(owner)
      .finalizeRound(roundId, [good, bad], [true, false], [reward, reward])).wait();

    await expect(round.connect(attackerB).claimPayout(roundId, bad))
      .to.be.revertedWithCustomError(round, 'NotPayable');
    await expect(round.connect(attackerA).claimPayout(roundId, materialHashOf('never submitted')))
      .to.be.revertedWithCustomError(round, 'NotPayable');
    await expect(round.connect(attackerA).claimPayout(roundId, good))
      .to.emit(round, 'PayoutClaimed');
  });

  it('caps the approved total at the funded pool', async function () {
    const roundId = ethers.id('round-5');
    const a = materialHashOf('a');
    const b = materialHashOf('b');
    await openRound(roundId);
    await (await round.connect(attackerA).submitClaim(roundId, a)).wait();
    await (await round.connect(attackerB).submitClaim(roundId, b)).wait();
    await (await round.connect(owner).fundRound(roundId, { value: ethers.parseEther('1') })).wait();
    await time.increaseTo((await time.latest()) + CLOSE_DELAY + 1);
    await expect(round.connect(owner)
      .finalizeRound(roundId, [a, b], [true, true],
                     [ethers.parseEther('0.8'), ethers.parseEther('0.8')]))
      .to.be.revertedWithCustomError(round, 'InsufficientPool');
    // The round is NOT finalized by the failed attempt; a fitting approval succeeds.
    await (await round.connect(owner)
      .finalizeRound(roundId, [a, b], [true, true],
                     [ethers.parseEther('0.5'), ethers.parseEther('0.5')])).wait();
  });

  it('rejects unknown rounds and malformed finalizations', async function () {
    const unknown = ethers.id('never-opened');
    await expect(round.connect(attackerA).submitClaim(unknown, materialHashOf('x')))
      .to.be.revertedWithCustomError(round, 'RoundUnknown');
    const roundId = ethers.id('round-6');
    await openRound(roundId);
    await time.increaseTo((await time.latest()) + CLOSE_DELAY + 1);
    await expect(round.connect(owner)
      .finalizeRound(roundId, [materialHashOf('x')], [true], []))
      .to.be.revertedWithCustomError(round, 'NotPayable');
    await expect(round.connect(owner).fundRound(unknown, { value: 1n }))
      .to.be.revertedWithCustomError(round, 'RoundUnknown');
  });
});
