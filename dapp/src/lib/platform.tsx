import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { useReadContract } from "wagmi";
import type { Address } from "viem";
import {
  api,
  type Contest,
  type ContestDetail,
  type IndexerStatus,
  type Leaderboards,
  type PlatformMeta,
} from "./api";
import { arenaAbi, dataMarketAbi, faucetAbi, rtmAbi } from "./contracts";
import { walletRpcUrl } from "./chain";
import { getLang } from "./i18n";

export type ContractAddresses = PlatformMeta["addresses"];
export type PlatformDefaults = Omit<PlatformMeta, "addresses">;

/**
 * Display defaults while GET /meta is loading or the API is offline.
 * Deliberately has no contract addresses: every deployment gets fresh ones, so
 * a hardcoded copy can only ever point reads and writes at stale contracts.
 */
export const FALLBACK_META: PlatformDefaults = {
  network: "besu-testnet",
  chainId: 48850,
  rpc: walletRpcUrl(),
  fees: {
    attackFeeBps: 50,
    miningFeeBps: 50,
    miningRewardWei: "1000000000000000000",
    miningFeeWei: "5000000000000000",
  },
  limits: {
    minDurationH: 6,
    maxDurationH: 168,
    minStakeBps: 200,
    maxStakeBps: 2000,
    maxActiveMining: 3,
  },
  providers: [],
  faucet: { dripAmountWei: "200000000000000000000", captchaRequired: false },
  features: { mining: true, dataMarket: true, defenderRegistration: true },
  indexer: { startBlock: 0 },
};

interface PlatformContextValue {
  meta: PlatformDefaults;
  /** Contract addresses from GET /meta only; null until the API answers. */
  addresses: ContractAddresses | null;
  metaSource: "api" | "fallback";
  metaLoading: boolean;
  status: IndexerStatus | undefined;
  online: boolean;
  refetchMeta: () => void;
  refetchStatus: () => void;
}

const PlatformContext = createContext<PlatformContextValue | null>(null);

export function PlatformProvider({ children }: { children: ReactNode }) {
  const metaQuery = useQuery({
    queryKey: ["platform", "meta"],
    queryFn: api.meta,
    retry: 1,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const statusQuery = useQuery({
    queryKey: ["platform", "status"],
    queryFn: api.status,
    retry: 1,
    refetchInterval: 12_000,
    refetchOnWindowFocus: false,
  });

  const meta: PlatformDefaults = metaQuery.data ?? FALLBACK_META;
  const online = Boolean(metaQuery.data) || Boolean(statusQuery.data);

  const value = useMemo<PlatformContextValue>(
    () => ({
      meta,
      addresses: metaQuery.data?.addresses ?? null,
      metaSource: metaQuery.data ? "api" : "fallback",
      metaLoading: metaQuery.isLoading,
      status: statusQuery.data,
      online,
      refetchMeta: () => void metaQuery.refetch(),
      refetchStatus: () => void statusQuery.refetch(),
    }),
    [meta, metaQuery.data, metaQuery.isLoading, online, statusQuery.data],
  );

  return <PlatformContext.Provider value={value}>{children}</PlatformContext.Provider>;
}

export function usePlatform(): PlatformContextValue {
  const context = useContext(PlatformContext);
  if (!context) throw new Error("usePlatform must be used inside PlatformProvider");
  return context;
}

export function useContractAddresses(): ContractAddresses | null {
  return usePlatform().addresses;
}

/** For write handlers: refuse to build a transaction without API addresses. */
export function requireAddresses(
  addresses: ContractAddresses | null,
): Record<keyof ContractAddresses, Address> {
  if (!addresses) {
    throw new Error(
      getLang() === "en"
        ? "Contract addresses come only from the platform API, which is not reachable. Retry once it is back online."
        : "合约地址只从平台 API 获取，当前 API 未连通；请等 API 恢复后重试。",
    );
  }
  return addresses as Record<keyof ContractAddresses, Address>;
}

export function useContestsQuery() {
  return useQuery<Contest[]>({
    queryKey: ["contests"],
    queryFn: () => api.contests(),
    retry: 1,
    staleTime: 6_000,
    refetchInterval: 12_000,
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
  });
}

export function useContestQuery(contestId: string | undefined) {
  return useQuery<ContestDetail>({
    queryKey: ["contest", contestId],
    queryFn: () => api.contest(contestId as string),
    enabled: Boolean(contestId),
    retry: 1,
    staleTime: 4_000,
    refetchInterval: (query) => {
      const state = query.state.data?.contest.state;
      return state === "live" ? 6_000 : 25_000;
    },
    refetchOnWindowFocus: false,
  });
}

export function useLeaderboardsQuery() {
  return useQuery<Leaderboards>({
    queryKey: ["leaderboards"],
    queryFn: api.leaderboards,
    retry: 1,
    staleTime: 12_000,
    refetchInterval: 20_000,
    refetchOnWindowFocus: false,
    placeholderData: (previous) => previous,
  });
}

export function useRtmBalance(address: string | undefined) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.rtm as Address | undefined,
    abi: rtmAbi,
    functionName: "balanceOf",
    args: address ? [address as Address] : undefined,
    query: {
      enabled: Boolean(address),
      refetchInterval: 15_000,
      staleTime: 5_000,
    },
  });
}

