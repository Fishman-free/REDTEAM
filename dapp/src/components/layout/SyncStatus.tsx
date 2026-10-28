import { Activity, WifiOff } from "lucide-react";
import { usePlatform } from "../../lib/platform";

export function SyncStatus() {
  const { online, status, meta } = usePlatform();
  const lastBlock = status?.indexer?.lastBlock;
  const lag = status?.indexer?.lag;

  if (!online) {
    return (
      <span className="sync-status sync-status--offline" title="平台 API 未连接">
        <WifiOff size={12} />
        <span>API 离线</span>
      </span>
    );
  }

  return (
    <span
      className="sync-status"
      title={
        lastBlock !== null && lastBlock !== undefined
          ? `链已同步至区块 ${lastBlock}${lag ? `，落后 ${lag} 块` : ""}`
          : `已连接 ${meta.network}`
      }
    >
      <span className="sync-status__dot" aria-hidden="true" />
      <Activity size={11} aria-hidden="true" />
      <span className="mono">
        {lastBlock !== null && lastBlock !== undefined
          ? `#${lastBlock.toLocaleString("zh-CN")}`
          : "已连接"}
      </span>
      {typeof lag === "number" && lag > 8 && (
        <span className="sync-status__lag">+{lag}</span>
      )}
    </span>
  );
}
