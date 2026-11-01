/**
 * Why the wallet and the site may not be on the same ledger.
 *
 * The chain id is not enough: two local Besu stacks can both claim 48850 while
 * holding different state. The stronger check compares a block both endpoints
 * should already have. This module only sequences those probes; `chain.ts`
 * supplies the real wallet/app calls so this part stays testable without a
 * browser extension.
 */

export const ARENA_CHAIN_ID = 48850;
export const CHAIN_PROBE_DEPTH = 12n;

export interface BlockRef {
  hash: string;
}

export interface Eip1193Provider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}

export interface WalletProbe {
  walletChainId(): Promise<number>;
  walletHead(): Promise<bigint>;
  walletBlock(height: bigint): Promise<BlockRef | null>;
  appHead(): Promise<bigint>;
  appBlock(height: bigint): Promise<BlockRef>;
}

export type WalletNetworkDiagnosis =
  | { kind: "ok"; height: bigint | null }
  | { kind: "no-wallet" }
  | {
      kind: "wallet-chain";
      actualChainId: number;
      expectedChainId: number;
    }
  | { kind: "wallet-rpc"; error: string }
  | { kind: "app-rpc"; error: string }
  | {
      kind: "fork";
      height: bigint;
      walletHash: string;
      appHash: string;
    }
  | { kind: "unverified"; error: string };

export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error) return error;
  try {
    const text = JSON.stringify(error);
    return text && text !== "{}" ? text : "unknown error";
  } catch {
    return "unknown error";
  }
}

/**
 * Classify the wallet's network.
 *
 * - A wallet that cannot even report `eth_chainId` is a wallet-RPC failure,
 *   not evidence of a fork. The caller must not tell the user to switch chains.
 * - A matching chain id plus a failed block read is inconclusive: we know the
 *   wallet claims the right network but cannot prove it. Callers may warn, but
 *   must not block a write on an inference they could not verify.
 * - Only two successfully read blocks with different hashes prove a fork.
 */
export async function diagnoseWalletNetwork(
  probe: WalletProbe,
  expectedChainId: number = ARENA_CHAIN_ID,
  depth: bigint = CHAIN_PROBE_DEPTH,
): Promise<WalletNetworkDiagnosis> {
  let chainId: number;
  try {
    chainId = await probe.walletChainId();
  } catch (error) {
    return { kind: "wallet-rpc", error: errorMessage(error) };
  }
  if (chainId !== expectedChainId) {
    return {
      kind: "wallet-chain",
      actualChainId: chainId,
      expectedChainId,
    };
  }

  let appHead: bigint;
  try {
    appHead = await probe.appHead();
  } catch (error) {
    return { kind: "app-rpc", error: errorMessage(error) };
  }

  let walletHead: bigint;
  try {
    walletHead = await probe.walletHead();
  } catch (error) {
    return { kind: "wallet-rpc", error: errorMessage(error) };
  }

  // Probe well behind both heads so normal propagation lag cannot look like a
  // fork, while two different chains diverge at every height.
  const probeHeight =
    (walletHead < appHead ? walletHead : appHead) - depth;
  if (probeHeight <= 0n) {
    return { kind: "ok", height: null };
  }

  let walletBlock: BlockRef | null;
  let appBlock: BlockRef;
  try {
    [walletBlock, appBlock] = await Promise.all([
      probe.walletBlock(probeHeight),
      probe.appBlock(probeHeight),
    ]);
  } catch (error) {
    return { kind: "unverified", error: errorMessage(error) };
  }

  if (!walletBlock || typeof walletBlock.hash !== "string" || !walletBlock.hash) {
    return {
      kind: "unverified",
      error: "the wallet returned no block at the probe height",
    };
  }
  if (
    walletBlock.hash.toLowerCase() !== appBlock.hash.toLowerCase()
  ) {
    return {
      kind: "fork",
      height: probeHeight,
      walletHash: walletBlock.hash,
      appHash: appBlock.hash,
    };
  }
  return { kind: "ok", height: probeHeight };
}
