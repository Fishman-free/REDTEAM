import { useState } from "react";
import { ArrowUpRight, Wallet } from "lucide-react";
import { useConnect } from "wagmi";
import { useI18n } from "../../lib/i18n";
import { Dialog } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { Alert } from "../ui/Alert";
import { errorText } from "../../lib/format";

const WALLETS = [
  { name: "MetaMask", url: "https://metamask.io/download/" },
  { name: "Rabby", url: "https://rabby.io/" },
  { name: "Coinbase Wallet", url: "https://www.coinbase.com/wallet" },
];

export function ConnectDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { connectors, connectAsync, isPending } = useConnect();
  const { t } = useI18n();
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);

  async function connect(connector: (typeof connectors)[number]) {
    setError("");
    setPendingId(connector.uid);
    try {
      await connectAsync({ connector });
      onClose();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPendingId(null);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      eyebrow={t("Access control / wallet", "访问控制 / 钱包")}
      title={t("Connect your operator wallet", "连接你的操作钱包")}
      description={t(
        "Use a browser wallet to sign transactions. The platform never sees your private key and never signs on your behalf.",
        "使用浏览器钱包签名交易。平台不会接触你的私钥，也不会代你签名。",
      )}
      size="sm"
    >
      <div className="connect-list">
        {connectors.length > 0 ? (
          connectors.map((connector) => (
            <button
              key={connector.uid}
              type="button"
              className="connect-option"
              onClick={() => void connect(connector)}
              disabled={isPending}
            >
              <span className="connect-option__icon">
                <Wallet size={19} />
              </span>
              <span className="connect-option__text">
                <strong>{connector.name}</strong>
                <span>{t("Browser-injected wallet", "浏览器注入式钱包")}</span>
              </span>
              <span className="connect-option__action">
                {pendingId === connector.uid
                  ? t("Connecting…", "连接中…")
                  : t("Connect", "连接")}
              </span>
            </button>
          ))
        ) : (
          <div className="connect-empty">
            <p>{t("No browser wallet extension was detected.", "没有检测到浏览器钱包扩展。")}</p>
            <p className="muted small">
              {t(
                "Install one of the wallets below, refresh the page and try again.",
                "安装下面任意一个钱包，刷新页面后重试。",
              )}
            </p>
            <div className="connect-links">
              {WALLETS.map((wallet) => (
                <a
                  key={wallet.name}
                  href={wallet.url}
                  target="_blank"
                  rel="noreferrer"
                  className="connect-link"
                >
                  {wallet.name}
                  <ArrowUpRight size={12} />
                </a>
              ))}
            </div>
          </div>
        )}
      </div>

      {error && (
        <Alert tone="error" title={t("Connection failed", "连接失败")}>
          {error}
        </Alert>
      )}

      <p className="dialog__note">
        {t(
          "On mobile, open this page inside your wallet app's built-in browser. Testnet assets have no value.",
          "移动端请在钱包 App 的内置浏览器中打开本页面。测试网资产无价值。",
        )}
      </p>
      <div className="dialog__inline-actions">
        <Button variant="ghost" onClick={onClose}>
          {t("Maybe later", "稍后再说")}
        </Button>
      </div>
    </Dialog>
  );
}
