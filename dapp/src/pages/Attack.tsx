import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Crosshair,
  Droplets,
  MessageSquare,
  Search,
  Shield,
  Swords,
  Timer,
  Wallet,
} from "lucide-react";
import { formatEther, type Address } from "viem";
import { useAccount } from "wagmi";
import { api } from "../lib/api";
import {
  attackFeeWei,
  contestEndMs,
  isContestLive,
  requiredStakeWei,
} from "../lib/contest";
import { arenaAbi, rtmAbi } from "../lib/contracts";
import {
  errorText,
  formatDateTime,
  formatRtmUnit,
  stateLabel,
} from "../lib/format";
import { useNow } from "../lib/hooks";
import { useI18n } from "../lib/i18n";
import {
  requireAddresses,
  useAllowance,
  useContestQuery,
  useContestsQuery,
  useIsAttacker,
  usePlatform,
  useRemainingStake,
  useRtmBalance,
} from "../lib/platform";
import { isSupportedChain } from "../lib/chain";
import { useWalletChainId } from "../lib/useWalletChainId";
import { useArenaWriteContract } from "../lib/useArenaWriteContract";
import { useActivity } from "../context/ActivityContext";
import { useToast } from "../context/ToastContext";
import { AddressChip, CopyButton } from "../components/ui/Address";
import { Alert } from "../components/ui/Alert";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { CheckboxField } from "../components/ui/Field";
import { Countdown } from "../components/ui/Countdown";
import { EmptyState } from "../components/ui/EmptyState";
import { Panel } from "../components/ui/Panel";
import { SectionHeader } from "../components/ui/SectionHeader";
import { SkeletonCard } from "../components/ui/Skeleton";
import { Stat } from "../components/ui/Stat";
import { AttackAgent } from "../components/contest/AttackAgent";
import { ContestStatusBadge } from "../components/contest/ContestStatusBadge";
import { PaidChat } from "../components/contest/PaidChat";
import { ConnectPrompt } from "../components/wallet/ConnectPrompt";

