import type { HTMLAttributes, ReactNode } from "react";

interface PanelProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  eyebrow?: ReactNode;
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  bracket?: boolean;
  tone?: "default" | "raised" | "flat" | "danger";
}

export function Panel({
  eyebrow,
  title,
  description,
  actions,
  bracket = false,
  tone = "default",
  className = "",
  children,
  ...rest
}: PanelProps) {
  const hasHead = Boolean(eyebrow || title || description || actions);
  return (
    <section
      className={`panel panel--${tone} ${bracket ? "panel--bracket" : ""} ${className}`.trim()}
      {...rest}
    >
      {hasHead && (
        <header className="panel__head">
          <div className="panel__head-text">
            {eyebrow && <p className="panel__eyebrow">{eyebrow}</p>}
            {title && <h2 className="panel__title">{title}</h2>}
            {description && <p className="panel__description">{description}</p>}
          </div>
          {actions && <div className="panel__actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}
