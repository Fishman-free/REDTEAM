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
import { useI18n } from "../lib/i18n";
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
  const { t } = useI18n();
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
          primary: { label: t("Wins", "胜场"), value: String(entry.wins) },
          metrics: [
            { label: t("Earned", "赢得"), value: `${formatRtm(entry.rtm_won)} tRTM` },
            { label: t("Difficulty", "难度"), value: String(entry.difficulty) },
            { label: t("Current streak", "当前连胜"), value: String(entry.current_streak) },
            { label: t("Longest streak", "最长连胜"), value: String(entry.longest_streak) },
          ],
        }));
    }
    if (tab === "defenders") {
      return Object.entries(boards.defenders)
        .sort((a, b) => b[1].contests_survived - a[1].contests_survived)
        .map(([who, entry]) => ({
          address: who,
          primary: {
            label: t("Defended", "守住"),
            value: `${entry.contests_survived} ${t("contests", "场")}`,
          },
          metrics: [
            { label: t("Messages withstood", "承受消息"), value: String(entry.msgs_withstood) },
            { label: t("Penalties", "罚款"), value: `${formatRtm(entry.penalties)} tRTM` },
            { label: t("Net income", "净收入"), value: `${formatRtm(entry.net_income)} tRTM` },
            { label: t("Longest survival", "最长存活"), value: formatDuration(entry.longest_survival) },
          ],
        }));
    }
    if (tab === "miners") {
      return Object.entries(boards.miners)
        .sort((a, b) => b[1].wins - a[1].wins || b[1].difficulty - a[1].difficulty)
        .map(([who, entry]) => ({
          address: who,
          primary: {
            label: t("Breaches", "攻破"),
            value: `${entry.wins} ${t("times", "次")}`,
          },
          metrics: [
            { label: t("Joined", "加入"), value: String(entry.joined) },
            { label: t("Decided", "已决"), value: String(entry.decided_joined) },
            { label: t("Fixed reward", "固定奖励"), value: `${formatRtm(entry.rtm_won_fixed)} tRTM` },
            { label: t("Breach rate", "攻破率"), value: formatPercent(entry.breach_rate) },
          ],
        }));
    }
    return [];
  }, [boards, tab, t]);

  const filtered = useMemo(() => {
    const needle = debounced.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => row.address.toLowerCase().includes(needle));
  }, [debounced, rows]);

  const mining = boards?.mining;
  const updatedAt = query.dataUpdatedAt / 1_000;
  const self = address?.toLowerCase();
  const network = boards?.network ?? t("chain", "链");

  return (
    <div className="leaderboard-page">
      <SectionHeader
        eyebrow={`${t("Leaderboards", "排行榜")} / ${network}`}
        title={
          <>
            {t("Who sets ", "谁在制定")}
            <em>{t("the rules", "规则")}</em>
          </>
        }
        description={t(
          "Rankings are computed entirely from on-chain events; smoke tests and deploy-time padding are excluded. Difficulty is the number of paid messages the target wallet withstood before a breach, which prevents farming soft targets.",
          "榜单完全由链上事件计算；烟测赛与部署注水不计入。难度 = 攻破前靶钱包承受的付费消息数，防止刷软靶。",
        )}
        actions={
          <div className="section-actions">
            {query.dataUpdatedAt > 0 && (
              <span className="muted small">
                {t("Updated", "更新于")} {timeAgo(updatedAt)}
              </span>
            )}
            <Button
              size="sm"
              variant="ghost"
              iconLeft={<RefreshCw size={12} />}
              loading={query.isFetching}
              onClick={() => void query.refetch()}
            >
              {t("Refresh", "刷新")}
            </Button>
          </div>
        }
      />

      <div className="stat-strip">
        <Stat
          label={t("Attacker addresses", "攻方地址")}
          numericValue={Object.keys(boards?.attackers ?? {}).length}
          format={(value) => String(Math.round(value))}
          icon={<Target size={14} />}
        />
        <Stat
          label={t("Defender addresses", "守方地址")}
          numericValue={Object.keys(boards?.defenders ?? {}).length}
          format={(value) => String(Math.round(value))}
          icon={<Trophy size={14} />}
        />
        <Stat
          label={t("Miner addresses", "矿工地址")}
          numericValue={Object.keys(boards?.miners ?? {}).length}
          format={(value) => String(Math.round(value))}
          icon={<Skull size={14} />}
        />
        <Stat
          label={t("Mining breach rate", "挖矿攻破率")}
          value={formatPercent(mining?.breach_rate ?? 0)}
          icon={<Target size={14} />}
        />
      </div>

      <div className="filter-bar">
        <Tabs
          ariaLabel={t("Leaderboard type", "榜单类型")}
          value={tab}
          onChange={setTab}
          items={[
            { id: "attackers", label: t("Attackers", "攻方榜"), count: Object.keys(boards?.attackers ?? {}).length },
            { id: "defenders", label: t("Defenders", "守方榜"), count: Object.keys(boards?.defenders ?? {}).length },
            { id: "miners", label: t("Miners", "矿工榜"), count: Object.keys(boards?.miners ?? {}).length },
            { id: "mining", label: t("Mining stats", "挖矿统计") },
          ]}
        />
        {tab !== "mining" && (
          <label className="search-box">
            <Search size={14} aria-hidden="true" />
            <span className="sr-only">{t("Search addresses", "搜索地址")}</span>
            <input
              className="search-box__input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("Search 0x address", "搜索 0x 地址")}
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
          title={t("Leaderboard unavailable", "榜单暂时不可用")}
          description={t(
            "The platform API or indexer did not respond. Try again later.",
            "平台 API 或索引器没有响应。稍后重试。",
          )}
          action={
            <Button size="sm" onClick={() => void query.refetch()}>
              {t("Retry", "重试")}
            </Button>
          }
        />
      ) : tab === "mining" ? (
        <div className="mining-stats">
          <div className="mining-stats__grid">
            <Stat label={t("Created", "创建")} numericValue={mining?.created ?? 0} format={(v) => String(Math.round(v))} />
            <Stat label={t("Breached", "已攻破")} numericValue={mining?.settled ?? 0} format={(v) => String(Math.round(v))} tone="danger" />
            <Stat label={t("Retired unbroken", "未攻破退役")} numericValue={mining?.retired ?? 0} format={(v) => String(Math.round(v))} />
            <Stat label={t("Decided", "已决")} numericValue={mining?.decided ?? 0} format={(v) => String(Math.round(v))} />
            <Stat label={t("Total fixed rewards", "固定奖励总额")} value={formatRtm(mining?.total_fixed_reward ?? "0")} unit="tRTM" />
            <Stat label={t("Active contests", "活跃赛")} numericValue={mining?.active_contests ?? 0} format={(v) => String(Math.round(v))} tone="live" />
          </div>

          <section className="mining-block">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">{t("Live now", "活跃版本")}</p>
                <h2>{t("Active versions", "当前活跃版本")}</h2>
              </div>
              <Badge tone="live" dot>
                {t(
                  `${mining?.active_versions.length ?? 0} ACTIVE`,
                  `${mining?.active_versions.length ?? 0} 场活跃`,
                )}
              </Badge>
            </div>
            {mining && mining.active_versions.length > 0 ? (
              <div className="version-list">
                {mining.active_versions.map((version) => (
                  <div className="version-row" key={version.contest_id}>
                    <span className="version-row__dot" />
                    <div className="version-row__main">
                      <span className="mono">{shortAddr(version.contest_id)}</span>
                      <span className="muted small">
                        {t("hash", "哈希")} {shortAddr(version.defense_hash)}
                      </span>
                    </div>
                    <span className="version-row__stat">
                      {version.paid_messages} {t("messages", "条消息")}
                    </span>
                    <Link className="btn btn--ghost btn--sm" to={`/mine/${version.contest_id}`}>
                      {t("Battlefield", "战场")}
                      <ArrowUpRight size={12} />
                    </Link>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title={t("No active versions", "没有活跃版本")}
                description={t(
                  "Versions appear here after the operator creates a mining contest.",
                  "运营创建挖矿赛后，版本会显示在这里。",
                )}
              />
            )}
          </section>

          <section className="mining-block">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">{t("Settled history", "已决记录")}</p>
                <h2>{t("Settled contests", "已决历史")}</h2>
              </div>
            </div>
            {mining && mining.history.length > 0 ? (
              <div className="history-table">
                <div className="history-table__head">
                  <span>{t("Contest", "比赛")}</span>
                  <span>{t("Outcome", "结果")}</span>
                  <span>{t("Paid messages", "付费消息")}</span>
                  <span>{t("Winner", "胜者")}</span>
                  <span>{t("End time", "结束时间")}</span>
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
              <EmptyState
                title={t("No settled records yet", "还没有已决记录")}
                description={t(
                  "Contests are archived here after they are breached or retired.",
                  "比赛被攻破或退役后会归档在这里。",
                )}
              />
            )}
          </section>
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title={search ? t("No matching addresses", "没有匹配的地址") : t("No rankings yet", "榜单还没有记录")}
          description={
            search
              ? t("Try a shorter search term.", "试试缩短搜索词。")
              : t("Rankings appear after the first contest settles.", "第一场比赛结算后，这里会出现排名。")
          }
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
              <span>{t("RANK", "排名")}</span>
              <span>{t("ADDRESS", "地址")}</span>
              <span>{t("PRIMARY", "主指标")}</span>
              <span>{t("METRICS", "指标")}</span>
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
                    {isSelf && <Badge tone="accent">{t("You", "你")}</Badge>}
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
        <Badge tone="outline">{t("Methodology", "计算口径")}</Badge>
        {t(
          "Wins and difficulty come from on-chain events; penalties accumulate with time decay; longest survival is measured in seconds. Excluded smoke tests do not count toward rankings.",
          "胜场与难度来自链上事件；罚款按时间衰减累计；最长存活以秒计。被排除的烟测赛不参与榜单。",
        )}
      </p>
    </div>
  );
}
