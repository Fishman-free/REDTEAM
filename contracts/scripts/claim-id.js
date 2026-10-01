/**
 * RTM claim binding primitives (docs/EVIDENCE_REWARD_PROTOCOL.md, frozen v1).
 *
 * JS twin of rsi4safety/execution/src/rsi4safety/claim_protocol.py: both sides
 * derive the identical content-bound claim_id from the same payload and are
 * pinned to the same sample constant by their unit tests. Only string fields
 * are allowed so the canonical JSON is byte-identical on both sides.
 */
'use strict';

const crypto = require('crypto');

const CLAIM_PROTOCOL = 'rtm-claim-binding-v1';
const REQUIRED_FIELDS = ['amount', 'beneficiary', 'dedup_key', 'protocol', 'sut_digest'];
const HEX64 = /^[0-9a-f]{64}$/;
const ADDRESS = /^0x[0-9a-f]{40}$/;
const DECIMAL = /^[0-9]+$/;

// Python json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)
// over string-only payloads: recursively sorted keys, no whitespace, UTF-8.
function canonicalJson(value) {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return '[' + value.map(canonicalJson).join(',') + ']';
  }
  const keys = Object.keys(value).sort();
  return '{' + keys.map((key) => JSON.stringify(key) + ':' + canonicalJson(value[key])).join(',') + '}';
}

function claimId(payload) {
  const keys = Object.keys(payload);
  const missing = REQUIRED_FIELDS.filter((key) => !keys.includes(key));
  const extra = keys.filter((key) => !REQUIRED_FIELDS.includes(key));
  if (missing.length || extra.length) {
    throw new Error(`claim payload fields mismatch: missing=${missing} extra=${extra}`);
  }
  if (payload.protocol !== CLAIM_PROTOCOL) {
    throw new Error(`protocol must be ${CLAIM_PROTOCOL}`);
  }
  if (!HEX64.test(payload.dedup_key) || !HEX64.test(payload.sut_digest)) {
    throw new Error('dedup_key and sut_digest must be lowercase 64-hex digests');
  }
  if (!ADDRESS.test(payload.beneficiary)) {
    throw new Error('beneficiary must be a lowercase 0x address');
  }
  if (!DECIMAL.test(payload.amount) || BigInt(payload.amount) <= 0n) {
    throw new Error('amount must be a positive decimal string');
  }
  return crypto.createHash('sha256').update(Buffer.from(canonicalJson(payload), 'utf8')).digest();
}

function claimIdHex(payload) {
  return claimId(payload).toString('hex');
}

function fixtureDigest(taskFixtureBrief) {
  return crypto.createHash('sha256')
    .update(Buffer.from(canonicalJson(taskFixtureBrief), 'utf8'))
    .digest('hex');
}

module.exports = { CLAIM_PROTOCOL, canonicalJson, claimId, claimIdHex, fixtureDigest };
