import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Crown,
  Medal,
  RefreshCw,
  Search,
  Skull,
  Target,
  Trophy,
} from "lucide-react";
import { useAccount } from "wagmi";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { SectionHeader } from "../components/ui/SectionHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import { Tabs } from "../components/ui/Tabs";
import { Identicon } from "../components/wallet/Identicon";
import { useLeaderboardsQuery } from "../lib/platform";
import {
  formatDateTime,
  formatDuration,
  formatPercent,
  formatRtm,
  outcomeLabel,
  shortAddr,
  timeAgo,
} from "../lib/format";
import { useDebouncedValue } from "../lib/hooks";

type RankTab = "attackers" | "defenders" | "miners" | "mining";

interface Row {
  address: string;
  primary: { label: string; value: string };
  metrics: Array<{ label: string; value: string }>;
}

function PodiumCard({
  row,
  rank,
}: {
  row: Row;
  rank: number;
}) {
  const tone = rank === 1 ? "gold" : rank === 2 ? "silver" : "bronze";
  return (
    <article className={`podium-card podium-card--${tone}`}>
      <span className="podium-card__rank">
        {rank === 1 ? <Crown size={16} /> : <Medal size={15} />}
        <span className="mono">0{rank}</span>
      </span>
      <Identicon address={row.address} size={44} />
      <p className="podium-card__address mono">{shortAddr(row.address, 8, 6)}</p>
      <div className="podium-card__primary">
        <strong>{row.primary.value}</strong>
        <span>{row.primary.label}</span>
      </div>
      <div className="podium-card__metrics">
        {row.metrics.slice(0, 2).map((metric) => (
          <span key={metric.label}>
            {metric.label} <strong>{metric.value}</strong>
          </span>
        ))}
      </div>
    </article>
  );
}

