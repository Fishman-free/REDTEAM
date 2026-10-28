import type { ReactNode } from "react";
import type { Tone } from "../../lib/format";

export type BadgeTone = Tone | "mining" | "outline";

interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  dot?: boolean;
  className?: string;
  title?: string;
}

export function Badge({ children, tone = "neutral", dot = false, className = "", title }: BadgeProps) {
  return (
    <span className={`badge badge--${tone} ${className}`.trim()} title={title}>
      {dot && <span className="badge__dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
