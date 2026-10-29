import { useCallback } from "react";
import { usePublicClient, useWriteContract } from "wagmi";
import { CHAIN_ID, assertWalletUsesAppChain } from "./chain";
import { getLang } from "./i18n";

type WriteArgs = Parameters<ReturnType<typeof useWriteContract>["writeContractAsync"]>[0];

/**
 * Every on-chain write first proves that the wallet's RPC points at the same
 * chain as the application. Without this guard, two local Besu stacks with the
 * same chain id can silently send a transaction to the wrong ledger.
 */
export function useArenaWriteContract() {
  const result = useWriteContract();
  const publicClient = usePublicClient({ chainId: CHAIN_ID });
  const { writeContractAsync } = result;

  const guardedWrite = useCallback(
    async (args: WriteArgs) => {
      if (!publicClient) {
        throw new Error(
          getLang() === "en"
            ? "The application RPC is not ready. Refresh the page and retry."
            : "本站 RPC 尚未就绪，请刷新页面后重试。",
        );
      }
      await assertWalletUsesAppChain(publicClient);
      return writeContractAsync(args);
    },
    [publicClient, writeContractAsync],
  );

  return { ...result, writeContractAsync: guardedWrite };
}
