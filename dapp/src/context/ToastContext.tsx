import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

export type ToastTone = "info" | "success" | "error" | "warning";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  duration?: number;
}

interface ToastRecord extends ToastInput {
  id: string;
  tone: ToastTone;
}

interface ToastContextValue {
  toast: (input: ToastInput) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let counter = 0;

function nextId(): string {
  counter += 1;
  return `toast-${Date.now()}-${counter}`;
}

const ICONS = {
  info: Info,
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
} satisfies Record<ToastTone, typeof Info>;

function ToastCard({
  record,
  onDismiss,
}: {
  record: ToastRecord;
  onDismiss: (id: string) => void;
}) {
  const [paused, setPaused] = useState(false);
  const remaining = useRef(record.duration ?? 5_500);
  const startedAt = useRef(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (paused) {
      if (timer.current !== null) window.clearTimeout(timer.current);
      remaining.current -= Date.now() - startedAt.current;
      return;
    }
    startedAt.current = Date.now();
    timer.current = window.setTimeout(
      () => onDismiss(record.id),
      Math.max(800, remaining.current),
    );
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [onDismiss, paused, record.id]);

  const Icon = ICONS[record.tone];

  return (
    <div
      className={`toast toast--${record.tone}`}
      role={record.tone === "error" ? "alert" : "status"}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <span className="toast__icon" aria-hidden="true">
        <Icon size={17} strokeWidth={1.8} />
      </span>
      <div className="toast__body">
        <p className="toast__title">{record.title}</p>
        {record.description && <p className="toast__description">{record.description}</p>}
      </div>
      <button
        type="button"
        className="toast__close"
        aria-label="关闭通知"
        onClick={() => onDismiss(record.id)}
      >
        <X size={14} />
      </button>
      <span className="toast__timer" style={{ animationDuration: `${record.duration ?? 5_500}ms` }} />
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback((input: ToastInput) => {
    const id = nextId();
    const record: ToastRecord = {
      ...input,
      id,
      tone: input.tone ?? "info",
    };
    setToasts((current) => [...current.slice(-3), record]);
    return id;
  }, []);

  const value = useMemo(() => ({ toast, dismiss }), [dismiss, toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div className="toast-viewport" aria-label="通知">
          {toasts.map((record) => (
            <ToastCard key={record.id} record={record} onDismiss={dismiss} />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
