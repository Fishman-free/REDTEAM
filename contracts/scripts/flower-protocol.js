'use strict';

// Local trusted-controller protocol, NOT an on-chain truth oracle. A reviewer
// reference is an audited workflow reference, NOT a cryptographic signature or
// authenticated reviewer identity. Use only reviewed, synthetic local fixtures.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { getAddress, ZeroAddress, keccak256, toUtf8Bytes, verifyTypedData } = require('ethers');

const PROTOCOL = 'redteam-flower';
const VERSION = 1;
const POLICY_VERSION = keccak256(toUtf8Bytes('redteam-flower-policy-v1'));
const CATEGORIES = Object.freeze({ model: 0, system: 1, research: 2 });
const CONSENT_TYPES = Object.freeze({ Consent: Object.freeze([
  { name: 'recipient', type: 'address' },
  { name: 'contributionId', type: 'bytes32' },
  { name: 'category', type: 'uint8' },
  { name: 'nonce', type: 'uint256' },
  { name: 'deadline', type: 'uint256' },
  { name: 'policyVersion', type: 'bytes32' },
]) });

function fail(message) { throw new Error(`Flower protocol: ${message}`); }
function exact(value, keys, label) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype) fail(`${label} must be a plain object`);
  const actual = Reflect.ownKeys(value);
  if (actual.length !== keys.length || actual.some((key) => !keys.includes(key))) {
    fail(`${label} has missing or unsupported fields (financial fields are forbidden)`);
  }
  for (const key of actual) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!Object.hasOwn(descriptor, 'value')) fail(`${label} accessors are unsupported`);
  }
}
function checksum(value, label) {
  try {
    if (typeof value !== 'string' || getAddress(value) !== value || value === ZeroAddress) fail(`${label} requires nonzero checksum address`);
  } catch { fail(`${label} requires nonzero checksum address`); }
  return value;
}
function uint(value, label) {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]{0,77})$/.test(value) || BigInt(value) >= 2n ** 256n) fail(`${label} requires canonical uint256 decimal string`);
  return BigInt(value);
}
function digest(value, label) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) fail(`${label} requires lowercase sha256 hex`);
}
function reference(value, label) {
  if (typeof value !== 'string' || !/^[a-z0-9][a-z0-9._/-]{2,95}$/.test(value)) fail(`${label} requires opaque audited reference, not a name or URL`);
}
function contributionId(contributionKey) {
  if (typeof contributionKey !== 'string' || !/^[a-z0-9][a-z0-9._/-]{2,127}$/.test(contributionKey) || contributionKey.includes('..') || contributionKey.split('/').some((part) => !part || part === '.')) fail('contributionKey requires canonical stable key');
  // Fixed property order is protocol v1 canonical serialization. Excludes
  // recipient, category, evidence filename, nonce and all financial quantities.
  return keccak256(toUtf8Bytes(JSON.stringify({ protocol: PROTOCOL, version: VERSION, contributionKey })));
}
function signableConsent({ recipient, contributionId: id, category, chainId, verifyingContract, nonce, deadline }) {
  checksum(recipient, 'recipient');
  checksum(verifyingContract, 'verifyingContract');
  if (chainId !== 31337) fail('consent chainId must be local 31337');
  if (!Object.hasOwn(CATEGORIES, category)) fail('unsupported category');
  if (!/^0x[0-9a-f]{64}$/.test(id) || id === '0x' + '0'.repeat(64)) fail('contributionId requires nonzero bytes32');
  uint(nonce, 'nonce');
  uint(deadline, 'deadline');
  return {
    domain: { name: 'REDTEAM Flower', version: '1', chainId, verifyingContract },
    types: CONSENT_TYPES,
    message: { recipient, contributionId: id, category: CATEGORIES[category], nonce, deadline, policyVersion: POLICY_VERSION },
  };
}

