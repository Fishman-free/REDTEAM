import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";

export type AlertTone = "info" | "success" | "error" | "warning";

const ICONS = {
  info: Info,
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
} satisfies Record<AlertTone, typeof Info>;

interface AlertProps {
  tone?: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function Alert({ tone = "info", title, children, action, className = "" }: AlertProps) {
  const Icon = ICONS[tone];
  return (
    <div
      className={`alert alert--${tone} ${className}`.trim()}
      role={tone === "error" || tone === "warning" ? "alert" : "status"}
    >
      <Icon size={17} className="alert__icon" aria-hidden="true" />
      <div className="alert__body">
        {title && <p className="alert__title">{title}</p>}
        {children && <div className="alert__content">{children}</div>}
      </div>
      {action && <div className="alert__action">{action}</div>}
    </div>
  );
}
