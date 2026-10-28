import { useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  Infinity as InfinityIcon,
  Banknote,
  CheckCircle2,
  Coins,
  Crosshair,
  Flag,
  Gavel,
  MessageSquare,
  Pickaxe,
  RefreshCw,
  Shield,
  Skull,
  Swords,
  Timer,
  Trophy,
  Wallet,
} from "lucide-react";
import { formatEther, type Address } from "viem";
import { useAccount, useChainId, useWriteContract } from "wagmi";
import { api } from "../lib/api";
import {
  attackFeeWei,
  contestEndMs,
  contestProgress,
  isContestLive,
  needsExpire,
  requiredStakeWei,
} from "../lib/contest";
import { arenaAbi, rtmAbi } from "../lib/contracts";
import {
  errorText,
  formatDateTime,
  formatRtm,
  formatRtmUnit,
  stateLabel,
} from "../lib/format";
import { useNow } from "../lib/hooks";
import {
  useAllowance,
  useContestQuery,
  useDataConsent,
  useIsAttacker,
  usePlatform,
  useRemainingStake,
  useRtmBalance,
} from "../lib/platform";
import { isSupportedChain } from "../lib/chain";
import { useActivity } from "../context/ActivityContext";
import { useToast } from "../context/ToastContext";
import { AddressChip, CopyButton } from "../components/ui/Address";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { CheckboxField } from "../components/ui/Field";
import { Countdown } from "../components/ui/Countdown";
import { Dialog } from "../components/ui/Dialog";
import { EmptyState } from "../components/ui/EmptyState";
import { Panel } from "../components/ui/Panel";
import { Progress } from "../components/ui/Progress";
import { Skeleton, SkeletonText } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import { ContestStatusBadge } from "../components/contest/ContestStatusBadge";
import { PaidChat } from "../components/contest/PaidChat";
import { ConnectPrompt } from "../components/wallet/ConnectPrompt";

interface ContestDetailProps {
  mode: "arena" | "mine";
}

function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="info-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="detail-loading">
      <Skeleton width={90} height={12} />
      <Skeleton width="52%" height={42} />
      <SkeletonText lines={2} />
      <div className="stat-strip">
        <Skeleton height={78} />
        <Skeleton height={78} />
        <Skeleton height={78} />
        <Skeleton height={78} />
      </div>
      <div className="detail-grid">
        <Skeleton height={280} />
        <Skeleton height={280} />
      </div>
    </div>
  );
}