function localEvidence(root, relative) {
  if (typeof root !== 'string' || !path.isAbsolute(root)) fail('evidenceRoot must be explicit absolute trusted root');
  if (typeof relative !== 'string' || relative.length > 240 || !/^[a-zA-Z0-9._/-]+$/.test(relative) || path.isAbsolute(relative) || path.win32.isAbsolute(relative)) fail('evidence path must be local relative path');
  const parts = relative.split('/');
  if (parts.some((part) => !part || part === '.' || part === '..')) fail('evidence path traversal is forbidden');
  let ancestor = path.resolve(root);
  for (;;) {
    if (fs.lstatSync(ancestor).isSymbolicLink()) fail('evidence root/ancestor symlink is forbidden');
    const parent = path.dirname(ancestor);
    if (parent === ancestor) break;
    ancestor = parent;
  }
  const realRoot = fs.realpathSync(root);
  let current = realRoot;
  for (const part of parts) {
    current = path.join(current, part);
    if (fs.lstatSync(current).isSymbolicLink()) fail('evidence symlink is forbidden');
  }
  const resolved = fs.realpathSync(current);
  const rel = path.relative(realRoot, resolved);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) fail('evidence escaped trusted root');
  const fd = fs.openSync(resolved, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.size > 65536) fail('evidence must be a small regular file');
    const bytes = fs.readFileSync(fd);
    if (bytes.length > 65536) fail('evidence size exceeds limit');
    return bytes;
  } finally { fs.closeSync(fd); }
}
function validateEvidence(document, category) {
  exact(document, ['protocol', 'version', 'synthetic', 'scope', 'claimType', 'summary', 'confirmation'], 'evidence document');
  if (document.protocol !== 'redteam-flower-evidence' || document.version !== 1 || document.synthetic !== true) fail('only versioned synthetic evidence is supported');
  if (document.scope !== category) fail('evidence scope cannot support category claim (false model claim)');
  const claims = { model: 'model-finding', system: 'system-finding', research: 'research-contribution' };
  if (document.claimType !== claims[category]) fail('unsupported or false model claim');
  if (typeof document.summary !== 'string' || !document.summary.trim() || document.summary.length > 1200) fail('evidence summary required');
  if (category === 'research') {
    if (document.confirmation !== null) fail('research confirmation must be null');
    return;
  }
  exact(document.confirmation, ['attack', 'control'], 'paired confirmation');
  for (const phase of ['attack', 'control']) {
    const facts = document.confirmation[phase];
    exact(facts, ['inputReached', 'modelViolation', 'systemViolation', 'infrastructureError'], `${phase} confirmation`);
    if (Object.values(facts).some((value) => typeof value !== 'boolean')) fail('confirmation facts require booleans');
    if (!facts.inputReached || facts.infrastructureError) fail('confirmation requires input reached and no infrastructure error');
  }
  const { attack, control } = document.confirmation;
  if (control.modelViolation || control.systemViolation) fail('paired control must not violate model/system policy');
  if (category === 'model' && (!attack.modelViolation || attack.systemViolation)) fail('false model claim: model-only finding requires model violation, not system-only evidence');
  if (category === 'system' && !attack.systemViolation) fail('false system claim: system finding requires actual system violation');
  // These facts are local reviewed attestations, not independent verification
  // and not evidence that the trained model was changed or improved.
}

/** Read bytes and check digest + explicit audited approval + EIP-712 consent.
 * expected* and seenContributionIds are supplied by the trusted controller from
 * its local chain/registry, never derived from untrusted record fields.
 * Does not mutate the dedup registry: mark consumed only after confirmed mint.
 */