export default function Leaderboard() {
  const query = useLeaderboardsQuery();
  const { address } = useAccount();
  const [tab, setTab] = useState<RankTab>("attackers");
  const [search, setSearch] = useState("");
  const debounced = useDebouncedValue(search, 200);
  const boards = query.data;

  const rows = useMemo<Row[]>(() => {
    if (!boards) return [];
    if (tab === "attackers") {
      return Object.entries(boards.attackers)
        .sort((a, b) => b[1].wins - a[1].wins || b[1].difficulty - a[1].difficulty)
        .map(([who, entry]) => ({
          address: who,
          primary: { label: "胜场", value: String(entry.wins) },
          metrics: [
            { label: "赢得", value: `${formatRtm(entry.rtm_won)} RTM` },
            { label: "难度", value: String(entry.difficulty) },
            { label: "当前连胜", value: String(entry.current_streak) },
            { label: "最长连胜", value: String(entry.longest_streak) },
          ],
        }));
    }
    if (tab === "defenders") {
      return Object.entries(boards.defenders)
        .sort((a, b) => b[1].contests_survived - a[1].contests_survived)
        .map(([who, entry]) => ({
          address: who,
          primary: { label: "守住", value: `${entry.contests_survived} 场` },
          metrics: [
            { label: "承受消息", value: String(entry.msgs_withstood) },
            { label: "罚款", value: `${formatRtm(entry.penalties)} RTM` },
            { label: "净收入", value: `${formatRtm(entry.net_income)} RTM` },
            { label: "最长存活", value: formatDuration(entry.longest_survival) },
          ],
        }));
    }
    if (tab === "miners") {
      return Object.entries(boards.miners)
        .sort((a, b) => b[1].wins - a[1].wins || b[1].difficulty - a[1].difficulty)
        .map(([who, entry]) => ({
          address: who,
          primary: { label: "攻破", value: `${entry.wins} 次` },
          metrics: [
            { label: "加入", value: String(entry.joined) },
            { label: "已决", value: String(entry.decided_joined) },
            { label: "固定奖励", value: `${formatRtm(entry.rtm_won_fixed)} RTM` },
            { label: "攻破率", value: formatPercent(entry.breach_rate) },
          ],
        }));
    }
    return [];
  }, [boards, tab]);

  const filtered = useMemo(() => {
    const needle = debounced.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => row.address.toLowerCase().includes(needle));
  }, [debounced, rows]);

  const mining = boards?.mining;
  const updatedAt = query.dataUpdatedAt / 1_000;
  const self = address?.toLowerCase();

  return (
    <div className="leaderboard-page">
      <SectionHeader
        eyebrow={`Leaderboards / ${boards?.network ?? "chain"}`}
        title={
          <>
            谁在制定<em>规则</em>
          </>
        }
        description="榜单完全由链上事件计算；烟测赛与部署注水不计入。难度 = 攻破前靶钱包承受的付费消息数，防止刷软靶。"
        actions={
          <div className="section-actions">
            {query.dataUpdatedAt > 0 && (
              <span className="muted small">更新于 {timeAgo(updatedAt)}</span>
            )}
            <Button
              size="sm"
              variant="ghost"
              iconLeft={<RefreshCw size={12} />}
              loading={query.isFetching}
              onClick={() => void query.refetch()}
            >
              刷新
            </Button>
          </div>
        }
      />

      <div className="stat-strip">
        <Stat
          label="攻方地址"
          numericValue={Object.keys(boards?.attackers ?? {}).length}
          format={(value) => String(Math.round(value))}
          icon={<Target size={14} />}
        />
        <Stat
          label="守方地址"
          numericValue={Object.keys(boards?.defenders ?? {}).length}
          format={(value) => String(Math.round(value))}
          icon={<Trophy size={14} />}
        />
        <Stat
          label="矿工地址"
          numericValue={Object.keys(boards?.miners ?? {}).length}
          format={(value) => String(Math.round(value))}
          icon={<Skull size={14} />}
        />
        <Stat
          label="挖矿攻破率"
          value={formatPercent(mining?.breach_rate ?? 0)}
          icon={<Target size={14} />}
        />
      </div>

      <div className="filter-bar">
        <Tabs
          ariaLabel="榜单类型"
          value={tab}
          onChange={setTab}
          items={[
            { id: "attackers", label: "攻方榜", count: Object.keys(boards?.attackers ?? {}).length },
            { id: "defenders", label: "守方榜", count: Object.keys(boards?.defenders ?? {}).length },
            { id: "miners", label: "矿工榜", count: Object.keys(boards?.miners ?? {}).length },
            { id: "mining", label: "挖矿统计" },
          ]}
        />
        {tab !== "mining" && (
          <label className="search-box">
            <Search size={14} aria-hidden="true" />
            <span className="sr-only">搜索地址</span>
            <input
              className="search-box__input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索 0x 地址"
            />
          </label>
        )}
      </div>

      {query.isLoading ? (
        <div className="rank-loading">
          <Skeleton height={92} />
          <Skeleton height={92} />
          <Skeleton height={92} />
          <Skeleton height={92} />
        </div>
      ) : query.isError ? (
        <EmptyState
          title="榜单暂时不可用"
          description="平台 API 或索引器没有响应。稍后重试。"
          action={
            <Button size="sm" onClick={() => void query.refetch()}>
              重试
            </Button>
          }
        />
      ) : tab === "mining" ? (
        <div className="mining-stats">
          <div className="mining-stats__grid">
            <Stat label="创建" numericValue={mining?.created ?? 0} format={(v) => String(Math.round(v))} />
            <Stat label="已攻破" numericValue={mining?.settled ?? 0} format={(v) => String(Math.round(v))} tone="danger" />
            <Stat label="未攻破退役" numericValue={mining?.retired ?? 0} format={(v) => String(Math.round(v))} />
            <Stat label="已决" numericValue={mining?.decided ?? 0} format={(v) => String(Math.round(v))} />
            <Stat label="固定奖励总额" value={formatRtm(mining?.total_fixed_reward ?? "0")} unit="RTM" />
            <Stat label="活跃赛" numericValue={mining?.active_contests ?? 0} format={(v) => String(Math.round(v))} tone="live" />
          </div>

          <section className="mining-block">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Active versions</p>
                <h2>当前活跃版本</h2>
              </div>
              <Badge tone="live" dot>
                {mining?.active_versions.length ?? 0} ACTIVE
              </Badge>
            </div>
            {mining && mining.active_versions.length > 0 ? (
              <div className="version-list">
                {mining.active_versions.map((version) => (
                  <div className="version-row" key={version.contest_id}>
                    <span className="version-row__dot" />
                    <div className="version-row__main">
                      <span className="mono">{shortAddr(version.contest_id)}</span>
                      <span className="muted small">hash {shortAddr(version.defense_hash)}</span>
                    </div>
                    <span className="version-row__stat">{version.paid_messages} 条消息</span>
                    <Link className="btn btn--ghost btn--sm" to={`/mine/${version.contest_id}`}>
                      战场
                      <ArrowUpRight size={12} />
                    </Link>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="没有活跃版本" description="运营创建挖矿赛后，版本会显示在这里。" />
            )}
          </section>

          <section className="mining-block">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Settled history</p>
                <h2>已决历史</h2>
              </div>
            </div>
            {mining && mining.history.length > 0 ? (
              <div className="history-table">
                <div className="history-table__head">
                  <span>比赛</span>
                  <span>结果</span>
                  <span>付费消息</span>
                  <span>胜者</span>
                  <span>结束时间</span>
                </div>
                {mining.history.map((item) => (
                  <div className="history-table__row" key={item.contest_id}>
                    <span className="mono">{shortAddr(item.contest_id)}</span>
                    <span>
                      <Badge tone={item.outcome === "settled" ? "danger" : "neutral"}>
                        {outcomeLabel(item.outcome)}
                      </Badge>
                    </span>
                    <span className="tabular">{item.paid_messages}</span>
                    <span className="mono">{shortAddr(item.winner)}</span>
                    <span className="muted">{formatDateTime(item.ended_ts)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="还没有已决记录" description="比赛被攻破或退役后会归档在这里。" />
            )}
          </section>
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title={search ? "没有匹配的地址" : "榜单还没有记录"}
          description={search ? "试试缩短搜索词。" : "第一场比赛结算后，这里会出现排名。"}
        />
      ) : (
        <>
          <div className="podium">
            {filtered.slice(0, 3).map((row, index) => (
              <PodiumCard key={row.address} row={row} rank={index + 1} />
            ))}
          </div>
          <div className="rank-list">
            <div className="rank-list__head">
              <span>RANK</span>
              <span>ADDRESS</span>
              <span>PRIMARY</span>
              <span>METRICS</span>
            </div>
            {filtered.map((row, index) => {
              const isSelf = self && row.address.toLowerCase() === self;
              return (
                <div className={`rank-row ${isSelf ? "is-self" : ""}`.trim()} key={row.address}>
                  <span className={`rank-row__rank ${index < 3 ? "is-top" : ""}`.trim()}>
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="rank-row__address">
                    <Identicon address={row.address} size={26} />
                    <span className="mono">{shortAddr(row.address, 8, 6)}</span>
                    {isSelf && <Badge tone="accent">你</Badge>}
                  </span>
                  <span className="rank-row__primary tabular">{row.primary.value}</span>
                  <span className="rank-row__metrics">
                    {row.metrics.map((metric) => (
                      <span key={metric.label}>
                        <small>{metric.label}</small>
                        <strong className="tabular">{metric.value}</strong>
                      </span>
                    ))}
                  </span>
                </div>
              );
            })}
          </div>
        </>
      )}

      <p className="page-note">
        <Badge tone="outline">计算口径</Badge>
        胜场与难度来自链上事件；罚款按时间衰减累计；最长存活以秒计。被排除的烟测赛不参与榜单。
      </p>
    </div>
  );
}
