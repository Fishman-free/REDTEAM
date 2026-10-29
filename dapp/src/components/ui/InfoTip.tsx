import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { CircleHelp } from "lucide-react";
import { useI18n } from "../../lib/i18n";

interface InfoTipProps {
  /** Short accessible label, e.g. "ticket validity". */
  label: string;
  children: ReactNode;
  side?: "top" | "bottom";
}

interface Position {
  top: number;
  left: number;
  below: boolean;
  arrowLeft: number;
}

/**
 * A click/keyboard accessible explanation for domain jargon. The panel is
 * portalled to the body and clamped to the viewport so it is never clipped by
 * a stat card or opens off-screen.
 */
export function InfoTip({ label, children, side = "top" }: InfoTipProps) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<Position | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLSpanElement>(null);
  const id = useId();
  const { t } = useI18n();

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    function place() {
      const trigger = triggerRef.current?.getBoundingClientRect();
      const panel = panelRef.current?.getBoundingClientRect();
      if (!trigger || !panel) return;
      const gap = 8;
      const margin = 8;
      const center = trigger.left + trigger.width / 2;
      const left = Math.min(
        Math.max(margin, center - panel.width / 2),
        window.innerWidth - panel.width - margin,
      );
      const preferBelow = side === "bottom";
      const topAbove = trigger.top - panel.height - gap;
      const topBelow = trigger.bottom + gap;
      const below =
        preferBelow
          ? topBelow + panel.height <= window.innerHeight - margin || topAbove < margin
          : topAbove < margin;
      const top = below ? topBelow : topAbove;
      setPosition({
        top: Math.min(Math.max(margin, top), window.innerHeight - panel.height - margin),
        left,
        below,
        arrowLeft: Math.min(Math.max(12, center - left), panel.width - 12),
      });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, side]);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: MouseEvent) {
      const target = event.target as Node;
      if (
        !triggerRef.current?.contains(target) &&
        !panelRef.current?.contains(target)
      ) {
        setOpen(false);
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <span className="info-tip">
      <button
        ref={triggerRef}
        type="button"
        className="info-tip__trigger"
        aria-label={t(`Explain: ${label}`, `解释：${label}`)}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((value) => !value);
        }}
      >
        <CircleHelp size={12} aria-hidden="true" />
      </button>
      {open &&
        createPortal(
          <span
            ref={panelRef}
            className={`info-tip__popover ${position?.below ? "is-below" : ""}`.trim()}
            id={id}
            role="tooltip"
            style={
              {
                top: position?.top ?? 0,
                left: position?.left ?? 0,
                visibility: position ? "visible" : "hidden",
                "--info-arrow": `${position?.arrowLeft ?? 24}px`,
              } as CSSProperties
            }
          >
            {children}
          </span>,
          document.body,
        )}
    </span>
  );
}