export function useAllowance(owner: string | undefined, spender: string | undefined) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.rtm as Address | undefined,
    abi: rtmAbi,
    functionName: "allowance",
    args: owner && spender ? [owner as Address, spender as Address] : undefined,
    query: {
      enabled: Boolean(owner && spender),
      refetchInterval: 12_000,
      staleTime: 5_000,
    },
  });
}

export function useFaucetDrip() {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.faucet as Address | undefined,
    abi: faucetAbi,
    functionName: "dripAmount",
    query: { staleTime: 60_000 },
  });
}

export function useFaucetNonce(address: string | undefined) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.faucet as Address | undefined,
    abi: faucetAbi,
    functionName: "nonces",
    args: address ? [address as Address] : undefined,
    query: { enabled: Boolean(address), refetchInterval: 20_000 },
  });
}

export function useDataMarketPrices() {
  const addresses = useContractAddresses();
  const priceBps = useReadContract({
    address: addresses?.dataMarket as Address | undefined,
    abi: dataMarketAbi,
    functionName: "dataPriceBps",
    query: { staleTime: 60_000 },
  });
  const attackerPrice = useReadContract({
    address: addresses?.dataMarket as Address | undefined,
    abi: dataMarketAbi,
    functionName: "attackerDataPrice",
    query: { staleTime: 60_000 },
  });
  return { priceBps: priceBps.data, attackerPrice: attackerPrice.data };
}

export function useDatasetRoot(contestId: string | undefined) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.dataMarket as Address | undefined,
    abi: dataMarketAbi,
    functionName: "datasetRoot",
    args: contestId ? [contestId as `0x${string}`] : undefined,
    query: { enabled: Boolean(contestId), refetchInterval: 12_000 },
  });
}

export function useIsAttacker(contestId: string | undefined, address: string | undefined) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.arena as Address | undefined,
    abi: arenaAbi,
    functionName: "isRegisteredAttacker",
    args:
      contestId && address
        ? [contestId as `0x${string}`, address as Address]
        : undefined,
    query: { enabled: Boolean(contestId && address), refetchInterval: 12_000 },
  });
}

export function useDataConsent(contestId: string | undefined, address: string | undefined) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.arena as Address | undefined,
    abi: arenaAbi,
    functionName: "dataConsent",
    args:
      contestId && address
        ? [contestId as `0x${string}`, address as Address]
        : undefined,
    query: { enabled: Boolean(contestId && address), refetchInterval: 20_000 },
  });
}

export function useRemainingStake(contestId: string | undefined, address: string | undefined) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.arena as Address | undefined,
    abi: arenaAbi,
    functionName: "remainingStake",
    args:
      contestId && address
        ? [contestId as `0x${string}`, address as Address]
        : undefined,
    query: { enabled: Boolean(contestId && address), refetchInterval: 15_000 },
  });
}

export function useBoughtOwn(contestId: string | undefined, address: string | undefined) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.dataMarket as Address | undefined,
    abi: dataMarketAbi,
    functionName: "boughtOwn",
    args:
      contestId && address
        ? [contestId as `0x${string}`, address as Address]
        : undefined,
    query: { enabled: Boolean(contestId && address) },
  });
}

export function useBoughtAttacker(
  contestId: string | undefined,
  attacker: string | undefined,
  buyer: string | undefined,
) {
  const addresses = useContractAddresses();
  return useReadContract({
    address: addresses?.dataMarket as Address | undefined,
    abi: dataMarketAbi,
    functionName: "boughtAttacker",
    args:
      contestId && attacker && buyer
        ? [contestId as `0x${string}`, attacker as Address, buyer as Address]
        : undefined,
    query: { enabled: Boolean(contestId && attacker && buyer) },
  });
}