export default function ContestDetail({ mode }: ContestDetailProps) {
  const { contestId } = useParams();
  const query = useContestQuery(contestId);
  const contest = query.data?.contest;
  const detail = query.data;
  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { meta } = usePlatform();
  const { writeContractAsync } = useWriteContract();
  const { trackTransaction } = useActivity();
  const { toast } = useToast();
  const now = useNow(1_000);
  const isAttacker = useIsAttacker(contestId, address);
  const remaining = useRemainingStake(contestId, address);
  const consent = useDataConsent(contestId, address);
  const allowance = useAllowance(address, meta.addresses.arena);
  const balance = useRtmBalance(address);
  const [joinOpen, setJoinOpen] = useState(false);
  const [miningIntent, setMiningIntent] = useState<string | null>(null);
  const [miningOpen, setMiningOpen] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [consentChoice, setConsentChoice] = useState<boolean | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [joinPending, setJoinPending] = useState(false);
  const [joinError, setJoinError] = useState("");
  const [actionPending, setActionPending] = useState("");
  const [actionError, setActionError] = useState("");
  const [miningPreparing, setMiningPreparing] = useState(false);

  const attackerInfo = useMemo(() => {
    if (!address || !detail) return undefined;
    return Object.entries(detail.attackers).find(
      ([who]) => who.toLowerCase() === address.toLowerCase(),
    )?.[1];
  }, [address, detail]);

  const joined = Boolean(isAttacker.data) || Boolean(attackerInfo);
  const isDefender =
    Boolean(address) && Boolean(contest) &&
    contest!.defender.toLowerCase() === address!.toLowerCase();
  const correctChain = isSupportedChain(chainId);
  const live = contest ? isContestLive(contest, now) : false;
  const fee = contest ? attackFeeWei(contest, meta) : 0n;
  const stake = contest ? requiredStakeWei(contest) : 0n;
  const endMs = contest ? contestEndMs(contest) : 0;
  const progress = contest ? contestProgress(contest, now) : 0;
  const settleNeeded = contest ? needsExpire(contest, now) : false;
  const canSettle = settleNeeded && !contest?.is_mining;
  const positionStake = remaining.data ?? attackerInfo?.stake;
  const positionConsent = consent.data ?? attackerInfo?.data_consent ?? null;
  const isMining = Boolean(contest?.is_mining);

  if (query.isLoading) return <LoadingState />;

  if (query.isError || !contest || !detail) {
    return (
      <EmptyState
        title="找不到这场战斗"
        description="比赛可能尚未被索引，或链接有误。等索引器同步后再试。"
        action={
          <div className="row-actions">
            <Link className="btn btn--ghost btn--sm" to={mode === "mine" ? "/mine" : "/arena"}>
              <ArrowLeft size={13} />
              返回列表
            </Link>
            <Button size="sm" onClick={() => void query.refetch()}>
              重试
            </Button>
          </div>
        }
      />
    );
  }

  const backTo = mode === "mine" || isMining ? "/mine" : "/arena";
  const backLabel = mode === "mine" || isMining ? "挖矿中心" : "竞技场";

  function openJoin() {
    setConsentChoice(null);
    setAcknowledged(false);
    setJoinError("");
    setJoinOpen(true);
  }

  async function confirmJoin(dataConsent: boolean) {
    if (!contest || !address) return;
    setJoinPending(true);
    setJoinError("");
    try {
      const required = requiredStakeWei(contest);
      const intent = await api.joinIntent(contest.id, {
        max_stake: formatEther(required),
        data_consent: dataConsent,
      });
      const approveAmount = BigInt(intent.approve.amount);
      if ((allowance.data ?? 0n) < approveAmount) {
        const approvalHash = await writeContractAsync({
          address: meta.addresses.rtm as Address,
          abi: rtmAbi,
          functionName: "approve",
          args: [intent.approve.spender as Address, approveAmount],
        });
        await trackTransaction(approvalHash, "授权攻方质押", "approve");
      }
      const joinHash = await writeContractAsync({
        address: meta.addresses.arena as Address,
        abi: arenaAbi,
        functionName: "join",
        args: [
          contest.id as `0x${string}`,
          BigInt(intent.args[1]),
          intent.args[2],
        ],
      });
      await trackTransaction(joinHash, "加入战场", "join");
      toast({
        title: "已加入战场",
        description: dataConsent
          ? "你同意了赛后数据出售（平台 70% / 你 30%）。"
          : "你选择了不落盘；对话不可出售。",
        tone: "success",
      });
      setJoinOpen(false);
      await Promise.all([
        query.refetch(),
        isAttacker.refetch(),
        remaining.refetch(),
        allowance.refetch(),
      ]);
    } catch (reason) {
      setJoinError(errorText(reason));
    } finally {
      setJoinPending(false);
    }
  }

  async function prepareMiningJoin() {
    if (!contest) return;
    setMiningPreparing(true);
    setActionError("");
    setJoinError("");
    try {
      const intent = await api.miningJoinIntent(contest.id);
      setMiningIntent(intent.terms);
      setTermsAccepted(false);
      setMiningOpen(true);
    } catch (reason) {
      setActionError(errorText(reason));
    } finally {
      setMiningPreparing(false);
    }
  }

  async function confirmMiningJoin() {
    if (!contest) return;
    setJoinPending(true);
    setJoinError("");
    try {
      const hash = await writeContractAsync({
        address: meta.addresses.arena as Address,
        abi: arenaAbi,
        functionName: "joinMining",
        args: [contest.id as `0x${string}`, true],
      });
      await trackTransaction(hash, "加入挖矿赛", "join");
      setMiningOpen(false);
      toast({ title: "已加入挖矿赛", description: "数据仅用于 RSI 修复，不进入数据市场。", tone: "success" });
      await Promise.all([query.refetch(), isAttacker.refetch()]);
    } catch (reason) {
      setJoinError(errorText(reason));
    } finally {
      setJoinPending(false);
    }
  }

  async function settle() {
    if (!contest) return;
    setActionPending("settle");
    setActionError("");
    try {
      const hash = await writeContractAsync({
        address: meta.addresses.arena as Address,
        abi: arenaAbi,
        functionName: "expire",
        args: [contest.id as `0x${string}`],
      });
      await trackTransaction(hash, "结算到期比赛", "expire");
      toast({
        title: "结算已提交",
        description: "索引器同步后状态会更新；W 余额会退回守方。",
        tone: "success",
      });
      await new Promise((resolve) => window.setTimeout(resolve, 1_500));
      await query.refetch();
    } catch (reason) {
      setActionError(errorText(reason));
    } finally {
      setActionPending("");
    }
  }

  async function withdraw() {
    if (!contest) return;
    setActionPending("withdraw");
    setActionError("");
    try {
      const hash = await writeContractAsync({
        address: meta.addresses.arena as Address,
        abi: arenaAbi,
        functionName: "withdrawStake",
        args: [contest.id as `0x${string}`],
      });
      await trackTransaction(hash, "提取剩余质押", "withdraw");
      toast({ title: "质押已提取", description: "剩余质押已转回你的钱包。", tone: "success" });
      await Promise.all([remaining.refetch(), query.refetch()]);
    } catch (reason) {
      setActionError(errorText(reason));
    } finally {
      setActionPending("");
    }
  }

  async function collect() {
    if (!contest) return;
    setActionPending("collect");
    setActionError("");
    try {
      const hash = await writeContractAsync({
        address: meta.addresses.arena as Address,
        abi: arenaAbi,
        functionName: "collectPenalties",
        args: [contest.id as `0x${string}`],
      });
      await trackTransaction(hash, "拉取攻方罚款", "collect");
      toast({ title: "罚款已拉取", tone: "success" });
      await query.refetch();
    } catch (reason) {
      setActionError(errorText(reason));
    } finally {
      setActionPending("");
    }
  }

  return (
    <div className="detail-page">
      <div className="detail-back">
        <Link to={backTo} className="detail-back__link">
          <ArrowLeft size={13} />
          {backLabel}
        </Link>
        <span className="mono">CONTEST / {contest.id.slice(0, 12)}…</span>
      </div>

      <header className="detail-head">
        <div className="detail-head__main">
          <div className="detail-head__badges">
            <ContestStatusBadge contest={contest} now={now} />
            <Badge tone={isMining ? "mining" : "neutral"}>
              {isMining ? "MINING" : "NORMAL"}
            </Badge>
            {needsExpire(contest, now) && <Badge tone="warning">等待 expire</Badge>}
          </div>
          <h1 className="detail-head__title">
            {isMining ? "挖矿靶" : "攻防靶"}{" "}
            <span className="mono muted">{contest.id.slice(0, 10)}…</span>
            <CopyButton value={contest.id} label="复制比赛 ID" />
          </h1>
          <div className="detail-head__meta">
            <span>
              <Shield size={13} /> 守方 <AddressChip value={contest.defender} />
            </span>
            <span>
              <Crosshair size={13} /> 靶钱包 <AddressChip value={contest.wallet} />
            </span>
            <span>
              <Timer size={13} /> <Countdown endMs={endMs} label={isMining ? "" : "剩余"} />
            </span>
          </div>
        </div>
        <div className="detail-head__aside">
          <span className="detail-head__aside-label mono">
            {isMining ? "OPEN-ENDED" : "TIME PROGRESS"}
          </span>
          {isMining ? (
            <div className="detail-open">
              <InfinityIcon size={16} />
              <span>由攻破或平台退役结束</span>
            </div>
          ) : (
            <Progress
              value={progress}
              tone={contest.state === "live" ? "accent" : "neutral"}
              right={`${Math.round(progress * 100)}%`}
            />
          )}
          <span className="detail-head__aside-foot mono">
            {formatDateTime(contest.start_ts)} →{" "}
            {isMining ? "无固定结束" : formatDateTime(Number(contest.end))}
          </span>
        </div>
      </header>

      <div className="stat-strip">
        <Stat
          label={isMining ? "固定奖励" : "奖池 S"}
          value={isMining ? "1 RTM" : formatRtm(contest.stake)}
          unit={isMining ? undefined : "RTM"}
          icon={isMining ? <Pickaxe size={14} /> : <Banknote size={14} />}
          tone="accent"
        />
        <Stat
          label={isMining ? "攻破奖励" : "攻方质押"}
          value={isMining ? "1" : formatRtm(stake)}
          unit="RTM"
          icon={isMining ? <Trophy size={14} /> : <Swords size={14} />}
        />
        <Stat
          label="单条消息"
          value={formatRtm(fee, { maxFraction: 4 })}
          unit="RTM"
          icon={<MessageSquare size={14} />}
        />
        <Stat
          label="已付费消息"
          numericValue={contest.paid_count}
          format={(value) => String(Math.round(value))}
          icon={<Flag size={14} />}
        />
      </div>

      <div className="detail-grid">
        <div className="detail-main">
          <Panel
            eyebrow="Field dossier / 战场档案"
            title={isMining ? "挖矿赛简报" : "普通赛简报"}
            bracket
            actions={
              <Button
                size="sm"
                variant="ghost"
                iconLeft={<RefreshCw size={12} />}
                loading={query.isFetching}
                onClick={() => void query.refetch()}
              >
                刷新
              </Button>
            }
          >
            <div className="info-grid">
              <InfoRow label="比赛状态">
                <ContestStatusBadge contest={contest} now={now} dot={false} />
              </InfoRow>
              <InfoRow label="守方">
                <AddressChip value={contest.defender} />
              </InfoRow>
              <InfoRow label="靶钱包 W">
                <AddressChip value={contest.wallet} />
              </InfoRow>
              <InfoRow label={isMining ? "Defense hash" : "防守版本"}>
                <AddressChip value={contest.defense_hash} kind="hash" />
              </InfoRow>
              <InfoRow label="开始时间">{formatDateTime(contest.start_ts)}</InfoRow>
              {isMining ? (
                <InfoRow label="结束方式">攻破或平台退役</InfoRow>
              ) : (
                <InfoRow label="结束时间">{formatDateTime(Number(contest.end))}</InfoRow>
              )}
              {contest.ended_ts ? (
                <InfoRow label="实际结束">{formatDateTime(contest.ended_ts)}</InfoRow>
              ) : null}
              {contest.winner ? (
                <InfoRow label="胜者">
                  <AddressChip value={contest.winner} />
                </InfoRow>
              ) : null}
              {!isMining && attackerInfo ? (
                <InfoRow label="你的质押">
                  {formatRtmUnit(attackerInfo.stake)}
                </InfoRow>
              ) : null}
              {!isMining && positionStake !== undefined && joined ? (
                <InfoRow label="当前可退质押">
                  {formatRtmUnit(positionStake)}
                </InfoRow>
              ) : null}
            </div>

            {contest.state !== "live" && (
              <div className={`outcome-banner outcome-banner--${contest.state}`}>
                {contest.state === "breached" ? <Skull size={18} /> : <CheckCircle2 size={18} />}
                <div>
                  <strong>{stateLabel(contest.state)}</strong>
                  <span>
                    {contest.winner
                      ? `胜者 ${contest.winner.slice(0, 10)}… 拿走靶钱包余额。`
                      : "比赛已结束，结算由合约完成。"}
                  </span>
                </div>
              </div>
            )}
          </Panel>

          {!isDefender && joined && (
            <PaidChat
              contest={contest}
              joined={joined}
              onAfterSend={() => void query.refetch()}
            />
          )}

          {!isDefender && !joined && (
            <Panel eyebrow="Dialogue" title="加入后解锁付费对话" tone="flat">
              <div className="locked-dialogue">
                <MessageSquare size={20} />
                <div>
                  <strong>对话区在等待你</strong>
                  <p>
                    加入后，每条消息先授权费用，再上链；索引器确认后平台才会运行守方智能体。
                  </p>
                </div>
                {live && isConnected && correctChain ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => (isMining ? void prepareMiningJoin() : openJoin())}
                    loading={isMining ? miningPreparing : false}
                  >
                    了解加入条件
                  </Button>
                ) : live ? (
                  <Badge tone="neutral">先连接钱包</Badge>
                ) : (
                  <Badge tone="neutral">比赛已结束</Badge>
                )}
              </div>
            </Panel>
          )}

          {isDefender && (
            <Panel eyebrow="Defender note" title="守方视角" tone="flat">
              <p className="muted small">
                攻方对话内容不会展示给守方。你可以拉取已累计的罚款；比赛到期后任何地址都可以结算。
                赛后可以在数据市场发布并购买数据。
              </p>
            </Panel>
          )}
        </div>

        <aside className="detail-side">
          <Panel eyebrow="Your position / 你的位置" title={joined ? "已在战场中" : "加入这场战斗"} bracket>
            {!isConnected ? (
              <ConnectPrompt title="连接钱包以加入" compact />
            ) : !correctChain ? (
              <ConnectPrompt title="先切换网络" compact />
            ) : joined ? (
              <div className="position">
                <div className="position__status">
                  <Badge tone="success" dot>
                    已加入
                  </Badge>
                  {attackerInfo?.won && <Badge tone="accent">你攻破了这场</Badge>}
                  {isMining ? (
                    <Badge tone="mining">RSI 留存</Badge>
                  ) : (
                    positionConsent !== null && (
                      <Badge tone={positionConsent ? "success" : "neutral"}>
                        {positionConsent ? "数据可售" : "不落盘"}
                      </Badge>
                    )
                  )}
                </div>
                <dl className="position__grid">
                  {isMining ? (
                    <>
                      <div>
                        <dt>固定奖励</dt>
                        <dd>1 RTM</dd>
                      </div>
                      <div>
                        <dt>付费消息</dt>
                        <dd>{attackerInfo?.paid ?? 0} 条</dd>
                      </div>
                      <div>
                        <dt>已送达</dt>
                        <dd>{attackerInfo?.delivered ?? 0} 条</dd>
                      </div>
                      <div>
                        <dt>数据用途</dt>
                        <dd>仅 RSI</dd>
                      </div>
                    </>
                  ) : (
                    <>
                      <div>
                        <dt>初始质押</dt>
                        <dd>{formatRtmUnit(positionStake ?? attackerInfo?.stake)}</dd>
                      </div>
                      <div>
                        <dt>已付费</dt>
                        <dd>{attackerInfo?.paid ?? 0} 条</dd>
                      </div>
                      <div>
                        <dt>已送达</dt>
                        <dd>{attackerInfo?.delivered ?? 0} 条</dd>
                      </div>
                      <div>
                        <dt>剩余质押</dt>
                        <dd>{formatRtmUnit(remaining.data)}</dd>
                      </div>
                    </>
                  )}
                </dl>

                {canSettle && (
                  <Alert tone="warning" title="时间已到">
                    到期比赛需要先调用 <code>expire</code> 才会进入 Ended；任何地址都可以结算。
                  </Alert>
                )}

                <div className="position__actions">
                  {canSettle && (
                    <Button
                      variant="secondary"
                      block
                      loading={actionPending === "settle"}
                      iconLeft={<Gavel size={14} />}
                      onClick={() => void settle()}
                    >
                      结算到期比赛
                    </Button>
                  )}
                  {!isMining && contest.state === "ended" && (remaining.data ?? 0n) > 0n && (
                    <Button
                      variant="primary"
                      block
                      loading={actionPending === "withdraw"}
                      iconLeft={<Coins size={14} />}
                      onClick={() => void withdraw()}
                    >
                      提取剩余质押
                    </Button>
                  )}
                  {!isMining && contest.state === "live" && (
                    <p className="position__hint">
                      比赛结束后，剩余质押可提取；未拉取的罚款留在 Arena 等待守方领取。
                    </p>
                  )}
                </div>
              </div>
            ) : live ? (
              isMining ? (
                <div className="join-summary">
                  <div className="join-summary__head">
                    <Pickaxe size={19} />
                    <div>
                      <strong>无质押加入挖矿赛</strong>
                      <p>固定奖励 1 RTM；每条消息 0.005 RTM。</p>
                    </div>
                  </div>
                  <ul className="mini-rules">
                    <li>矿工数据强制留存，仅用于 RSI 修复。</li>
                    <li>攻破后比赛立即停止，defenseHash 永久退役。</li>
                    <li>不进入数据市场、不出售。</li>
                  </ul>
                  <Button
                    block
                    loading={miningPreparing}
                    iconLeft={<Pickaxe size={14} />}
                    onClick={() => void prepareMiningJoin()}
                  >
                    查看条款并加入
                  </Button>
                </div>
              ) : (
                <div className="join-summary">
                  <div className="join-summary__head">
                    <Swords size={19} />
                    <div>
                      <strong>质押加入普通赛</strong>
                      <p>攻方质押 = 守方质押 × {(contest.stake_bps / 100).toFixed(2)}%。</p>
                    </div>
                  </div>
                  <dl className="join-summary__grid">
                    <div>
                      <dt>需要质押</dt>
                      <dd>{formatRtmUnit(stake)}</dd>
                    </div>
                    <div>
                      <dt>单条消息</dt>
                      <dd>{formatRtmUnit(fee, { maxFraction: 4 })}</dd>
                    </div>
                    <div>
                      <dt>你的 RTM</dt>
                      <dd>{formatRtmUnit(balance?.data)}</dd>
                    </div>
                    <div>
                      <dt>预计可发</dt>
                      <dd>{fee > 0n && balance?.data ? `${balance.data / fee} 条` : "—"}</dd>
                    </div>
                  </dl>
                  {balance?.data !== undefined && balance.data < stake && (
                    <Alert
                      tone="warning"
                      title="余额不足"
                      action={
                        <Link className="btn btn--ghost btn--sm" to="/faucet">
                          去领水
                        </Link>
                      }
                    >
                      加入需要 {formatRtmUnit(stake)}，当前余额 {formatRtmUnit(balance.data)}。
                    </Alert>
                  )}
                  <Button
                    block
                    disabled={balance?.data !== undefined && balance.data < stake}
                    iconLeft={<Swords size={14} />}
                    onClick={openJoin}
                  >
                    选择数据同意并加入
                  </Button>
                  <p className="position__hint">
                    数据同意在 join 后不可撤回。不同意也可加入，但消息不会落盘、不可出售。
                  </p>
                </div>
              )
            ) : (
              <div className="ended-panel">
                <CheckCircle2 size={20} />
                <div>
                  <strong>比赛已结束</strong>
                  <p>{contest.winner ? "攻方已攻破靶钱包，等待提取质押。" : "没有攻破记录。"}</p>
                </div>
              </div>
            )}

            {actionError && (
              <Alert tone="error" className="position__alert">
                {actionError}
              </Alert>
            )}
          </Panel>

          {isDefender && !isMining && (
            <Panel eyebrow="Defender controls" title="守方操作">
              <div className="stack-actions">
                {canSettle && (
                  <Button
                    block
                    variant="secondary"
                    loading={actionPending === "settle"}
                    iconLeft={<Gavel size={14} />}
                    onClick={() => void settle()}
                  >
                    结算到期比赛
                  </Button>
                )}
                {contest.paid_count > 0 && (
                  <Button
                    block
                    variant="ghost"
                    loading={actionPending === "collect"}
                    iconLeft={<Coins size={14} />}
                    onClick={() => void collect()}
                  >
                    拉取已累计罚款
                  </Button>
                )}
                {contest.state !== "live" && (
                  <Link className="btn btn--ghost btn--block" to={`/market/${contest.id}`}>
                    <ArrowUpRight size={14} />
                    查看赛后数据
                  </Link>
                )}
                <p className="position__hint">
                  一次注册只能创建一场普通赛。罚款按时间衰减累计，可重复拉取差额。
                </p>
              </div>
            </Panel>
          )}

          <Panel eyebrow="Rules / 规则" title={isMining ? "挖矿结算" : "攻防结算"} tone="flat">
            <ul className="rule-list">
              {isMining ? (
                <>
                  <li>无质押；每条消息费率固定为 1 RTM 的 0.5%。</li>
                  <li>攻破后平台补铸 1 RTM 给 Treasury，胜者拿走 W 余额。</li>
                  <li>比赛结束或退役后 defenseHash 永久不可复用。</li>
                  <li>全部对话与工具轨迹仅用于 RSI 修复，不进入数据市场。</li>
                </>
              ) : (
                <>
                  <li>攻方质押按 stakeBps 计算，随链上时间按 epoch 衰减。</li>
                  <li>每条消息费 = 守方质押 × 0.5%，付款后才能运行智能体。</li>
                  <li>W 向登记攻方转账会原子触发结算；到期后任何人可 expire。</li>
                  <li>dataConsent 在 join 时锁定；同意出售时平台 70% / 攻方 30%。</li>
                </>
              )}
            </ul>
          </Panel>

          <div className="detail-side__note mono">
            <Wallet size={12} />
            <span>所有签名都在你的钱包中完成</span>
          </div>
        </aside>
      </div>

      {!isMining && (
        <Dialog
          open={joinOpen}
          onClose={() => !joinPending && setJoinOpen(false)}
          eyebrow="Join contest / 加入"
          title="确认质押与数据同意"
          description="这两项都会写入链上；数据同意在加入后不可撤回。"
          size="md"
          footer={
            <div className="dialog__footer-row">
              <Button variant="ghost" onClick={() => setJoinOpen(false)} disabled={joinPending}>
                取消
              </Button>
              <Button
                loading={joinPending}
                disabled={consentChoice === null || !acknowledged}
                onClick={() => consentChoice !== null && void confirmJoin(consentChoice)}
              >
                授权并加入
              </Button>
            </div>
          }
        >
          <div className="join-dialog">
            <div className="join-dialog__summary">
              <div>
                <span>攻方质押</span>
                <strong>{formatRtmUnit(stake)}</strong>
              </div>
              <div>
                <span>单条消息</span>
                <strong>{formatRtmUnit(fee, { maxFraction: 4 })}</strong>
              </div>
              <div>
                <span>当前余额</span>
                <strong>{formatRtmUnit(balance?.data)}</strong>
              </div>
            </div>

            <div className="choice-grid">
              <button
                type="button"
                className={`choice ${consentChoice === true ? "is-selected" : ""}`.trim()}
                onClick={() => setConsentChoice(true)}
              >
                <span className="choice__icon">
                  <Banknote size={17} />
                </span>
                <strong>同意数据留存与出售</strong>
                <span>赛后守方可购买你的对话切片；平台 70% / 你 30%。</span>
              </button>
              <button
                type="button"
                className={`choice ${consentChoice === false ? "is-selected" : ""}`.trim()}
                onClick={() => setConsentChoice(false)}
              >
                <span className="choice__icon">
                  <Shield size={17} />
                </span>
                <strong>不落盘，不出售</strong>
                <span>消息只在内存处理；赛后没有你的数据切片。</span>
              </button>
            </div>

            <CheckboxField
              checked={acknowledged}
              onChange={setAcknowledged}
              tone="danger"
            >
              我理解 dataConsent 在链上 join 后不可撤回，并确认质押金额。
            </CheckboxField>

            {joinError && <Alert tone="error">{joinError}</Alert>}
          </div>
        </Dialog>
      )}

      <Dialog
        open={miningOpen}
        onClose={() => !joinPending && setMiningOpen(false)}
        eyebrow="Mining terms / 挖矿条款"
        title="确认矿工数据条款"
        description="加入挖矿赛不需要质押，但数据会被强制留存，仅用于 RSI 修复。"
        size="md"
        footer={
          <div className="dialog__footer-row">
            <Button variant="ghost" onClick={() => setMiningOpen(false)} disabled={joinPending}>
              取消
            </Button>
            <Button
              loading={joinPending}
              disabled={!termsAccepted}
              onClick={() => void confirmMiningJoin()}
            >
              joinMining(id, true)
            </Button>
          </div>
        }
      >
        <div className="join-dialog">
          <div className="terms-box">
            {miningIntent ?? "加入挖矿赛即视为同意平台留存全部消息、回复与工具轨迹。"}
          </div>
          <CheckboxField
            checked={termsAccepted}
            onChange={setTermsAccepted}
            tone="danger"
          >
            我已阅读并同意：矿工数据仅用于 RSI 修复，不进入数据市场、不出售。
          </CheckboxField>
          {joinError && <Alert tone="error">{joinError}</Alert>}
        </div>
      </Dialog>
    </div>
  );
}

