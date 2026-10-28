import { parseAbi } from "viem";

/**
 * Fallback addresses for the current Anvil / Base Sepolia fork deployment.
 * Runtime values come from GET /meta and override these defaults.
 */
export const ADDRESSES = {
  treasury: "0x2E88565fA4A126Fcd5a219fBE9Fdb6366898862E",
  arena: "0x5a8E8B7D1B52b1fA3B8bdcb0b38d9b55AAFBbe68",
  rtm: "0x7f48B5FD805c70A95ed9cB7A6280F52A5323fD33",
  faucet: "0xD30D8d0A2bcf5624BbC3Aa0C802D0CD7AB7faEDF",
  dataMarket: "0x1848eb5131db8E35423138e8e88E12f983604781",
} as const;

export const ZERO_HASH =
  "0x0000000000000000000000000000000000000000000000000000000000000000" as const;

export const rtmAbi = parseAbi([
  "function approve(address spender, uint256 amount) returns (bool)",
  "function allowance(address owner, address spender) view returns (uint256)",
  "function balanceOf(address owner) view returns (uint256)",
  "function decimals() view returns (uint8)",
  "function symbol() view returns (string)",
]);

export const arenaAbi = parseAbi([
  "function join(bytes32 id, uint256 maxStake, bool dataConsent)",
  "function joinMining(bytes32 id, bool acceptData)",
  "function attack(bytes32 id, bytes32 msgHash) returns (uint256)",
  "function expire(bytes32 id)",
  "function withdrawStake(bytes32 id)",
  "function collectPenalties(bytes32 id)",
  "function isRegisteredAttacker(bytes32 id, address who) view returns (bool)",
  "function remainingStake(bytes32 id, address who) view returns (uint256)",
  "function accruedPenalties(bytes32 id, address who) view returns (uint256)",
  "function penaltyDue(bytes32 id, address who) view returns (uint256)",
  "function dataConsent(bytes32 id, address who) view returns (bool)",
  "function contestState(bytes32 id) view returns (uint8)",
  "function contestWallet(bytes32 id) view returns (address)",
  "function activeMiningCount() view returns (uint256)",
  "function contestInfo(bytes32 id) view returns (address defender, address wallet, uint256 stake, uint32 stakeBps, bytes32 defenseHash, uint64 start, uint64 end, uint64 endedAt, uint8 state, bool isMining, uint32 attackerCount, bool paused)",
]);

export const faucetAbi = parseAbi([
  "function claim((address to, uint256 nonce, uint64 deadline) ticket, bytes sig)",
  "function nonces(address owner) view returns (uint256)",
  "function dripAmount() view returns (uint256)",
]);

export const dataMarketAbi = parseAbi([
  "function buyOwn(bytes32 contestId)",
  "function buyFromAttacker(bytes32 contestId, address attacker)",
  "function datasetRoot(bytes32 contestId) view returns (bytes32)",
  "function dataPriceBps() view returns (uint256)",
  "function attackerDataPrice() view returns (uint256)",
  "function boughtOwn(bytes32 contestId, address buyer) view returns (bool)",
  "function boughtAttacker(bytes32 contestId, address attacker, address buyer) view returns (bool)",
]);
