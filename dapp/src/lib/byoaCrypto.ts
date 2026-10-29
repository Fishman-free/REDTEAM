import { x25519 } from "@noble/curves/ed25519";
import { gcm } from "@noble/ciphers/aes";
import { hkdf } from "@noble/hashes/hkdf";
import { sha256 } from "@noble/hashes/sha256";
import {
  bytesToHex,
  getAddress,
  hexToBytes,
  keccak256,
  type Hex,
} from "viem";

/**
 * Must match redteam_platform.byoa.envelope:
 * X25519 + HKDF-SHA256 + AES-256-GCM, canonical envelope JSON.
 * The wallet signature deterministically seeds the attacker's X25519 key.
 */
export const IDENTITY_MESSAGE = "RTM BYOA identity v1";
const SUITE = "X25519-HKDF-SHA256-AES-256-GCM";
const VERSION = 1;
const INFO_PREFIX = new TextEncoder().encode("RTM BYOA envelope v1");
const SALT = sha256(new TextEncoder().encode("RTM BYOA salt v1"));

export interface Envelope {
  v: number;
  suite: string;
  epk: Hex;
  nonce: Hex;
  ct: Hex;
  ctx: string;
}

export interface Identity {
  privateKey: Uint8Array;
  publicKey: Hex;
}

export function deriveIdentity(signature: Hex): Identity {
  const seed = sha256(hexToBytes(signature));
  return {
    privateKey: seed,
    publicKey: bytesToHex(x25519.getPublicKey(seed)) as Hex,
  };
}

function concatBytes(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function deriveKey(
  shared: Uint8Array,
  recipient: Uint8Array,
  ephemeral: Uint8Array,
  context: string,
): Uint8Array {
  const info = concatBytes(
    INFO_PREFIX,
    recipient,
    ephemeral,
    new TextEncoder().encode(context),
  );
  return hkdf(sha256, shared, SALT, info, 32);
}

export function sealTo(
  recipientPublic: Hex,
  plaintext: string,
  context: string,
): Envelope {
  const recipient = hexToBytes(recipientPublic);
  if (recipient.length !== 32) throw new Error("invalid recipient public key");
  const ephemeralPrivate = x25519.utils.randomPrivateKey();
  const ephemeralPublic = x25519.getPublicKey(ephemeralPrivate);
  const shared = x25519.getSharedSecret(ephemeralPrivate, recipient);
  const key = deriveKey(shared, recipient, ephemeralPublic, context);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const aad = new TextEncoder().encode(context);
  const ciphertext = gcm(key, nonce, aad).encrypt(
    new TextEncoder().encode(plaintext),
  );
  return {
    v: VERSION,
    suite: SUITE,
    epk: bytesToHex(ephemeralPublic) as Hex,
    nonce: bytesToHex(nonce) as Hex,
    ct: bytesToHex(ciphertext) as Hex,
    ctx: context,
  };
}

export function openFrom(
  privateKey: Uint8Array,
  envelope: Envelope,
  context: string,
): string {
  if (envelope.v !== VERSION || envelope.suite !== SUITE) {
    throw new Error("unsupported envelope");
  }
  if (envelope.ctx !== context) throw new Error("envelope context mismatch");
  const recipient = x25519.getPublicKey(privateKey);
  const ephemeral = hexToBytes(envelope.epk);
  const shared = x25519.getSharedSecret(privateKey, ephemeral);
  const key = deriveKey(shared, recipient, ephemeral, context);
  const aad = new TextEncoder().encode(context);
  const plaintext = gcm(key, hexToBytes(envelope.nonce), aad).decrypt(
    hexToBytes(envelope.ct),
  );
  return new TextDecoder().decode(plaintext);
}

export function ciphertextHash(envelope: Envelope): Hex {
  return keccak256(envelope.ct);
}

export function attackContext(contestId: string, attacker: string): string {
  return `rtm-byoa/attack/v1/${contestId.toLowerCase()}/${getAddress(attacker)}`;
}

export function replyContext(
  contestId: string,
  attacker: string,
  msgHash: string,
  seq: number,
): string {
  return `rtm-byoa/reply/v1/${contestId.toLowerCase()}/${getAddress(attacker)}/${msgHash.toLowerCase()}/${seq}`;
}

export function isEnvelope(value: unknown): value is Envelope {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return (
    item.v === VERSION &&
    item.suite === SUITE &&
    typeof item.epk === "string" &&
    typeof item.nonce === "string" &&
    typeof item.ct === "string" &&
    typeof item.ctx === "string"
  );
}