export default function Attack() {
  const { t } = useI18n();
  const { meta } = usePlatform();
  const now = useNow(30_000);
  const [params, setParams] = useSearchParams();
  const selectedId = (params.get("contest") ?? "").trim().toLowerCase();
  const contestsQuery = useContestsQuery();
  const [search, setSearch] = useState("");

  const contests = useMemo(
    () =>
      (contestsQuery.data ?? [])
        .filter((contest) => !contest.is_mining && !contest.is_byoa)
        .sort((a, b) => {
          const live = (value: typeof a) => (value.state === "live" ? 0 : 1);
          if (live(a) !== live(b)) return live(a) - live(b);
          return contestEndMs(a) - contestEndMs(b);
        }),
    [contestsQuery.data],
  );

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return contests;
    return contests.filter(
      (contest) =>
        contest.id.toLowerCase().includes(needle) ||
        contest.defender.toLowerCase().includes(needle),
    );
  }, [contests, search]);

  const selectContest = (id: string) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("contest", id);
      return next;
    });
  };

  if (selectedId && /^0x[0-9a-f]{64}$/.test(selectedId)) {
    return (
      <AttackConsole
        contestId={selectedId}
        onBack={() =>
          setParams((current) => {
            const next = new URLSearchParams(current);
            next.delete("contest");
            return next;
          })
        }
      />
    );
  }

  return (
    <div className="attack-page">
      <SectionHeader
        eyebrow={t("Attacker entrance", "攻方入口")}
        title={
          <>
            {t("Pick a target, ", "选一个目标，")}
            <em>{t("then attack", "开始进攻")}</em>
          </>
        }
        description={t(
          "Choose a live standard contest. After joining, the paid chat is the attack console: every message costs the listed fee and is signed by your wallet.",
          "选择一场进行中的普通赛。加入后，付费对话就是你的进攻控制台：每条消息按标价收费，并由你的钱包签名。",
        )}
        actions={
          <Link to="/faucet" className="btn btn--ghost btn--sm">
            <Droplets size={13} /> {t("Need tRTM?", "需要 tRTM？")}
          </Link>
        }
      />

      <section className="arena-brief">
        <div className="arena-brief__item">
          <span className="mono">01</span>
          <div>
            <strong>{t("Choose a target", "选择目标")}</strong>
            <p>{t("Live standard contests are listed first.", "进行中的普通赛排在最前。")}</p>
          </div>
        </div>
        <div className="arena-brief__item">
          <span className="mono">02</span>
          <div>
            <strong>{t("Join with stake", "质押加入")}</strong>
            <p>{t("Approve the attacker stake once, then send paid messages.", "授权一次攻方质押，然后逐条发送付费消息。")}</p>
          </div>
        </div>
        <div className="arena-brief__item">
          <span className="mono">03</span>
          <div>
            <strong>{t("Attack manually or with an agent", "手动或 Agent 进攻")}</strong>
            <p>{t("Type messages yourself, or let an agent generate them while your wallet pays.", "自己输入消息，或让 agent 生成消息、你的钱包付款。")}</p>
          </div>
        </div>
      </section>

      <div className="filter-bar">
        <label className="search-box">
          <Search size={14} aria-hidden="true" />
          <span className="sr-only">{t("Search contests", "搜索比赛")}</span>
          <input
            className="search-box__input"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("Contest ID or defender address", "比赛 ID 或守方地址")}
          />
        </label>
        <div className="filter-bar__right">
          <Badge tone="neutral">
            {visible.length} {t("targets", "个目标")}
          </Badge>
          <Button
            size="sm"
            variant="quiet"
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
      ) : visible.length === 0 ? (
        <EmptyState
          icon={<Crosshair size={22} />}
          title={t("No attackable contests", "暂无可进攻的比赛")}
          description={t(
            "A standard contest appears here after a defender registers and creates it.",
            "守方注册并创建普通赛后，会出现在这里。",
          )}
          action={
            <Link className="btn btn--ghost btn--sm" to="/defend">
              {t("Register as a defender", "去注册守方")}
            </Link>
          }
        />
      ) : (
        <div className="attack-targets">
          {visible.map((contest) => {
            const fee = attackFeeWei(contest, meta);
            const stake = requiredStakeWei(contest);
            return (
              <article className="attack-target" key={contest.id}>
                <div className="attack-target__top">
                  <ContestStatusBadge contest={contest} now={now} />
                  <span className="mono muted">{contest.id.slice(0, 12)}…</span>
                </div>
                <div className="attack-target__main">
                  <div>
                    <p className="mono muted">{t("DEFENDER", "守方")}</p>
                    <AddressChip value={contest.defender} />
                  </div>
                  <div>
                    <p className="mono muted">{t("STAKE TO JOIN", "加入质押")}</p>
                    <strong>{formatRtmUnit(stake)}</strong>
                  </div>
                  <div>
                    <p className="mono muted">{t("PER MESSAGE", "单条费用")}</p>
                    <strong>{formatRtmUnit(fee, { maxFraction: 4 })}</strong>
                  </div>
                  <div>
                    <p className="mono muted">{t("PAID MESSAGES", "已付费消息")}</p>
                    <strong>{contest.paid_count}</strong>
                  </div>
                </div>
                <div className="attack-target__foot">
                  <span>
                    <Timer size={12} />{" "}
                    {contest.state === "live" ? (
                      <Countdown endMs={contestEndMs(contest)} showIcon={false} label="" />
                    ) : (
                      stateLabel(contest.state)
                    )}
                  </span>
                  <Button size="sm" onClick={() => selectContest(contest.id)}>
                    {t("Attack this target", "进攻这个目标")}
                    <ArrowRight size={13} />
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AttackConsole({
  contestId,
  onBack,
}: {
  contestId: string;
  onBack: () => void;
}) {
  const { t } = useI18n();
  const query = useContestQuery(contestId);
  const contest = query.data?.contest;
  const detail = query.data;
  const { address, isConnected } = useAccount();
  const chainId = useWalletChainId();
  const { meta, addresses } = usePlatform();
  const { writeContractAsync } = useArenaWriteContract();
  const { trackTransaction } = useActivity();
  const { toast } = useToast();
  const now = useNow(1_000);
  const isAttacker = useIsAttacker(contestId, address);
  const remaining = useRemainingStake(contestId, address);
  const allowance = useAllowance(address, addresses?.arena);
  const balance = useRtmBalance(address);
  const [consentChoice, setConsentChoice] = useState<boolean | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [joinPending, setJoinPending] = useState(false);
  const [joinError, setJoinError] = useState("");
  const [mode, setMode] = useState<"manual" | "agent">("manual");

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

  async function joinContest(dataConsent: boolean) {
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
      const refreshed = await allowance.refetch();
      const available = refreshed.error ? 0n : refreshed.data ?? 0n;
      if (available < approveAmount) {
        const approvalHash = await writeContractAsync({
          address: requireAddresses(addresses).rtm,
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
        address: requireAddresses(addresses).arena,
        abi: arenaAbi,
        functionName: "join",
        args: [contest.id as `0x${string}`, BigInt(intent.args[1]), intent.args[2]],
      });
      await trackTransaction(joinHash, t("Join contest", "加入战场"), "join");
      toast({
        title: t("Joined the contest", "已加入战场"),
        description: dataConsent
          ? t(
              "You agreed to post-contest data sales (70% platform / 30% you).",
              "你同意了赛后数据出售（平台 70% / 你 30%）。",
            )
          : t("You opted out; the dialogue cannot be sold.", "你选择了不落盘；对话不可出售。"),
        tone: "success",
      });
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

  if (query.isLoading) {
    return (
      <div className="attack-loading">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (query.isError || !contest || !detail) {
    return (
      <EmptyState
        title={t("Contest not found", "找不到这场战斗")}
        description={t(
          "The contest may not be indexed yet. Try again after the indexer syncs.",
          "比赛可能尚未被索引，等索引器同步后再试。",
        )}
        action={
          <Button size="sm" onClick={onBack}>
            <ArrowLeft size={13} /> {t("Back to targets", "返回目标列表")}
          </Button>
        }
      />
    );
  }

  const attackUrl =
    typeof window === "undefined"
      ? `/attack?contest=${contest.id}`
      : `${window.location.origin}/attack?contest=${contest.id}`;

  return (
    <div className="attack-console">
      <div className="detail-back">
        <button type="button" className="detail-back__link" onClick={onBack}>
          <ArrowLeft size={13} /> {t("Targets", "目标列表")}
        </button>
        <span className="mono">
          {t("ATTACK", "进攻")} / {contest.id.slice(0, 12)}…
        </span>
      </div>

      <header className="detail-head">
        <div className="detail-head__main">
          <div className="detail-head__badges">
            <ContestStatusBadge contest={contest} now={now} />
            <Badge tone="neutral">{t("NORMAL", "普通")}</Badge>
            {joined && <Badge tone="success" dot>{t("Joined as attacker", "已作为攻方加入")}</Badge>}
          </div>
          <h1 className="detail-head__title">
            {t("Attack console", "进攻控制台")}{" "}
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
              <Timer size={13} /> <Countdown endMs={endMs} label={t("Remaining", "剩余")} />
            </span>
          </div>
        </div>
        <div className="detail-head__aside">
          <span className="detail-head__aside-label mono">
            {t("YOUR ATTACK", "你的进攻")}
          </span>
          <div className="attack-fee">
            <strong>{formatRtmUnit(fee, { maxFraction: 4 })}</strong>
            <span>{t("per message", "每条消息")}</span>
          </div>
          <span className="detail-head__aside-foot mono">
            {t("Stake", "质押")} {formatRtmUnit(stake)} ·{" "}
            {formatDateTime(Number(contest.end))}
          </span>
        </div>
      </header>

      <div className="stat-strip">
        <Stat label={t("Prize pool S", "奖池 S")} value={formatRtmUnit(contest.stake)} tone="accent" />
        <Stat label={t("Attacker stake", "攻方质押")} value={formatRtmUnit(stake)} />
        <Stat label={t("Per message", "单条消息")} value={formatRtmUnit(fee, { maxFraction: 4 })} />
        <Stat label={t("Paid messages", "已付费消息")} numericValue={contest.paid_count} format={(value) => String(Math.round(value))} />
      </div>

      {!isConnected ? (
        <ConnectPrompt
          title={t("Connect the attacker wallet", "连接攻方钱包")}
          description={t(
            "The attacker wallet signs the stake and every paid message. Use a different wallet from the defender.",
            "攻方钱包用于签署质押与每条付费消息。请使用与守方不同的钱包。",
          )}
        />
      ) : !correctChain ? (
        <ConnectPrompt title={t("Switch to RTM Testnet first", "请先切换到 RTM Testnet")} compact />
      ) : isDefender ? (
        <Alert tone="error" title={t("This is your own defender contest", "这是你自己的守方比赛")}>
          <p>
            {t(
              "The defender wallet cannot join or attack its own contest. Open the link below in another wallet to act as the attacker.",
              "守方钱包不能加入或攻击自己的比赛。请用另一个钱包打开下面的链接作为攻方。",
            )}
          </p>
          <div className="row-actions" style={{ marginTop: 10 }}>
            <CopyButton value={attackUrl} label={t("Copy attacker link", "复制攻方链接")} />
            <Link className="btn btn--ghost btn--sm" to={`/arena/${contest.id}`}>
              {t("Open battlefield", "打开战场")}
            </Link>
          </div>
        </Alert>
      ) : !live ? (
        <Alert tone="info" title={t("Contest ended", "比赛已结束")}>
          {t("Paid messages are closed.", "已关闭付费消息。")}{" "}
          <Link to={`/arena/${contest.id}`}>{t("View result", "查看结果")}</Link>
        </Alert>
      ) : !joined ? (
        <Panel
          eyebrow={t("Step 1 · Join", "第一步 · 加入")}
          title={t("Approve stake and enter", "授权质押并进入")}
          bracket
        >
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
              <dt>
                {t("Your", "你的")} <span className="preserve-case">tRTM</span>
              </dt>
              <dd>{formatRtmUnit(balance.data)}</dd>
            </div>
            <div>
              <dt>{t("Wallet", "钱包")}</dt>
              <dd>
                <AddressChip value={address!} />
              </dd>
            </div>
          </dl>

          {balance.data !== undefined && balance.data < stake && (
            <Alert
              tone="warning"
              title={t("Insufficient balance", "余额不足")}
              action={
                <Link className="btn btn--ghost btn--sm" to="/faucet">
                  <Droplets size={13} /> {t("Get test tRTM", "去领水")}
                </Link>
              }
            >
              {t(
                `Joining requires ${formatRtmUnit(stake)}; current balance ${formatRtmUnit(balance.data)}.`,
                `加入需要 ${formatRtmUnit(stake)}，当前余额 ${formatRtmUnit(balance.data)}。`,
              )}
            </Alert>
          )}

          <div className="choice-grid">
            <button
              type="button"
              className={`choice ${consentChoice === true ? "is-selected" : ""}`.trim()}
              onClick={() => setConsentChoice(true)}
            >
              <span className="choice__icon">
                <Swords size={17} />
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
              "I understand that dataConsent cannot be revoked after joining, and I confirm the stake amount.",
              "我理解 dataConsent 在加入后不可撤回，并确认质押金额。",
            )}
          </CheckboxField>

          {joinError && <Alert tone="error">{joinError}</Alert>}

          <Button
            block
            loading={joinPending}
            disabled={consentChoice === null || !acknowledged}
            iconLeft={<Swords size={14} />}
            onClick={() => consentChoice !== null && void joinContest(consentChoice)}
          >
            {t("Approve and join", "授权并加入")}
          </Button>
          <p className="position__hint">
            {t(
              "After joining, the attack composer appears below. Every message pays the fee on-chain before reaching the defender agent.",
              "加入后下方会出现进攻输入框。每条消息先上链付费，再交给守方 agent。",
            )}
          </p>
        </Panel>
      ) : (
        <div className="attack-modes">
          <div className="attack-modes__tabs" role="tablist" aria-label={t("Attack mode", "进攻模式")}>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "manual"}
              className={`attack-mode ${mode === "manual" ? "is-active" : ""}`.trim()}
              onClick={() => setMode("manual")}
            >
              <MessageSquare size={15} />
              <span>
                <strong>{t("Manual attack", "手动进攻")}</strong>
                <small>{t("You type every message", "自己输入每条消息")}</small>
              </span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "agent"}
              className={`attack-mode ${mode === "agent" ? "is-active" : ""}`.trim()}
              onClick={() => setMode("agent")}
            >
              <Crosshair size={15} />
              <span>
                <strong>{t("Agent attack", "Agent 进攻")}</strong>
                <small>{t("A model writes, your wallet signs", "模型出招，钱包签名")}</small>
              </span>
            </button>
          </div>

          {mode === "manual" ? (
            <PaidChat
              contest={contest}
              joined={joined}
              onAfterSend={() => void query.refetch()}
            />
          ) : (
            <AttackAgent
              contest={contest}
              joined={joined}
              onAfterSend={() => void query.refetch()}
            />
          )}

          <Panel eyebrow={t("Your position", "你的位置")} title={t("Attacker position", "攻方位置")} tone="flat">
            <dl className="position__grid">
              <div>
                <dt>{t("Initial stake", "初始质押")}</dt>
                <dd>{formatRtmUnit(attackerInfo?.stake)}</dd>
              </div>
              <div>
                <dt>{t("Paid", "已付费")}</dt>
                <dd>
                  {attackerInfo?.paid ?? 0} {t("messages", "条")}
                </dd>
              </div>
              <div>
                <dt>{t("Delivered", "已送达")}</dt>
                <dd>
                  {attackerInfo?.delivered ?? 0} {t("messages", "条")}
                </dd>
              </div>
              <div>
                <dt>{t("Remaining stake", "剩余质押")}</dt>
                <dd>{formatRtmUnit(remaining.data)}</dd>
              </div>
            </dl>
            <div className="row-actions">
              <Link className="btn btn--ghost btn--sm" to={`/arena/${contest.id}`}>
                <Wallet size={13} /> {t("Battlefield details", "战场详情")}
              </Link>
              <Link className="btn btn--ghost btn--sm" to="/faucet">
                <Droplets size={13} /> {t("Faucet", "水龙头")}
              </Link>
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}
