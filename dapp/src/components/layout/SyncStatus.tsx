import { Activity, WifiOff } from "lucide-react";
import { usePlatform } from "../../lib/platform";
import { useI18n } from "../../lib/i18n";

export function SyncStatus() {
  const { online, status, meta } = usePlatform();
  const { t, lang } = useI18n();
  const lastBlock = status?.indexer?.lastBlock;
  const lag = status?.indexer?.lag;

  if (!online) {
    return (
      <span className="sync-status sync-status--offline" title={t("Platform API is offline", "平台 API 未连接")}>
        <WifiOff size={12} />
        <span>{t("API offline", "API 离线")}</span>
      </span>
    );
  }

  return (
    <span
      className="sync-status"
      title={
        lastBlock !== null && lastBlock !== undefined
          ? t(
              `Chain synced to block ${lastBlock}${lag ? `, ${lag} blocks behind` : ""}`,
              `链已同步至区块 ${lastBlock}${lag ? `，落后 ${lag} 块` : ""}`,
            )
          : t(`Connected to ${meta.network}`, `已连接 ${meta.network}`)
      }
    >
      <span className="sync-status__dot" aria-hidden="true" />
      <Activity size={11} aria-hidden="true" />
      <span className="mono">
        {lastBlock !== null && lastBlock !== undefined
          ? `#${lastBlock.toLocaleString(lang === "en" ? "en-US" : "zh-CN")}`
          : t("Connected", "已连接")}
      </span>
      {typeof lag === "number" && lag > 8 && (
        <span className="sync-status__lag">+{lag}</span>
      )}
    </span>
  );
}
