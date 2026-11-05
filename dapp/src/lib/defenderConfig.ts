import { keccak256, stringToBytes } from "viem";

/**
 * The EIP-712 config hash for a defender registration.
 *
 * Must match `redteam_platform.signatures.config_hash`: v1 commits to
 * provider\0prompt\0mandate. A custom endpoint extends that preimage with
 * base_url\0model, keeping v1 registrations verifiable.
 */
export function defenderConfigHash(
  provider: string,
  prompt: string,
  mandate: string,
  baseUrl = "",
  model = "",
): `0x${string}` {
  const separator = "\u0000";
  const payload =
    baseUrl || model
      ? [provider, baseUrl, model, prompt, mandate].join(separator)
      : [provider, prompt, mandate].join(separator);
  return keccak256(stringToBytes(payload));
}
