import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, RefreshCw, TriangleAlert } from "lucide-react";
import { useAccount, useChainId, usePublicClient } from "wagmi";
import { CHAIN_ID, assertWalletUsesAppChain, isSupportedChain, walletRpcUrl } from "../../lib/chain";
import { errorText } from "../../lib/format";
import { useI18n } from "../../lib/i18n";

/**
 * The chain id alone cannot distinguish two local stacks. Probe the wallet's
 * RPC against the application RPC and explain the mismatch before a write.
 */
export function RpcBanner() {
  const { isConnected } = useAccount();
  const chainId = useChainId();
  const publicClient = usePublicClient({ chainId: CHAIN_ID });
  const { t } = useI18n();
  const [message, setMessage] = useState<string | null>(null);

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
        <button type="button" className="btn btn--ghost btn--sm" onClick={check}>
          <RefreshCw size={12} />
          {t("Recheck", "重新检查")}
        </button>
        <Link to="/docs#troubleshooting" className="btn btn--secondary btn--sm">
          <BookOpen size={13} />
          {t("Fix RPC", "修复 RPC")}
        </Link>
      </div>
    </div>
  );
}
