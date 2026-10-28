import { createConfig, http } from "wagmi";
import { injected } from "wagmi/connectors";

export const RPC_URL =
  import.meta.env.VITE_RPC_URL || "http://127.0.0.1:8546";

export const besuTestnet = {
  id: 48850,
  name: "RTM Testnet",
  nativeCurrency: { name: "RTMGAS", symbol: "G", decimals: 18 },
  rpcUrls: {
    default: { http: [RPC_URL] },
  },
  blockExplorers: undefined,
} as const;

export const wagmiConfig = createConfig({
  chains: [besuTestnet],
  connectors: [injected()],
  transports: {
    [besuTestnet.id]: http(RPC_URL),
  },
  ssr: false,
});
