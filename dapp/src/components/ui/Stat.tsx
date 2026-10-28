import type { ReactNode } from "react";
import type { Tone } from "../../lib/format";
import { useCountUp } from "../../lib/hooks";

interface StatProps {
  label: ReactNode;
  value?: ReactNode;
  numericValue?: number;
  format?: (value: number) => string;
  unit?: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  tone?: Tone;
  className?: string;
  size?: "sm" | "md" | "lg";
}

export function Stat({
  label,
  value,
  numericValue,
  format,
  unit,
  hint,
  icon,
  tone = "neutral",
  className = "",
  size = "md",
}: StatProps) {
  const animated = useCountUp(numericValue ?? 0);
  const rendered =
    numericValue !== undefined ? (format ? format(animated) : animated.toFixed(0)) : value;

  return (
    <div className={`stat stat--${size} stat--${tone} ${className}`.trim()}>
      <div className="stat__top">
        <span className="stat__label">{label}</span>
        {icon && (
          <span className="stat__icon" aria-hidden="true">
            {icon}
          </span>
        )}
      </div>
      <div className="stat__value-row">
        <span className="stat__value tabular">{rendered ?? "—"}</span>
        {unit && <span className="stat__unit">{unit}</span>}
      </div>
      {hint && <span className="stat__hint">{hint}</span>}
    </div>
  );
}
