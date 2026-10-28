import { parseAbi } from "viem";

/** R4 testnet addresses (contracts/deploy/addresses.json). */
export const ADDRESSES = {
  treasury: "0x08d41a76E333AaC5b20DfE79B5d94C0BD08624B8",
  arena: "0x5db4cB817379173C76E6756F080Fb37FD135698b",
  rtm: "0x24bCC902beEAebE5702e28bB8DF6A4056FA2dCCF",
  faucet: "0x0887e8D5878f5c227aD00aA8bAD593d779aC396B",
  dataMarket: "0x51Fb2032fcF0d158f1Ea82d5Fe680DF1814997a7",
} as const;

export const ZERO_HASH =
  "0x0000000000000000000000000000000000000000000000000000000000000000" as const;

export const rtmAbi = parseAbi([
  "function approve(address spender, uint256 amount) returns (bool)",
  "function allowance(address owner, address spender) view returns (uint256)",
  "function balanceOf(address owner) view returns (uint256)",
  "function decimals() view returns (uint8)",
]);

export const arenaAbi = parseAbi([
  "function join(bytes32 id, uint256 maxStake, bool dataConsent)",
  "function joinMining(bytes32 id, bool acceptData)",
  "function attack(bytes32 id, bytes32 msgHash) returns (uint256)",
  "function withdrawStake(bytes32 id)",
  "function collectPenalties(bytes32 id)",
  "function dataConsent(bytes32 id, address who) view returns (bool)",
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
