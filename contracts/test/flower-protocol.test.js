'use strict';

// Independent Mocha suite: no Hardhat/artifact dependency. Can run during
// contract implementation with node ../node_modules/mocha/bin/mocha.js ... .
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { Wallet, getAddress } = require('ethers');
const { PROTOCOL, POLICY_VERSION, contributionId, signableConsent, validateReviewedRecord, assertLocalNetwork } = require('../scripts/flower-protocol');
const fixtures = path.resolve(__dirname, '../scenarios/flower-v1');
const template = JSON.parse(fs.readFileSync(path.join(fixtures, 'reviewed-contribution.json'), 'utf8'));
const clone = (object) => JSON.parse(JSON.stringify(object));
const recipient = Wallet.createRandom();
const stranger = Wallet.createRandom();
const contract = getAddress('0x0000000000000000000000000000000000001234');
const now = 1800000000;

function context(extra = {}) {
  return { evidenceRoot: fixtures, expectedChainId: 31337, expectedContract: contract, expectedNonce: '0', now, seenContributionIds: new Set(), ...extra };
}
async function signed(record = clone(template), signer = recipient) {
  record.recipient = recipient.address;
  const typed = signableConsent({ recipient: record.recipient, contributionId: contributionId(record.contributionKey), category: record.category,
    chainId: 31337, verifyingContract: contract, nonce: '0', deadline: String(now + 3600) });
  record.consent = { domain: typed.domain, message: typed.message, signature: await signer.signTypedData(typed.domain, typed.types, typed.message) };
  return record;
}
function mockNetwork() {
  return {
    config: { networks: { hardhat: { chainId: 31337 } } },
    ethers: { provider: { getNetwork: async () => ({ chainId: 31337n }) } },
    network: { name: 'hardhat', config: { chainId: 31337 }, provider: { send: async (method) => {
      if (method === 'eth_chainId') return '0x7a69';
      if (method === 'hardhat_metadata') return { chainId: 31337, clientVersion: 'HardhatNetwork/2.22.0' };
      throw new Error('unexpected RPC');
    } } },
  };
}

