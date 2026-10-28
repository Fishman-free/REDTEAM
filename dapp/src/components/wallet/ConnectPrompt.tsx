import type { ReactNode } from "react";
import { Wallet } from "lucide-react";
import { useAccount, useChainId } from "wagmi";
import { ConnectButton } from "./ConnectButton";
import { isSupportedChain } from "../../lib/chain";
import { Button } from "../ui/Button";
import { useSwitchChain } from "wagmi";
import { CHAIN_ID, ensureChain } from "../../lib/chain";
import { useState } from "react";
import { useToast } from "../../context/ToastContext";
import { errorText } from "../../lib/format";

interface ConnectPromptProps {
  title?: ReactNode;
  description?: ReactNode;
  compact?: boolean;
}

export function ConnectPrompt({
  title = "连接钱包后开始",
  description = "钱包只用于签名交易；平台不会托管你的私钥。",
  compact = false,
}: ConnectPromptProps) {
  const { isConnected } = useAccount();
  const chainId = useChainId();
  const { switchChainAsync } = useSwitchChain();
  const [pending, setPending] = useState(false);
  const { toast } = useToast();

  if (!isConnected) {
    return (
      <div className={`connect-prompt ${compact ? "connect-prompt--compact" : ""}`.trim()}>
        <span className="connect-prompt__icon">
          <Wallet size={20} />
        </span>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <ConnectButton label="连接钱包" size={compact ? "sm" : "md"} />
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
          toast({ title: "切换失败", description: errorText(reason), tone: "error" });
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
          <h3>网络不正确</h3>
          <p>请切换到 RTM Testnet（{CHAIN_ID}）后再继续。</p>
        </div>
        <Button size={compact ? "sm" : "md"} variant="secondary" loading={pending} onClick={() => void change()}>
          切换网络
        </Button>
      </div>
    );
  }

  return null;
}
