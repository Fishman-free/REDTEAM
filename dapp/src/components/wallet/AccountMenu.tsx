import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen,
  ChevronDown,
  Copy,
  Droplets,
  ExternalLink,
  LogOut,
  RefreshCw,
  Wallet,
} from "lucide-react";
import { useAccount, useBalance, useChainId, useDisconnect, useSwitchChain } from "wagmi";
import { Identicon } from "./Identicon";
import { useOnClickOutside, useCopy } from "../../lib/hooks";
import { usePlatform, useRtmBalance } from "../../lib/platform";
import { CHAIN_ID, ensureChain, isSupportedChain } from "../../lib/chain";
import { useI18n } from "../../lib/i18n";
import { errorText, formatRtm, shortAddr } from "../../lib/format";
import { useToast } from "../../context/ToastContext";
import { Badge } from "../ui/Badge";

export function AccountMenu() {
  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { disconnect } = useDisconnect();
  const { switchChainAsync } = useSwitchChain();
  const { meta } = usePlatform();
  const { t } = useI18n();
  const rtm = useRtmBalance(address);
  const native = useBalance({ address, query: { enabled: Boolean(address) } });
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const [copied, copy] = useCopy();
  const { toast } = useToast();

  useOnClickOutside(rootRef, () => setOpen(false), open);

  if (!isConnected || !address) return null;

  async function switchNetwork() {
    setSwitching(true);
    try {
      await switchChainAsync({ chainId: CHAIN_ID });
    } catch (reason) {
      try {
        await ensureChain();
      } catch {
        toast({
          title: t("Network switch failed", "切换网络失败"),
          description: errorText(reason),
          tone: "error",
        });
      }
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div className="account" ref={rootRef}>
      <button
        type="button"
        className={`account__trigger ${open ? "is-open" : ""}`.trim()}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Identicon address={address} size={30} />
        <span className="account__trigger-text">
          <span className="account__address mono">{shortAddr(address)}</span>
          <span className={`account__network ${isSupportedChain(chainId) ? "" : "is-wrong"}`}>
            {isSupportedChain(chainId)
              ? meta.network
              : t(`Wrong network #${chainId}`, `错误网络 #${chainId}`)}
          </span>
        </span>
        <ChevronDown size={14} className={open ? "rotate-180" : ""} />
      </button>

      {open && (
        <div className="account__menu" role="menu">
          <div className="account__head">
            <Identicon address={address} size={38} />
            <div>
              <p className="account__full mono">{shortAddr(address, 10, 8)}</p>
              <button
                type="button"
                className="account__copy"
                onClick={() => void copy(address)}
              >
                <Copy size={11} />
                {copied ? t("Copied", "已复制") : t("Copy full address", "复制完整地址")}
              </button>
            </div>
          </div>

          <div className="account__balances">
            <div>
              <span><span className="preserve-case">tRTM</span> {t("balance", "余额")}</span>
              <strong className="tabular">{formatRtm(rtm.data)}</strong>
            </div>
            <div>
              <span>{t("Gas (G)", "gas（G）")}</span>
              <strong className="tabular">
                {native.data ? `${Number(native.data.formatted).toFixed(3)}` : "—"}
              </strong>
            </div>
          </div>

          <div className="account__row">
            <span className="account__row-label">{t("Network", "网络")}</span>
            {isSupportedChain(chainId) ? (
              <Badge tone="success" dot>
                {meta.network} · {meta.chainId}
              </Badge>
            ) : (
              <button
                type="button"
                className="account__link"
                onClick={() => void switchNetwork()}
                disabled={switching}
              >
                <RefreshCw size={12} className={switching ? "spin" : ""} />
                {t(`Switch to ${meta.chainId}`, `切换到 ${meta.chainId}`)}
              </button>
            )}
          </div>

          <Link className="account__action" to="/faucet" onClick={() => setOpen(false)}>
            <Droplets size={15} />
            {t("Claim test tRTM", "领取测试 tRTM")}
          </Link>
          <Link className="account__action" to="/docs" onClick={() => setOpen(false)}>
            <BookOpen size={15} />
            {t("Field manual", "使用文档")}
          </Link>
          <button
            type="button"
            className="account__action"
            onClick={() => {
              void rtm.refetch();
              void native.refetch();
            }}
          >
            <Wallet size={15} />
            {t("Refresh balances", "刷新余额")}
          </button>
          <button
            type="button"
            className="account__action account__action--danger"
            onClick={() => {
              disconnect();
              setOpen(false);
            }}
          >
            <LogOut size={15} />
            {t("Disconnect wallet", "断开钱包")}
          </button>
          {isSupportedChain(chainId) && (
            <a
              className="account__foot mono"
              href={`${meta.rpc}`}
              target="_blank"
              rel="noreferrer"
              onClick={(event) => event.preventDefault()}
            >
              <ExternalLink size={10} />
              RPC {meta.rpc}
            </a>
          )}
        </div>
      )}
    </div>
  );
}
