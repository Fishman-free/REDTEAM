import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useI18n } from "../../lib/i18n";
import { useScrollLock } from "../../lib/hooks";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  closeOnOverlay?: boolean;
  className?: string;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Dialog({
  open,
  onClose,
  title,
  description,
  eyebrow,
  children,
  footer,
  size = "md",
  closeOnOverlay = true,
  className = "",
}: DialogProps) {
  const { t } = useI18n();
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  useScrollLock(open);

  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const target = panel?.querySelector<HTMLElement>("[data-autofocus]") ?? panel;
    window.setTimeout(() => target?.focus(), 30);

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => element.offsetParent !== null || element === document.activeElement,
      );
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus.current?.focus?.();
    };
  }, [onClose, open]);

  if (!open) return null;

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") onClose();
  }

  return createPortal(
    <div
      className="dialog"
      onMouseDown={(event) => {
        if (closeOnOverlay && event.target === event.currentTarget) onClose();
      }}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={panelRef}
        className={`dialog__panel dialog__panel--${size} ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
      >
        <div className="dialog__scanline" aria-hidden="true" />
        <header className="dialog__head">
          <div>
            {eyebrow && <p className="dialog__eyebrow">{eyebrow}</p>}
            <h2 className="dialog__title" id={titleId}>
              {title}
            </h2>
            {description && (
              <p className="dialog__description" id={descriptionId}>
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label={t("Close dialog", "关闭对话框")}
          >
            <X size={17} />
          </button>
        </header>
        {children && <div className="dialog__body">{children}</div>}
        {footer && <footer className="dialog__footer">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
