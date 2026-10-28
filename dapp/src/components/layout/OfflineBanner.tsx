import { RefreshCw, ServerOff } from "lucide-react";
import { usePlatform } from "../../lib/platform";
import { Button } from "../ui/Button";

export function OfflineBanner() {
  const { online, metaLoading, refetchMeta, refetchStatus } = usePlatform();
  if (online || metaLoading) return null;

  return (
    <div className="offline-banner" role="status">
      <span className="offline-banner__icon">
        <ServerOff size={16} />
      </span>
      <div className="offline-banner__text">
        <strong>平台 API 暂未连接</strong>
        <span>钱包与链上只读功能仍可用；列表、聊天与索引数据需要 API。</span>
      </div>
      <Button
        size="sm"
        variant="ghost"
        iconLeft={<RefreshCw size={12} />}
        onClick={() => {
          refetchMeta();
          refetchStatus();
        }}
      >
        重试
      </Button>
    </div>
  );
}
