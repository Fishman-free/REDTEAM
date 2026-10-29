import { Link } from "react-router-dom";
import { ArrowLeft, Crosshair } from "lucide-react";
import { EmptyState } from "../components/ui/EmptyState";
import { useI18n } from "../lib/i18n";

export default function NotFound() {
  const { t } = useI18n();
  return (
    <div className="not-found">
      <EmptyState
        icon={<Crosshair size={26} />}
        title={t("404 / This sector does not exist", "404 / 没有这个作战区域")}
        description={t(
          "The link may be stale, or this page has not been deployed. Return to the overview and choose another task.",
          "链接可能已经失效，或者 page 还未被部署。回到总览重新选择任务。",
        )}
        action={
          <Link className="btn btn--primary btn--sm" to="/">
            <ArrowLeft size={13} />
            {t("Back to overview", "返回总览")}
          </Link>
        }
      />
    </div>
  );
}
