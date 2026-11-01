import { createConfig, http } from "wagmi";
import { getAccount } from "wagmi/actions";
import { injected } from "wagmi/connectors";
import type { PublicClient } from "viem";
import { getLang } from "./i18n";
import {
  ARENA_CHAIN_ID,
  diagnoseWalletNetwork,
  type Eip1193Provider,
  type WalletNetworkDiagnosis,
} from "./walletNetwork";

const isBrowser = typeof window !== "undefined";

export const CHAIN_ID = ARENA_CHAIN_ID;
export const CHAIN_ID_HEX = "0xbed2";

export const RPC_URL =
  import.meta.env.VITE_RPC_URL ||
  (import.meta.env.DEV ? "http://127.0.0.1:8546" : `${isBrowser ? window.location.origin : ""}/rpc`);

export const EXPLORER_URL = (import.meta.env.VITE_EXPLORER_URL || "").replace(/\/+$/, "");

export const besuTestnet = {
  id: CHAIN_ID,
  name: "RTM Testnet",
  nativeCurrency: { name: "RTM Gas", symbol: "G", decimals: 18 },
  rpcUrls: {
    default: { http: [RPC_URL] },
    public: { http: [RPC_URL] },
  },
  blockExplorers: EXPLORER_URL
    ? { default: { name: "RTM Explorer", url: EXPLORER_URL } }
    : undefined,
  testnet: true,
} as const;

export const wagmiConfig = createConfig({
  chains: [besuTestnet],
  connectors: [injected({ shimDisconnect: true })],
  transports: {
    // The public testnet RPC occasionally stalls. One retry with a wider
    // timeout keeps transient stalls from aborting reads and receipt waits.
    [besuTestnet.id]: http(RPC_URL, { timeout: 20_000, retryCount: 1, retryDelay: 800 }),
  },
  ssr: false,
});

export function isSupportedChain(chainId?: number | null): boolean {
  return chainId === CHAIN_ID;
}

/** Absolute RPC for wallet_addEthereumChain (wallets reject relative URLs). */
export function walletRpcUrl(): string {
  if (/^https?:\/\//i.test(RPC_URL)) return RPC_URL;
  if (!isBrowser) return RPC_URL;
  return `${window.location.origin}${RPC_URL.startsWith("/") ? "" : "/"}${RPC_URL}`;
}

type ProviderError = Error & { code?: number };

interface RpcBlock {
  number: string;
  hash: string;
}

function isInjectedProvider(value: unknown): value is Eip1193Provider {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Eip1193Provider).request === "function"
  );
}

/**
 * Resolve the provider of the wallet the user actually connected.
 *
 * Several extensions can inject themselves at once. `window.ethereum` is
 * whichever one won the injection race, which is not necessarily the wallet
 * wagmi connected through EIP-6963 discovery. Probing or switching that global
 * provider would report another wallet's chain (for example MetaMask on chain 1
 * while Binance Wallet is on 48850) and block every write with a false alarm.
 */
async function injectedProvider(): Promise<Eip1193Provider | null> {
  if (!isBrowser) return null;
  const connector = getAccount(wagmiConfig).connector;
  if (connector) {
    const provider: unknown = await connector.getProvider();
    return isInjectedProvider(provider) ? provider : null;
  }
  // Disconnected: fall back to the legacy global for pre-connect checks.
  const candidate = (window as unknown as { ethereum?: Eip1193Provider }).ethereum;
  return candidate ?? null;
}

/** Name of the connected wallet, for diagnostics in the banner. */
export function connectedWalletName(): string {
  if (!isBrowser) return "";
  try {
    return getAccount(wagmiConfig).connector?.name ?? "";
  } catch {
    return "";
  }
}

