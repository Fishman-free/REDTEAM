import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { useChainId, usePublicClient } from "wagmi";
import type { TransactionReceipt } from "viem";
import { useLocalStorage } from "../lib/hooks";
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
  clear: () => void;
  remove: (id: string) => void;
}

const ActivityContext = createContext<ActivityContextValue | null>(null);

const STORAGE_KEY = "rtm.activity.v1";

export function ActivityProvider({ children }: { children: ReactNode }) {
  const [records, setRecords] = useLocalStorage<ActivityRecord[]>(STORAGE_KEY, []);
  const publicClient = usePublicClient();
  const chainId = useChainId();
  const { toast } = useToast();

  const update = useCallback(
    (id: string, patch: Partial<ActivityRecord>) => {
      setRecords((current) =>
        current.map((record) => (record.id === id ? { ...record, ...patch } : record)),
      );
    },
    [setRecords],
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
        title: "交易已提交",
        description: `${label} · ${shortHash(hash)}`,
        tone: "info",
        duration: 3_500,
      });

      if (!publicClient) {
        update(id, { status: "failed", error: "RPC 未就绪" });
        toast({ title: "RPC 未就绪", tone: "error" });
        throw new Error("RPC 未就绪");
      }

      try {
        const receipt = await publicClient.waitForTransactionReceipt({
          hash,
          timeout: 180_000,
        });
        if (receipt.status !== "success") {
          update(id, { status: "reverted", error: "交易执行失败" });
          toast({
            title: "交易执行失败",
            description: `${label} 在链上被回滚。`,
            tone: "error",
          });
          throw new Error("交易执行失败");
        }
        update(id, { status: "confirmed" });
        toast({
          title: "交易已确认",
          description: `${label} · ${shortHash(hash)}`,
          tone: "success",
          duration: 4_000,
        });
        return receipt;
      } catch (error) {
        const message = errorText(error);
        update(id, { status: "failed", error: message });
        toast({
          title: "交易未完成",
          description: message,
          tone: "error",
        });
        throw error;
      }
    },
    [chainId, publicClient, setRecords, toast, update],
  );

  const clear = useCallback(() => setRecords([]), [setRecords]);
  const remove = useCallback(
    (id: string) => setRecords((current) => current.filter((record) => record.id !== id)),
    [setRecords],
  );

  const pendingCount = records.filter((record) => record.status === "pending").length;

  const value = useMemo(
    () => ({ records, pendingCount, trackTransaction, clear, remove }),
    [clear, pendingCount, records, remove, trackTransaction],
  );

  return <ActivityContext.Provider value={value}>{children}</ActivityContext.Provider>;
}

export function useActivity(): ActivityContextValue {
  const context = useContext(ActivityContext);
  if (!context) throw new Error("useActivity must be used inside ActivityProvider");
  return context;
}
