import { useMemo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Crosshair,
  Droplets,
  Pickaxe,
  Radio,
  Shield,
  Swords,
  Trophy,
  Users,
} from "lucide-react";
import { useAccount, useChainId, useSwitchChain } from "wagmi";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { SectionHeader } from "../components/ui/SectionHeader";
import { SkeletonCard } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import { Countdown } from "../components/ui/Countdown";
import { ContestCard } from "../components/contest/ContestCard";
import { ConnectButton } from "../components/wallet/ConnectButton";
import { useToast } from "../context/ToastContext";
import {
  useContestsQuery,
  useLeaderboardsQuery,
  usePlatform,
  useRtmBalance,
} from "../lib/platform";
import { CHAIN_ID, ensureChain, isSupportedChain } from "../lib/chain";
import { contestEndMs } from "../lib/contest";
import { readDefenderRegistration } from "../lib/defender";
import {
  errorText,
  formatInt,
  formatRtm,
  shortAddr,
} from "../lib/format";
import { useNow } from "../lib/hooks";

function StartStep({
  index,
  title,
  description,
  done,
  action,
}: {
  index: number;
  title: string;
  description: string;
  done: boolean;
  action: ReactNode;
}) {
  return (
    <li className={`start-step ${done ? "is-done" : ""}`.trim()}>
      <span className="start-step__index" aria-hidden="true">
        {done ? <Check size={13} /> : String(index).padStart(2, "0")}
      </span>
      <div className="start-step__text">
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <div className="start-step__action">{action}</div>
    </li>
  );
}

function RoleCard({
  index,
  tone,
  icon,
  title,
  en,
  description,
  points,
  to,
  cta,
}: {
  index: string;
  tone: string;
  icon: ReactNode;
  title: string;
  en: string;
  description: string;
  points: string[];
  to: string;
  cta: string;
}) {
  return (
    <Link to={to} className={`role-card role-card--${tone}`}>
      <div className="role-card__top">
        <span className="role-card__index mono">{index}</span>
        <span className="role-card__icon" aria-hidden="true">
          {icon}
        </span>
      </div>
      <p className="role-card__en mono">{en}</p>
      <h3 className="role-card__title">{title}</h3>
      <p className="role-card__description">{description}</p>
      <ul className="role-card__points">
        {points.map((point) => (
          <li key={point}>
            <span className="role-card__tick" aria-hidden="true">+</span>
            {point}
          </li>
        ))}
      </ul>
      <span className="role-card__cta">
        {cta}
        <ArrowUpRight size={14} />
      </span>
    </Link>
  );
}

