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
import { useAccount, useChainId } from "wagmi";
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
import { useI18n } from "../lib/i18n";
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
import { useArenaWriteContract } from "../lib/useArenaWriteContract";
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
  const { writeContractAsync } = useArenaWriteContract();
  const { trackTransaction } = useActivity();
  const { toast } = useToast();
  const { t } = useI18n();
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
        title={t("Contest not found", "找不到这场战斗")}
        description={t(
          "The contest may not be indexed yet, or the link is incorrect. Try again after the indexer syncs.",
          "比赛可能尚未被索引，或链接有误。等索引器同步后再试。",
        )}
        action={
          <div className="row-actions">
            <Link className="btn btn--ghost btn--sm" to={mode === "mine" ? "/mine" : "/arena"}>
              <ArrowLeft size={13} />
              {t("Back to list", "返回列表")}
            </Link>
            <Button size="sm" onClick={() => void query.refetch()}>
              {t("Retry", "重试")}
            </Button>
          </div>
        }
      />
    );
  }

  const backTo = mode === "mine" || isMining ? "/mine" : "/arena";
  const backLabel = mode === "mine" || isMining
    ? t("Mining center", "挖矿中心")
    : t("Arena", "竞技场");

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
        await trackTransaction(
          approvalHash,
          t("Approve attacker stake", "授权攻方质押"),
          "approve",
        );
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
      await trackTransaction(joinHash, t("Join contest", "加入战场"), "join");
      toast({
        title: t("Joined the contest", "已加入战场"),
        description: dataConsent
          ? t(
              "You agreed to post-contest data sales (70% platform / 30% you).",
              "你同意了赛后数据出售（平台 70% / 你 30%）。",
            )
          : t(
              "You opted out; the dialogue cannot be sold.",
              "你选择了不落盘；对话不可出售。",
            ),
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
      await trackTransaction(hash, t("Join mining contest", "加入挖矿赛"), "join");
      setMiningOpen(false);
      toast({
        title: t("Joined the mining contest", "已加入挖矿赛"),
        description: t(
          "Data is used only for RSI repair and does not enter the data market.",
          "数据仅用于 RSI 修复，不进入数据市场。",
        ),
        tone: "success",
      });
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
      await trackTransaction(hash, t("Settle expired contest", "结算到期比赛"), "expire");
      toast({
        title: t("Settlement submitted", "结算已提交"),
        description: t(
          "The status will update after the indexer syncs; the W balance will be returned to the defender.",
          "索引器同步后状态会更新；W 余额会退回守方。",
        ),
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
      await trackTransaction(hash, t("Withdraw remaining stake", "提取剩余质押"), "withdraw");
      toast({
        title: t("Stake withdrawn", "质押已提取"),
        description: t(
          "The remaining stake has been returned to your wallet.",
          "剩余质押已转回你的钱包。",
        ),
        tone: "success",
      });
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
      await trackTransaction(hash, t("Collect attacker penalties", "拉取攻方罚款"), "collect");
      toast({ title: t("Penalties collected", "罚款已拉取"), tone: "success" });
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
        <span className="mono">{t("CONTEST", "比赛")} / {contest.id.slice(0, 12)}…</span>
      </div>

      <header className="detail-head">
        <div className="detail-head__main">
          <div className="detail-head__badges">
            <ContestStatusBadge contest={contest} now={now} />
            <Badge tone={isMining ? "mining" : "neutral"}>
              {isMining ? t("MINING", "挖矿") : t("NORMAL", "普通")}
            </Badge>
            {needsExpire(contest, now) && (
              <Badge tone="warning">{t("Expire pending", "等待 expire")}</Badge>
            )}
          </div>
          <h1 className="detail-head__title">
            {isMining ? t("Mining target", "挖矿靶") : t("Defense target", "攻防靶")}{" "}
            <span className="mono muted">{contest.id.slice(0, 10)}…</span>
            <CopyButton value={contest.id} label={t("Copy contest ID", "复制比赛 ID")} />
          </h1>
          <div className="detail-head__meta">
            <span>
              <Shield size={13} /> {t("Defender", "守方")}{" "}
              <AddressChip value={contest.defender} />
            </span>
            <span>
              <Crosshair size={13} /> {t("Target wallet", "靶钱包")}{" "}
              <AddressChip value={contest.wallet} />
            </span>
            <span>
              <Timer size={13} />{" "}
              <Countdown endMs={endMs} label={isMining ? "" : t("Remaining", "剩余")} />
            </span>
          </div>
        </div>
        <div className="detail-head__aside">
          <span className="detail-head__aside-label mono">
            {isMining ? t("OPEN-ENDED", "开放赛制") : t("TIME PROGRESS", "时间进度")}
          </span>
          {isMining ? (
            <div className="detail-open">
              <InfinityIcon size={16} />
              <span>{t("Ends on breach or platform retirement", "由攻破或平台退役结束")}</span>
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
            {isMining ? t("No fixed end time", "无固定结束时间") : formatDateTime(Number(contest.end))}
          </span>
        </div>
      </header>

      <div className="stat-strip">
        <Stat
          label={isMining ? t("Fixed reward", "固定奖励") : t("Prize pool S", "奖池 S")}
          value={isMining ? "1 tRTM" : formatRtm(contest.stake)}
          unit={isMining ? undefined : "tRTM"}
          icon={isMining ? <Pickaxe size={14} /> : <Banknote size={14} />}
          tone="accent"
        />
        <Stat
          label={isMining ? t("Breach reward", "攻破奖励") : t("Attacker stake", "攻方质押")}
          value={isMining ? "1" : formatRtm(stake)}
          unit="tRTM"
          icon={isMining ? <Trophy size={14} /> : <Swords size={14} />}
        />
        <Stat
          label={t("Per message", "单条消息")}
          value={formatRtm(fee, { maxFraction: 4 })}
          unit="tRTM"
          icon={<MessageSquare size={14} />}
        />
        <Stat
          label={t("Paid messages", "已付费消息")}
          numericValue={contest.paid_count}
          format={(value) => String(Math.round(value))}
          icon={<Flag size={14} />}
        />
      </div>

      <div className="detail-grid">
        <div className="detail-main">
          <Panel
            eyebrow={t("Field dossier", "战场档案")}
            title={isMining ? t("Mining briefing", "挖矿赛简报") : t("Standard contest briefing", "普通赛简报")}
            bracket
            actions={
              <Button
                size="sm"
                variant="ghost"
                iconLeft={<RefreshCw size={12} />}
                loading={query.isFetching}
                onClick={() => void query.refetch()}
              >
                {t("Refresh", "刷新")}
              </Button>
            }
          >
            <div className="info-grid">
              <InfoRow label={t("Contest status", "比赛状态")}>
                <ContestStatusBadge contest={contest} now={now} dot={false} />
              </InfoRow>
              <InfoRow label={t("Defender", "守方")}>
                <AddressChip value={contest.defender} />
              </InfoRow>
              <InfoRow label={t("Target wallet W", "靶钱包 W")}>
                <AddressChip value={contest.wallet} />
              </InfoRow>
              <InfoRow label={t("Defense hash", "防守版本")}>
                <AddressChip value={contest.defense_hash} kind="hash" />
              </InfoRow>
              <InfoRow label={t("Start time", "开始时间")}>{formatDateTime(contest.start_ts)}</InfoRow>
              {isMining ? (
                <InfoRow label={t("End condition", "结束方式")}>
                  {t("Breach or platform retirement", "攻破或平台退役")}
                </InfoRow>
              ) : (
                <InfoRow label={t("End time", "结束时间")}>{formatDateTime(Number(contest.end))}</InfoRow>
              )}
              {contest.ended_ts ? (
                <InfoRow label={t("Actual end", "实际结束")}>{formatDateTime(contest.ended_ts)}</InfoRow>
              ) : null}
              {contest.winner ? (
                <InfoRow label={t("Winner", "胜者")}>
                  <AddressChip value={contest.winner} />
                </InfoRow>
              ) : null}
              {!isMining && attackerInfo ? (
                <InfoRow label={t("Your stake", "你的质押")}>
                  {formatRtmUnit(attackerInfo.stake)}
                </InfoRow>
              ) : null}
              {!isMining && positionStake !== undefined && joined ? (
                <InfoRow label={t("Withdrawable stake", "当前可退质押")}>
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
                      ? t(
                          `Winner ${contest.winner.slice(0, 10)}… takes the target wallet balance.`,
                          `胜者 ${contest.winner.slice(0, 10)}… 拿走靶钱包余额。`,
                        )
                      : t(
                          "The contest has ended; settlement is handled by the contract.",
                          "比赛已结束，结算由合约完成。",
                        )}
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
            <Panel
              eyebrow={t("Dialogue", "对话")}
              title={t("Paid chat unlocks after joining", "加入后解锁付费对话")}
              tone="flat"
            >
              <div className="locked-dialogue">
                <MessageSquare size={20} />
                <div>
                  <strong>{t("The dialogue is waiting for you", "对话区在等待你")}</strong>
                  <p>
                    {t(
                      "After joining, each message approves the fee before going on-chain; the platform runs the defender agent only after the indexer confirms it.",
                      "加入后，每条消息先授权费用，再上链；索引器确认后平台才会运行守方智能体。",
                    )}
                  </p>
                </div>
                {live && isConnected && correctChain ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => (isMining ? void prepareMiningJoin() : openJoin())}
                    loading={isMining ? miningPreparing : false}
                  >
                    {t("See joining requirements", "了解加入条件")}
                  </Button>
                ) : live ? (
                  <Badge tone="neutral">{t("Connect wallet first", "先连接钱包")}</Badge>
                ) : (
                  <Badge tone="neutral">{t("Contest ended", "比赛已结束")}</Badge>
                )}
              </div>
            </Panel>
          )}

          {isDefender && (
            <Panel
              eyebrow={t("Defender note", "守方须知")}
              title={t("Defender view", "守方视角")}
              tone="flat"
            >
              <p className="muted small">
                {t(
                  "Attacker messages are not shown to the defender. You can collect accrued penalties; after expiry, any address can settle. After the contest, data can be published and purchased in the data market.",
                  "攻方对话内容不会展示给守方。你可以拉取已累计的罚款；比赛到期后任何地址都可以结算。赛后可以在数据市场发布并购买数据。",
                )}
              </p>
            </Panel>
          )}
        </div>

        <aside className="detail-side">
          <Panel
            eyebrow={t("Your position", "你的位置")}
            title={joined ? t("You are in the contest", "已在战场中") : t("Join this contest", "加入这场战斗")}
            bracket
          >
            {!isConnected ? (
              <ConnectPrompt title={t("Connect wallet to join", "连接钱包以加入")} compact />
            ) : !correctChain ? (
              <ConnectPrompt title={t("Switch network first", "先切换网络")} compact />
            ) : joined ? (
              <div className="position">
                <div className="position__status">
                  <Badge tone="success" dot>
                    {t("Joined", "已加入")}
                  </Badge>
                  {attackerInfo?.won && (
                    <Badge tone="accent">{t("You breached this contest", "你攻破了这场")}</Badge>
                  )}
                  {isMining ? (
                    <Badge tone="mining">{t("RSI data retained", "RSI 留存")}</Badge>
                  ) : (
                    positionConsent !== null && (
                      <Badge tone={positionConsent ? "success" : "neutral"}>
                        {positionConsent ? t("Data sellable", "数据可售") : t("Not persisted", "不落盘")}
                      </Badge>
                    )
                  )}
                </div>
                <dl className="position__grid">
                  {isMining ? (
                    <>
                      <div>
                        <dt>{t("Fixed reward", "固定奖励")}</dt>
                        <dd>1 tRTM</dd>
                      </div>
                      <div>
                        <dt>{t("Paid messages", "付费消息")}</dt>
                        <dd>{attackerInfo?.paid ?? 0} {t("messages", "条")}</dd>
                      </div>
                      <div>
                        <dt>{t("Delivered", "已送达")}</dt>
                        <dd>{attackerInfo?.delivered ?? 0} {t("messages", "条")}</dd>
                      </div>
                      <div>
                        <dt>{t("Data use", "数据用途")}</dt>
                        <dd>{t("RSI only", "仅 RSI")}</dd>
                      </div>
                    </>
                  ) : (
                    <>
                      <div>
                        <dt>{t("Initial stake", "初始质押")}</dt>
                        <dd>{formatRtmUnit(positionStake ?? attackerInfo?.stake)}</dd>
                      </div>
                      <div>
                        <dt>{t("Paid", "已付费")}</dt>
                        <dd>{attackerInfo?.paid ?? 0} {t("messages", "条")}</dd>
                      </div>
                      <div>
                        <dt>{t("Delivered", "已送达")}</dt>
                        <dd>{attackerInfo?.delivered ?? 0} {t("messages", "条")}</dd>
                      </div>
                      <div>
                        <dt>{t("Remaining stake", "剩余质押")}</dt>
                        <dd>{formatRtmUnit(remaining.data)}</dd>
                      </div>
                    </>
                  )}
                </dl>

                {canSettle && (
                  <Alert tone="warning" title={t("Time is up", "时间已到")}>
                    {t("Expired contests must call ", "到期比赛需要先调用 ")}
                    <code>expire</code>
                    {t(
                      " before they enter Ended; any address can settle.",
                      " 才会进入 Ended；任何地址都可以结算。",
                    )}
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
                      {t("Settle expired contest", "结算到期比赛")}
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
                      {t("Withdraw remaining stake", "提取剩余质押")}
                    </Button>
                  )}
                  {!isMining && contest.state === "live" && (
                    <p className="position__hint">
                      {t(
                        "After the contest ends, the remaining stake can be withdrawn; uncollected penalties stay in the Arena for the defender to claim.",
                        "比赛结束后，剩余质押可提取；未拉取的罚款留在 Arena 等待守方领取。",
                      )}
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
                      <strong>{t("Join the mining contest without a stake", "无质押加入挖矿赛")}</strong>
                      <p>
                        {t(
                          "Fixed reward 1 tRTM; 0.005 tRTM per message.",
                          "固定奖励 1 tRTM；每条消息 0.005 tRTM。",
                        )}
                      </p>
                    </div>
                  </div>
                  <ul className="mini-rules">
                    <li>{t("Miner data is always retained for RSI repair only.", "矿工数据强制留存，仅用于 RSI 修复。")}</li>
                    <li>
                      {t(
                        "The contest stops immediately on a breach, and the defenseHash is permanently retired.",
                        "攻破后比赛立即停止，defenseHash 永久退役。",
                      )}
                    </li>
                    <li>{t("No data-market listing and no sales.", "不进入数据市场、不出售。")}</li>
                  </ul>
                  <Button
                    block
                    loading={miningPreparing}
                    iconLeft={<Pickaxe size={14} />}
                    onClick={() => void prepareMiningJoin()}
                  >
                    {t("Review terms and join", "查看条款并加入")}
                  </Button>
                </div>
              ) : (
                <div className="join-summary">
                  <div className="join-summary__head">
                    <Swords size={19} />
                    <div>
                      <strong>{t("Join the standard contest with a stake", "质押加入普通赛")}</strong>
                      <p>
                        {t(
                          `Attacker stake = defender stake × ${(contest.stake_bps / 100).toFixed(2)}%.`,
                          `攻方质押 = 守方质押 × ${(contest.stake_bps / 100).toFixed(2)}%。`,
                        )}
                      </p>
                    </div>
                  </div>
                  <dl className="join-summary__grid">
                    <div>
                      <dt>{t("Stake required", "需要质押")}</dt>
                      <dd>{formatRtmUnit(stake)}</dd>
                    </div>
                    <div>
                      <dt>{t("Per message", "单条消息")}</dt>
                      <dd>{formatRtmUnit(fee, { maxFraction: 4 })}</dd>
                    </div>
                    <div>
                      <dt>{t("Your", "你的")} <span className="preserve-case">tRTM</span></dt>
                      <dd>{formatRtmUnit(balance?.data)}</dd>
                    </div>
                    <div>
                      <dt>{t("Est. messages", "预计可发")}</dt>
                      <dd>
                        {fee > 0n && balance?.data
                          ? t(`${balance.data / fee} messages`, `${balance.data / fee} 条`)
                          : "—"}
                      </dd>
                    </div>
                  </dl>
                  {balance?.data !== undefined && balance.data < stake && (
                    <Alert
                      tone="warning"
                      title={t("Insufficient balance", "余额不足")}
                      action={
                        <Link className="btn btn--ghost btn--sm" to="/faucet">
                          {t("Get test tRTM", "去领水")}
                        </Link>
                      }
                    >
                      {t(
                        `Joining requires ${formatRtmUnit(stake)}; current balance ${formatRtmUnit(balance.data)}.`,
                        `加入需要 ${formatRtmUnit(stake)}，当前余额 ${formatRtmUnit(balance.data)}。`,
                      )}
                    </Alert>
                  )}
                  <Button
                    block
                    disabled={balance?.data !== undefined && balance.data < stake}
                    iconLeft={<Swords size={14} />}
                    onClick={openJoin}
                  >
                    {t("Choose data consent and join", "选择数据同意并加入")}
                  </Button>
                  <p className="position__hint">
                    {t(
                      "Data consent cannot be revoked after joining. You can join without consent, but messages will not be persisted or sold.",
                      "数据同意在 join 后不可撤回。不同意也可加入，但消息不会落盘、不可出售。",
                    )}
                  </p>
                </div>
              )
            ) : (
              <div className="ended-panel">
                <CheckCircle2 size={20} />
                <div>
                  <strong>{t("Contest ended", "比赛已结束")}</strong>
                  <p>
                    {contest.winner
                      ? t(
                          "The attacker breached the target wallet; awaiting stake withdrawal.",
                          "攻方已攻破靶钱包，等待提取质押。",
                        )
                      : t("No breach recorded.", "没有攻破记录。")}
                  </p>
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
            <Panel
              eyebrow={t("Defender controls", "守方操作")}
              title={t("Defender actions", "守方操作")}
            >
              <div className="stack-actions">
                {canSettle && (
                  <Button
                    block
                    variant="secondary"
                    loading={actionPending === "settle"}
                    iconLeft={<Gavel size={14} />}
                    onClick={() => void settle()}
                  >
                    {t("Settle expired contest", "结算到期比赛")}
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
                    {t("Collect accrued penalties", "拉取已累计罚款")}
                  </Button>
                )}
                {contest.state !== "live" && (
                  <Link className="btn btn--ghost btn--block" to={`/market/${contest.id}`}>
                    <ArrowUpRight size={14} />
                    {t("View post-contest data", "查看赛后数据")}
                  </Link>
                )}
                <p className="position__hint">
                  {t(
                    "One registration creates only one standard contest. Penalties accrue with time decay and the remaining difference can be collected again.",
                    "一次注册只能创建一场普通赛。罚款按时间衰减累计，可重复拉取差额。",
                  )}
                </p>
              </div>
            </Panel>
          )}

          <Panel
            eyebrow={t("Rules", "规则")}
            title={isMining ? t("Mining settlement", "挖矿结算") : t("Attack & defense settlement", "攻防结算")}
            tone="flat"
          >
            <ul className="rule-list">
              {isMining ? (
                <>
                  <li>
                    {t(
                      "No stake; the message fee is fixed at 0.5% of 1 tRTM.",
                      "无质押；每条消息费率固定为 1 tRTM 的 0.5%。",
                    )}
                  </li>
                  <li>
                    {t(
                      "On a breach, the platform mints 1 tRTM to the Treasury and the winner takes the W balance.",
                      "攻破后平台补铸 1 tRTM 给 Treasury，胜者拿走 W 余额。",
                    )}
                  </li>
                  <li>
                    {t(
                      "After the contest ends or is retired, the defenseHash cannot be reused.",
                      "比赛结束或退役后 defenseHash 永久不可复用。",
                    )}
                  </li>
                  <li>
                    {t(
                      "All dialogue and tool traces are used only for RSI repair and never enter the data market.",
                      "全部对话与工具轨迹仅用于 RSI 修复，不进入数据市场。",
                    )}
                  </li>
                </>
              ) : (
                <>
                  <li>
                    {t(
                      "The attacker stake is calculated from stakeBps and decays by epoch in on-chain time.",
                      "攻方质押按 stakeBps 计算，随链上时间按 epoch 衰减。",
                    )}
                  </li>
                  <li>
                    {t(
                      "Fee per message = 0.5% of the defender stake; the agent runs only after payment.",
                      "每条消息费 = 守方质押 × 0.5%，付款后才能运行智能体。",
                    )}
                  </li>
                  <li>
                    {t(
                      "A W transfer to the registered attacker triggers settlement atomically; after expiry, anyone can call expire.",
                      "W 向登记攻方转账会原子触发结算；到期后任何人可 expire。",
                    )}
                  </li>
                  <li>
                    {t(
                      "dataConsent is locked when joining; if you consent to sales, the split is 70% platform / 30% attacker.",
                      "dataConsent 在 join 时锁定；同意出售时平台 70% / 攻方 30%。",
                    )}
                  </li>
                </>
              )}
            </ul>
          </Panel>

          <div className="detail-side__note mono">
            <Wallet size={12} />
            <span>{t("All signatures are completed in your wallet", "所有签名都在你的钱包中完成")}</span>
          </div>
        </aside>
      </div>

      {!isMining && (
        <Dialog
          open={joinOpen}
          onClose={() => !joinPending && setJoinOpen(false)}
          eyebrow={t("Join contest", "加入")}
          title={t("Confirm stake and data consent", "确认质押与数据同意")}
          description={t(
            "Both choices are written on-chain; data consent cannot be revoked after joining.",
            "这两项都会写入链上；数据同意在加入后不可撤回。",
          )}
          size="md"
          footer={
            <div className="dialog__footer-row">
              <Button variant="ghost" onClick={() => setJoinOpen(false)} disabled={joinPending}>
                {t("Cancel", "取消")}
              </Button>
              <Button
                loading={joinPending}
                disabled={consentChoice === null || !acknowledged}
                onClick={() => consentChoice !== null && void confirmJoin(consentChoice)}
              >
                {t("Approve and join", "授权并加入")}
              </Button>
            </div>
          }
        >
          <div className="join-dialog">
            <div className="join-dialog__summary">
              <div>
                <span>{t("Attacker stake", "攻方质押")}</span>
                <strong>{formatRtmUnit(stake)}</strong>
              </div>
              <div>
                <span>{t("Per message", "单条消息")}</span>
                <strong>{formatRtmUnit(fee, { maxFraction: 4 })}</strong>
              </div>
              <div>
                <span>{t("Current balance", "当前余额")}</span>
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
                <strong>{t("Consent to data retention and sales", "同意数据留存与出售")}</strong>
                <span>
                  {t(
                    "After the contest, the defender can buy slices of your dialogue; 70% platform / 30% you.",
                    "赛后守方可购买你的对话切片；平台 70% / 你 30%。",
                  )}
                </span>
              </button>
              <button
                type="button"
                className={`choice ${consentChoice === false ? "is-selected" : ""}`.trim()}
                onClick={() => setConsentChoice(false)}
              >
                <span className="choice__icon">
                  <Shield size={17} />
                </span>
                <strong>{t("Do not persist or sell", "不落盘，不出售")}</strong>
                <span>
                  {t(
                    "Messages are processed in memory only; no data slices of yours exist after the contest.",
                    "消息只在内存处理；赛后没有你的数据切片。",
                  )}
                </span>
              </button>
            </div>

            <CheckboxField
              checked={acknowledged}
              onChange={setAcknowledged}
              tone="danger"
            >
              {t(
                "I understand that dataConsent cannot be revoked after the on-chain join, and I confirm the stake amount.",
                "我理解 dataConsent 在链上 join 后不可撤回，并确认质押金额。",
              )}
            </CheckboxField>

            {joinError && <Alert tone="error">{joinError}</Alert>}
          </div>
        </Dialog>
      )}

      <Dialog
        open={miningOpen}
        onClose={() => !joinPending && setMiningOpen(false)}
        eyebrow={t("Mining terms", "挖矿条款")}
        title={t("Confirm miner data terms", "确认矿工数据条款")}
        description={t(
          "Joining a mining contest requires no stake, but data is retained by force and used only for RSI repair.",
          "加入挖矿赛不需要质押，但数据会被强制留存，仅用于 RSI 修复。",
        )}
        size="md"
        footer={
          <div className="dialog__footer-row">
            <Button variant="ghost" onClick={() => setMiningOpen(false)} disabled={joinPending}>
              {t("Cancel", "取消")}
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
            {miningIntent ??
              t(
                "By joining a mining contest, you agree that the platform retains all messages, replies, and tool traces.",
                "加入挖矿赛即视为同意平台留存全部消息、回复与工具轨迹。",
              )}
          </div>
          <CheckboxField
            checked={termsAccepted}
            onChange={setTermsAccepted}
            tone="danger"
          >
            {t(
              "I have read and agree: miner data is used only for RSI repair and will not enter the data market or be sold.",
              "我已阅读并同意：矿工数据仅用于 RSI 修复，不进入数据市场、不出售。",
            )}
          </CheckboxField>
          {joinError && <Alert tone="error">{joinError}</Alert>}
        </div>
      </Dialog>
    </div>
  );
}