describe('Flower reviewed-record protocol (independent)', function () {
  let good;
  before(async () => { good = await signed(); });
  it('accepts the explicit audited synthetic fixture and verifies EIP-712 recipient consent', () => {
    const result = validateReviewedRecord(good, context());
    assert.equal(result.contributionId, contributionId(template.contributionKey));
    assert.equal(result.category, 1);
    assert.equal(result.consent.policyVersion, POLICY_VERSION);
    assert.equal(result.typedData.domain.name, 'REDTEAM Flower');
    assert.equal(result.typedData.domain.version, '1');
  });
  it('canonical contribution identity excludes wallet, evidence, nonce and financial amounts', async () => {
    const id = contributionId(template.contributionKey);
    const typed = signableConsent({ recipient: stranger.address, contributionId: id, category: 'research', chainId: 31337,
      verifyingContract: contract, nonce: '400', deadline: String(now + 7200) });
    assert.equal(typed.message.contributionId, id);
    assert.notEqual(contributionId(template.contributionKey + '-other'), id);
    assert.equal(id, contributionId(template.contributionKey));
    assert.equal(PROTOCOL, 'redteam-flower');
  });
  it('rejects duplicate contribution even after recipient changes', async () => {
    const changed = clone(good);
    changed.recipient = stranger.address;
    assert.throws(() => validateReviewedRecord(changed, context({ seenContributionIds: new Set([contributionId(template.contributionKey)]) })), /duplicate contribution/);
  });
  it('does not consume dedup registry on validation alone', () => {
    const ctx = context();
    validateReviewedRecord(good, ctx);
    assert.equal(ctx.seenContributionIds.size, 0);
  });
  const mutations = [
    ['protocol', (r) => { r.protocol = 'payment'; }, /protocol\/version/],
    ['version string', (r) => { r.version = '1'; }, /protocol\/version/],
    ['future version', (r) => { r.version = 2; }, /protocol\/version/],
    ['category case', (r) => { r.category = 'Model'; }, /category/],
    ['category prototype', (r) => { r.category = 'toString'; }, /category/],
    ['numeric category', (r) => { r.category = 1; }, /category/],
    ['noncanonical key', (r) => { r.contributionKey = 'UpperCase'; }, /stable key/],
    ['key traversal', (r) => { r.contributionKey = 'synthetic/../key'; }, /stable key/],
    ['key empty segment', (r) => { r.contributionKey = 'synthetic//key'; }, /stable key/],
    ['key dot segment', (r) => { r.contributionKey = 'synthetic/./key'; }, /stable key/],
    ['recipient lowercase', (r) => { r.recipient = recipient.address.toLowerCase(); }, /checksum/],
    ['zero recipient', (r) => { r.recipient = '0x' + '0'.repeat(40); }, /checksum/],
    ['invalid recipient', (r) => { r.recipient = 'not-address'; }, /checksum/],
    ['digest mismatch', (r) => { r.evidence.sha256 = '0'.repeat(64); }, /digest mismatch/],
    ['malformed digest', (r) => { r.evidence.sha256 = '0x' + r.evidence.sha256; }, /sha256/],
    ['real evidence', (r) => { r.evidence.synthetic = false; }, /synthetic/],
    ['missing evidence', (r) => { r.evidence.path = 'does-not-exist.json'; }, /ENOENT/],
    ['absolute evidence', (r) => { r.evidence.path = path.join(fixtures, 'synthetic-system-evidence.json'); }, /local relative/],
    ['windows absolute', (r) => { r.evidence.path = 'C:/evidence.json'; }, /local relative/],
    ['traversal', (r) => { r.evidence.path = '../outside.json'; }, /traversal/],
    ['dot segment', (r) => { r.evidence.path = './synthetic-system-evidence.json'; }, /traversal/],
    ['empty segment', (r) => { r.evidence.path = 'dir//evidence.json'; }, /traversal/],
    ['backslash traversal', (r) => { r.evidence.path = '..\\outside.json'; }, /local relative/],
    ['URL evidence', (r) => { r.evidence.path = 'https://example.org/evidence'; }, /local relative/],
    ['unreviewed', (r) => { r.review.status = 'pending'; }, /audited approval/],
    ['rejected', (r) => { r.review.status = 'rejected'; }, /audited approval/],
    ['not audited', (r) => { r.review.audited = false; }, /audited approval/],
    ['reviewer missing', (r) => { r.review.reviewerReference = ''; }, /reviewerReference/],
    ['reviewer URL', (r) => { r.review.reviewerReference = 'https://reviewer.example'; }, /reviewerReference/],
    ['audit missing', (r) => { r.review.auditReference = ''; }, /auditReference/],
    ['review scope', (r) => { r.review.scope = 'model'; }, /bind evidence/],
    ['review digest', (r) => { r.review.evidenceSha256 = '0'.repeat(64); }, /bind evidence/],
    ['system as model', (r) => { r.category = 'model'; r.review.scope = 'model'; }, /false model claim/],
    ['wrong chain', (r) => { r.consent.domain.chainId = 1; }, /domain chainId/],
    ['wrong contract', (r) => { r.consent.domain.verifyingContract = stranger.address; }, /verifyingContract/],
    ['wrong domain name', (r) => { r.consent.domain.name = 'Flower'; }, /domain name/],
    ['wrong domain version', (r) => { r.consent.domain.version = '2'; }, /domain version/],
    ['wrong policy', (r) => { r.consent.message.policyVersion = '0x' + '0'.repeat(64); }, /policyVersion/],
    ['message recipient', (r) => { r.consent.message.recipient = stranger.address; }, /message recipient/],
    ['message contribution', (r) => { r.consent.message.contributionId = '0x' + '0'.repeat(64); }, /contributionId/],
    ['message category', (r) => { r.consent.message.category = 0; }, /message category/],
    ['message nonce', (r) => { r.consent.message.nonce = '1'; }, /nonce/],
    ['numeric nonce', (r) => { r.consent.message.nonce = 0; }, /nonce/],
    ['expired consent', (r) => { r.consent.message.deadline = String(now - 1); }, /expired/],
    ['boundary deadline', (r) => { r.consent.message.deadline = String(now); }, /expired/],
    ['numeric deadline', (r) => { r.consent.message.deadline = now + 1; }, /uint256/],
    ['leading-zero deadline', (r) => { r.consent.message.deadline = '01'; }, /uint256/],
    ['overflow deadline', (r) => { r.consent.message.deadline = (2n ** 256n).toString(); }, /uint256/],
    ['negative deadline', (r) => { r.consent.message.deadline = '-1'; }, /uint256/],
    ['absent consent', (r) => { r.consent = null; }, /plain object/],
    ['missing signature', (r) => { r.consent.signature = ''; }, /signature/],
    ['tampered signature', (r) => { r.consent.signature = '0x' + '00'.repeat(65); }, /signature/],
  ];
  for (const [name, mutate, error] of mutations) it(`rejects ${name}`, () => {
    const record = clone(good);
    mutate(record);
    assert.throws(() => validateReviewedRecord(record, context()), error);
  });
  for (const level of ['record', 'evidence', 'review', 'consent', 'domain', 'message']) {
    for (const field of ['amount', 'payout', 'unsupported']) it(`rejects unsupported ${level}.${field}`, () => {
      const record = clone(good);
      const target = level === 'record' ? record : ['domain', 'message'].includes(level) ? record.consent[level] : record[level];
      target[field] = '100';
      assert.throws(() => validateReviewedRecord(record, context()), /unsupported fields/);
    });
  }
  it('rejects missing field and accessor/prototype records', () => {
    const missing = clone(good); delete missing.review;
    assert.throws(() => validateReviewedRecord(missing, context()), /unsupported fields/);
    const access = clone(good); Object.defineProperty(access, 'version', { get() { throw new Error('accessor executed'); } });
    assert.throws(() => validateReviewedRecord(access, context()), /accessors/);
    assert.throws(() => validateReviewedRecord(Object.assign(Object.create({}), good), context()), /plain object/);
  });
  it('rejects consent signed by a different recipient', async () => {
    const record = await signed(clone(template), stranger);
    assert.throws(() => validateReviewedRecord(record, context()), /signer mismatch/);
  });
  for (const [key, value, error] of [
    ['expectedChainId', 1, /31337/], ['expectedContract', stranger.address, /verifyingContract/],
    ['expectedNonce', '1', /nonce/], ['expectedNonce', undefined, /uint256/], ['now', undefined, /timestamp/],
    ['now', -1, /timestamp/], ['seenContributionIds', undefined, /duplicate registry/], ['evidenceRoot', '.', /absolute trusted root/],
  ]) it(`rejects invalid trusted context ${key}=${String(value)}`, () => {
    assert.throws(() => validateReviewedRecord(good, context({ [key]: value })), error);
  });

  describe('evidence scope and local filesystem safeguards', function () {
    let root;
    beforeEach(() => { root = fs.mkdtempSync(path.join(os.tmpdir(), 'flower-synthetic-test-')); });
    afterEach(() => { fs.rmSync(root, { recursive: true, force: true }); });
    async function withEvidence(document, category = 'system') {
      const record = clone(template);
      record.category = category;
      record.review.scope = category;
      const bytes = Buffer.from(JSON.stringify(document));
      fs.writeFileSync(path.join(root, 'evidence.json'), bytes);
      record.evidence.path = 'evidence.json';
      record.evidence.sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
      record.review.evidenceSha256 = record.evidence.sha256;
      return signed(record);
    }
    const system = JSON.parse(fs.readFileSync(path.join(fixtures, 'synthetic-system-evidence.json'), 'utf8'));
    const model = { ...system, scope: 'model', claimType: 'model-finding',
      confirmation: { ...system.confirmation, attack: { ...system.confirmation.attack, modelViolation: true, systemViolation: false } } };
    const factsChanged = (document, phase, facts) => ({ ...document,
      confirmation: { ...document.confirmation, [phase]: { ...document.confirmation[phase], ...facts } } });
    it('accepts explicit audited model-layer finding without model-change claims (no truth oracle)', async () => {
      const record = await withEvidence(model, 'model');
      assert.equal(validateReviewedRecord(record, context({ evidenceRoot: root })).category, 0);
    });
    it('accepts explicit synthetic research contribution without violation claims', async () => {
      const record = await withEvidence({ ...system, scope: 'research', claimType: 'research-contribution', confirmation: null }, 'research');
      assert.equal(validateReviewedRecord(record, context({ evidenceRoot: root })).category, 2);
    });
    for (const [name, document, category, error] of [
      ['extra financial evidence', { ...system, amount: '42' }, 'system', /unsupported fields/],
      ['unsynthetic document', { ...system, synthetic: false }, 'system', /synthetic/],
      ['model improvement field', { ...system, modelChanged: true }, 'system', /unsupported fields/],
      ['false model claim type', { ...model, claimType: 'system-finding' }, 'model', /false model claim/],
      ['model layer not violated', factsChanged(model, 'attack', { modelViolation: false }), 'model', /false model claim/],
      ['system masquerading as model', factsChanged(model, 'attack', { modelViolation: false, systemViolation: true }), 'model', /false model claim/],
      ['mixed layers claimed model-only', factsChanged(model, 'attack', { systemViolation: true }), 'model', /false model claim/],
      ['system not violated', factsChanged(system, 'attack', { systemViolation: false }), 'system', /false system claim/],
      ['attack input not reached', factsChanged(system, 'attack', { inputReached: false }), 'system', /input reached/],
      ['attack infrastructure error', factsChanged(system, 'attack', { infrastructureError: true }), 'system', /infrastructure error/],
      ['control input not reached', factsChanged(system, 'control', { inputReached: false }), 'system', /input reached/],
      ['control infrastructure error', factsChanged(system, 'control', { infrastructureError: true }), 'system', /infrastructure error/],
      ['violating control', factsChanged(system, 'control', { systemViolation: true }), 'system', /control must not violate/],
      ['extra confirmation payout', factsChanged(system, 'attack', { payout: 1 }), 'system', /unsupported fields/],
      ['string confirmation fact', factsChanged(system, 'attack', { inputReached: 'true' }), 'system', /booleans/],
      ['unpaired attack', { ...system, confirmation: { attack: system.confirmation.attack } }, 'system', /unsupported fields/],
      ['unconfirmed research violation', { ...system, scope: 'research', claimType: 'research-contribution' }, 'research', /must be null/],
      ['empty summary', { ...system, summary: '' }, 'system', /summary/],
    ]) it(`rejects ${name}`, async () => {
      const record = await withEvidence(document, category);
      assert.throws(() => validateReviewedRecord(record, context({ evidenceRoot: root })), error);
    });
    it('rejects malformed JSON even with matching evidence SHA-256', () => {
      const record = clone(good);
      const bytes = Buffer.from('not json');
      fs.writeFileSync(path.join(root, 'evidence.json'), bytes);
      record.evidence.path = 'evidence.json';
      record.evidence.sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
      assert.throws(() => validateReviewedRecord(record, context({ evidenceRoot: root })), /must be JSON/);
    });
    it('rejects directory masquerading as evidence', () => {
      fs.mkdirSync(path.join(root, 'directory.json'));
      const record = clone(good); record.evidence.path = 'directory.json';
      assert.throws(() => validateReviewedRecord(record, context({ evidenceRoot: root })), /regular file|EISDIR|EACCES|EPERM/);
    });
    it('rejects oversized evidence', () => {
      fs.writeFileSync(path.join(root, 'large.json'), Buffer.alloc(65537));
      const record = clone(good); record.evidence.path = 'large.json';
      assert.throws(() => validateReviewedRecord(record, context({ evidenceRoot: root })), /small regular file/);
    });
    it('rejects escaped-root directory symlink/junction', () => {
      fs.symlinkSync(fixtures, path.join(root, 'escaped'), process.platform === 'win32' ? 'junction' : 'dir');
      const record = clone(good); record.evidence.path = 'escaped/synthetic-system-evidence.json';
      assert.throws(() => validateReviewedRecord(record, context({ evidenceRoot: root })), /symlink/);
    });
    it('rejects symlinked evidence root', () => {
      fs.symlinkSync(fixtures, path.join(root, 'root-link'), process.platform === 'win32' ? 'junction' : 'dir');
      assert.throws(() => validateReviewedRecord(good, context({ evidenceRoot: path.join(root, 'root-link') })), /symlink/);
    });
    it('rejects an evidence root below a symlinked ancestor', () => {
      const outer = path.join(root, 'outer'); fs.mkdirSync(outer);
      const inner = path.join(outer, 'inner'); fs.mkdirSync(inner);
      fs.symlinkSync(outer, path.join(root, 'ancestor-link'), process.platform === 'win32' ? 'junction' : 'dir');
      assert.throws(() => validateReviewedRecord(good, context({ evidenceRoot: path.join(root, 'ancestor-link', 'inner') })), /ancestor symlink/);
    });
    it('rejects a symlink even when its target stays inside root', () => {
      const inner = path.join(root, 'inner'); fs.mkdirSync(inner);
      fs.copyFileSync(path.join(fixtures, 'synthetic-system-evidence.json'), path.join(inner, 'evidence.json'));
      fs.symlinkSync(inner, path.join(root, 'alias'), process.platform === 'win32' ? 'junction' : 'dir');
      const record = clone(good); record.evidence.path = 'alias/evidence.json';
      assert.throws(() => validateReviewedRecord(record, context({ evidenceRoot: root })), /symlink/);
    });
  });
});