function normalizeProviderError(error: unknown): ProviderError {
  if (error instanceof Error) return error as ProviderError;
  if (typeof error === "object" && error !== null) {
    const record = error as { message?: unknown; code?: unknown };
    const normalized = new Error(
      typeof record.message === "string" ? record.message : "wallet request failed",
    ) as ProviderError;
    if (typeof record.code === "number") normalized.code = record.code;
    return normalized;
  }
  return new Error(String(error));
}

function withTimeout<T>(promise: Promise<T>, milliseconds: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = globalThis.setTimeout(
      () => reject(new Error("Wallet RPC did not respond in time")),
      milliseconds,
    );
    promise.then(
      (value) => {
        globalThis.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        globalThis.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

const PROBE_TIMEOUT_MS = 12_000;
const APP_PROBE_TIMEOUT_MS = 8_000;
const PROBE_ATTEMPTS = 2;
const PROBE_RETRY_DELAY_MS = 350;

/**
 * A slow or briefly unreachable wallet RPC is not a wrong-chain wallet. Retry
 * network-shaped failures once so a transient stall does not surface as a
 * fork warning. User rejections and unsupported methods are never retried.
 */
function isRetryableProbeError(error: unknown): boolean {
  const normalized = normalizeProviderError(error);
  if (normalized.code === 4001 || normalized.code === 4100 || normalized.code === 4200) {
    return false;
  }
  if (normalized.code === -32601) return false;
  return /did not respond in time|failed to fetch|network ?error|networkerror|fetch failed|timeout|timed out|econn|socket hang up|load failed/i.test(
    normalized.message,
  );
}

async function probeProvider<T>(
  provider: Eip1193Provider,
  method: string,
  params?: unknown[],
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < PROBE_ATTEMPTS; attempt += 1) {
    try {
      return (await withTimeout(
        provider.request({ method, params }),
        PROBE_TIMEOUT_MS,
      )) as T;
    } catch (error) {
      lastError = normalizeProviderError(error);
      if (!isRetryableProbeError(error) || attempt === PROBE_ATTEMPTS - 1) {
        throw lastError;
      }
      await new Promise((resolve) =>
        globalThis.setTimeout(resolve, PROBE_RETRY_DELAY_MS),
      );
    }
  }
  throw lastError;
}

/** Translate the raw wallet/app RPC probes into a user-visible diagnosis. */
export async function diagnoseWallet(
  publicClient: PublicClient,
): Promise<WalletNetworkDiagnosis> {
  const provider = await injectedProvider();
  if (!provider) return { kind: "no-wallet" };
  return diagnoseWalletNetwork({
    walletChainId: async () => {
      const raw = await probeProvider<string>(provider, "eth_chainId");
      const chainId = Number.parseInt(String(raw), 16);
      if (!Number.isFinite(chainId) || chainId <= 0) {
        throw new Error("The wallet returned an invalid chain id.");
      }
      return chainId;
    },
    walletHead: async () =>
      BigInt(String(await probeProvider<string>(provider, "eth_blockNumber"))),
    walletBlock: async (height) => {
      const block = await probeProvider<RpcBlock | null>(
        provider,
        "eth_getBlockByNumber",
        [`0x${height.toString(16)}`, false],
      );
      return block && typeof block.hash === "string" ? { hash: block.hash } : null;
    },
    // Cap the app-side probes so a dead RPC cannot stall every write for the
    // transport's 20 s timeout plus retry. A timeout is inconclusive, not a
    // fork; the guard lets the wallet try.
    appHead: () =>
      withTimeout(publicClient.getBlockNumber(), APP_PROBE_TIMEOUT_MS),
    appBlock: async (height) => ({
      hash: (
        await withTimeout(
          publicClient.getBlock({ blockNumber: height }),
          APP_PROBE_TIMEOUT_MS,
        )
      ).hash,
    }),
  });
}

export class WalletChainMismatchError extends Error {
  readonly actualChainId: number;

  constructor(actualChainId: number) {
    super(
      getLang() === "en"
        ? `Your wallet is on chain ${actualChainId}; switch it to RTM Testnet (${CHAIN_ID}).`
        : `钱包当前在链 ${actualChainId}，请先切换到 RTM Testnet（${CHAIN_ID}）。`,
    );
    this.name = "WalletChainMismatchError";
    this.actualChainId = actualChainId;
  }
}

export class WalletForkError extends Error {
  constructor() {
    super(
      getLang() === "en"
        ? `This wallet is on a different chain with the same chain ID (${CHAIN_ID}). Open the wallet's RTM Testnet network settings and change its RPC to ${walletRpcUrl()}, or delete the network and add it again.`
        : `这个钱包连接到了另一条 chain ID 同为 ${CHAIN_ID} 的链。请打开钱包的 RTM Testnet 网络设置，把 RPC 改为 ${walletRpcUrl()}，或删除该网络后重新添加。`,
    );
    this.name = "WalletForkError";
  }
}

/**
 * Guard called before every write.
 *
 * A different chain id, or two successfully read blocks with different hashes,
 * blocks the write. A wallet that merely cannot read its own RPC is *not*
 * proof of a fork: blocking there turned a transient wallet-RPC failure into a
 * permanent "wrong network" alarm. In that case we let the wallet attempt the
 * transaction and surface its own error, while the banner explains the RPC.
 */
export async function assertWalletUsesAppChain(
  publicClient: PublicClient,
): Promise<void> {
  const diagnosis = await diagnoseWallet(publicClient);
  if (diagnosis.kind === "wallet-chain") {
    throw new WalletChainMismatchError(diagnosis.actualChainId);
  }
  if (diagnosis.kind === "fork") {
    throw new WalletForkError();
  }
  if (diagnosis.kind === "no-wallet") {
    throw new Error(
      getLang() === "en"
        ? "No browser wallet is available."
        : "未检测到浏览器钱包扩展。",
    );
  }
  if (diagnosis.kind !== "ok") {
    console.warn("[wallet] chain cross-check was inconclusive:", diagnosis);
  }
}

function chainParams() {
  return {
    chainId: CHAIN_ID_HEX,
    chainName: besuTestnet.name,
    nativeCurrency: besuTestnet.nativeCurrency,
    rpcUrls: [walletRpcUrl()],
    blockExplorerUrls: EXPLORER_URL ? [EXPLORER_URL] : [],
  };
}

function isUnknownChainError(error: unknown): boolean {
  const normalized = normalizeProviderError(error);
  return (
    normalized.code === 4902 ||
    /unrecognized chain|unknown chain|not added|未添加|不支持.*链/i.test(
      normalized.message,
    )
  );
}

/**
 * Switch the injected wallet to RTM Testnet. If the chain is unknown to the
 * wallet, add it first. Throws a readable error when no wallet is available.
 */
export async function ensureChain(): Promise<void> {
  const provider = await injectedProvider();
  if (!provider) throw new Error("未检测到浏览器钱包扩展。");
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: CHAIN_ID_HEX }],
    });
  } catch (error) {
    if (!isUnknownChainError(error)) throw error;
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [chainParams()],
    });
  }
}

/**
 * Try to repair a wallet entry whose RPC no longer works.
 *
 * Wallets have no standard method to *edit* an existing chain. Some wallets
 * update the entry when `wallet_addEthereumChain` is called again; others
 * ignore it. Callers must re-probe afterwards and show manual instructions if
 * the RPC still fails. `wallet_switchEthereumChain` alone never rewrites an
 * existing entry, which is why the old "Switch network" button could not fix
 * this case.
 */
export async function repairWalletNetwork(): Promise<void> {
  const provider = await injectedProvider();
  if (!provider) throw new Error("未检测到浏览器钱包扩展。");
  let addError: unknown;
  try {
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [chainParams()],
    });
  } catch (error) {
    addError = error;
  }
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: CHAIN_ID_HEX }],
    });
  } catch (error) {
    if (addError) throw addError;
    throw error;
  }
}
