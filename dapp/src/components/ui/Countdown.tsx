import { Clock3, Infinity as InfinityIcon } from "lucide-react";
import { formatCountdown } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { useNow } from "../../lib/hooks";

interface CountdownProps {
  endMs: number;
  label?: string;
  showIcon?: boolean;
  className?: string;
  endedLabel?: string;
}

export function Countdown({
  endMs,
  label,
  showIcon = true,
  className = "",
  endedLabel,
}: CountdownProps) {
  const now = useNow(1_000);
  const { t } = useI18n();
  const resolvedEndedLabel = endedLabel ?? t("Ended", "已结束");
  if (!Number.isFinite(endMs)) {
    return (
      <span
        className={`countdown is-open ${className}`.trim()}
        title={t("No fixed end time", "无固定结束时间")}
      >
        {showIcon && <InfinityIcon size={12} aria-hidden="true" />}
        {label && <span className="countdown__label">{label}</span>}
        <span className="countdown__value">{t("Open-ended", "开放中")}</span>
      </span>
    );
  }
  const remaining = endMs - now;
  const ended = remaining <= 0;
  const urgent = !ended && remaining < 60 * 60 * 1_000;

  return (
    <span
      className={`countdown ${ended ? "is-ended" : ""} ${urgent ? "is-urgent" : ""} ${className}`.trim()}
      title={
        ended
          ? resolvedEndedLabel
          : t(`Remaining ${formatCountdown(remaining)}`, `剩余 ${formatCountdown(remaining)}`)
      }
    >
      {showIcon && <Clock3 size={12} aria-hidden="true" />}
      {label && <span className="countdown__label">{label}</span>}
      <span className="countdown__value tabular">
        {ended ? resolvedEndedLabel : formatCountdown(remaining)}
      </span>
    </span>
  );
}
