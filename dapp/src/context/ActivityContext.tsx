import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { useChainId, usePublicClient } from "wagmi";
import type { TransactionReceipt } from "viem";
import { assertWalletUsesAppChain } from "../lib/chain";
import { useLocalStorage } from "../lib/hooks";
import { useI18n } from "../lib/i18n";
import { errorText, shortHash } from "../lib/format";
import { useToast } from "./ToastContext";

export type ActivityStatus = "pending" | "confirmed" | "reverted" | "failed";

export interface ActivityRecord {
  id: string;
  label: string;
  hash?: string;
  kind: string;
  status: ActivityStatus;
  createdAt: number;
  chainId: number;
  error?: string;
}

interface ActivityContextValue {
  records: ActivityRecord[];
  pendingCount: number;
  trackTransaction: (hash: `0x${string}`, label: string, kind?: string) => Promise<TransactionReceipt>;
  refreshTransaction: (id: string) => Promise<void>;
  clear: () => void;
  remove: (id: string) => void;
}

const ActivityContext = createContext<ActivityContextValue | null>(null);

const STORAGE_KEY = "rtm.activity.v1";
const CONFIRMATION_TIMEOUT_MS = 90_000;

export function ActivityProvider({ children }: { children: ReactNode }) {
  const [records, setRecords] = useLocalStorage<ActivityRecord[]>(STORAGE_KEY, []);
  const publicClient = usePublicClient();
  const chainId = useChainId();
  const { toast } = useToast();
  const { t } = useI18n();

  const update = useCallback(
    (id: string, patch: Partial<ActivityRecord>) => {
      setRecords((current) =>
        current.map((record) => (record.id === id ? { ...record, ...patch } : record)),
      );
    },
    [setRecords],
  );

  const explainMissingTransaction = useCallback(
    async (
      hash: `0x${string}`,
    ): Promise<{ message: string; status: "pending" | "failed" }> => {
      if (!publicClient) {
        return {
          message: t("The application RPC is unavailable.", "本站 RPC 不可用。"),
          status: "failed",
        };
      }
      const transaction = await publicClient
        .getTransaction({ hash })
        .catch(() => null);
      if (transaction) {
        return {
          message: t(
            "The transaction was broadcast but is still waiting to be mined. Check it again in the activity drawer.",
            "交易已经广播，但还没有被打包。可以在交易活动中点击“重新检查”。",
          ),
          status: "pending",
        };
      }
      try {
        await assertWalletUsesAppChain(publicClient);
      } catch (reason) {
        return { message: errorText(reason), status: "failed" };
      }
      return {
        message: t(
          "The transaction never reached the chain used by this site. Check that your wallet RPC matches the site RPC, then request a new ticket and retry.",
          "这笔交易没有到达本站使用的链。请确认钱包 RPC 与本站一致，然后重新领取票据并重试。",
        ),
        status: "failed",
      };
    },
    [publicClient, t],
  );

  const trackTransaction = useCallback(
    async (hash: `0x${string}`, label: string, kind = "transaction") => {
      const id = hash.toLowerCase();
      setRecords((current) => {
        const without = current.filter((record) => record.id !== id);
        const record: ActivityRecord = {
          id,
          hash,
          label,
          kind,
          status: "pending",
          createdAt: Math.floor(Date.now() / 1000),
          chainId,
        };
        return [record, ...without].slice(0, 60);
      });
      toast({
        title: t("Transaction submitted", "交易已提交"),
        description: `${label} · ${shortHash(hash)}`,
        tone: "info",
        duration: 3_500,
      });

      if (!publicClient) {
        const message = t("The application RPC is not ready.", "本站 RPC 尚未就绪。");
        update(id, { status: "failed", error: message });
        toast({ title: message, tone: "error" });
        throw new Error(message);
      }

      try {
        const receipt = await publicClient.waitForTransactionReceipt({
          hash,
          timeout: CONFIRMATION_TIMEOUT_MS,
          pollingInterval: 1_500,
        });
        if (receipt.status !== "success") {
          update(id, { status: "reverted", error: t("Transaction reverted", "交易执行失败") });
          toast({
            title: t("Transaction reverted", "交易执行失败"),
            description: t(
              `${label} was reverted on-chain.`,
              `${label} 在链上被回滚。`,
            ),
            tone: "error",
          });
          throw new Error(t("Transaction reverted", "交易执行失败"));
        }
        update(id, { status: "confirmed", error: undefined });
        toast({
          title: t("Transaction confirmed", "交易已确认"),
          description: `${label} · ${shortHash(hash)}`,
          tone: "success",
          duration: 4_000,
        });
        return receipt;
      } catch (error) {
        const diagnosis = await explainMissingTransaction(hash);
        update(id, { status: diagnosis.status, error: diagnosis.message });
        toast({
          title: t("Transaction not confirmed", "交易尚未确认"),
          description: diagnosis.message,
          tone: "error",
          duration: 8_000,
        });
        throw error;
      }
    },
    [chainId, explainMissingTransaction, publicClient, setRecords, t, toast, update],
  );

  const refreshTransaction = useCallback(
    async (id: string) => {
      const record = records.find((item) => item.id === id);
      if (!record?.hash || !publicClient) return;
      const hash = record.hash as `0x${string}`;
      toast({
        title: t("Checking transaction", "正在检查交易"),
        description: shortHash(hash),
        tone: "info",
        duration: 2_500,
      });
      try {
        const receipt = await publicClient.getTransactionReceipt({ hash });
        if (receipt.status === "success") {
          update(id, { status: "confirmed", error: undefined });
          toast({ title: t("Transaction confirmed", "交易已确认"), tone: "success" });
        } else {
          update(id, { status: "reverted", error: t("Transaction reverted", "交易执行失败") });
          toast({ title: t("Transaction reverted", "交易执行失败"), tone: "error" });
        }
      } catch {
        const diagnosis = await explainMissingTransaction(hash);
        update(id, { status: diagnosis.status, error: diagnosis.message });
        toast({
          title: t("Still waiting", "仍未找到交易"),
          description: diagnosis.message,
          tone: "info",
          duration: 7_000,
        });
      }
    },
    [explainMissingTransaction, publicClient, records, t, toast, update],
  );

  const clear = useCallback(() => setRecords([]), [setRecords]);
  const remove = useCallback(
    (id: string) => setRecords((current) => current.filter((record) => record.id !== id)),
    [setRecords],
  );

  const pendingCount = records.filter((record) => record.status === "pending").length;

  const value = useMemo(
    () => ({
      records,
      pendingCount,
      trackTransaction,
      refreshTransaction,
      clear,
      remove,
    }),
    [clear, pendingCount, records, refreshTransaction, remove, trackTransaction],
  );

  return <ActivityContext.Provider value={value}>{children}</ActivityContext.Provider>;
}

export function useActivity(): ActivityContextValue {
  const context = useContext(ActivityContext);
  if (!context) throw new Error("useActivity must be used inside ActivityProvider");
  return context;
}
