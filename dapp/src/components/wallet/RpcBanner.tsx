import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, RefreshCw, TriangleAlert } from "lucide-react";
import { useAccount, usePublicClient } from "wagmi";
import {
  CHAIN_ID,
  assertWalletUsesAppChain,
  ensureChain,
  isSupportedChain,
  walletRpcUrl,
} from "../../lib/chain";
import { useWalletChainId } from "../../lib/useWalletChainId";
import { errorText } from "../../lib/format";
import { useI18n } from "../../lib/i18n";

/**
 * The chain id alone cannot distinguish two local stacks. Probe the wallet's
 * RPC against the application RPC and explain the mismatch before a write.
 */
export function RpcBanner() {
  const { isConnected } = useAccount();
  const chainId = useWalletChainId();
  const publicClient = usePublicClient({ chainId: CHAIN_ID });
  const { t } = useI18n();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const check = useCallback(() => {
    setMessage(null);
    if (!isConnected || !isSupportedChain(chainId) || !publicClient) return;
    let cancelled = false;
    void assertWalletUsesAppChain(publicClient)
      .then(() => {
        if (!cancelled) setMessage(null);
      })
      .catch((reason) => {
        if (!cancelled) setMessage(errorText(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [chainId, isConnected, publicClient]);

  useEffect(() => check(), [check]);

  async function switchNetwork() {
    setPending(true);
    try {
      // Targets the connected connector, not whichever wallet owns
      // window.ethereum, then re-runs the probe against that same wallet.
      await ensureChain();
      check();
    } catch (reason) {
      setMessage(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  if (!message) return null;

  return (
    <div className="network-banner network-banner--rpc" role="alert">
      <span className="network-banner__icon">
        <TriangleAlert size={17} />
      </span>
      <div className="network-banner__text">
        <strong>{t("Wallet RPC does not match this arena", "钱包 RPC 与本站不是同一条链")}</strong>
        <span>
          {message}{" "}
          <code>{walletRpcUrl()}</code>
        </span>
      </div>
      <div className="rpc-banner__actions">
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          onClick={() => void switchNetwork()}
          disabled={pending}
        >
          {pending ? t("Switching…", "切换中…") : t("Switch network", "切换网络")}
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={check}>
          <RefreshCw size={12} />
          {t("Recheck", "重新检查")}
        </button>
        <Link to="/docs#troubleshooting" className="btn btn--secondary btn--sm">
          <BookOpen size={13} />
          {t("Network help", "网络说明")}
        </Link>
      </div>
    </div>
  );
}
