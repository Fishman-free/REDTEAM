import { RefreshCw, ServerOff } from "lucide-react";
import { usePlatform } from "../../lib/platform";
import { useI18n } from "../../lib/i18n";
import { Button } from "../ui/Button";

export function OfflineBanner() {
  const { online, metaLoading, refetchMeta, refetchStatus } = usePlatform();
  const { t } = useI18n();
  if (online || metaLoading) return null;

  return (
    <div className="offline-banner" role="status">
      <span className="offline-banner__icon">
        <ServerOff size={16} />
      </span>
      <div className="offline-banner__text">
        <strong>{t("Platform API is offline", "平台 API 暂未连接")}</strong>
        <span>
          {t(
            "Wallet and on-chain reads still work; lists, chat and indexing require the API.",
            "钱包与链上只读功能仍可用；列表、聊天与索引数据需要 API。",
          )}
        </span>
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
        {t("Retry", "重试")}
      </Button>
    </div>
  );
}
