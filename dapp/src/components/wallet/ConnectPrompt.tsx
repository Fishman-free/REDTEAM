import type { ReactNode } from "react";
import { Wallet } from "lucide-react";
import { useAccount, useSwitchChain } from "wagmi";
import { ConnectButton } from "./ConnectButton";
import { CHAIN_ID, ensureChain, isSupportedChain } from "../../lib/chain";
import { useWalletChainId } from "../../lib/useWalletChainId";
import { useI18n } from "../../lib/i18n";
import { Button } from "../ui/Button";
import { useState } from "react";
import { useToast } from "../../context/ToastContext";
import { errorText } from "../../lib/format";

interface ConnectPromptProps {
  title?: ReactNode;
  description?: ReactNode;
  compact?: boolean;
}

export function ConnectPrompt({ title, description, compact = false }: ConnectPromptProps) {
  const { isConnected } = useAccount();
  const chainId = useWalletChainId();
  const { switchChainAsync } = useSwitchChain();
  const [pending, setPending] = useState(false);
  const { toast } = useToast();
  const { t } = useI18n();
  const heading = title ?? t("Connect a wallet to start", "连接钱包后开始");
  const body =
    description ??
    t(
      "Your wallet only signs transactions; the platform never holds your private key.",
      "钱包只用于签名交易；平台不会托管你的私钥。",
    );

  if (!isConnected) {
    return (
      <div className={`connect-prompt ${compact ? "connect-prompt--compact" : ""}`.trim()}>
        <span className="connect-prompt__icon">
          <Wallet size={20} />
        </span>
        <div>
          <h3>{heading}</h3>
          <p>{body}</p>
        </div>
        <ConnectButton label={t("Connect wallet", "连接钱包")} size={compact ? "sm" : "md"} />
      </div>
    );
  }

  if (!isSupportedChain(chainId)) {
    async function change() {
      setPending(true);
      try {
        await switchChainAsync({ chainId: CHAIN_ID });
      } catch (reason) {
        try {
          await ensureChain();
        } catch {
          toast({
            title: t("Switch failed", "切换失败"),
            description: errorText(reason),
            tone: "error",
          });
        }
      } finally {
        setPending(false);
      }
    }
    return (
      <div className={`connect-prompt connect-prompt--warning ${compact ? "connect-prompt--compact" : ""}`.trim()}>
        <span className="connect-prompt__icon">
          <Wallet size={20} />
        </span>
        <div>
          <h3>{t("Wrong network", "网络不正确")}</h3>
          <p>
            {t(
              `Switch to RTM Testnet (${CHAIN_ID}) before continuing.`,
              `请切换到 RTM Testnet（${CHAIN_ID}）后再继续。`,
            )}
          </p>
        </div>
        <Button size={compact ? "sm" : "md"} variant="secondary" loading={pending} onClick={() => void change()}>
          {t("Switch network", "切换网络")}
        </Button>
      </div>
    );
  }

  return null;
}
