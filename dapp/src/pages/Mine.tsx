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
import { useNow } from "../lib/hooks";

type MineTab = "live" | "all" | "ended";

export default function Mine() {
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
        eyebrow="Mining program / 挖矿中心"
        title={
          <>
            攻破平台智能体，<em>固定 1 RTM</em>
          </>
        }
        description="矿工无需质押，每条消息 0.005 RTM。平台自持智能体；攻破后比赛立即停止，defenseHash 永久退役，矿工数据只进入 RSI 修复闭环。"
        actions={
          <Link to="/leaderboard" className="btn btn--ghost btn--sm">
            挖矿统计
            <ArrowUpRight size={13} />
          </Link>
        }
      />

      <div className="stat-strip">
        <Stat
          label="活跃挖矿赛"
          numericValue={mining?.active_contests ?? live.length}
          format={(value) => String(Math.round(value)).padStart(2, "0")}
          tone="live"
          icon={<Pickaxe size={14} />}
        />
        <Stat
          label="固定奖励"
          value={formatRtm(meta.fees.miningRewardWei)}
          unit="RTM"
          icon={<Trophy size={14} />}
        />
        <Stat
          label="累计攻破"
          numericValue={mining?.settled ?? 0}
          format={(value) => String(Math.round(value))}
          icon={<Skull size={14} />}
        />
        <Stat
          label="平台攻破率"
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
            <p className="mono">PLATFORM-OWNED TARGET</p>
            <h2>没有质押，只有攻击成本</h2>
            <p>
              矿工加入不锁定资金；每条消息固定 0.005 RTM。攻破后平台向 Treasury 补铸 1 RTM，
              胜者拿走 W 余额，hash 永久退役。没有 accrue，也没有随时间累积的奖池。
            </p>
          </div>
        </div>
        <div className="mine-brief__facts">
          <div>
            <span>单条消息</span>
            <strong>{formatRtm(meta.fees.miningFeeWei, { maxFraction: 4 })} RTM</strong>
          </div>
          <div>
            <span>攻破奖励</span>
            <strong>1.000 RTM</strong>
          </div>
          <div>
            <span>活跃上限</span>
            <strong>{meta.limits.maxActiveMining} 场</strong>
          </div>
          <div>
            <span>数据用途</span>
            <strong>仅 RSI 修复</strong>
          </div>
        </div>
      </section>

      <div className="filter-bar">
        <Tabs
          ariaLabel="挖矿赛状态"
          value={tab}
          onChange={setTab}
          items={[
            { id: "live", label: "进行中", count: live.length },
            { id: "all", label: "全部", count: all.length },
            { id: "ended", label: "已结束", count: ended.length },
          ]}
        />
        <div className="filter-bar__right">
          <Badge tone="mining">固定奖励 1 RTM</Badge>
          <Button
            size="sm"
            variant="quiet"
            iconLeft={<RefreshCw size={12} />}
            loading={contestsQuery.isFetching}
            onClick={() => void contestsQuery.refetch()}
          >
            刷新
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
          title={tab === "live" ? "当前没有活跃挖矿赛" : "还没有挖矿记录"}
          description="挖矿赛由平台运营创建（最多 3 场并发）。比赛出现后，这里会显示加入入口与战况。"
          action={
            tab !== "all" ? (
              <Button variant="ghost" size="sm" onClick={() => setTab("all")}>
                查看全部
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
            <p className="eyebrow">Version history / 版本历史</p>
            <h2>已决与退役</h2>
          </div>
          <Badge tone="neutral">{mining?.history.length ?? 0} 条记录</Badge>
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
                    hash {shortAddr(item.defense_hash)} · {item.paid_messages} 条付费消息 ·{" "}
                    {formatDateTime(item.ended_ts)}
                  </span>
                </div>
                <div className="mining-history__winner">
                  <span className="muted small">胜者</span>
                  <span className="mono">{shortAddr(item.winner)}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<History size={22} />}
            title="还没有已决记录"
            description="挖矿赛被攻破或退役后，会记录在这里。"
          />
        )}
      </section>

      <p className="page-note">
        <Badge tone="outline">数据边界</Badge>
        矿工数据强制留存，但只用于防守方智能体的 RSI 修复，不进入 DataMarket、不出售。
      </p>
    </div>
  );
}
