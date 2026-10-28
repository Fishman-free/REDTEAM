import { useState } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";
import { useAccount, useChainId, useSwitchChain } from "wagmi";
import { CHAIN_ID, ensureChain, isSupportedChain } from "../../lib/chain";
import { errorText } from "../../lib/format";
import { useToast } from "../../context/ToastContext";
import { Button } from "../ui/Button";

export function NetworkBanner() {
  const { isConnected } = useAccount();
  const chainId = useChainId();
  const { switchChainAsync } = useSwitchChain();
  const [pending, setPending] = useState(false);
  const { toast } = useToast();

  if (!isConnected || isSupportedChain(chainId)) return null;

  async function changeNetwork() {
    setPending(true);
    try {
      await switchChainAsync({ chainId: CHAIN_ID });
      toast({ title: "网络已切换", tone: "success" });
    } catch (reason) {
      try {
        await ensureChain();
        toast({ title: "网络已添加/切换", tone: "success" });
      } catch (fallback) {
        toast({
          title: "无法切换网络",
          description: errorText(fallback || reason),
          tone: "error",
        });
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="network-banner" role="alert">
      <span className="network-banner__icon">
        <TriangleAlert size={17} />
      </span>
      <div className="network-banner__text">
        <strong>钱包当前在链 #{chainId}</strong>
        <span>竞技场运行在 RTM Testnet（{CHAIN_ID} / 0xbed2）。切换后才能签名交易。</span>
      </div>
      <Button
        size="sm"
        variant="secondary"
        loading={pending}
        iconLeft={<RefreshCw size={13} />}
        onClick={() => void changeNetwork()}
      >
        切换网络
      </Button>
    </div>
  );
}
