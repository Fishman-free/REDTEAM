import { Clock3, Infinity as InfinityIcon } from "lucide-react";
import { formatCountdown } from "../../lib/format";
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
  endedLabel = "已结束",
}: CountdownProps) {
  const now = useNow(1_000);
  if (!Number.isFinite(endMs)) {
    return (
      <span className={`countdown is-open ${className}`.trim()} title="无固定结束时间">
        {showIcon && <InfinityIcon size={12} aria-hidden="true" />}
        {label && <span className="countdown__label">{label}</span>}
        <span className="countdown__value">开放中</span>
      </span>
    );
  }
  const remaining = endMs - now;
  const ended = remaining <= 0;
  const urgent = !ended && remaining < 60 * 60 * 1_000;

  return (
    <span
      className={`countdown ${ended ? "is-ended" : ""} ${urgent ? "is-urgent" : ""} ${className}`.trim()}
      title={ended ? endedLabel : `剩余 ${formatCountdown(remaining)}`}
    >
      {showIcon && <Clock3 size={12} aria-hidden="true" />}
      {label && <span className="countdown__label">{label}</span>}
      <span className="countdown__value tabular">
        {ended ? endedLabel : formatCountdown(remaining)}
      </span>
    </span>
  );
}
