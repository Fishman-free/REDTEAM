/**
 * RTM reward bridge tests (docs/EVIDENCE_REWARD_PROTOCOL.md, frozen v1).
 *
 * Covers the RESEARCH_PLAN §8 P1 bridging acceptance: only independently
 * validated findings become claims; a duplicate finding can never claim again
 * under a new id; configure/settle retries, budget exhaustion, pause,
 * evaluator rotation, year expiry and cancellation all behave per protocol.
 */
const { expect } = require('chai');
const { time } = require('@nomicfoundation/hardhat-network-helpers');
const { ethers } = require('hardhat');
const { toBytes32, deployRtmStack, dedupeRequests, settleClaimRequests } = require('../scripts/rtm-reward-bridge');
const { claimIdHex, CLAIM_PROTOCOL } = require('../scripts/claim-id');

const YEAR = 365 * 24 * 60 * 60;

function sampleRequest(overrides = {}) {
  const beneficiary = overrides.beneficiary ?? ('0x' + 'ab'.repeat(20));
  const amount = overrides.amount ?? '1500000';
  const dedup_key = overrides.dedup_key ?? 'aa'.repeat(32);
  const sut_digest = overrides.sut_digest ?? 'bb'.repeat(32);
  return {
    schema_version: 1, protocol: CLAIM_PROTOCOL,
    claim_id: claimIdHex({ protocol: CLAIM_PROTOCOL, dedup_key, sut_digest, beneficiary, amount }),
    dedup_key, sut_digest, beneficiary, amount,
    evidence_id: 'ev-test00000001', status: 'pending', ...overrides,
  };
}

describe('RTM reward bridge', function () {
  let owner, evaluator, outsider;
  let vault, rtm, emissionStart;

  beforeEach(async function () {
    [owner, evaluator, outsider] = await ethers.getSigners();
    emissionStart = await time.latest();
    ({ vault, rtm } = await deployRtmStack(owner, evaluator, {
      emissionStart, maxPerClaim: 10_500_000n * 10n ** 18n,  // full year-0 budget
    }));
  });

  it('settles a content-bound claim request end to end', async function () {
    const request = sampleRequest();
    const results = await settleClaimRequests(vault.connect(evaluator), [request]);
    expect(results).to.have.length(1);
    expect(results[0].status).to.equal('settled');
    const id = toBytes32(request.claim_id);
    expect((await vault.claims(id)).settled).to.equal(true);
    expect(await rtm.balanceOf(request.beneficiary)).to.equal(BigInt(request.amount));
    expect(await rtm.mintedByYear(0)).to.equal(BigInt(request.amount));
  });

  it('a duplicate finding can never claim again under a new id', async function () {
    const request = sampleRequest();
    await settleClaimRequests(vault.connect(evaluator), [request]);
    // Same content re-registered in the arena under a "new" record: the frozen
    // protocol derives the identical claim id, so configure reverts.
    const duplicate = sampleRequest();
    expect(duplicate.claim_id).to.equal(request.claim_id);
    await expect(vault.connect(evaluator)
      .configureClaim(toBytes32(duplicate.claim_id), duplicate.beneficiary,
                      BigInt(duplicate.amount)))
      .to.be.revertedWithCustomError(vault, 'ClaimAlreadyConfigured');
    await expect(vault.connect(evaluator).settleClaim(toBytes32(request.claim_id)))
      .to.be.revertedWithCustomError(vault, 'ClaimAlreadySettled');
  });

  it('dedupes the registry by claim id and skips non-pending records', async function () {
    const first = sampleRequest();
    const duplicate = sampleRequest({ evidence_id: 'ev-test00000002' });
    const settled = sampleRequest({ dedup_key: 'cd'.repeat(32), status: 'settled' });
    expect(duplicate.claim_id).to.equal(first.claim_id);
    const pending = dedupeRequests([first, duplicate, settled]);
    expect(pending).to.have.length(1);
    expect(pending[0].claim_id).to.equal(first.claim_id);
  });

  it('isolates per-claim failures without blocking the rest', async function () {
    await (await vault.setMaxPerClaim(1_000_000n)).wait();
    const tooLarge = sampleRequest();
    const fine = sampleRequest({ dedup_key: 'cc'.repeat(32), amount: '900000' });
    const results = await settleClaimRequests(vault.connect(evaluator), [tooLarge, fine]);
    expect(results[0].status).to.equal('failed');
    expect(results[0].error).to.include('ClaimTooLarge');
    expect(results[1].status).to.equal('settled');
    // The failed request stays pending in the arena registry for retry.
    await (await vault.setMaxPerClaim(2_000_000n)).wait();
    const retry = await settleClaimRequests(vault.connect(evaluator), [tooLarge]);
    expect(retry[0].status).to.equal('settled');
  });

  it('respects the year budget, pause and evaluator rotation', async function () {
    const yearBudget = await vault.availableCurrentYearBudget();
    // Raise the per-claim ceiling above the year budget first, so the rejection
    // is genuinely the budget check, not the cap check.
    await (await vault.connect(owner).setMaxPerClaim(yearBudget + 1n)).wait();
    const huge = sampleRequest({ amount: (yearBudget + 1n).toString() });
    const results = await settleClaimRequests(vault.connect(evaluator), [huge]);
    expect(results[0].status).to.equal('failed');
    expect(results[0].error).to.include('YearBudgetUnavailable');

    await (await vault.connect(owner).pause()).wait();
    const id = toBytes32(sampleRequest({ dedup_key: 'dd'.repeat(32) }).claim_id);
    await expect(vault.connect(evaluator).configureClaim(id, sampleRequest().beneficiary, 1n))
      .to.be.revertedWithCustomError(vault, 'EnforcedPause');
    await (await vault.connect(owner).unpause()).wait();

    await expect(vault.connect(outsider)
      .configureClaim(id, sampleRequest().beneficiary, 1n))
      .to.be.revertedWithCustomError(vault, 'NotEvaluator');
    await (await vault.connect(owner).setEvaluator(outsider.address)).wait();
    await expect(vault.connect(evaluator)
      .configureClaim(id, sampleRequest().beneficiary, 1n))
      .to.be.revertedWithCustomError(vault, 'NotEvaluator');
  });

  it('expired claims settle after renewal, never after cancellation', async function () {
    const request = sampleRequest();
    const id = toBytes32(request.claim_id);
    await (await vault.connect(evaluator)
      .configureClaim(id, request.beneficiary, BigInt(request.amount))).wait();
    await time.increaseTo(emissionStart + YEAR + 1);
    await expect(vault.connect(evaluator).settleClaim(id))
      .to.be.revertedWithCustomError(vault, 'ClaimYearExpired');
    await (await vault.connect(evaluator).renewClaim(id)).wait();
    await (await vault.connect(evaluator).settleClaim(id)).wait();
    expect(await rtm.balanceOf(request.beneficiary)).to.equal(BigInt(request.amount));

    // Cancelled ids are terminal: the reservation is released and the id can
    // never be configured again, so a re-registered request cannot pay.
    const cancelled = sampleRequest({ dedup_key: 'ee'.repeat(32) });
    const cancelledId = toBytes32(cancelled.claim_id);
    await (await vault.connect(evaluator)
      .configureClaim(cancelledId, cancelled.beneficiary, BigInt(cancelled.amount))).wait();
    await (await vault.connect(evaluator).cancelClaim(cancelledId)).wait();
    await expect(vault.connect(evaluator)
      .configureClaim(cancelledId, cancelled.beneficiary, BigInt(cancelled.amount)))
      .to.be.revertedWithCustomError(vault, 'ClaimAlreadyConfigured');
  });
});
