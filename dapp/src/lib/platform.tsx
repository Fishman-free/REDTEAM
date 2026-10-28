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
import { ADDRESSES, arenaAbi, dataMarketAbi, faucetAbi, rtmAbi } from "./contracts";

export const FALLBACK_META: PlatformMeta = {
  network: "besu-testnet",
  chainId: 48850,
  rpc: "http://127.0.0.1:8546",
  addresses: { ...ADDRESSES },
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
  meta: PlatformMeta;
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

  const meta = metaQuery.data ?? FALLBACK_META;
  const online = Boolean(metaQuery.data) || Boolean(statusQuery.data);

  const value = useMemo<PlatformContextValue>(
    () => ({
      meta,
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

export function useContractAddresses() {
  const { meta } = usePlatform();
  return meta.addresses;
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
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.rtm as Address,
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
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.rtm as Address,
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
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.faucet as Address,
    abi: faucetAbi,
    functionName: "dripAmount",
    query: { staleTime: 60_000 },
  });
}

export function useFaucetNonce(address: string | undefined) {
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.faucet as Address,
    abi: faucetAbi,
    functionName: "nonces",
    args: address ? [address as Address] : undefined,
    query: { enabled: Boolean(address), refetchInterval: 20_000 },
  });
}

export function useDataMarketPrices() {
  const { meta } = usePlatform();
  const priceBps = useReadContract({
    address: meta.addresses.dataMarket as Address,
    abi: dataMarketAbi,
    functionName: "dataPriceBps",
    query: { staleTime: 60_000 },
  });
  const attackerPrice = useReadContract({
    address: meta.addresses.dataMarket as Address,
    abi: dataMarketAbi,
    functionName: "attackerDataPrice",
    query: { staleTime: 60_000 },
  });
  return { priceBps: priceBps.data, attackerPrice: attackerPrice.data };
}

export function useDatasetRoot(contestId: string | undefined) {
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.dataMarket as Address,
    abi: dataMarketAbi,
    functionName: "datasetRoot",
    args: contestId ? [contestId as `0x${string}`] : undefined,
    query: { enabled: Boolean(contestId), refetchInterval: 12_000 },
  });
}

export function useIsAttacker(contestId: string | undefined, address: string | undefined) {
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.arena as Address,
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
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.arena as Address,
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
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.arena as Address,
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
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.dataMarket as Address,
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
  const { meta } = usePlatform();
  return useReadContract({
    address: meta.addresses.dataMarket as Address,
    abi: dataMarketAbi,
    functionName: "boughtAttacker",
    args:
      contestId && attacker && buyer
        ? [contestId as `0x${string}`, attacker as Address, buyer as Address]
        : undefined,
    query: { enabled: Boolean(contestId && attacker && buyer) },
  });
}
