'use strict';

/**
 * RTM reward bridge (docs/EVIDENCE_REWARD_PROTOCOL.md, frozen v1).
 *
 * Consumes the arena's claim-requests.jsonl registry — one record per deduped,
 * independently validated finding — and drives the BountyVault lifecycle:
 * configureClaim(bytes32(claim_id), beneficiary, amount) then settleClaim.
 * The claim id is derived from content on BOTH sides by the frozen protocol
 * (contracts/scripts/claim-id.js twin of rsi4safety claim_protocol.py), so the
 * same mechanism can never be configured twice under a different id: the vault
 * reverts with ClaimAlreadyConfigured. Local Hardhat only, evaluator-gated.
 */
const fs = require('fs');
const path = require('path');
const { claimIdHex, CLAIM_PROTOCOL } = require('./claim-id');

function toBytes32(claimId) {
  if (!/^[0-9a-f]{64}$/.test(claimId)) throw new Error(`claim id must be 64 hex: ${claimId}`);
  return ethers.zeroPadValue('0x' + claimId, 32);
}

/** Deploy the RTM stack in the frozen order: vault → token(minter=vault) → bind → evaluator. */
async function deployRtmStack(owner, evaluator, { emissionStart, maxPerClaim } = {}) {
  const vault = await (await ethers.getContractFactory('BountyVault')).connect(owner).deploy(owner.address);
  await vault.waitForDeployment();
  const start = emissionStart ?? (await ethers.provider.getBlock('latest')).timestamp;
  const rtm = await (await ethers.getContractFactory('RTMToken'))
    .connect(owner).deploy(owner.address, await vault.getAddress(), start);
  await rtm.waitForDeployment();
  await (await vault.initializeRtm(await rtm.getAddress())).wait();
  if (evaluator.address !== owner.address) {
    await (await vault.setEvaluator(evaluator.address)).wait();
  }
  // The vault starts with maxPerClaim = 0 (nothing is payable until the owner
  // sets the ceiling), so the bridge always configures it explicitly.
  if (maxPerClaim !== undefined) {
    await (await vault.connect(owner).setMaxPerClaim(maxPerClaim)).wait();
  }
  return { vault, rtm };
}

/** Registry-level dedup: one request per claim_id (content + beneficiary + amount). */
function dedupeRequests(requests) {
  const byId = new Map();
  for (const request of requests) {
    if (request.protocol !== CLAIM_PROTOCOL) throw new Error(`unknown protocol ${request.protocol}`);
    if (request.status !== 'pending') continue;
    byId.set(request.claim_id, request);
  }
  return [...byId.values()];
}

/** Configure and settle every pending request; per-claim failures are isolated. */
async function settleClaimRequests(vault, requests, { signer, skipSettle = false } = {}) {
  const results = [];
  for (const request of dedupeRequests(requests)) {
    const id = toBytes32(request.claim_id);
    const outcome = { claim_id: request.claim_id, evidence_id: request.evidence_id,
                      status: 'pending' };
    try {
      const vaultAs = signer ? vault.connect(signer) : vault;
      await (await vaultAs.configureClaim(id, request.beneficiary, BigInt(request.amount))).wait();
      outcome.status = 'configured';
      if (!skipSettle) {
        await (await vaultAs.settleClaim(id)).wait();
        outcome.status = 'settled';
      }
    } catch (error) {
      outcome.status = 'failed';
      outcome.error = (error.shortMessage || error.message || String(error)).slice(0, 200);
    }
    results.push(outcome);
  }
  return results;
}

/** Arena-side registry reader. */
function readClaimRequests(filePath) {
  const resolved = path.resolve(filePath);
  return fs.readFileSync(resolved, 'utf8').split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

module.exports = { toBytes32, deployRtmStack, dedupeRequests, readClaimRequests, settleClaimRequests };

// -- local demo ---------------------------------------------------------------
// Usage: npx hardhat run scripts/rtm-reward-bridge.js
//        npx hardhat run scripts/rtm-reward-bridge.js -- <claim-requests.jsonl>
if (require.main === module) {
  (async () => {
    const [owner, evaluator, attacker] = await ethers.getSigners();
    const { vault, rtm } = await deployRtmStack(owner, evaluator, {
      maxPerClaim: 10_500_000n * 10n ** 18n,  // full year-0 emission budget
    });
    console.log('BountyVault:', await vault.getAddress());
    console.log('RTMToken  :', await rtm.getAddress());

    // Demo request built with the frozen protocol from a validated finding.
    const dedupKey = 'aa'.repeat(32);
    const sutDigest = 'bb'.repeat(32);
    const beneficiary = ('0x' + 'ab'.repeat(20));
    const request = {
      schema_version: 1, protocol: CLAIM_PROTOCOL,
      claim_id: claimIdHex({ protocol: CLAIM_PROTOCOL, dedup_key: dedupKey,
        sut_digest: sutDigest, beneficiary, amount: '1500000' }),
      dedup_key: dedupKey, sut_digest: sutDigest, beneficiary, amount: '1500000',
      evidence_id: 'ev-demo0000000', status: 'pending',
    };

    const id = toBytes32(request.claim_id);
    await (await vault.connect(evaluator).configureClaim(id, beneficiary, BigInt(request.amount))).wait();
    console.log('ClaimConfigured:', request.claim_id);
    await (await vault.connect(evaluator).settleClaim(id)).wait();
    console.log('ClaimSettled   :', request.claim_id);
    const balance = await rtm.balanceOf(beneficiary);
    console.log('beneficiary RTM balance:', balance.toString());

    // Duplicate mechanism, different id attempt: identical content derives the
    // identical claim id, so the vault reverts instead of paying twice.
    try {
      await (await vault.connect(evaluator)
        .configureClaim(id, beneficiary, BigInt(request.amount))).wait();
      throw new Error('duplicate configure should have reverted');
    } catch (error) {
      console.log('duplicate configure rejected:', (error.message || '').includes('ClaimAlreadyConfigured')
        ? 'ClaimAlreadyConfigured' : error.message.slice(0, 120));
    }
  })().catch((error) => { console.error(error); process.exitCode = 1; });
}
