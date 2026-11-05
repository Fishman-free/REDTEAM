import { useMemo, useState } from "react";
import { keccak256, toHex } from "viem";
import { useAccount } from "wagmi";
import { api, ApiClientError, type Contest, type MessageResponse } from "./api";
import { attackFeeWei, isContestLive } from "./contest";
import { arenaAbi, rtmAbi } from "./contracts";
import { CHAIN_ID, isSupportedChain } from "./chain";
import { useWalletChainId } from "./useWalletChainId";
import { useArenaWriteContract } from "./useArenaWriteContract";
import { useActivity } from "../context/ActivityContext";
import { useI18n } from "./i18n";
import { useLocalStorage, useNow } from "./hooks";
import {
  requireAddresses,
  useAllowance,
  usePlatform,
  useRtmBalance,
} from "./platform";

export interface PendingTurn {
  content: string;
  msgHash: string;
  txHash: `0x${string}`;
  createdAt: number;
}

type Step = "idle" | "approve" | "chain" | "deliver" | "done";

const sleep = (milliseconds: number) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * The on-chain and delivery half of a paid attack, shared by the manual chat
 * and the attacker agent.
 *
 * ``send`` resolves only after the platform returns the defender reply. A
 * failed delivery leaves ``pendingTurn`` behind so the user can retry without
 * paying twice.
 */