export default function Overview() {
  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { switchChainAsync } = useSwitchChain();
  const { toast } = useToast();
  const { meta } = usePlatform();
  const contestsQuery = useContestsQuery();
  const boardsQuery = useLeaderboardsQuery();
  const balance = useRtmBalance(address);
  const now = useNow(30_000);
  const registration = useMemo(() => readDefenderRegistration(address), [address]);

  const allContests = contestsQuery.data ?? [];
  const liveContests = useMemo(
    () =>
      allContests
        .filter((contest) => contest.state === "live" && contestEndMs(contest) > now)
        .sort((a, b) => contestEndMs(a) - contestEndMs(b)),
    [allContests, now],
  );
  const normalContests = liveContests.filter((contest) => !contest.is_mining);
  const miningContests = liveContests.filter((contest) => contest.is_mining);
  const totalPool = useMemo(
    () =>
      normalContests.reduce((sum, contest) => {
        try {
          return sum + BigInt(contest.stake);
        } catch {
          return sum;
        }
      }, 0n),
    [normalContests],
  );
  const messages = allContests.reduce((sum, contest) => sum + contest.paid_count, 0);
  const boards = boardsQuery.data;
  const operators =
    (Object.keys(boards?.attackers ?? {}).length +
      Object.keys(boards?.defenders ?? {}).length +
      Object.keys(boards?.miners ?? {}).length) ||
    0;

  const topAttackers = Object.entries(boards?.attackers ?? {})
    .sort((a, b) => b[1].wins - a[1].wins || b[1].difficulty - a[1].difficulty)
    .slice(0, 3);
  const topDefenders = Object.entries(boards?.defenders ?? {})
    .sort((a, b) => b[1].contests_survived - a[1].contests_survived)
    .slice(0, 3);

  const networkReady = isConnected && isSupportedChain(chainId);
  const walletReady = isConnected;
  const funded = Boolean(balance.data && balance.data > 0n);
  const roleReady = Boolean(registration);
  const allReady = walletReady && networkReady && funded && roleReady;

  async function switchNetwork() {
    try {
      await switchChainAsync({ chainId: CHAIN_ID });
    } catch (reason) {
      try {
        await ensureChain();
      } catch {
        toast({ title: "切换网络失败", description: errorText(reason), tone: "error" });
      }
    }
  }

  return (
    <div className="overview">
      <section className="hero">
        <div className="hero__copy">
          <div className="hero__topline">
            <span className="eyebrow">Red team arena / defensive research</span>
            <Badge tone="accent" dot>
              TESTNET LIVE
            </Badge>
          </div>
          <h1 className="hero__title">
            Break the
            <br />
            <em>agent.</em>
          </h1>
          <p className="hero__lede">
            让自主智能体在<strong>真实链上资金</strong>与真实对手之间接受检验。
            守方自带 BYOK 智能体，攻方付费对话，结算由合约完成。
          </p>
          <div className="hero__actions">
            <Link to="/faucet" className="btn btn--primary btn--lg">
              <Droplets size={16} />
              领取测试 RTM
            </Link>
            <Link to="/arena" className="btn btn--secondary btn--lg">
              <Swords size={16} />
              进入竞技场
            </Link>
            <Link to="/defend" className="btn btn--ghost btn--lg">
              注册守方
              <ArrowRight size={15} />
            </Link>
          </div>
          <div className="hero__meta mono">
            <span>CHAIN {meta.chainId}</span>
            <span className="hero__meta-dot" />
            <span>{meta.network.toUpperCase()}</span>
            <span className="hero__meta-dot" />
            <span>ZERO-GAS TESTNET</span>
          </div>
        </div>

        <aside className="field-brief">
          <div className="field-brief__head">
            <div>
              <p className="mono">FIELD BRIEF / 现场简报</p>
              <h2>LIVE OPERATIONS</h2>
            </div>
            <span className="field-brief__stamp" aria-hidden="true">LIVE</span>
          </div>
          <div className="field-brief__stats">
            <Stat
              label="进行中"
              numericValue={liveContests.length}
              format={(value) => String(Math.round(value)).padStart(2, "0")}
              size="lg"
              tone="live"
              icon={<Radio size={14} />}
            />
            <Stat
              label="锁定奖池"
              value={formatRtm(totalPool)}
              unit="RTM"
              size="lg"
              icon={<Swords size={14} />}
            />
            <Stat
              label="付费消息"
              numericValue={messages}
              format={(value) => formatInt(Math.round(value))}
              size="sm"
              icon={<Crosshair size={13} />}
            />
            <Stat
              label="参战地址"
              numericValue={operators}
              format={(value) => formatInt(Math.round(value))}
              size="sm"
              icon={<Users size={13} />}
            />
          </div>

          <div className="field-brief__list">
            <div className="field-brief__list-head">
              <span className="mono">NEXT TO SETTLE</span>
              <span className="mono">{normalContests.length + miningContests.length} LIVE</span>
            </div>
            {liveContests.slice(0, 3).map((contest) => (
              <Link
                key={contest.id}
                to={contest.is_mining ? `/mine/${contest.id}` : `/arena/${contest.id}`}
                className="field-brief__row"
              >
                <span className={`field-brief__dot ${contest.is_mining ? "is-mining" : ""}`} />
                <span className="mono">{contest.id.slice(0, 10)}…</span>
                <span className="field-brief__row-pool">
                  {contest.is_mining ? "1 RTM" : formatRtm(contest.stake)}
                </span>
                <Countdown endMs={contestEndMs(contest)} showIcon={false} />
              </Link>
            ))}
            {liveContests.length === 0 && (
              <p className="field-brief__empty">
                {contestsQuery.isLoading ? "正在读取链上战场…" : "当前没有进行中的战斗。"}
              </p>
            )}
          </div>
          <div className="field-brief__foot mono">
            <span>AUTO REFRESH · 12S</span>
            <span className="status-dot is-live" />
          </div>
        </aside>
      </section>

      <section className={`start-panel ${allReady ? "is-ready" : ""}`.trim()}>
        <div className="start-panel__head">
          <div>
            <p className="eyebrow">Start sequence / 入门序列</p>
            <h2>四步进入战场</h2>
          </div>
          {allReady ? (
            <span className="ready-stamp">READY</span>
          ) : (
            <span className="start-panel__progress mono">
              {[walletReady, networkReady, funded, roleReady].filter(Boolean).length} / 4
            </span>
          )}
        </div>
        <ol className="start-steps">
          <StartStep
            index={1}
            title="连接钱包"
            description="MetaMask / Rabby 等注入式钱包"
            done={walletReady}
            action={walletReady ? <Badge tone="success">已连接</Badge> : <ConnectButton size="sm" label="连接" />}
          />
          <StartStep
            index={2}
            title="切换测试网"
            description={`RTM Testnet · ${CHAIN_ID}`}
            done={networkReady}
            action={
              networkReady ? (
                <Badge tone="success">已就绪</Badge>
              ) : (
                <Button size="sm" variant="secondary" onClick={() => void switchNetwork()}>
                  切换网络
                </Button>
              )
            }
          />
          <StartStep
            index={3}
            title="领取测试 RTM"
            description="每 24 小时 200 RTM，测试资产无价值"
            done={funded}
            action={
              funded ? (
                <Badge tone="success">{formatRtm(balance.data)} RTM</Badge>
              ) : (
                <Link to="/faucet" className="btn btn--ghost btn--sm">
                  去领水
                </Link>
              )
            }
          />
          <StartStep
            index={4}
            title="选择你的角色"
            description="守方、攻方或矿工，随时可以切换"
            done={roleReady}
            action={
              roleReady ? (
                <Badge tone="success">守方已注册</Badge>
              ) : (
                <Link to="/defend" className="btn btn--ghost btn--sm">
                  选择角色
                </Link>
              )
            }
          />
        </ol>
      </section>

      <section className="section">
        <SectionHeader
          eyebrow="Choose your seat / 选择席位"
          title="三种角色，同一套链上规则"
          description="你可以同时是守方、攻方和矿工。所有结算由 Arena 合约执行，平台只负责托管与索引。"
        />
        <div className="role-grid">
          <RoleCard
            index="01"
            tone="defender"
            icon={<Shield size={19} />}
            title="守方"
            en="DEFENDER"
            description="自带 BYOK 智能体与授权书，通过资格测试后质押开赛。"
            points={["一次注册创建一场普通赛", "承受攻击消息的 0.5% 罚款", "购买赛后数据做修复"]}
            to="/defend"
            cta="进入守方计划"
          />
          <RoleCard
            index="02"
            tone="attacker"
            icon={<Swords size={19} />}
            title="攻方"
            en="ATTACKER"
            description="质押加入战场，为每条消息付费，诱导智能体转出真实资金。"
            points={["赢家拿走 W 余额与奖池", "消息费 = 守方质押 × 0.5%", "数据同意在加入后锁定"]}
            to="/arena"
            cta="进入竞技场"
          />
          <RoleCard
            index="03"
            tone="miner"
            icon={<Pickaxe size={19} />}
            title="矿工"
            en="MINER"
            description="无质押挑战平台自持智能体，每次攻破固定 1 RTM。"
            points={["每条消息 0.005 RTM", "数据仅用于 RSI 修复", "攻破后 hash 永久退役"]}
            to="/mine"
            cta="进入挖矿中心"
          />
        </div>
      </section>

      <section className="section">
        <SectionHeader
          eyebrow="Live operations / 正在发生"
          title="正在进行的战斗"
          actions={
            <Link to="/arena" className="btn btn--ghost btn--sm">
              查看全部
              <ArrowUpRight size={13} />
            </Link>
          }
        />
        {contestsQuery.isLoading ? (
          <div className="contest-grid">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : contestsQuery.isError ? (
          <EmptyState
            title="无法读取战场列表"
            description="平台 API 或索引器暂时不可用。钱包与水龙头仍然可用。"
            action={
              <Button variant="ghost" onClick={() => void contestsQuery.refetch()}>
                重试
              </Button>
            }
          />
        ) : liveContests.length === 0 ? (
          <EmptyState
            title="当前没有进行中的战斗"
            description="守方注册并创建比赛后，战场会出现在这里。"
            action={
              <Link to="/defend" className="btn btn--primary btn--sm">
                去注册守方
              </Link>
            }
          />
        ) : (
          <div className="contest-grid">
            {liveContests.slice(0, 3).map((contest, index) => (
              <ContestCard key={contest.id} contest={contest} index={index} />
            ))}
          </div>
        )}
      </section>

      <section className="section overview-bottom">
        <article className="panel panel--bracket pulse-panel">
          <div className="panel__head">
            <div className="panel__head-text">
              <p className="panel__eyebrow">Leaderboard pulse</p>
              <h2 className="panel__title">谁在制定规则</h2>
            </div>
            <Trophy size={18} className="muted" />
          </div>
          <div className="pulse-columns">
            <div>
              <p className="pulse-title mono">TOP ATTACKERS / 攻方</p>
              {topAttackers.length === 0 ? (
                <p className="muted small">还没有攻方记录。</p>
              ) : (
                <ol className="pulse-list">
                  {topAttackers.map(([who, entry], index) => (
                    <li key={who}>
                      <span className="pulse-rank">{index + 1}</span>
                      <span className="mono">{shortAddr(who)}</span>
                      <span>{entry.wins} 胜</span>
                      <span className="muted mono">{formatRtm(entry.rtm_won)} RTM</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            <div>
              <p className="pulse-title mono">TOP DEFENDERS / 守方</p>
              {topDefenders.length === 0 ? (
                <p className="muted small">还没有守方记录。</p>
              ) : (
                <ol className="pulse-list">
                  {topDefenders.map(([who, entry], index) => (
                    <li key={who}>
                      <span className="pulse-rank">{index + 1}</span>
                      <span className="mono">{shortAddr(who)}</span>
                      <span>{entry.contests_survived} 场守住</span>
                      <span className="muted mono">{formatRtm(entry.net_income)} RTM</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
          <Link to="/leaderboard" className="panel__inline-link">
            打开完整排行榜
            <ArrowRight size={13} />
          </Link>
        </article>

        <article className="panel panel--bracket loop-panel">
          <div className="panel__head">
            <div className="panel__head-text">
              <p className="panel__eyebrow">Engagement loop</p>
              <h2 className="panel__title">从付费到结算</h2>
            </div>
          </div>
          <ol className="loop-steps">
            <li>
              <span className="mono">01</span>
              <div>
                <strong>加入 or 开赛</strong>
                <p>守方质押；攻方按 bps 质押；矿工无质押。</p>
              </div>
            </li>
            <li>
              <span className="mono">02</span>
              <div>
                <strong>付费对话</strong>
                <p>每条消息先上链付费，再由平台运行智能体。</p>
              </div>
            </li>
            <li>
              <span className="mono">03</span>
              <div>
                <strong>触发结算</strong>
                <p>W 向登记攻方转账即触发原子结算；到期则 expire。</p>
              </div>
            </li>
            <li>
              <span className="mono">04</span>
              <div>
                <strong>数据修复</strong>
                <p>同意出售的数据进入市场；矿工数据只进 RSI。</p>
              </div>
            </li>
          </ol>
          <p className="loop-panel__note">
            结算全部由合约完成。平台不保管用户私钥，也不能替任意一方签名。
          </p>
        </article>
      </section>

      <section className="testnet-note">
        <Crosshair size={15} />
        <p>
          这是 <strong>{meta.network}</strong>（chainId {meta.chainId}）测试环境，资产无价值。
          所有对话只用于防御性安全研究，不要提交真实密钥、个人信息或生产数据。
        </p>
        <span className="mono">RTM/48850</span>
      </section>
    </div>
  );
}
