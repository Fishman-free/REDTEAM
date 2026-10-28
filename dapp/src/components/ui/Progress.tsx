import type { ReactNode } from "react";
import type { Tone } from "../../lib/format";

interface ProgressProps {
  value: number;
  tone?: Tone;
  label?: ReactNode;
  right?: ReactNode;
  className?: string;
  size?: "sm" | "md";
}

export function Progress({
  value,
  tone = "accent",
  label,
  right,
  className = "",
  size = "md",
}: ProgressProps) {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  return (
    <div className={`progress progress--${size} ${className}`.trim()}>
      {(label || right) && (
        <div className="progress__meta">
          {label && <span>{label}</span>}
          {right && <span className="tabular">{right}</span>}
        </div>
      )}
      <div
        className="progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clamped * 100)}
      >
        <span
          className={`progress__bar progress__bar--${tone}`}
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
    </div>
  );
}
