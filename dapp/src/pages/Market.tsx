import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Database,
  LockKeyhole,
  Search,
  ShieldCheck,
  ShoppingBag,
} from "lucide-react";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { SectionHeader } from "../components/ui/SectionHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import { Countdown } from "../components/ui/Countdown";
import { AddressChip } from "../components/ui/Address";
import { useContestsQuery } from "../lib/platform";
import { contestEndMs } from "../lib/contest";
import { formatInt, formatRtm, stateLabel, stateTone } from "../lib/format";
import { useDebouncedValue } from "../lib/hooks";

export default function Market() {
  const contestsQuery = useContestsQuery();
  const [search, setSearch] = useState("");
  const debounced = useDebouncedValue(search, 200);

  const ended = useMemo(
    () =>
      (contestsQuery.data ?? [])
        .filter((contest) => !contest.is_mining && contest.state !== "live")
        .sort((a, b) => (b.ended_ts ?? b.start_ts) - (a.ended_ts ?? a.start_ts)),
    [contestsQuery.data],
  );

  const filtered = useMemo(() => {
    const needle = debounced.trim().toLowerCase();
    if (!needle) return ended;
    return ended.filter(
      (contest) =>
        contest.id.toLowerCase().includes(needle) ||
        contest.defender.toLowerCase().includes(needle),
    );
  }, [debounced, ended]);

  const messages = ended.reduce((sum, contest) => sum + contest.paid_count, 0);
  const defenders = new Set(ended.map((contest) => contest.defender.toLowerCase())).size;

  return (
    <div className="market-page">
      <SectionHeader
        eyebrow="Data market / 数据市场"
        title={
          <>
            只为<em>已同意</em>的数据付费
          </>
        }
        description="数据集只包含普通赛、守方自有数据与已同意出售的攻方数据。平台 70% / 数据提供方 30%，每份数据每地址仅可购买一次。"
        actions={
          <Badge tone="neutral">
            <LockKeyhole size={11} /> DEFENDER ONLY
          </Badge>
        }
      />

      <div className="stat-strip">
        <Stat
          label="已结束比赛"
          numericValue={ended.length}
          format={(value) => String(Math.round(value))}
          icon={<Database size={14} />}
        />
        <Stat
          label="可索引消息"
          numericValue={messages}
          format={(value) => formatInt(Math.round(value))}
          icon={<ShoppingBag size={14} />}
        />
        <Stat
          label="数据守方"
          numericValue={defenders}
          format={(value) => formatInt(Math.round(value))}
          icon={<ShieldCheck size={14} />}
        />
        <Stat label="分账" value="70 / 30" hint="平台 / 数据提供方" icon={<Database size={14} />} />
      </div>

      <div className="market-brief">
        <div>
          <span className="mono">01 / CONSENT</span>
          <strong>opt-out 永不出现</strong>
          <p>攻方加入时选择不落盘，赛后就不会有数据切片。</p>
        </div>
        <div>
          <span className="mono">02 / BUYER</span>
          <strong>只有该场守方可以购买</strong>
          <p>数据用于修复自己的智能体；买家就是守方。</p>
        </div>
        <div>
          <span className="mono">03 / RSI ONLY</span>
          <strong>矿工数据不在市场</strong>
          <p>挖矿数据强制留存，但只进入 RSI 修复闭环。</p>
        </div>
      </div>

      <div className="filter-bar">
        <div className="filter-bar__title">
          <p className="eyebrow">Closed contests</p>
          <h2>已结束的普通赛</h2>
        </div>
        <label className="search-box">
          <Search size={14} aria-hidden="true" />
          <span className="sr-only">搜索数据集</span>
          <input
            className="search-box__input"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索比赛 ID / 守方地址"
          />
        </label>
      </div>

      {contestsQuery.isLoading ? (
        <div className="market-list">
          <Skeleton height={78} />
          <Skeleton height={78} />
          <Skeleton height={78} />
        </div>
      ) : contestsQuery.isError ? (
        <EmptyState
          title="无法读取数据市场"
          description="平台 API 或索引器暂时不可用。"
          action={
            <button className="btn btn--ghost btn--sm" onClick={() => void contestsQuery.refetch()}>
              重试
            </button>
          }
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Database size={22} />}
          title={search ? "没有匹配的数据集" : "还没有可购买的数据"}
          description={
            search
              ? "试试缩短搜索词。"
              : "普通赛结束且运营发布数据集后，这里会显示购买入口。"
          }
        />
      ) : (
        <div className="market-list">
          <div className="market-list__head">
            <span>CONTEST</span>
            <span>DEFENDER</span>
            <span>状态</span>
            <span>MESSAGES</span>
            <span>POOL</span>
            <span />
          </div>
          {filtered.map((contest) => (
            <div className="market-row" key={contest.id}>
              <div className="market-row__id">
                <span className="mono">{contest.id.slice(0, 12)}…</span>
                <Countdown endMs={contestEndMs(contest)} showIcon={false} endedLabel="已结束" />
              </div>
              <div>
                <AddressChip value={contest.defender} />
              </div>
              <div>
                <Badge tone={stateTone(contest.state)}>
                  {stateLabel(contest.state)}
                </Badge>
              </div>
              <div className="tabular">{contest.paid_count}</div>
              <div className="tabular">{formatRtm(contest.stake)} RTM</div>
              <div>
                <Link className="btn btn--ghost btn--sm" to={`/market/${contest.id}`}>
                  打开数据集
                  <ArrowUpRight size={12} />
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      <p className="page-note">
        <Badge tone="outline">隐私边界</Badge>
        数据集按 consent-aware 规则打包；下载令牌有有效期，过期后可由守方重新发起交付。
      </p>
    </div>
  );
}
