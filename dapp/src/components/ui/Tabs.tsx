import type { KeyboardEvent, ReactNode } from "react";

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
  count?: number;
  icon?: ReactNode;
}

interface TabsProps<T extends string> {
  items: Array<TabItem<T>>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
  ariaLabel?: string;
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className = "",
  ariaLabel,
}: TabsProps<T>) {
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const index = items.findIndex((item) => item.id === value);
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const next = items[(index + direction + items.length) % items.length];
    if (next) {
      onChange(next.id);
      const container = event.currentTarget;
      window.setTimeout(() => {
        container.querySelector<HTMLElement>(`[data-tab="${next.id}"]`)?.focus();
      }, 0);
    }
  }

  return (
    <div
      className={`tabs ${className}`.trim()}
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
    >
      {items.map((item) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            data-tab={item.id}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className={`tab ${selected ? "is-active" : ""}`.trim()}
            onClick={() => onChange(item.id)}
          >
            {item.icon && <span className="tab__icon">{item.icon}</span>}
            <span>{item.label}</span>
            {item.count !== undefined && <span className="tab__count">{item.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
