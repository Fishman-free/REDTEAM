import { Loader2 } from "lucide-react";

export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  return (
    <span className="spinner" role={label ? "status" : undefined} aria-label={label}>
      <Loader2 size={size} className="spin" aria-hidden="true" />
      {label && <span>{label}</span>}
    </span>
  );
}
