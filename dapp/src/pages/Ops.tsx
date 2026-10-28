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
import { errorText, formatDateTime, timeAgo } from "../lib/format";
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
      setError("请输入运营密钥。");
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
      setError("版本名只能包含小写字母、数字、下划线和短横线，且以字母或数字开头。");
      return;
    }
    setBusy("mining");
    try {
      const result = await api.createMiningContest(version.trim(), adminKey);
      setMiningResult(result);
      toast({ title: "挖矿赛已创建", description: `contest ${result.contest_id.slice(0, 12)}…`, tone: "success" });
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
      setError("请选择一场已结束的普通赛。");
      return;
    }
    setBusy("publish");
    try {
      const result = await api.publishDataSet(selectedContest, adminKey);
      setPublishResult(result);
      toast({ title: "数据集已发布", description: `root ${result.root.slice(0, 12)}…`, tone: "success" });
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
          <p className="eyebrow">Restricted / 运营入口</p>
          <h1>运营控制台</h1>
          <p className="muted">
            这里可以创建挖矿赛与发布数据集。公开玩家界面不展示这些操作；生产环境由同源代理校验管理密钥。
          </p>
          <TextField
            label="管理密钥 X-Admin-Key"
            type="password"
            value={draftKey}
            onChange={(event) => setDraftKey(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") unlock();
            }}
            placeholder="由部署环境变量 PLATFORM_ADMIN_KEY 设置"
            autoComplete="off"
            autoFocus
          />
          {error && <Alert tone="error">{error}</Alert>}
          <Button block iconLeft={<KeyRound size={14} />} onClick={unlock}>
            进入控制台
          </Button>
          <p className="ops-gate__note mono">
            KEY IS STORED IN SESSION STORAGE ONLY · NEVER BUILT INTO THE BUNDLE
          </p>
        </div>
      </div>
    );
  }

  const indexer = status?.indexer;

  return (
    <div className="ops-page">
      <SectionHeader
        eyebrow="Operations / 运营"
        title={
          <>
            运营<em>控制台</em>
          </>
        }
        description="平台级操作与同步状态。所有请求都带 X-Admin-Key；生产环境必须由代理校验后再转发到平台 API。"
        actions={
          <div className="section-actions">
            <Badge tone="warning">
              <Shield size={11} /> OPERATOR ONLY
            </Badge>
            <Button size="sm" variant="ghost" iconLeft={<Lock size={12} />} onClick={lock}>
              锁定
            </Button>
          </div>
        }
      />

      {error && <Alert tone="error">{error}</Alert>}
      {!online && (
        <Alert tone="warning" title="平台 API 未连接">
          状态与操作可能不可用。检查 API 进程与代理配置后刷新。
        </Alert>
      )}

      <div className="stat-strip">
        <Stat
          label="API"
          value={online ? "ONLINE" : "OFFLINE"}
          tone={online ? "live" : "danger"}
          icon={<Server size={14} />}
        />
        <Stat
          label="索引区块"
          value={indexer?.lastBlock !== null && indexer?.lastBlock !== undefined ? `#${indexer.lastBlock.toLocaleString("zh-CN")}` : "—"}
          icon={<Activity size={14} />}
        />
        <Stat
          label="同步延迟"
          value={typeof indexer?.lag === "number" ? `${indexer.lag} 块` : "—"}
          tone={typeof indexer?.lag === "number" && indexer.lag > 10 ? "warning" : "neutral"}
          icon={<RefreshCw size={14} />}
        />
        <Stat label="链 ID" value={String(meta.chainId)} icon={<Terminal size={14} />} />
      </div>

      <div className="ops-grid">
        <Panel
          eyebrow="Indexer / 同步"
          title="链上事件索引器"
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
              刷新
            </Button>
          }
        >
          <dl className="ops-kv">
            <div>
              <dt>network</dt>
              <dd className="mono">{meta.network}</dd>
            </div>
            <div>
              <dt>chain</dt>
              <dd className="mono">{meta.chainId}</dd>
            </div>
            <div>
              <dt>RPC</dt>
              <dd className="mono">{meta.rpc}</dd>
            </div>
            <div>
              <dt>last block</dt>
              <dd className="mono">
                {indexer?.lastBlock !== null && indexer?.lastBlock !== undefined
                  ? indexer.lastBlock.toLocaleString("zh-CN")
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>latest block</dt>
              <dd className="mono">
                {indexer?.latestBlock !== null && indexer?.latestBlock !== undefined
                  ? indexer.latestBlock.toLocaleString("zh-CN")
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>updated</dt>
              <dd>{indexer?.updatedAt ? timeAgo(indexer.updatedAt) : "—"}</dd>
            </div>
            <div>
              <dt>events</dt>
              <dd className="mono">{indexer?.events ?? "—"}</dd>
            </div>
            <div>
              <dt>running</dt>
              <dd>{indexer?.running === undefined ? "—" : indexer.running ? "yes" : "no"}</dd>
            </div>
          </dl>
          {indexer?.lastError && (
            <Alert tone="error" title="索引器错误">
              {indexer.lastError}
            </Alert>
          )}
        </Panel>

        <Panel eyebrow="Contracts / 合约" title="当前地址" bracket>
          <div className="contract-list">
            {Object.entries(meta.addresses).map(([name, address]) => (
              <div key={name}>
                <span className="mono">{name}</span>
                <AddressChip value={address} />
              </div>
            ))}
          </div>
          <p className="position__hint">
            地址来自 <code>GET /meta</code>；前端只缓存只读公开信息。
          </p>
        </Panel>
      </div>

      <div className="ops-grid">
        <Panel eyebrow="Create mining contest" title="创建挖矿赛" bracket>
          <p className="muted small">
            平台使用自持智能体与固定 1 RTM 奖励。并发上限 {meta.limits.maxActiveMining} 场；
            defenseHash 退役后不可复用。
          </p>
          <TextField
            label="Agent version"
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            hint="小写字母/数字/下划线/短横线；对应平台已加载的 agent version"
          />
          <Button
            block
            loading={busy === "mining"}
            iconLeft={<Pickaxe size={14} />}
            onClick={() => void createMining()}
          >
            创建挖矿赛
          </Button>
          {miningResult && (
            <div className="ops-result">
              <p className="mono">CONTEST {miningResult.contest_id}</p>
              <p className="mono">TX {miningResult.tx_hash}</p>
              <div className="row-actions">
                <Link className="btn btn--ghost btn--sm" to={`/mine/${miningResult.contest_id}`}>
                  打开战场
                  <ArrowUpRight size={12} />
                </Link>
                <AddressChip value={miningResult.tx_hash} kind="tx" />
              </div>
            </div>
          )}
        </Panel>

        <Panel eyebrow="Publish dataset" title="发布赛后数据" bracket>
          <p className="muted small">
            只允许已结束的普通赛；发布会把 consent-aware 数据根写入 DataMarket，之后守方才能购买。
          </p>
          <SelectField
            label="选择比赛"
            value={selectedContest}
            onChange={(event) => setSelectedContest(event.target.value)}
            options={endedContests.map((contest) => ({
              value: contest.id,
              label: `${contest.id.slice(0, 12)}… · ${contest.state} · ${contest.paid_count} msgs`,
            }))}
            placeholder={endedContests.length ? "选择已结束比赛" : "没有已结束比赛"}
            hint={`${endedContests.length} 场可发布`}
          />
          <Button
            block
            loading={busy === "publish"}
            disabled={!selectedContest}
            iconLeft={<Database size={14} />}
            onClick={() => void publish()}
          >
            发布数据集
          </Button>
          {publishResult && (
            <div className="ops-result">
              <p className="mono">ROOT {publishResult.root}</p>
              <div className="row-actions">
                <Link className="btn btn--ghost btn--sm" to={`/market/${publishResult.contest_id}`}>
                  打开数据市场
                  <ArrowUpRight size={12} />
                </Link>
                <AddressChip value={publishResult.tx_hash} kind="tx" />
              </div>
            </div>
          )}
        </Panel>
      </div>

      <Panel eyebrow="Recent contests" title="最近比赛" tone="flat">
        {contestsQuery.data && contestsQuery.data.length > 0 ? (
          <div className="ops-contests">
            {contestsQuery.data.slice(0, 8).map((contest) => (
              <div className="ops-contests__row" key={contest.id}>
                <span className="mono">{contest.id.slice(0, 12)}…</span>
                <Badge tone={contest.is_mining ? "mining" : contest.state === "live" ? "live" : "neutral"}>
                  {contest.is_mining ? "mining" : contest.state}
                </Badge>
                <span className="muted small">
                  {contest.paid_count} msgs · {formatDateTime(contest.start_ts)}
                </span>
                <Link
                  className="btn btn--ghost btn--sm"
                  to={contest.is_mining ? `/mine/${contest.id}` : `/arena/${contest.id}`}
                >
                  查看
                </Link>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted small">还没有索引到比赛。</p>
        )}
      </Panel>

      <div className="ops-footer-note">
        <TriangleAlert size={14} />
        <span>
          管理密钥只保存在 sessionStorage，关闭标签页即清除。不要把密钥写进 <code>VITE_*</code> 变量。
        </span>
        <CheckCircle2 size={14} />
      </div>
    </div>
  );
}
