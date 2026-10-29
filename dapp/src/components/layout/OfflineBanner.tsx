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
            "Contract addresses come only from the API, so on-chain reads and writes are paused until it reconnects; the wallet itself is unaffected.",
            "合约地址只从 API 获取，API 恢复前链上读写已暂停，避免发到错误合约；钱包本身不受影响。",
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
