import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  CheckCircle2,
  CircleDashed,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import { useActivity, type ActivityStatus } from "../../context/ActivityContext";
import { explorerTxUrl, shortHash, timeAgo } from "../../lib/format";
import { useScrollLock } from "../../lib/hooks";
import { AddressChip } from "../ui/Address";
import { EmptyState } from "../ui/EmptyState";
import { Button } from "../ui/Button";

const STATUS_META: Record<
  ActivityStatus,
  { label: string; className: string; icon: ReactNode }
> = {
  pending: {
    label: "等待确认",
    className: "activity__status--pending",
    icon: <CircleDashed size={15} className="spin-slow" />,
  },
  confirmed: {
    label: "已确认",
    className: "activity__status--confirmed",
    icon: <CheckCircle2 size={15} />,
  },
  reverted: {
    label: "已回滚",
    className: "activity__status--failed",
    icon: <XCircle size={15} />,
  },
  failed: {
    label: "失败",
    className: "activity__status--failed",
    icon: <XCircle size={15} />,
  },
};

export function ActivityDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { records, pendingCount, clear } = useActivity();
  useScrollLock(open);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, open]);

  if (!open) return null;

  return createPortal(
    <div className="drawer" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="drawer__panel" role="dialog" aria-modal="true" aria-labelledby="activity-title">
        <header className="drawer__head">
          <div>
            <p className="eyebrow">Transaction log</p>
            <h2 id="activity-title">交易活动</h2>
            <p className="drawer__sub">
              {pendingCount > 0 ? `${pendingCount} 笔等待链上确认` : "所有交易状态在此汇总"}
            </p>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭交易活动">
            <X size={17} />
          </button>
        </header>

        <div className="drawer__body">
          {records.length === 0 ? (
            <EmptyState
              title="还没有交易记录"
              description="签名后，交易会在这里显示确认、回滚与失败状态。"
            />
          ) : (
            <ol className="activity">
              {records.map((record) => {
                const meta = STATUS_META[record.status];
                const url = explorerTxUrl(record.hash);
                return (
                  <li className="activity__item" key={record.id}>
                    <span className={`activity__status ${meta.className}`} title={meta.label}>
                      {meta.icon}
                    </span>
                    <div className="activity__main">
                      <div className="activity__top">
                        <strong>{record.label}</strong>
                        <span className="activity__time">{timeAgo(record.createdAt)}</span>
                      </div>
                      <div className="activity__meta">
                        <span className="activity__kind mono">{record.kind}</span>
                        <span>{meta.label}</span>
                        {record.chainId ? <span className="mono">#{record.chainId}</span> : null}
                      </div>
                      {record.hash && (
                        <div className="activity__hash">
                          <span className="mono">{shortHash(record.hash)}</span>
                          <AddressChip value={record.hash} kind="tx" copy link={Boolean(url)} />
                        </div>
                      )}
                      {record.error && <p className="activity__error">{record.error}</p>}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>

        <footer className="drawer__foot">
          <span className="muted small">记录保存在本浏览器，最多 60 条。</span>
          <Button
            size="sm"
            variant="ghost"
            iconLeft={<Trash2 size={12} />}
            disabled={records.length === 0}
            onClick={clear}
          >
            清空
          </Button>
        </footer>
      </aside>
    </div>,
    document.body,
  );
}
