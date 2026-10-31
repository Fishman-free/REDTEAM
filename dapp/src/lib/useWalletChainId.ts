import { useAccount, useChainId } from "wagmi";

/**
 * The chain the injected wallet is actually on.
 *
 * wagmi's `useChainId` reads the config's active chain, and the config ignores
 * `chainChanged` events for chains it does not know. This app only configures
 * the arena chain, so a wallet left on Ethereum mainnet still reports 48850 —
 * and every wrong-network guard silently passes. The connection record keeps
 * the wallet's real chain id, so read it from there instead.
 */
export function useWalletChainId(): number {
  const { chainId } = useAccount();
  const configuredChainId = useChainId();
  return chainId ?? configuredChainId;
}