describe('Flower fail-closed local network guard (independent)', function () {
  it('accepts explicit chain 31337 in-process Hardhat with no fork', async () => {
    assert.deepEqual(await assertLocalNetwork(mockNetwork()), { chainId: 31337, network: 'hardhat', localOnly: true, forked: false });
  });
  it('accepts observed Hardhat EDR runtime metadata', async () => {
    const mock = mockNetwork();
    mock.network.provider.send = async (method) => method === 'eth_chainId' ? '0x7a69' : { chainId: 31337, clientVersion: 'edr/0.3.8/revm/33.1.0' };
    await assertLocalNetwork(mock);
  });
  it('accepts explicitly disabled fork configuration', async () => {
    const mock = mockNetwork(); mock.network.config.forking = { enabled: false };
    await assertLocalNetwork(mock);
  });
  for (const [name, mutate] of [
    ['remote mainnet name', (m) => { m.network.name = 'mainnet'; }],
    ['localhost RPC name', (m) => { m.network.name = 'localhost'; }],
    ['remote RPC on spoofed hardhat name', (m) => { m.network.config.url = 'https://example.org'; }],
    ['configured other chain', (m) => { m.network.config.chainId = 1; }],
    ['unspecified config chain', (m) => { delete m.network.config.chainId; }],
    ['enabled fork', (m) => { m.network.config.forking = { enabled: true, url: 'https://example.org' }; }],
    ['implicit enabled fork', (m) => { m.network.config.forking = { url: 'https://example.org' }; }],
    ['raw configured fork', (m) => { m.config.networks.hardhat.forking = { enabled: true }; }],
    ['implicit raw configured fork', (m) => { m.config.networks.hardhat.forking = { url: 'https://example.org' }; }],
    ['provider chain mismatch', (m) => { m.ethers.provider.getNetwork = async () => ({ chainId: 1n }); }],
    ['missing provider', (m) => { delete m.ethers; }],
    ['RPC provider chain mismatch', (m) => { m.network.provider.send = async () => '0x1'; }],
    ['runtime fork metadata', (m) => { m.network.provider.send = async (method) => method === 'eth_chainId' ? '0x7a69' : { chainId: 31337, clientVersion: 'HardhatNetwork/2.22.0', forkedNetwork: { chainId: 1 } }; }],
    ['non-Hardhat metadata', (m) => { m.network.provider.send = async (method) => method === 'eth_chainId' ? '0x7a69' : { chainId: 31337, clientVersion: 'remote' }; }],
    ['metadata wrong chain', (m) => { m.network.provider.send = async (method) => method === 'eth_chainId' ? '0x7a69' : { chainId: 1, clientVersion: 'HardhatNetwork/2.22.0' }; }],
    ['provider RPC error', (m) => { m.network.provider.send = async () => { throw new Error('provider unavailable'); }; }],
  ]) it(`rejects ${name} before controller can transact`, async () => {
    const mock = mockNetwork(); mutate(mock);
    let sentTransaction = false;
    await assert.rejects(async () => { await assertLocalNetwork(mock); sentTransaction = true; });
    assert.equal(sentTransaction, false);
  });
});
