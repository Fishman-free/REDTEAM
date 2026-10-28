import { createConfig, http } from "wagmi";
import { injected } from "wagmi/connectors";

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
function absoluteRpcUrl(): string {
  if (/^https?:\/\//i.test(RPC_URL)) return RPC_URL;
  if (!isBrowser) return RPC_URL;
  return `${window.location.origin}${RPC_URL.startsWith("/") ? "" : "/"}${RPC_URL}`;
}

type ProviderError = Error & { code?: number };

interface InjectedProvider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}

function injectedProvider(): InjectedProvider | null {
  if (!isBrowser) return null;
  const candidate = (window as unknown as { ethereum?: InjectedProvider }).ethereum;
  return candidate ?? null;
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
          rpcUrls: [absoluteRpcUrl()],
          blockExplorerUrls: EXPLORER_URL ? [EXPLORER_URL] : [],
        },
      ],
    });
  }
}
