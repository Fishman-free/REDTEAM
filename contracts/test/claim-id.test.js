/**
 * Claim binding protocol cross-side anchor (docs/EVIDENCE_REWARD_PROTOCOL.md).
 *
 * The sample constant is shared with
 * rsi4safety/execution/tests/test_claim_protocol.py: the JS canonicalization
 * must derive the identical claim_id from the identical payload as Python.
 */
const { expect } = require('chai');
const { CLAIM_PROTOCOL, canonicalJson, claimIdHex, fixtureDigest } = require('../scripts/claim-id');

describe('claim-id cross-side anchor', function () {
  const samplePayload = {
    protocol: CLAIM_PROTOCOL,
    dedup_key: 'aa'.repeat(32),
    sut_digest: 'bb'.repeat(32),
    beneficiary: '0x' + 'ab'.repeat(20),
    amount: '1500000',
  };
  // Pinned by rsi4safety/execution/tests/test_claim_protocol.py as well.
  const sampleClaimId = '658b35c00f93a7be5708257b0888f6a3ca43c5978198155330a3973ef721349f';

  it('derives the frozen constant for the shared sample payload', function () {
    expect(claimIdHex(samplePayload)).to.equal(sampleClaimId);
    expect(canonicalJson(samplePayload)).to.equal(
      '{"amount":"1500000",' +
      '"beneficiary":"0xabababababababababababababababababababab",' +
      '"dedup_key":"' + 'aa'.repeat(32) + '",' +
      '"protocol":"rtm-claim-binding-v1",' +
      '"sut_digest":"' + 'bb'.repeat(32) + '"}'
    );
  });

  it('changes the id when any bound field changes', function () {
    const base = claimIdHex(samplePayload);
    expect(claimIdHex({ ...samplePayload, amount: '1500001' })).to.not.equal(base);
    expect(claimIdHex({ ...samplePayload, beneficiary: '0x' + 'ac'.repeat(20) })).to.not.equal(base);
    expect(claimIdHex({ ...samplePayload, dedup_key: 'ab'.repeat(32) })).to.not.equal(base);
  });

  it('refuses invalid payloads like the Python side', function () {
    const cases = [
      { ...samplePayload, beneficiary: '0xAB' + 'ab'.repeat(19) },
      { ...samplePayload, amount: '0' },
      { ...samplePayload, protocol: 'other-v1' },
      { ...samplePayload, extra: 'field' },
    ];
    for (const payload of cases) {
      expect(() => claimIdHex(payload)).to.throw();
    }
  });

  it('keeps the fixture digest aligned with the control.digest shape', function () {
    // sha256 over canonical JSON of the brief; both sides must agree.
    expect(fixtureDigest({ task_id: 't' })).to.equal(
      require('crypto').createHash('sha256')
        .update(Buffer.from('{"task_id":"t"}', 'utf8')).digest('hex'));
  });
});
