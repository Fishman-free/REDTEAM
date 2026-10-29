import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Crosshair,
  History,
  Pickaxe,
  RefreshCw,
  Skull,
  Target,
  Trophy,
} from "lucide-react";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { SectionHeader } from "../components/ui/SectionHeader";
import { SkeletonCard } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import { Tabs } from "../components/ui/Tabs";
import { ContestCard } from "../components/contest/ContestCard";
import { useContestsQuery, useLeaderboardsQuery, usePlatform } from "../lib/platform";
import { contestEndMs } from "../lib/contest";
import { formatDateTime, formatPercent, formatRtm, outcomeLabel, shortAddr } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { useNow } from "../lib/hooks";

type MineTab = "live" | "all" | "ended";

export default function Mine() {
  const { t } = useI18n();
  const contestsQuery = useContestsQuery();
  const boardsQuery = useLeaderboardsQuery();
  const { meta } = usePlatform();
  const now = useNow(30_000);
  const [tab, setTab] = useState<MineTab>("live");

  const all = useMemo(
    () => (contestsQuery.data ?? []).filter((contest) => contest.is_mining),
    [contestsQuery.data],
  );
  const live = useMemo(
    () => all.filter((contest) => contest.state === "live" && contestEndMs(contest) > now),
    [all, now],
  );
  const ended = useMemo(() => all.filter((contest) => contest.state !== "live"), [all]);
  const mining = boardsQuery.data?.mining;

  const filtered = tab === "live" ? live : tab === "ended" ? ended : all;

  return (
    <div className="mine-page">
      <SectionHeader
        eyebrow={t("Mining program", "挖矿中心")}
        title={
          <>
            {t("Breach the platform agent and earn ", "攻破平台 agent，")}
            <em>{t("a fixed 1 tRTM", "固定 1 tRTM")}</em>
          </>
        }
        description={t(
          "Miners stake nothing; each message costs 0.005 tRTM. The platform owns the agent: a breach ends the contest immediately, retires the defenseHash for good, and miner data only feeds the RSI repair loop.",
          "矿工无需质押，每条消息 0.005 tRTM。平台自持 agent；攻破后比赛立即停止，defenseHash 永久退役，矿工数据只进入 RSI 修复闭环。",
        )}
        actions={
          <Link to="/leaderboard" className="btn btn--ghost btn--sm">
            {t("Mining stats", "挖矿统计")}
            <ArrowUpRight size={13} />
          </Link>
        }
      />

      <div className="stat-strip">
        <Stat
          label={t("Active mining contests", "活跃挖矿赛")}
          numericValue={mining?.active_contests ?? live.length}
          format={(value) => String(Math.round(value)).padStart(2, "0")}
          tone="live"
          icon={<Pickaxe size={14} />}
        />
        <Stat
          label={t("Fixed reward", "固定奖励")}
          value={formatRtm(meta.fees.miningRewardWei)}
          unit="tRTM"
          icon={<Trophy size={14} />}
        />
        <Stat
          label={t("Total breaches", "累计攻破")}
          numericValue={mining?.settled ?? 0}
          format={(value) => String(Math.round(value))}
          icon={<Skull size={14} />}
        />
        <Stat
          label={t("Platform breach rate", "平台攻破率")}
          value={formatPercent(mining?.breach_rate ?? 0)}
          icon={<Target size={14} />}
        />
      </div>

      <section className="mine-brief">
        <div className="mine-brief__lead">
          <span className="mine-brief__glyph" aria-hidden="true">
            <Crosshair size={24} />
          </span>
          <div>
            <p className="mono">{t("PLATFORM-OWNED TARGET", "平台自持目标")}</p>
            <h2>{t("No stake, only attack cost", "没有质押，只有攻击成本")}</h2>
            <p>
              {t(
                "Miners lock no capital to join, and each message costs a fixed 0.005 tRTM. On a breach, the platform mints 1 tRTM to Treasury and the winner takes the W balance; the hash is permanently retired. No accrual, and no prize pool that grows over time.",
                "矿工加入不锁定资金；每条消息固定 0.005 tRTM。攻破后平台向 Treasury 补铸 1 tRTM，胜者拿走 W 余额，hash 永久退役。没有 accrue，也没有随时间累积的奖池。",
              )}
            </p>
          </div>
        </div>
        <div className="mine-brief__facts">
          <div>
            <span>{t("Per message", "单条消息")}</span>
            <strong>{formatRtm(meta.fees.miningFeeWei, { maxFraction: 4 })} tRTM</strong>
          </div>
          <div>
            <span>{t("Breach reward", "攻破奖励")}</span>
            <strong>1.000 tRTM</strong>
          </div>
          <div>
            <span>{t("Active cap", "活跃上限")}</span>
            <strong>
              {meta.limits.maxActiveMining} {t("contests", "场")}
            </strong>
          </div>
          <div>
            <span>{t("Data use", "数据用途")}</span>
            <strong>{t("RSI repair only", "仅 RSI 修复")}</strong>
          </div>
        </div>
      </section>

      <div className="filter-bar">
        <Tabs
          ariaLabel={t("Mining contest status", "挖矿赛状态")}
          value={tab}
          onChange={setTab}
          items={[
            { id: "live", label: t("Live", "进行中"), count: live.length },
            { id: "all", label: t("All", "全部"), count: all.length },
            { id: "ended", label: t("Ended", "已结束"), count: ended.length },
          ]}
        />
        <div className="filter-bar__right">
          <Badge tone="mining">{t("Fixed 1 tRTM reward", "固定奖励 1 tRTM")}</Badge>
          <Button
            size="sm"
            variant="quiet"
            iconLeft={<RefreshCw size={12} />}
            loading={contestsQuery.isFetching}
            onClick={() => void contestsQuery.refetch()}
          >
            {t("Refresh", "刷新")}
          </Button>
        </div>
      </div>

      {contestsQuery.isLoading ? (
        <div className="contest-grid">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Pickaxe size={22} />}
          title={
            tab === "live"
              ? t("No active mining contests", "当前没有活跃挖矿赛")
              : t("No mining history yet", "还没有挖矿记录")
          }
          description={t(
            "Mining contests are created by the operator (up to 3 at once). New contests appear here with a join entry and live status.",
            "挖矿赛由平台运营创建（最多 3 场并发）。比赛出现后，这里会显示加入入口与战况。",
          )}
          action={
            tab !== "all" ? (
              <Button variant="ghost" size="sm" onClick={() => setTab("all")}>
                {t("View all", "查看全部")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="contest-grid">
          {filtered.map((contest, index) => (
            <ContestCard
              key={contest.id}
              contest={contest}
              index={index}
              href={`/mine/${contest.id}`}
            />
          ))}
        </div>
      )}

      <section className="section">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">{t("Version history", "版本历史")}</p>
            <h2>{t("Settled and retired", "已决与退役")}</h2>
          </div>
          <Badge tone="neutral">
            {mining?.history.length ?? 0} {t("records", "条记录")}
          </Badge>
        </div>
        {mining && mining.history.length > 0 ? (
          <div className="mining-history">
            {mining.history.map((item) => (
              <div className="mining-history__row" key={item.contest_id}>
                <span className={`mining-history__icon ${item.outcome === "settled" ? "is-breach" : ""}`.trim()}>
                  {item.outcome === "settled" ? <Skull size={14} /> : <History size={14} />}
                </span>
                <div className="mining-history__main">
                  <div>
                    <strong>{outcomeLabel(item.outcome)}</strong>
                    <span className="mono">{shortAddr(item.contest_id)}</span>
                  </div>
                  <span className="muted small">
                    {t("hash", "哈希")} {shortAddr(item.defense_hash)} · {item.paid_messages}{" "}
                    {t("paid messages", "条付费消息")} · {formatDateTime(item.ended_ts)}
                  </span>
                </div>
                <div className="mining-history__winner">
                  <span className="muted small">{t("Winner", "胜者")}</span>
                  <span className="mono">{shortAddr(item.winner)}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<History size={22} />}
            title={t("No settled records yet", "还没有已决记录")}
            description={t(
              "Mining contests appear here once they are breached or retired.",
              "挖矿赛被攻破或退役后，会记录在这里。",
            )}
          />
        )}
      </section>

      <p className="page-note">
        <Badge tone="outline">{t("Data boundary", "数据边界")}</Badge>
        {t(
          "Miner data is retained as required, but used only for the defending agent's RSI repair. It never enters DataMarket and is never sold.",
          "矿工数据强制留存，但只用于防守方 agent 的 RSI 修复，不进入 DataMarket、不出售。",
        )}
      </p>
    </div>
  );
}
