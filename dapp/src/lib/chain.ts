import { createConfig, http } from "wagmi";
import { injected } from "wagmi/connectors";
import type { PublicClient } from "viem";
import { getLang } from "./i18n";

const isBrowser = typeof window !== "undefined";

export const CHAIN_ID = 48850;
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
    [besuTestnet.id]: http(RPC_URL),
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

interface InjectedProvider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}

interface RpcBlock {
  number: string;
  hash: string;
}

function injectedProvider(): InjectedProvider | null {
  if (!isBrowser) return null;
  const candidate = (window as unknown as { ethereum?: InjectedProvider }).ethereum;
  return candidate ?? null;
}

function withTimeout<T>(promise: Promise<T>, milliseconds: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(
      () => reject(new Error("Wallet RPC did not respond in time")),
      milliseconds,
    );
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    );
  });
}

/**
 * Several local stacks can expose the same chain id (48850) while holding
 * completely different state. Chain-id checks alone therefore cannot prove
 * that the wallet and this page talk to the same chain. Compare a block that
 * both endpoints should already have; different hashes mean a different chain.
 */
export async function assertWalletUsesAppChain(publicClient: PublicClient): Promise<void> {
  const provider = injectedProvider();
  if (!provider) throw new Error("未检测到浏览器钱包扩展。");

  const actualChainHex = (await withTimeout(
    provider.request({ method: "eth_chainId" }),
    8_000,
  )) as string;
  const actualChainId = Number.parseInt(actualChainHex, 16);
  if (actualChainId !== CHAIN_ID) {
    throw new Error(
      getLang() === "en"
        ? `Your wallet is on chain ${actualChainId}; switch it to RTM Testnet (${CHAIN_ID}).`
        : `钱包当前在链 ${actualChainId}，请先切换到 RTM Testnet（${CHAIN_ID}）。`,
    );
  }

  const [walletHeadHex, appHead] = await Promise.all([
    withTimeout(
      provider.request({ method: "eth_blockNumber" }) as Promise<string>,
      8_000,
    ),
    publicClient.getBlockNumber(),
  ]);
  const walletHead = BigInt(walletHeadHex);
  // Probe well behind both heads so normal propagation lag cannot cause a
  // false mismatch, while a different chain diverges at every height.
  const probeHeight = (walletHead < appHead ? walletHead : appHead) - 12n;
  if (probeHeight <= 0n) return;

  const [walletBlock, appBlock] = await Promise.all([
    withTimeout(
      provider.request({
        method: "eth_getBlockByNumber",
        params: [`0x${probeHeight.toString(16)}`, false],
      }) as Promise<RpcBlock | null>,
      8_000,
    ),
    publicClient.getBlock({ blockNumber: probeHeight }),
  ]);

  if (walletBlock && walletBlock.hash.toLowerCase() !== appBlock.hash.toLowerCase()) {
    throw new Error(
      getLang() === "en"
        ? `Your wallet is connected to a different local chain with the same chain ID (${CHAIN_ID}). Set the RTM Testnet RPC URL to ${walletRpcUrl()}, or remove and re-add the network from this site.`
        : `你的钱包连接到了另一条 chainId 同为 ${CHAIN_ID} 的本地链。请把钱包里 RTM Testnet 的 RPC 改为 ${walletRpcUrl()}，或删除该网络后从本站重新添加。`,
    );
  }
}

/**
 * Switch the injected wallet to RTM Testnet. If the chain is unknown to the
 * wallet, add it first. Throws a readable error when no wallet is available.
 */
export async function ensureChain(): Promise<void> {
  const provider = injectedProvider();
  if (!provider) throw new Error("未检测到浏览器钱包扩展。");
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: CHAIN_ID_HEX }],
    });
  } catch (error) {
    const code = (error as ProviderError).code;
    if (code !== 4902) throw error;
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [
        {
          chainId: CHAIN_ID_HEX,
          chainName: besuTestnet.name,
          nativeCurrency: besuTestnet.nativeCurrency,
          rpcUrls: [walletRpcUrl()],
          blockExplorerUrls: EXPLORER_URL ? [EXPLORER_URL] : [],
        },
      ],
    });
  }
}
