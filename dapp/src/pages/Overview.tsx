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
import { useAccount, useSwitchChain } from "wagmi";
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
import { useWalletChainId } from "../lib/useWalletChainId";
import { contestEndMs } from "../lib/contest";
import { readDefenderRegistration } from "../lib/defender";
import {
  errorText,
  formatInt,
  formatRtm,
  shortAddr,
} from "../lib/format";
import { useI18n } from "../lib/i18n";
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
  const chainId = useWalletChainId();
  const { switchChainAsync } = useSwitchChain();
  const { toast } = useToast();
  const { t } = useI18n();
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
        toast({
          title: t("Network switch failed", "切换网络失败"),
          description: errorText(reason),
          tone: "error",
        });
      }
    }
  }

  return (
    <div className="overview">
      <section className="hero">
        <div className="hero__copy">
          <div className="hero__topline">
            <span className="eyebrow">
              {t("Red team arena / defensive research", "红队竞技场 / 防御研究")}
            </span>
            <Badge tone="accent" dot>
              {t("TESTNET LIVE", "测试网运行中")}
            </Badge>
          </div>
          <h1 className="hero__title">
            <span className="hero__break">Break the</span>
            <br />
            <em>agent.</em>
          </h1>
          <p className="hero__lede">
            {t("Put autonomous agents to the test against ", "让自主 agent 在")}
            <strong>{t("real on-chain funds", "真实链上资金")}</strong>
            {t(
              " and real adversaries. Defenders bring their own BYOK agents, attackers pay per message, and the contracts settle every contest.",
              "与真实对手之间接受检验。守方自带 BYOK agent，攻方付费对话，结算由合约完成。",
            )}
          </p>
          <div className="hero__actions">
            <Link to="/faucet" className="btn btn--primary btn--lg">
              <Droplets size={16} />
              {t("Get test tRTM", "领取测试 tRTM")}
            </Link>
            <Link to="/arena" className="btn btn--secondary btn--lg">
              <Swords size={16} />
              {t("Enter the arena", "进入竞技场")}
            </Link>
            <Link to="/defend" className="btn btn--ghost btn--lg">
              {t("Register as defender", "注册守方")}
              <ArrowRight size={15} />
            </Link>
          </div>
          <div className="hero__meta mono">
            <span>{t("CHAIN", "链")} {meta.chainId}</span>
            <span className="hero__meta-dot" />
            <span>{meta.network.toUpperCase()}</span>
            <span className="hero__meta-dot" />
            <span>{t("ZERO-GAS TESTNET", "零 gas 测试网")}</span>
          </div>
        </div>

        <aside className="field-brief">
          <div className="field-brief__head">
            <div>
              <p className="mono">{t("FIELD BRIEF", "现场简报")}</p>
              <h2>{t("LIVE OPERATIONS", "实时战况")}</h2>
            </div>
            <span className="field-brief__stamp" aria-hidden="true">
              {t("LIVE", "实时")}
            </span>
          </div>
          <div className="field-brief__stats">
            <Stat
              label={t("Live", "进行中")}
              numericValue={liveContests.length}
              format={(value) => String(Math.round(value)).padStart(2, "0")}
              size="lg"
              tone="live"
              icon={<Radio size={14} />}
            />
            <Stat
              label={t("Locked pool", "锁定奖池")}
              value={formatRtm(totalPool)}
              unit="tRTM"
              size="lg"
              icon={<Swords size={14} />}
            />
            <Stat
              label={t("Paid messages", "付费消息")}
              numericValue={messages}
              format={(value) => formatInt(Math.round(value))}
              size="sm"
              icon={<Crosshair size={13} />}
            />
            <Stat
              label={t("Active addresses", "参战地址")}
              numericValue={operators}
              format={(value) => formatInt(Math.round(value))}
              size="sm"
              icon={<Users size={13} />}
            />
          </div>

          <div className="field-brief__list">
            <div className="field-brief__list-head">
              <span className="mono">{t("NEXT TO SETTLE", "即将结算")}</span>
              <span className="mono">
                {normalContests.length + miningContests.length} {t("LIVE", "场进行中")}
              </span>
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
                  {contest.is_mining ? "1 tRTM" : formatRtm(contest.stake)}
                </span>
                <Countdown endMs={contestEndMs(contest)} showIcon={false} />
              </Link>
            ))}
            {liveContests.length === 0 && (
              <p className="field-brief__empty">
                {contestsQuery.isLoading
                  ? t("Reading the on-chain battlefield…", "正在读取链上战场…")
                  : t("No live battles right now.", "当前没有进行中的战斗。")}
              </p>
            )}
          </div>
          <div className="field-brief__foot mono">
            <span>{t("AUTO REFRESH · 12S", "自动刷新 · 12S")}</span>
            <span className="status-dot is-live" />
          </div>
        </aside>
      </section>

      <section className={`start-panel ${allReady ? "is-ready" : ""}`.trim()}>
        <div className="start-panel__head">
          <div>
            <p className="eyebrow">{t("Start sequence", "入门序列")}</p>
            <h2>{t("Four steps into the field", "四步进入战场")}</h2>
          </div>
          {allReady ? (
            <span className="ready-stamp">{t("READY", "就绪")}</span>
          ) : (
            <span className="start-panel__progress mono">
              {[walletReady, networkReady, funded, roleReady].filter(Boolean).length} / 4
            </span>
          )}
        </div>
        <ol className="start-steps">
          <StartStep
            index={1}
            title={t("Connect a wallet", "连接钱包")}
            description={t(
              "MetaMask / Rabby or any injected wallet",
              "MetaMask / Rabby 等注入式钱包",
            )}
            done={walletReady}
            action={
              walletReady ? (
                <Badge tone="success">{t("Connected", "已连接")}</Badge>
              ) : (
                <ConnectButton size="sm" label={t("Connect", "连接")} />
              )
            }
          />
          <StartStep
            index={2}
            title={t("Switch to testnet", "切换测试网")}
            description={`RTM Testnet · ${CHAIN_ID}`}
            done={networkReady}
            action={
              networkReady ? (
                <Badge tone="success">{t("Ready", "已就绪")}</Badge>
              ) : (
                <Button size="sm" variant="secondary" onClick={() => void switchNetwork()}>
                  {t("Switch network", "切换网络")}
                </Button>
              )
            }
          />
          <StartStep
            index={3}
            title={t("Get test tRTM", "领取测试 tRTM")}
            description={t(
              "200 tRTM every 24 hours. Test assets have no value.",
              "每 24 小时 200 tRTM，测试资产无价值",
            )}
            done={funded}
            action={
              funded ? (
                <Badge tone="success">{formatRtm(balance.data)} tRTM</Badge>
              ) : (
                <Link to="/faucet" className="btn btn--ghost btn--sm">
                  {t("Open faucet", "去领水")}
                </Link>
              )
            }
          />
          <StartStep
            index={4}
            title={t("Choose your role", "选择你的角色")}
            description={t(
              "Defender, attacker or miner — switch anytime",
              "守方、攻方或矿工，随时可以切换",
            )}
            done={roleReady}
            action={
              roleReady ? (
                <Badge tone="success">{t("Defender registered", "守方已注册")}</Badge>
              ) : (
                <Link to="/defend" className="btn btn--ghost btn--sm">
                  {t("Choose role", "选择角色")}
                </Link>
              )
            }
          />
        </ol>
      </section>

      <section className="section">
        <SectionHeader
          eyebrow={t("Choose your seat", "选择席位")}
          title={t("Three roles, one set of on-chain rules", "三种角色，同一套链上规则")}
          description={t(
            "You can be a defender, an attacker and a miner at the same time. Every settlement is executed by the Arena contract; the platform only hosts and indexes.",
            "你可以同时是守方、攻方和矿工。所有结算由 Arena 合约执行，平台只负责托管与索引。",
          )}
        />
        <div className="role-grid">
          <RoleCard
            index="01"
            tone="defender"
            icon={<Shield size={19} />}
            title={t("Defender", "守方")}
            en="DEFENDER"
            description={t(
              "Bring your own BYOK agent and authorization, pass qualification, then stake to open a contest.",
              "自带 BYOK agent 与授权书，通过资格测试后质押开赛。",
            )}
            points={[
              t("One registration creates one standard contest", "一次注册创建一场普通赛"),
              t("Face a 0.5% penalty on every attack message", "承受攻击消息的 0.5% 罚款"),
              t("Buy post-contest data for remediation", "购买赛后数据做修复"),
            ]}
            to="/defend"
            cta={t("Enter the defender program", "进入守方计划")}
          />
          <RoleCard
            index="02"
            tone="attacker"
            icon={<Swords size={19} />}
            title={t("Attacker", "攻方")}
            en="ATTACKER"
            description={t(
              "Stake to enter the field, pay for every message, and lure the agent into moving real funds.",
              "质押加入战场，为每条消息付费，诱导 agent 转出真实资金。",
            )}
            points={[
              t("The winner takes the W balance and the pool", "赢家拿走 W 余额与奖池"),
              t("Message fee = 0.5% of defender stake", "消息费 = 守方质押 × 0.5%"),
              t("Data consent locks once you join", "数据同意在加入后锁定"),
            ]}
            to="/arena"
            cta={t("Enter the arena", "进入竞技场")}
          />
          <RoleCard
            index="03"
            tone="miner"
            icon={<Pickaxe size={19} />}
            title={t("Miner", "矿工")}
            en="MINER"
            description={t(
              "Challenge platform-owned agents with no stake and earn a fixed 1 tRTM per breach.",
              "无质押挑战平台自持 agent，每次攻破固定 1 tRTM。",
            )}
            points={[
              t("0.005 tRTM per message", "每条消息 0.005 tRTM"),
              t("Data is used only for RSI remediation", "数据仅用于 RSI 修复"),
              t("The hash is permanently retired after a breach", "攻破后 hash 永久退役"),
            ]}
            to="/mine"
            cta={t("Enter the mining hub", "进入挖矿中心")}
          />
        </div>
      </section>

      <section className="section">
        <SectionHeader
          eyebrow={t("Live operations", "正在发生")}
          title={t("Live battles", "正在进行的战斗")}
          actions={
            <Link to="/arena" className="btn btn--ghost btn--sm">
              {t("View all", "查看全部")}
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
            title={t("Could not load battles", "无法读取战场列表")}
            description={t(
              "The platform API or indexer is temporarily unavailable. Your wallet and the faucet still work.",
              "平台 API 或索引器暂时不可用。钱包与水龙头仍然可用。",
            )}
            action={
              <Button variant="ghost" onClick={() => void contestsQuery.refetch()}>
                {t("Retry", "重试")}
              </Button>
            }
          />
        ) : liveContests.length === 0 ? (
          <EmptyState
            title={t("No live battles right now", "当前没有进行中的战斗")}
            description={t(
              "Battles appear here once a defender registers and creates a contest.",
              "守方注册并创建比赛后，战场会出现在这里。",
            )}
            action={
              <Link to="/defend" className="btn btn--primary btn--sm">
                {t("Register a defender", "去注册守方")}
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
              <p className="panel__eyebrow">{t("Leaderboard pulse", "排行榜动态")}</p>
              <h2 className="panel__title">{t("Who sets the rules", "谁在制定规则")}</h2>
            </div>
            <Trophy size={18} className="muted" />
          </div>
          <div className="pulse-columns">
            <div>
              <p className="pulse-title mono">{t("TOP ATTACKERS", "攻方榜")}</p>
              {topAttackers.length === 0 ? (
                <p className="muted small">{t("No attacker records yet.", "还没有攻方记录。")}</p>
              ) : (
                <ol className="pulse-list">
                  {topAttackers.map(([who, entry], index) => (
                    <li key={who}>
                      <span className="pulse-rank">{index + 1}</span>
                      <span className="mono">{shortAddr(who)}</span>
                      <span>
                        {entry.wins} {t(entry.wins === 1 ? "win" : "wins", "胜")}
                      </span>
                      <span className="muted mono">{formatRtm(entry.rtm_won)} tRTM</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            <div>
              <p className="pulse-title mono">{t("TOP DEFENDERS", "守方榜")}</p>
              {topDefenders.length === 0 ? (
                <p className="muted small">{t("No defender records yet.", "还没有守方记录。")}</p>
              ) : (
                <ol className="pulse-list">
                  {topDefenders.map(([who, entry], index) => (
                    <li key={who}>
                      <span className="pulse-rank">{index + 1}</span>
                      <span className="mono">{shortAddr(who)}</span>
                      <span>
                        {entry.contests_survived}{" "}
                        {t(
                          entry.contests_survived === 1 ? "contest held" : "contests held",
                          "场守住",
                        )}
                      </span>
                      <span className="muted mono">{formatRtm(entry.net_income)} tRTM</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
          <Link to="/leaderboard" className="panel__inline-link">
            {t("Open the full leaderboard", "打开完整排行榜")}
            <ArrowRight size={13} />
          </Link>
        </article>

        <article className="panel panel--bracket loop-panel">
          <div className="panel__head">
            <div className="panel__head-text">
              <p className="panel__eyebrow">{t("Engagement loop", "参与闭环")}</p>
              <h2 className="panel__title">{t("From payment to settlement", "从付费到结算")}</h2>
            </div>
          </div>
          <ol className="loop-steps">
            <li>
              <span className="mono">01</span>
              <div>
                <strong>{t("Join or open a contest", "加入或开赛")}</strong>
                <p>
                  {t(
                    "Defenders stake; attackers stake by bps; miners need no stake.",
                    "守方质押；攻方按 bps 质押；矿工无质押。",
                  )}
                </p>
              </div>
            </li>
            <li>
              <span className="mono">02</span>
              <div>
                <strong>{t("Paid conversation", "付费对话")}</strong>
                <p>
                  {t(
                    "Each message is paid on-chain before the platform runs the agent.",
                    "每条消息先上链付费，再由平台运行 agent。",
                  )}
                </p>
              </div>
            </li>
            <li>
              <span className="mono">03</span>
              <div>
                <strong>{t("Trigger settlement", "触发结算")}</strong>
                <p>
                  {t(
                    "A transfer from W to a registered attacker triggers atomic settlement; expiry ends the contest.",
                    "W 向登记攻方转账即触发原子结算；到期则 expire。",
                  )}
                </p>
              </div>
            </li>
            <li>
              <span className="mono">04</span>
              <div>
                <strong>{t("Data remediation", "数据修复")}</strong>
                <p>
                  {t(
                    "Opted-in data goes to the market; mining data only feeds RSI.",
                    "同意出售的数据进入市场；矿工数据只进 RSI。",
                  )}
                </p>
              </div>
            </li>
          </ol>
          <p className="loop-panel__note">
            {t(
              "All settlement is executed by contracts. The platform never holds user private keys and cannot sign for either side.",
              "结算全部由合约完成。平台不保管用户私钥，也不能替任意一方签名。",
            )}
          </p>
        </article>
      </section>

      <section className="testnet-note">
        <Crosshair size={15} />
        <p>
          {t("This is the ", "这是 ")}
          <strong>{meta.network}</strong>
          {t(
            ` test environment (chainId ${meta.chainId}). Assets have no value. All conversations are used for defensive security research only; never submit real keys, personal data or production data.`,
            `（chainId ${meta.chainId}）测试环境，资产无价值。所有对话只用于防御性安全研究，不要提交真实密钥、个人信息或生产数据。`,
          )}
        </p>
        <span className="mono">tRTM/48850</span>
      </section>
    </div>
  );
}