function validateReviewedRecord(record, { evidenceRoot, expectedChainId, expectedContract, expectedNonce, now, seenContributionIds } = {}) {
  exact(record, ['protocol', 'version', 'contributionKey', 'category', 'recipient', 'evidence', 'review', 'consent'], 'reviewed record');
  if (record.protocol !== PROTOCOL || record.version !== VERSION) fail('unsupported protocol/version');
  if (!Object.hasOwn(CATEGORIES, record.category)) fail('unsupported category');
  checksum(record.recipient, 'recipient');
  const id = contributionId(record.contributionKey);
  if (!(seenContributionIds instanceof Set)) fail('trusted duplicate registry is required');
  if (seenContributionIds.has(id)) fail('duplicate contribution');
  exact(record.evidence, ['path', 'sha256', 'synthetic'], 'evidence');
  if (record.evidence.synthetic !== true) fail('only synthetic local evidence supported');
  digest(record.evidence.sha256, 'evidence sha256');
  const bytes = localEvidence(evidenceRoot, record.evidence.path);
  if (crypto.createHash('sha256').update(bytes).digest('hex') !== record.evidence.sha256) fail('evidence digest mismatch');
  let document;
  try { document = JSON.parse(bytes.toString('utf8')); } catch { fail('evidence must be JSON'); }
  validateEvidence(document, record.category);
  exact(record.review, ['status', 'audited', 'reviewerReference', 'auditReference', 'scope', 'evidenceSha256'], 'review');
  if (record.review.status !== 'approved' || record.review.audited !== true) fail('explicit audited approval required; unreviewed record rejected');
  reference(record.review.reviewerReference, 'reviewerReference');
  reference(record.review.auditReference, 'auditReference');
  if (record.review.scope !== record.category || record.review.evidenceSha256 !== record.evidence.sha256) fail('review must bind evidence digest and category scope');
  exact(record.consent, ['domain', 'message', 'signature'], 'consent');
  exact(record.consent.domain, ['name', 'version', 'chainId', 'verifyingContract'], 'consent domain');
  exact(record.consent.message, ['recipient', 'contributionId', 'category', 'nonce', 'deadline', 'policyVersion'], 'consent message');
  const message = record.consent.message;
  const typed = signableConsent({ recipient: record.recipient, contributionId: id, category: record.category,
    chainId: expectedChainId, verifyingContract: expectedContract, nonce: expectedNonce, deadline: message.deadline });
  if (typeof now !== 'number' || !Number.isSafeInteger(now) || now < 0) fail('trusted chain timestamp required');
  if (uint(message.deadline, 'deadline') <= BigInt(now)) fail('consent expired');
  for (const [key, value] of Object.entries(typed.domain)) if (record.consent.domain[key] !== value) fail(`consent domain ${key} mismatch`);
  for (const [key, value] of Object.entries(typed.message)) if (message[key] !== value) fail(`consent message ${key} mismatch`);
  if (typeof record.consent.signature !== 'string' || !/^0x[0-9a-fA-F]{130}$/.test(record.consent.signature)) fail('recipient signature required');
  let signer;
  try { signer = verifyTypedData(typed.domain, typed.types, typed.message, record.consent.signature); } catch { fail('invalid recipient signature'); }
  if (signer !== record.recipient) fail('recipient signer mismatch');
  return { contributionId: id, category: CATEGORIES[record.category], typedData: typed, consent: typed.message, signature: record.consent.signature };
}

/** Fail closed BEFORE any transaction: only in-process unforked Hardhat. */
async function assertLocalNetwork(hre) {
  const network = hre?.network;
  if (network?.name !== 'hardhat' || network.config?.chainId !== 31337 || network.config?.url !== undefined) fail('only in-process hardhat chain 31337 allowed; remote/localhost forbidden');
  const forkEnabled = (config) => config !== undefined && config !== false && config?.enabled !== false;
  if (forkEnabled(network.config.forking)) fail('forking is forbidden');
  if (forkEnabled(hre.config?.networks?.hardhat?.forking)) fail('configured fork is forbidden');
  const provider = hre.ethers?.provider;
  if (!provider || !network.provider?.send) fail('local provider required');
  const observed = await provider.getNetwork();
  const rpcChainId = await network.provider.send('eth_chainId');
  if (observed.chainId !== 31337n || rpcChainId !== '0x7a69') fail('provider chainId mismatch');
  const metadata = await network.provider.send('hardhat_metadata');
  if (metadata?.chainId !== 31337 || typeof metadata.clientVersion !== 'string' || !(/^(HardhatNetwork\/|edr\/)/.test(metadata.clientVersion)) || metadata.forkedNetwork !== undefined) fail('provider must be unforked Hardhat; fork/runtime mismatch');
  return { chainId: 31337, network: 'hardhat', localOnly: true, forked: false };
}

module.exports = { PROTOCOL, VERSION, POLICY_VERSION, CATEGORIES, CONSENT_TYPES, contributionId, signableConsent, validateReviewedRecord, assertLocalNetwork };
