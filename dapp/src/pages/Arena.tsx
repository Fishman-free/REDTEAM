import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Crosshair, MessageSquare, Search, Shield, Swords, Timer } from "lucide-react";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { SectionHeader } from "../components/ui/SectionHeader";
import { SkeletonCard } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import { Tabs } from "../components/ui/Tabs";
import { ContestCard } from "../components/contest/ContestCard";
import { useContestsQuery } from "../lib/platform";
import { contestEndMs } from "../lib/contest";
import { formatInt, formatRtm } from "../lib/format";
import { useDebouncedValue } from "../lib/hooks";

type ArenaTab = "live" | "all" | "ended";
type SortMode = "ending" | "newest" | "pool";

export default function Arena() {
  const contestsQuery = useContestsQuery();
  const [tab, setTab] = useState<ArenaTab>("live");
  const [sort, setSort] = useState<SortMode>("ending");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 220);

  const all = useMemo(
    () => (contestsQuery.data ?? []).filter((contest) => !contest.is_mining),
    [contestsQuery.data],
  );

  const live = useMemo(
    () => all.filter((contest) => contest.state === "live"),
    [all],
  );
  const ended = useMemo(
    () => all.filter((contest) => contest.state !== "live"),
    [all],
  );

  const stats = useMemo(() => {
    const pool = live.reduce((sum, contest) => {
      try {
        return sum + BigInt(contest.stake);
      } catch {
        return sum;
      }
    }, 0n);
    const messages = all.reduce((sum, contest) => sum + contest.paid_count, 0);
    const defenders = new Set(all.map((contest) => contest.defender.toLowerCase())).size;
    return { pool, messages, defenders };
  }, [all, live]);

  const filtered = useMemo(() => {
    const needle = debouncedSearch.trim().toLowerCase();
    const source = tab === "live" ? live : tab === "ended" ? ended : all;
    const matched = needle
      ? source.filter(
          (contest) =>
            contest.id.toLowerCase().includes(needle) ||
            contest.defender.toLowerCase().includes(needle) ||
            contest.wallet.toLowerCase().includes(needle),
        )
      : source;

    return [...matched].sort((a, b) => {
      if (sort === "newest") return b.start_ts - a.start_ts;
      if (sort === "ending") {
        const aEnd = contestEndMs(a);
        const bEnd = contestEndMs(b);
        const aLive = a.state === "live" ? 0 : 1;
        const bLive = b.state === "live" ? 0 : 1;
        if (aLive !== bLive) return aLive - bLive;
        return aEnd - bEnd;
      }
      try {
        const diff = BigInt(b.stake) - BigInt(a.stake);
        return diff > 0n ? 1 : diff < 0n ? -1 : 0;
      } catch {
        return 0;
      }
    });
  }, [all, debouncedSearch, ended, live, sort, tab]);

  return (
    <div className="arena-page">
      <SectionHeader
        eyebrow="The arena / 普通赛"
        title={
          <>
            付费进攻，<em>拿下奖池</em>
          </>
        }
        description="选择一场进行中的普通赛，质押加入，然后为每条消息付费。攻破守方智能体后，W 余额会按合约规则结算。"
        actions={
          <Link to="/faucet" className="btn btn--ghost btn--sm">
            需要 RTM？
          </Link>
        }
      />

      <div className="stat-strip">
        <Stat
          label="进行中"
          numericValue={live.length}
          format={(value) => String(Math.round(value)).padStart(2, "0")}
          tone="live"
          icon={<Swords size={14} />}
        />
        <Stat
          label="锁定奖池"
          value={formatRtm(stats.pool)}
          unit="RTM"
          icon={<Shield size={14} />}
        />
        <Stat
          label="付费消息"
          numericValue={stats.messages}
          format={(value) => formatInt(Math.round(value))}
          icon={<MessageSquare size={14} />}
        />
        <Stat
          label="守方地址"
          numericValue={stats.defenders}
          format={(value) => formatInt(Math.round(value))}
          icon={<Crosshair size={14} />}
        />
      </div>

      <section className="arena-brief">
        <div className="arena-brief__item">
          <span className="mono">01</span>
          <div>
            <strong>先质押，再对话</strong>
            <p>攻方质押 = 守方质押 × stakeBps，加入时锁定。</p>
          </div>
        </div>
        <div className="arena-brief__item">
          <span className="mono">02</span>
          <div>
            <strong>每条消息都上链</strong>
            <p>消息费 = S × 0.5%，付款被索引后才运行智能体。</p>
          </div>
        </div>
        <div className="arena-brief__item">
          <span className="mono">03</span>
          <div>
            <strong>数据同意不可撤回</strong>
            <p>同意出售的数据赛后进入市场，平台 70% / 你 30%。</p>
          </div>
        </div>
      </section>

      <div className="filter-bar">
        <Tabs
          ariaLabel="比赛状态"
          value={tab}
          onChange={(value) => setTab(value)}
          items={[
            { id: "live", label: "进行中", count: live.length },
            { id: "all", label: "全部", count: all.length },
            { id: "ended", label: "已结束", count: ended.length },
          ]}
        />
        <div className="filter-bar__right">
          <label className="search-box">
            <Search size={14} aria-hidden="true" />
            <span className="sr-only">搜索比赛</span>
            <input
              className="search-box__input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索 ID / 守方地址"
            />
          </label>
          <label className="sort-box">
            <Timer size={13} aria-hidden="true" />
            <span className="sr-only">排序方式</span>
            <select
              className="sort-box__select"
              value={sort}
              onChange={(event) => setSort(event.target.value as SortMode)}
            >
              <option value="ending">最快结束</option>
              <option value="newest">最新创建</option>
              <option value="pool">奖池最大</option>
            </select>
          </label>
          <Button
            size="sm"
            variant="quiet"
            onClick={() => void contestsQuery.refetch()}
            loading={contestsQuery.isFetching}
          >
            刷新
          </Button>
        </div>
      </div>

      {contestsQuery.isError && (
        <Alert tone="error" title="无法读取战场">
          平台 API 或索引器暂时不可用。请检查服务端，或稍后重试。
        </Alert>
      )}

      {contestsQuery.isLoading ? (
        <div className="contest-grid">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title={search ? "没有匹配的比赛" : tab === "live" ? "当前没有进行中的比赛" : "还没有比赛"}
          description={
            search
              ? "试试缩短搜索词，或切换到“全部”。"
              : "守方注册并创建比赛后，战场会出现在这里。"
          }
          action={
            tab !== "all" ? (
              <Button variant="ghost" size="sm" onClick={() => setTab("all")}>
                查看全部比赛
              </Button>
            ) : (
              <Link className="btn btn--ghost btn--sm" to="/defend">
                去注册守方
              </Link>
            )
          }
        />
      ) : (
        <>
          <div className="results-meta">
            <span className="mono">{filtered.length} RESULTS</span>
            <span>{tab === "live" ? "仅显示状态为 live 的比赛" : "包含历史与待结算比赛"}</span>
            <Badge tone="neutral">数据每 12 秒刷新</Badge>
          </div>
          <div className="contest-grid">
            {filtered.map((contest, index) => (
              <ContestCard key={contest.id} contest={contest} index={index} />
            ))}
          </div>
        </>
      )}

      <p className="page-note">
        <Badge tone="outline">注意</Badge>
        攻方质押、消息费与罚款在加入后按链上时间衰减。到期但状态仍为 live 的比赛，任何地址都可以调用
        <code> expire</code> 结算。
      </p>
    </div>
  );
}
