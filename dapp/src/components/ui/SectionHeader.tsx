import type { ReactNode } from "react";

interface SectionHeaderProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  level?: 1 | 2;
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
  className = "",
  level = 1,
}: SectionHeaderProps) {
  const Heading = level === 1 ? "h1" : "h2";
  return (
    <header className={`section-header ${className}`.trim()}>
      <div className="section-header__text">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <Heading className="section-header__title">{title}</Heading>
        {description && <p className="section-header__description">{description}</p>}
      </div>
      {actions && <div className="section-header__actions">{actions}</div>}
    </header>
  );
}
