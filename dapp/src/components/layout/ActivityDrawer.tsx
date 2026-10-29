import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  CircleDashed,
  RefreshCw,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import { useActivity, type ActivityStatus } from "../../context/ActivityContext";
import { explorerTxUrl, shortHash, timeAgo } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { useScrollLock } from "../../lib/hooks";
import { AddressChip } from "../ui/Address";
import { EmptyState } from "../ui/EmptyState";
import { Button } from "../ui/Button";

const STATUS_META: Record<ActivityStatus, { className: string; icon: ReactNode }> = {
  pending: {
    className: "activity__status--pending",
    icon: <CircleDashed size={15} className="spin-slow" />,
  },
  confirmed: {
    className: "activity__status--confirmed",
    icon: <CheckCircle2 size={15} />,
  },
  reverted: {
    className: "activity__status--failed",
    icon: <XCircle size={15} />,
  },
  failed: {
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
  const { records, pendingCount, clear, refreshTransaction } = useActivity();
  const { t } = useI18n();
  const [checking, setChecking] = useState<string | null>(null);
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

  function statusLabel(status: ActivityStatus): string {
    if (status === "pending") return t("Waiting for confirmation", "等待确认");
    if (status === "confirmed") return t("Confirmed", "已确认");
    if (status === "reverted") return t("Reverted", "已回滚");
    return t("Failed", "失败");
  }

  return createPortal(
    <div className="drawer" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="drawer__panel" role="dialog" aria-modal="true" aria-labelledby="activity-title">
        <header className="drawer__head">
          <div>
            <p className="eyebrow">Transaction log</p>
            <h2 id="activity-title">{t("Transaction activity", "交易活动")}</h2>
            <p className="drawer__sub">
              {pendingCount > 0
                ? t(
                    `${pendingCount} transaction(s) waiting for confirmation`,
                    `${pendingCount} 笔等待链上确认`,
                  )
                : t(
                    "Every transaction status is collected here.",
                    "所有交易状态在此汇总",
                  )}
            </p>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label={t("Close transaction activity", "关闭交易活动")}
          >
            <X size={17} />
          </button>
        </header>

        <div className="drawer__body">
          {records.length === 0 ? (
            <EmptyState
              title={t("No transactions yet", "还没有交易记录")}
              description={t(
                "After you sign, confirmations, reverts and failures appear here.",
                "签名后，交易会在这里显示确认、回滚与失败状态。",
              )}
            />
          ) : (
            <ol className="activity">
              {records.map((record) => {
                const meta = STATUS_META[record.status];
                const label = statusLabel(record.status);
                const url = explorerTxUrl(record.hash);
                const checkable = Boolean(record.hash) && record.status !== "confirmed";
                return (
                  <li className="activity__item" key={record.id}>
                    <span className={`activity__status ${meta.className}`} title={label}>
                      {meta.icon}
                    </span>
                    <div className="activity__main">
                      <div className="activity__top">
                        <strong>{record.label}</strong>
                        <span className="activity__time">{timeAgo(record.createdAt)}</span>
                      </div>
                      <div className="activity__meta">
                        <span className="activity__kind mono">{record.kind}</span>
                        <span>{label}</span>
                        {record.chainId ? <span className="mono">#{record.chainId}</span> : null}
                      </div>
                      {record.hash && (
                        <div className="activity__hash">
                          <span className="mono">{shortHash(record.hash)}</span>
                          <AddressChip value={record.hash} kind="tx" copy link={Boolean(url)} />
                          {checkable && (
                            <button
                              type="button"
                              className="activity__check"
                              disabled={checking === record.id}
                              onClick={() => {
                                setChecking(record.id);
                                void refreshTransaction(record.id).finally(() => setChecking(null));
                              }}
                            >
                              <RefreshCw
                                size={10}
                                className={checking === record.id ? "spin" : ""}
                              />
                              {t("Check again", "重新检查")}
                            </button>
                          )}
                        </div>
                      )}
                      {record.error && <p className="activity__error">{record.error}</p>}
                      {record.status === "failed" && (
                        <Link
                          to="/docs#troubleshooting"
                          className="activity__help"
                          onClick={onClose}
                        >
                          {t("Wallet / transaction troubleshooting", "钱包 / 交易故障排查")}
                        </Link>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>

        <footer className="drawer__foot">
          <span className="muted small">
            {t("Saved in this browser, up to 60 records.", "记录保存在本浏览器，最多 60 条。")}
          </span>
          <Button
            size="sm"
            variant="ghost"
            iconLeft={<Trash2 size={12} />}
            disabled={records.length === 0}
            onClick={clear}
          >
            {t("Clear", "清空")}
          </Button>
        </footer>
      </aside>
    </div>,
    document.body,
  );
}
