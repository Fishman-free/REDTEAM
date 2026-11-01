import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { BookOpen, RefreshCw, TriangleAlert, X } from "lucide-react";
import { useAccount, usePublicClient } from "wagmi";
import {
  CHAIN_ID,
  connectedWalletName,
  diagnoseWallet,
  ensureChain,
  isSupportedChain,
  repairWalletNetwork,
  walletRpcUrl,
} from "../../lib/chain";
import type { WalletNetworkDiagnosis } from "../../lib/walletNetwork";
import { useWalletChainId } from "../../lib/useWalletChainId";
import { errorText } from "../../lib/format";
import { useI18n } from "../../lib/i18n";

/**
 * Explain which side of the wallet/network pair is broken.
 *
 * A matching chain id is not proof of the same ledger: two stacks can both
 * claim 48850. But an unreachable wallet RPC is also not proof of a fork. The
 * banner therefore separates "wrong chain", "wallet RPC cannot read", "site
 * RPC cannot read" and "definitively different block at the same height", and
 * only offers the action that can address that case.
 */
export function RpcBanner() {
  const { isConnected } = useAccount();
  const chainId = useWalletChainId();
  const publicClient = usePublicClient({ chainId: CHAIN_ID });
  const { t } = useI18n();
  const [diagnosis, setDiagnosis] = useState<WalletNetworkDiagnosis | null>(null);
  const [pending, setPending] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const sequence = useRef(0);

  const runCheck = useCallback(async () => {
    if (!isConnected || !publicClient) {
      setDiagnosis(null);
      return;
    }
    const id = sequence.current + 1;
    sequence.current = id;
    setNote(null);
    try {
      const result = await diagnoseWallet(publicClient);
      if (id === sequence.current) {
        if (result.kind !== "ok") {
          console.warn("[wallet] network diagnosis:", result);
        }
        setDiagnosis(result);
      }
    } catch (reason) {
      if (id === sequence.current) {
        setDiagnosis({ kind: "unverified", error: errorText(reason) });
      }
    }
  }, [isConnected, publicClient]);

  useEffect(() => {
    void runCheck();
  }, [runCheck, chainId]);

  async function switchNetwork() {
    setPending(true);
    setNote(null);
    try {
      await ensureChain();
      await new Promise((resolve) => window.setTimeout(resolve, 600));
      await runCheck();
    } catch (reason) {
      setNote(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  async function repairNetwork() {
    if (!publicClient) return;
    setPending(true);
    setNote(null);
    try {
      // Wallets do not expose a standard "edit existing chain" method. Some
      // accept wallet_addEthereumChain again and replace the RPC; others
      // ignore it. Re-probe and tell the user when the entry did not change.
      await repairWalletNetwork();
      await new Promise((resolve) => window.setTimeout(resolve, 700));
      const result = await diagnoseWallet(publicClient);
      setDiagnosis(result);
      if (result.kind === "wallet-rpc" || result.kind === "fork") {
        setNote(
          t(
            "The wallet did not update its RPC. Edit or delete the RTM Testnet entry in the wallet, then add it again with the address below.",
            "钱包没有更新 RPC。请在钱包中编辑或删除 RTM Testnet，然后用下方地址重新添加。",
          ),
        );
      } else if (result.kind === "wallet-chain") {
        setNote(
          t(
            "The wallet is still on another chain. Approve the switch in the wallet.",
            "钱包仍在其他链上，请在钱包中确认切换。",
          ),
        );
      }
    } catch (reason) {
      setNote(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  async function copyRpc() {
    try {
      await navigator.clipboard.writeText(walletRpcUrl());
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setNote(
        t(
          "Copy failed. Select the address manually.",
          "复制失败，请手动选择地址。",
        ),
      );
    }
  }

  // Render the wallet's own chain id immediately while the async probe runs.
  const fallback: WalletNetworkDiagnosis | null =
    chainId && !isSupportedChain(chainId)
      ? {
          kind: "wallet-chain",
          actualChainId: chainId,
          expectedChainId: CHAIN_ID,
        }
      : null;
  const issue = diagnosis && diagnosis.kind !== "ok" ? diagnosis : fallback;
  if (!isConnected || !issue || issue.kind === "no-wallet" || issue.kind === "unverified") {
    return null;
  }
  // A wallet-side RPC entry is the user's to fix; let them silence the warning
  // for this visit. The wrong-chain and fork cases still block writes, so
  // those banners stay visible.
  if (dismissed && issue.kind === "wallet-rpc") return null;

  const wallet = connectedWalletName() || t("This wallet", "当前钱包");
  const canEditRpc = issue.kind === "wallet-rpc" || issue.kind === "fork";
  const shortError = (text: string) => {
    const oneLine = text.replace(/\s+/g, " ").trim();
    return oneLine.length > 220 ? `${oneLine.slice(0, 220)}…` : oneLine;
  };
  let title: string;
  let body: ReactNode;

  if (issue.kind === "wallet-chain") {
    title = t("Wallet network is not the arena network", "钱包网络不正确");
    body = t(
      `The wallet is on chain ${issue.actualChainId}; switch it to RTM Testnet (${CHAIN_ID}).`,
      `钱包当前在链 ${issue.actualChainId}，请先切换到 RTM Testnet（${CHAIN_ID}）。`,
    );
  } else if (issue.kind === "wallet-rpc") {
    title = t("Your wallet cannot reach its RPC", "钱包 RPC 无法访问");
    body = (
      <>
        {t(
          `${wallet} reports chain ${CHAIN_ID}, but it cannot read a block from the RPC saved in the wallet. This usually means its RTM Testnet entry still points at an old or local address (for example localhost), not the address below. Open the wallet's network settings and change the RPC; if the wallet does not allow editing, delete the network and add it again. Switching networks alone does not rewrite an existing entry.`,
          `${wallet}报告的是链 ${CHAIN_ID}，但它无法从钱包里保存的 RPC 读取区块。通常是钱包中的 RTM Testnet 仍指向旧地址或本地地址（例如 localhost），而不是下方地址。请打开钱包的网络设置修改 RPC；如果钱包不允许编辑，请删除该网络后重新添加。只点“切换网络”不会改写已有网络的 RPC。`,
        )}{" "}
        <span className="network-banner__detail">
          {t("Wallet returned: ", "钱包返回：")}
          {shortError(issue.error)}
        </span>
      </>
    );
  } else if (issue.kind === "fork") {
    title = t(
      "Your wallet is on a different chain with the same ID",
      "钱包连接到了同 ID 的另一条链",
    );
    body = t(
      `Both sides report chain ${CHAIN_ID}, but block ${issue.height.toString()} has different hashes. The wallet's RPC points at another ledger. Set the wallet's RTM Testnet RPC to the address below.`,
      `钱包与本站都报告链 ${CHAIN_ID}，但区块 ${issue.height.toString()} 的哈希不同。钱包的 RPC 指向了另一条链。请把钱包里 RTM Testnet 的 RPC 改为下方地址。`,
    );
  } else {
    title = t("This site's RPC is unavailable", "本站 RPC 暂时不可用");
    body = (
      <>
        {t(
          "The page cannot read a block from this site's RPC. This is not a wallet network error. Retry shortly; if it persists, the site's RPC proxy is down.",
          "页面无法从本站 RPC 读取区块。这不是钱包网络错误。请稍后重试；如果持续出现，说明本站 RPC 代理不可用。",
        )}{" "}
        <span className="network-banner__detail">{shortError(issue.error)}</span>
      </>
    );
  }

  return (
    <div className={`network-banner network-banner--rpc network-banner--${issue.kind}`} role="alert">
      <span className="network-banner__icon">
        <TriangleAlert size={17} />
      </span>
      <div className="network-banner__text">
        <strong>{title}</strong>
        <div className="network-banner__message">{body}</div>
        {canEditRpc && (
          <div className="network-banner__rpc">
            <span>{t("Expected RPC", "期望 RPC")}</span>
            <code>{walletRpcUrl()}</code>
          </div>
        )}
        {note && <div className="network-banner__note">{note}</div>}
      </div>
      <div className="rpc-banner__actions">
        {issue.kind === "wallet-chain" && (
          <button
            type="button"
            className="btn btn--secondary btn--sm"
            onClick={() => void switchNetwork()}
            disabled={pending}
          >
            {pending ? t("Switching…", "切换中…") : t("Switch network", "切换网络")}
          </button>
        )}
        {canEditRpc && (
          <button
            type="button"
            className="btn btn--secondary btn--sm"
            onClick={() => void repairNetwork()}
            disabled={pending}
          >
            {pending ? t("Repairing…", "修复中…") : t("Try to repair network", "尝试修复网络")}
          </button>
        )}
        {canEditRpc && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => void copyRpc()}
          >
            {copied ? t("Copied", "已复制") : t("Copy RPC", "复制 RPC")}
          </button>
        )}
        <button
          type="button"
          className="btn btn--ghost btn--sm"
          onClick={() => void runCheck()}
          disabled={pending}
        >
          <RefreshCw size={12} />
          {t("Recheck", "重新检查")}
        </button>
        <Link to="/docs#troubleshooting" className="btn btn--secondary btn--sm">
          <BookOpen size={13} />
          {t("Network help", "网络说明")}
        </Link>
        {issue.kind === "wallet-rpc" && (
          <button
            type="button"
            className="icon-btn"
            aria-label={t("Dismiss", "关闭")}
            title={t("Dismiss", "关闭")}
            onClick={() => setDismissed(true)}
          >
            <X size={14} />
          </button>
        )}
      </div>
    </div>
  );
}
