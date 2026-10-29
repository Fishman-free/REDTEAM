import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Database,
  KeyRound,
  Lock,
  Pickaxe,
  RefreshCw,
  Server,
  Shield,
  Terminal,
  TriangleAlert,
} from "lucide-react";
import { api, type MiningContestResult, type PublishResult } from "../lib/api";
import { errorText, formatDateTime, stateLabel, timeAgo } from "../lib/format";
import { locale, useI18n } from "../lib/i18n";
import { usePlatform, useContestsQuery } from "../lib/platform";
import { useToast } from "../context/ToastContext";
import { AddressChip } from "../components/ui/Address";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { SelectField, TextField } from "../components/ui/Field";
import { Panel } from "../components/ui/Panel";
import { SectionHeader } from "../components/ui/SectionHeader";
import { Stat } from "../components/ui/Stat";

const ADMIN_KEY_STORAGE = "rtm.ops.adminKey";

export default function Ops() {
  const [adminKey, setAdminKey] = useState(
    () => sessionStorage.getItem(ADMIN_KEY_STORAGE) ?? "",
  );
  const [draftKey, setDraftKey] = useState("");
  const [unlocked, setUnlocked] = useState(Boolean(adminKey));
  const [version, setVersion] = useState("e2e-mining");
  const [selectedContest, setSelectedContest] = useState("");
  const [miningResult, setMiningResult] = useState<MiningContestResult | null>(null);
  const [publishResult, setPublishResult] = useState<PublishResult | null>(null);
  const [busy, setBusy] = useState<"mining" | "publish" | null>(null);
  const [error, setError] = useState("");
  const { meta, status, online, refetchStatus, refetchMeta } = usePlatform();
  const contestsQuery = useContestsQuery();
  const { toast } = useToast();
  const { t } = useI18n();

  const endedContests = useMemo(
    () =>
      (contestsQuery.data ?? [])
        .filter((contest) => !contest.is_mining && contest.state !== "live")
        .sort((a, b) => (b.ended_ts ?? b.start_ts) - (a.ended_ts ?? a.start_ts)),
    [contestsQuery.data],
  );

  function unlock() {
    const value = draftKey.trim();
    if (!value) {
      setError(t("Enter the operator key.", "请输入运营密钥。"));
      return;
    }
    sessionStorage.setItem(ADMIN_KEY_STORAGE, value);
    setAdminKey(value);
    setUnlocked(true);
    setDraftKey("");
    setError("");
  }

  function lock() {
    sessionStorage.removeItem(ADMIN_KEY_STORAGE);
    setAdminKey("");
    setUnlocked(false);
    setError("");
  }

  async function createMining() {
    setError("");
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(version.trim())) {
      setError(
        t(
          "Version names may only contain lowercase letters, digits, underscores and hyphens, and must start with a letter or digit.",
          "版本名只能包含小写字母、数字、下划线和短横线，且以字母或数字开头。",
        ),
      );
      return;
    }
    setBusy("mining");
    try {
      const result = await api.createMiningContest(version.trim(), adminKey);
      setMiningResult(result);
      toast({
        title: t("Mining contest created", "挖矿赛已创建"),
        description: t(
          `contest ${result.contest_id.slice(0, 12)}…`,
          `比赛 ${result.contest_id.slice(0, 12)}…`,
        ),
        tone: "success",
      });
      await contestsQuery.refetch();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(null);
    }
  }

  async function publish() {
    setError("");
    if (!selectedContest) {
      setError(t("Select a completed standard contest.", "请选择一场已结束的普通赛。"));
      return;
    }
    setBusy("publish");
    try {
      const result = await api.publishDataSet(selectedContest, adminKey);
      setPublishResult(result);
      toast({
        title: t("Dataset published", "数据集已发布"),
        description: `root ${result.root.slice(0, 12)}…`,
        tone: "success",
      });
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(null);
    }
  }

  if (!unlocked) {
    return (
      <div className="ops-gate">
        <div className="ops-gate__panel">
          <div className="ops-gate__icon">
            <Lock size={22} />
          </div>
          <p className="eyebrow">{t("Restricted access", "运营入口")}</p>
          <h1>{t("Operations console", "运营控制台")}</h1>
          <p className="muted">
            {t(
              "Create mining contests and publish datasets here. These actions are hidden from the public player UI; in production, a same-origin proxy validates the admin key.",
              "这里可以创建挖矿赛与发布数据集。公开玩家界面不展示这些操作；生产环境由同源代理校验管理密钥。",
            )}
          </p>
          <TextField
            label={t("Admin key X-Admin-Key", "管理密钥 X-Admin-Key")}
            type="password"
            value={draftKey}
            onChange={(event) => setDraftKey(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") unlock();
            }}
            placeholder={t(
              "Set by the PLATFORM_ADMIN_KEY deployment environment variable",
              "由部署环境变量 PLATFORM_ADMIN_KEY 设置",
            )}
            autoComplete="off"
            autoFocus
          />
          {error && <Alert tone="error">{error}</Alert>}
          <Button block iconLeft={<KeyRound size={14} />} onClick={unlock}>
            {t("Enter console", "进入控制台")}
          </Button>
          <p className="ops-gate__note mono">
            {t(
              "KEY IS STORED IN SESSION STORAGE ONLY · NEVER BUILT INTO THE BUNDLE",
              "密钥仅存于 SESSION STORAGE · 绝不打包进前端产物",
            )}
          </p>
        </div>
      </div>
    );
  }

  const indexer = status?.indexer;

  return (
    <div className="ops-page">
      <SectionHeader
        eyebrow={t("Operations", "运营")}
        title={
          <>
            {t("Operations ", "运营")}
            <em>{t("console", "控制台")}</em>
          </>
        }
        description={t(
          "Platform-level actions and sync status. Every request carries X-Admin-Key; in production a proxy must validate it before forwarding to the platform API.",
          "平台级操作与同步状态。所有请求都带 X-Admin-Key；生产环境必须由代理校验后再转发到平台 API。",
        )}
        actions={
          <div className="section-actions">
            <Badge tone="warning">
              <Shield size={11} /> {t("OPERATOR ONLY", "仅运营")}
            </Badge>
            <Button size="sm" variant="ghost" iconLeft={<Lock size={12} />} onClick={lock}>
              {t("Lock", "锁定")}
            </Button>
          </div>
        }
      />

      {error && <Alert tone="error">{error}</Alert>}
      {!online && (
        <Alert tone="warning" title={t("Platform API is offline", "平台 API 未连接")}>
          {t(
            "Status and actions may be unavailable. Check the API process and proxy configuration, then refresh.",
            "状态与操作可能不可用。检查 API 进程与代理配置后刷新。",
          )}
        </Alert>
      )}

      <div className="stat-strip">
        <Stat
          label="API"
          value={online ? t("ONLINE", "在线") : t("OFFLINE", "离线")}
          tone={online ? "live" : "danger"}
          icon={<Server size={14} />}
        />
        <Stat
          label={t("Indexed block", "索引区块")}
          value={
            indexer?.lastBlock !== null && indexer?.lastBlock !== undefined
              ? `#${indexer.lastBlock.toLocaleString(locale())}`
              : "—"
          }
          icon={<Activity size={14} />}
        />
        <Stat
          label={t("Sync lag", "同步延迟")}
          value={
            typeof indexer?.lag === "number"
              ? t(`${indexer.lag} blocks`, `${indexer.lag} 块`)
              : "—"
          }
          tone={typeof indexer?.lag === "number" && indexer.lag > 10 ? "warning" : "neutral"}
          icon={<RefreshCw size={14} />}
        />
        <Stat label={t("Chain ID", "链 ID")} value={String(meta.chainId)} icon={<Terminal size={14} />} />
      </div>

      <div className="ops-grid">
        <Panel
          eyebrow={t("Indexer", "索引器")}
          title={t("On-chain event indexer", "链上事件索引器")}
          bracket
          actions={
            <Button
              size="sm"
              variant="ghost"
              iconLeft={<RefreshCw size={12} />}
              loading={status === undefined}
              onClick={() => {
                refetchStatus();
                refetchMeta();
              }}
            >
              {t("Refresh", "刷新")}
            </Button>
          }
        >
          <dl className="ops-kv">
            <div>
              <dt>{t("network", "网络")}</dt>
              <dd className="mono">{meta.network}</dd>
            </div>
            <div>
              <dt>{t("chain", "链")}</dt>
              <dd className="mono">{meta.chainId}</dd>
            </div>
            <div>
              <dt>RPC</dt>
              <dd className="mono">{meta.rpc}</dd>
            </div>
            <div>
              <dt>{t("last block", "最后索引块")}</dt>
              <dd className="mono">
                {indexer?.lastBlock !== null && indexer?.lastBlock !== undefined
                  ? indexer.lastBlock.toLocaleString(locale())
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>{t("latest block", "链上最新块")}</dt>
              <dd className="mono">
                {indexer?.latestBlock !== null && indexer?.latestBlock !== undefined
                  ? indexer.latestBlock.toLocaleString(locale())
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>{t("updated", "更新时间")}</dt>
              <dd>{indexer?.updatedAt ? timeAgo(indexer.updatedAt) : "—"}</dd>
            </div>
            <div>
              <dt>{t("events", "事件数")}</dt>
              <dd className="mono">{indexer?.events ?? "—"}</dd>
            </div>
            <div>
              <dt>{t("running", "运行中")}</dt>
              <dd>
                {indexer?.running === undefined
                  ? "—"
                  : indexer.running
                    ? t("yes", "是")
                    : t("no", "否")}
              </dd>
            </div>
          </dl>
          {indexer?.lastError && (
            <Alert tone="error" title={t("Indexer error", "索引器错误")}>
              {indexer.lastError}
            </Alert>
          )}
        </Panel>

        <Panel
          eyebrow={t("Contracts", "合约")}
          title={t("Current addresses", "当前地址")}
          bracket
        >
          <div className="contract-list">
            {Object.entries(meta.addresses).map(([name, address]) => (
              <div key={name}>
                <span className="mono">{name}</span>
                <AddressChip value={address} />
              </div>
            ))}
          </div>
          <p className="position__hint">
            {t("Addresses come from ", "地址来自 ")}
            <code>GET /meta</code>
            {t(
              "; the frontend caches read-only public info only.",
              "；前端只缓存只读公开信息。",
            )}
          </p>
        </Panel>
      </div>

      <div className="ops-grid">
        <Panel
          eyebrow={t("Create mining contest", "创建挖矿赛")}
          title={t("Create mining contest", "创建挖矿赛")}
          bracket
        >
          <p className="muted small">
            {t(
              `The platform uses its own agent and a fixed 1 tRTM reward. Concurrent limit: ${meta.limits.maxActiveMining} contests; a retired defenseHash cannot be reused.`,
              `平台使用自持 agent 与固定 1 tRTM 奖励。并发上限 ${meta.limits.maxActiveMining} 场；defenseHash 退役后不可复用。`,
            )}
          </p>
          <TextField
            label={t("Agent version", "Agent 版本")}
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            hint={t(
              "Lowercase letters, digits, underscores or hyphens; must match an agent version loaded by the platform",
              "小写字母/数字/下划线/短横线；对应平台已加载的 agent version",
            )}
          />
          <Button
            block
            loading={busy === "mining"}
            iconLeft={<Pickaxe size={14} />}
            onClick={() => void createMining()}
          >
            {t("Create mining contest", "创建挖矿赛")}
          </Button>
          {miningResult && (
            <div className="ops-result">
              <p className="mono">CONTEST {miningResult.contest_id}</p>
              <p className="mono">TX {miningResult.tx_hash}</p>
              <div className="row-actions">
                <Link className="btn btn--ghost btn--sm" to={`/mine/${miningResult.contest_id}`}>
                  {t("Open battlefield", "打开战场")}
                  <ArrowUpRight size={12} />
                </Link>
                <AddressChip value={miningResult.tx_hash} kind="tx" />
              </div>
            </div>
          )}
        </Panel>

        <Panel
          eyebrow={t("Publish dataset", "发布数据集")}
          title={t("Publish post-contest data", "发布赛后数据")}
          bracket
        >
          <p className="muted small">
            {t(
              "Only completed standard contests. Publishing writes the consent-aware data root to DataMarket; the defender can purchase only afterward.",
              "只允许已结束的普通赛；发布会把 consent-aware 数据根写入 DataMarket，之后守方才能购买。",
            )}
          </p>
          <SelectField
            label={t("Select contest", "选择比赛")}
            value={selectedContest}
            onChange={(event) => setSelectedContest(event.target.value)}
            options={endedContests.map((contest) => ({
              value: contest.id,
              label: t(
                `${contest.id.slice(0, 12)}… · ${stateLabel(contest.state)} · ${contest.paid_count} msgs`,
                `${contest.id.slice(0, 12)}… · ${stateLabel(contest.state)} · ${contest.paid_count} 条消息`,
              ),
            }))}
            placeholder={
              endedContests.length
                ? t("Select a completed contest", "选择已结束比赛")
                : t("No completed contests", "没有已结束比赛")
            }
            hint={t(
              `${endedContests.length} contests available to publish`,
              `${endedContests.length} 场可发布`,
            )}
          />
          <Button
            block
            loading={busy === "publish"}
            disabled={!selectedContest}
            iconLeft={<Database size={14} />}
            onClick={() => void publish()}
          >
            {t("Publish dataset", "发布数据集")}
          </Button>
          {publishResult && (
            <div className="ops-result">
              <p className="mono">ROOT {publishResult.root}</p>
              <div className="row-actions">
                <Link className="btn btn--ghost btn--sm" to={`/market/${publishResult.contest_id}`}>
                  {t("Open data market", "打开数据市场")}
                  <ArrowUpRight size={12} />
                </Link>
                <AddressChip value={publishResult.tx_hash} kind="tx" />
              </div>
            </div>
          )}
        </Panel>
      </div>

      <Panel
        eyebrow={t("Recent contests", "最近比赛")}
        title={t("Recent contests", "最近比赛")}
        tone="flat"
      >
        {contestsQuery.data && contestsQuery.data.length > 0 ? (
          <div className="ops-contests">
            {contestsQuery.data.slice(0, 8).map((contest) => (
              <div className="ops-contests__row" key={contest.id}>
                <span className="mono">{contest.id.slice(0, 12)}…</span>
                <Badge tone={contest.is_mining ? "mining" : contest.state === "live" ? "live" : "neutral"}>
                  {contest.is_mining ? t("mining", "挖矿赛") : stateLabel(contest.state)}
                </Badge>
                <span className="muted small">
                  {t(
                    `${contest.paid_count} msgs`,
                    `${contest.paid_count} 条消息`,
                  )}{" "}
                  · {formatDateTime(contest.start_ts)}
                </span>
                <Link
                  className="btn btn--ghost btn--sm"
                  to={contest.is_mining ? `/mine/${contest.id}` : `/arena/${contest.id}`}
                >
                  {t("View", "查看")}
                </Link>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted small">{t("No contests indexed yet.", "还没有索引到比赛。")}</p>
        )}
      </Panel>

      <div className="ops-footer-note">
        <TriangleAlert size={14} />
        <span>
          {t(
            "The admin key lives only in sessionStorage and is cleared when the tab closes. Never put the key in a ",
            "管理密钥只保存在 sessionStorage，关闭标签页即清除。不要把密钥写进 ",
          )}
          <code>VITE_*</code>
          {t(" variable.", " 变量。")}
        </span>
        <CheckCircle2 size={14} />
      </div>
    </div>
  );
}