export function usePaidAttack(
  contest: Contest,
  joined: boolean,
  onAfterSend?: () => void,
) {
  const { address, isConnected } = useAccount();
  const walletChainId = useWalletChainId();
  const { writeContractAsync } = useArenaWriteContract();
  const { meta, addresses } = usePlatform();
  const { trackTransaction } = useActivity();
  const { t } = useI18n();
  const balance = useRtmBalance(address);
  const allowance = useAllowance(address, addresses?.arena);
  const now = useNow(15_000);
  const live = isContestLive(contest, now);
  const correctChain = isSupportedChain(walletChainId);
  const fee = attackFeeWei(contest, meta);

  const storageSuffix = useMemo(() => {
    const who = address?.toLowerCase() ?? "guest";
    return `${CHAIN_ID}:${contest.id.toLowerCase()}:${who}`;
  }, [address, contest.id]);

  const [pendingTurn, setPendingTurn] = useLocalStorage<PendingTurn | null>(
    `rtm.pending.v1:${storageSuffix}`,
    null,
  );
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<Step>("idle");
  const [error, setError] = useState("");

  async function requestDelivery(turn: PendingTurn): Promise<MessageResponse> {
    let lastError: unknown = null;
    for (let attempt = 0; attempt < 15; attempt += 1) {
      try {
        return await api.sendMessage(contest.id, {
          tx_hash: turn.txHash,
          content: turn.content,
        });
      } catch (reason) {
        lastError = reason;
        if (reason instanceof ApiClientError) {
          const detail = typeof reason.detail === "string" ? reason.detail : "";
          if (reason.status === 409 && /already processed/i.test(detail)) throw reason;
          if (reason.status === 503 || reason.status === 403 || reason.status === 410) {
            throw reason;
          }
          if ([408, 409, 502].includes(reason.status)) {
            await sleep(2_000);
            continue;
          }
        }
        throw reason;
      }
    }
    throw (
      lastError ??
      new Error(t("The message was not processed by the platform.", "消息未被平台处理。"))
    );
  }

  async function runDelivery(turn: PendingTurn): Promise<MessageResponse> {
    setStep("deliver");
    const response = await requestDelivery(turn);
    setPendingTurn(null);
    setStep("done");
    void balance.refetch();
    void allowance.refetch();
    onAfterSend?.();
    window.setTimeout(() => setStep("idle"), 2_000);
    return response;
  }

  async function send(content: string): Promise<MessageResponse> {
    setError("");
    if (!isConnected || !address) {
      throw new Error(t("Connect your wallet first.", "请先连接钱包。"));
    }
    if (!correctChain) {
      throw new Error(
        t("Switch to RTM Testnet (48850) first.", "请先切换到 RTM Testnet（48850）。"),
      );
    }
    if (!addresses) {
      throw new Error(
        t(
          "The platform API is not reachable yet, so contract addresses are unavailable.",
          "平台 API 尚未连通，暂时拿不到合约地址。",
        ),
      );
    }
    if (!joined) {
      throw new Error(t("You need to join this contest first.", "你需要先加入这场比赛。"));
    }
    if (!live) {
      throw new Error(
        t(
          "The contest has ended; paid messages can no longer be sent.",
          "比赛已经结束，不能再发送付费消息。",
        ),
      );
    }
    if (pendingTurn) {
      throw new Error(
        t(
          "A message is still undelivered. Continue delivery or discard the record first.",
          "还有一笔消息未送达，请先继续送达或丢弃记录。",
        ),
      );
    }
    const text = content.trim();
    if (!text) throw new Error(t("Enter a message to send.", "请输入要发送的消息。"));
    if (text.length > 1_000) {
      throw new Error(t("Messages can be up to 1,000 characters.", "消息最多 1000 个字符。"));
    }
    if (balance.data !== undefined && balance.data < fee) {
      throw new Error(
        t(
          "Insufficient tRTM balance. Get test tRTM from the faucet first.",
          "tRTM 余额不足，请先去水龙头领取测试 tRTM。",
        ),
      );
    }

    setBusy(true);
    try {
      // The cached allowance can be stale: joining spends the approval, but the
      // query may still hold the pre-join value.
      const refreshed = await allowance.refetch();
      const currentAllowance = refreshed.error ? 0n : refreshed.data ?? 0n;
      if (currentAllowance < fee) {
        setStep("approve");
        const desired = fee * 5n;
        const approvalAmount =
          balance.data !== undefined && balance.data < desired ? fee : desired;
        const approvalHash = await writeContractAsync({
          address: requireAddresses(addresses).rtm,
          abi: rtmAbi,
          functionName: "approve",
          args: [requireAddresses(addresses).arena, approvalAmount],
        });
        await trackTransaction(
          approvalHash,
          t("Approve message fees", "授权消息费"),
          "approve",
        );
      }

      setStep("chain");
      const msgHash = keccak256(
        toHex(`${address}:${contest.id}:${Date.now()}:${newId()}:${text}`),
      );
      const attackHash = await writeContractAsync({
        address: requireAddresses(addresses).arena,
        abi: arenaAbi,
        functionName: "attack",
        args: [contest.id as `0x${string}`, msgHash],
      });
      const turn: PendingTurn = {
        content: text,
        msgHash,
        txHash: attackHash,
        createdAt: Math.floor(Date.now() / 1000),
      };
      setPendingTurn(turn);
      await trackTransaction(attackHash, t("Send paid message", "发送付费消息"), "attack");
      return await runDelivery(turn);
    } catch (reason) {
      const message =
        reason instanceof Error
          ? reason.message
          : t("The message could not be sent.", "消息发送失败。");
      setError(message);
      setStep("idle");
      throw reason;
    } finally {
      setBusy(false);
    }
  }

  async function continuePending(): Promise<MessageResponse> {
    if (!pendingTurn) {
      throw new Error(t("There is no pending message.", "没有待送达的消息。"));
    }
    setError("");
    setBusy(true);
    try {
      return await runDelivery(pendingTurn);
    } catch (reason) {
      const message =
        reason instanceof Error
          ? reason.message
          : t("Delivery failed.", "送达失败。");
      setError(message);
      setStep("idle");
      throw reason;
    } finally {
      setBusy(false);
    }
  }

  function discardPending() {
    setPendingTurn(null);
  }

  const allowanceCount = fee > 0n && allowance.data ? allowance.data / fee : 0n;

  return {
    address,
    isConnected,
    correctChain,
    platformReady: Boolean(addresses),
    live,
    fee,
    balance,
    allowance,
    allowanceCount,
    pendingTurn,
    busy,
    step,
    error,
    setError,
    send,
    continuePending,
    discardPending,
  };
}
