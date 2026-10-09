'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const hre = require('hardhat');
const { assertLocalNetwork, contributionId, signableConsent, validateReviewedRecord } = require('./flower-protocol');

function decodeMetadata(uri) {
  const prefix = 'data:application/json;base64,';
  assert.ok(uri.startsWith(prefix), 'tokenURI must embed Base64 JSON');
  const metadata = JSON.parse(Buffer.from(uri.slice(prefix.length), 'base64').toString('utf8'));
  assert.equal(typeof metadata.name, 'string');
  assert.equal(typeof metadata.description, 'string');
  assert.ok(metadata.image.startsWith('data:image/svg+xml;base64,'), 'NFT artwork must embed Base64 SVG');
  const svg = Buffer.from(metadata.image.split(',')[1], 'base64').toString('utf8');
  assert.ok(svg.startsWith('<svg') && svg.includes('</svg>'), 'NFT artwork must decode');
  assert.ok(Array.isArray(metadata.attributes));
  // Explicit allowlist; never serialize a raw record, evidence, signer, signature
  // or receipt. Contract metadata is deterministic; no local path/name input.
  const traits = new Set(['Token number', 'Category', 'Status']);
  const attributes = metadata.attributes.map(({ trait_type, value }) => {
    assert.ok(traits.has(trait_type), 'unexpected metadata trait');
    assert.ok(typeof value === 'string' || typeof value === 'number');
    return { trait_type, value };
  });
  return { name: metadata.name, description: metadata.description, image: metadata.image, attributes };
}
async function expectContractRevert(contract, operation) {
  try {
    const tx = await operation();
    await tx.wait();
  } catch (error) {
    // A provider outage is not proof of nontransferability. Require a decoded
    // Solidity custom-error revert from the actual contract's interface.
    const data = error.data || error.info?.error?.data;
    const decoded = typeof data === 'string' ? contract.interface.parseError(data) : null;
    assert.ok(decoded && /transfer|approval|soulbound|locked/i.test(decoded.name), 'expected transfer/approval policy revert');
    return;
  }
  throw new Error('nontransferability operation unexpectedly succeeded');
}

async function main() {
  // Guard MUST precede getSigners, deploy, mint, approvals and revoke. No CLI
  // RPC overrides or remote deployment mode are supported by this sample.
  await assertLocalNetwork(hre);
  const [owner, issuer, recipient, other] = await hre.ethers.getSigners();
  assert.notEqual(owner.address, issuer.address);
  const flower = await (await hre.ethers.getContractFactory('ContributionFlower', owner)).deploy(owner.address, issuer.address);
  await flower.waitForDeployment();
  const contractAddress = await flower.getAddress();
  const evidenceRoot = path.resolve(__dirname, '../scenarios/flower-v1');
  const record = JSON.parse(fs.readFileSync(path.join(evidenceRoot, 'reviewed-contribution.json'), 'utf8'));
  // Fixture review is a synthetic manual attestation under local controller
  // trust, NOT authentication of a reviewer or proof that evidence is true.
  record.recipient = recipient.address;
  const nonce = (await flower.nonces(recipient.address)).toString();
  const now = (await hre.ethers.provider.getBlock('latest')).timestamp;
  const typed = signableConsent({ recipient: recipient.address, contributionId: contributionId(record.contributionKey),
    category: record.category, chainId: 31337, verifyingContract: contractAddress, nonce, deadline: String(now + 3600) });
  record.consent = { domain: typed.domain, message: typed.message,
    signature: await recipient.signTypedData(typed.domain, typed.types, typed.message) };
  const seenContributionIds = new Set();
  const validated = validateReviewedRecord(record, { evidenceRoot, expectedChainId: 31337, expectedContract: contractAddress,
    expectedNonce: nonce, now, seenContributionIds });
  assert.equal(await flower.contributionUsed(validated.contributionId), false);
  await assertLocalNetwork(hre);
  const tokenId = await flower.connect(issuer).mint.staticCall(validated.consent, validated.signature);
  assert.equal(tokenId, 1n);
  await (await flower.connect(issuer).mint(validated.consent, validated.signature)).wait();
  seenContributionIds.add(validated.contributionId);
  assert.equal(await flower.ownerOf(tokenId), recipient.address);
  assert.equal(await flower.revoked(tokenId), false);
  await expectContractRevert(flower, () => flower.connect(recipient).transferFrom(recipient.address, other.address, tokenId));
  await expectContractRevert(flower, () => flower.connect(recipient).approve(other.address, tokenId));
  await expectContractRevert(flower, () => flower.connect(recipient).setApprovalForAll(other.address, true));
  const issued = decodeMetadata(await flower.tokenURI(tokenId));
  await (await flower.connect(issuer).revoke(tokenId)).wait();
  assert.equal(await flower.ownerOf(tokenId), recipient.address);
  assert.equal(await flower.revoked(tokenId), true);
  const revoked = decodeMetadata(await flower.tokenURI(tokenId));
  assert.equal(issued.image, revoked.image, 'same token retains deterministic artwork');
  assert.equal(issued.attributes.find((a) => a.trait_type === 'Status')?.value, 'active');
  assert.equal(revoked.attributes.find((a) => a.trait_type === 'Status')?.value, 'revoked');
  const output = {
    protocol: 'redteam-flower-demo-v1', synthetic: true,
    network: { name: 'hardhat', chainId: 31337, forked: false }, contractAddress,
    snapshots: [
      { label: 'issued', tokenId: tokenId.toString(), revoked: false, metadata: issued },
      { label: 'revoked', tokenId: tokenId.toString(), revoked: true, metadata: revoked },
    ],
    checks: { transferBlocked: true, approvalsBlocked: true },
  };
  // Historical snapshots of ONE token on an ephemeral local test chain, not
  // two NFTs and not live public-chain issuance. Do not export raw owner wallet.
  const destination = path.resolve(__dirname, '../../docs/site/flower-demo.json');
  fs.writeFileSync(destination, JSON.stringify(output, null, 2) + '\n');
  console.log('Synthetic local flower demo: token 1 issued, transfer/approvals blocked, then revoked.');
  console.log('Exported docs/site/flower-demo.json (same-token historical snapshots; no live public chain).');
}

module.exports = { main, decodeMetadata };
if (require.main === module) main().catch((error) => {
  // Avoid raw exception objects leaking transaction consent/signatures to logs.
  console.error('Flower demo failed:', error.shortMessage || error.message);
  process.exitCode = 1;
});
