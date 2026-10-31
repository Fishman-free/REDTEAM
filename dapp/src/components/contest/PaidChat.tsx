import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Droplets,
  LockKeyhole,
  Send,
  ShieldCheck,
  User,
} from "lucide-react";
import { keccak256, toHex } from "viem";
import { useAccount } from "wagmi";
import {
  api,
  ApiClientError,
  type Contest,
  type MessageResponse,
} from "../../lib/api";
import { attackFeeWei, isContestLive } from "../../lib/contest";
import { arenaAbi, rtmAbi } from "../../lib/contracts";
import { errorText, formatRtm, timeAgo } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import { useLocalStorage, useNow } from "../../lib/hooks";
import {
  useAllowance,
  useDataConsent,
  requireAddresses,
  usePlatform,
  useRtmBalance,
} from "../../lib/platform";
import { CHAIN_ID, isSupportedChain } from "../../lib/chain";
import { useWalletChainId } from "../../lib/useWalletChainId";
import { useArenaWriteContract } from "../../lib/useArenaWriteContract";
import { useActivity } from "../../context/ActivityContext";
import { useToast } from "../../context/ToastContext";
import { Alert } from "../ui/Alert";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

type ChatRole = "attacker" | "agent" | "system";

interface ChatEntry {
  id: string;
  role: ChatRole;
  text: string;
  at: number;
  txHash?: string;
  tone?: "muted" | "success" | "warning" | "danger";
}

interface PendingTurn {
  content: string;
  msgHash: string;
  txHash: `0x${string}`;
  createdAt: number;
}

interface PaidChatProps {
  contest: Contest;
  joined: boolean;
  onAfterSend?: () => void;
}

type Step = "idle" | "approve" | "chain" | "deliver" | "done";

const sleep = (milliseconds: number) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function replyText(
  response: MessageResponse,
  t: (en: string, zh: string) => string,
): string {
  if (response.reply && response.reply.trim()) return response.reply;
  if (response.error?.message) {
    return t(
      `Agent error: ${response.error.message}`,
      `agent 返回错误：${response.error.message}`,
    );
  }
  if (response.defender_fault) {
    return t(
      "Defender infrastructure failure; the platform will treat it as a forfeit.",
      "守方基础设施故障，平台将按弃权处理。",
    );
  }
  return t("(No reply)", "（没有回复）");
}

export function PaidChat({ contest, joined, onAfterSend }: PaidChatProps) {
  const { address, isConnected } = useAccount();
  const walletChainId = useWalletChainId();
  const { writeContractAsync } = useArenaWriteContract();
  const { meta, addresses } = usePlatform();
  const { trackTransaction } = useActivity();
  const { toast } = useToast();
  const { t } = useI18n();
  const balance = useRtmBalance(address);
  const allowance = useAllowance(address, addresses?.arena);
  const consent = useDataConsent(contest.id, address);
  const now = useNow(15_000);
  const live = isContestLive(contest, now);
  const correctChain = isSupportedChain(walletChainId);
  const fee = attackFeeWei(contest, meta);

  const storageSuffix = useMemo(() => {
    const who = address?.toLowerCase() ?? "guest";
    return `${CHAIN_ID}:${contest.id.toLowerCase()}:${who}`;
  }, [address, contest.id]);

  const [messages, setMessages] = useLocalStorage<ChatEntry[]>(
    `rtm.chat.v1:${storageSuffix}`,
    [],
  );
  const [pendingTurn, setPendingTurn] = useLocalStorage<PendingTurn | null>(
    `rtm.pending.v1:${storageSuffix}`,
    null,
  );
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<Step>("idle");
  const [error, setError] = useState("");
  const [discardOpen, setDiscardOpen] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages.length, pendingTurn]);

  function append(entry: Omit<ChatEntry, "id" | "at">) {
    setMessages((current) =>
      [...current, { ...entry, id: newId(), at: Math.floor(Date.now() / 1000) }].slice(-160),
    );
  }

  async function requestDelivery(turn: PendingTurn): Promise<MessageResponse> {
    let lastError: unknown = null;
    for (let attempt = 0; attempt < 15; attempt += 1) {
      try {
        return await api.sendMessage(contest.id, {
          tx_hash: turn.txHash,
          content: turn.content,
        });
      } catch (reason) {
        lastError = reason;
        if (reason instanceof ApiClientError) {
          const detail = typeof reason.detail === "string" ? reason.detail : "";
          if (reason.status === 409 && /already processed/i.test(detail)) throw reason;
          if (reason.status === 503 || reason.status === 403 || reason.status === 410) throw reason;
          if ([408, 409, 502].includes(reason.status)) {
            await sleep(2_000);
            continue;
          }
        }
        throw reason;
      }
    }
    throw lastError ?? new Error(
      t("The message was not processed by the platform.", "消息未被平台处理。"),
    );
  }

  async function runDelivery(turn: PendingTurn) {
    setStep("deliver");
    const response = await requestDelivery(turn);
    append({
      role: "attacker",
      text: turn.content,
      txHash: turn.txHash,
      tone: "success",
    });
    append({
      role: "agent",
      text: replyText(response, t),
      tone: response.defender_fault ? "warning" : "muted",
    });
    if (!response.persisted) {
      append({
        role: "system",
        text: t(
          "This turn was handled as an opt-out; it ran only in memory and was not persisted or sold.",
          "本轮内容按 opt-out 处理，只在内存中运行，没有落盘、不可出售。",
        ),
        tone: "muted",
      });
    }
    if (response.defender_fault) {
      append({
        role: "system",
        text: t(
          "The defender infrastructure fault has been recorded; the platform will settle via the forfeit path.",
          "守方基础设施故障已记录；平台会按弃权路径结算。",
        ),
        tone: "warning",
      });
    }
    setPendingTurn(null);
    setContent("");
    setStep("done");
    void balance.refetch();
    void allowance.refetch();
    onAfterSend?.();
    toast({
      title: t("Message delivered", "消息已送达"),
      description: t(
        `Round ${response.turn} reply received.`,
        `第 ${response.turn} 轮回复已返回。`,
      ),
      tone: response.defender_fault ? "warning" : "success",
    });
    window.setTimeout(() => setStep("idle"), 2_000);
  }

  async function send() {
    setError("");
    if (!isConnected || !address) {
      setError(t("Connect your wallet first.", "请先连接钱包。"));
      return;
    }
    if (!correctChain) {
      setError(t("Switch to RTM Testnet (48850) first.", "请先切换到 RTM Testnet（48850）。"));
      return;
    }
    if (!addresses) {
      setError(
        t(
          "The platform API is not reachable yet, so contract addresses are unavailable. Retry once it is back.",
          "平台 API 尚未连通，暂时拿不到合约地址；请等 API 恢复后重试。",
        ),
      );
      return;
    }
    if (!joined) {
      setError(t("You need to join this contest first.", "你需要先加入这场比赛。"));
      return;
    }
    if (!live) {
      setError(
        t(
          "The contest has ended; paid messages can no longer be sent.",
          "比赛已经结束，不能再发送付费消息。",
        ),
      );
      return;
    }
    if (pendingTurn) {
      setError(
        t(
          "A message is still undelivered. Continue delivery or discard the record first.",
          "还有一笔消息未送达，请先继续送达或丢弃记录。",
        ),
      );
      return;
    }
    const text = content.trim();
    if (!text) {
      setError(t("Enter a message to send.", "请输入要发送的消息。"));
      return;
    }
    if (text.length > 1_000) {
      setError(t("Messages can be up to 1,000 characters.", "消息最多 1000 个字符。"));
      return;
    }
    if (balance.data !== undefined && balance.data < fee) {
      setError(
        t(
          "Insufficient tRTM balance. Get test tRTM from the faucet first.",
          "tRTM 余额不足，请先去水龙头领取测试 tRTM。",
        ),
      );
      return;
    }
    setBusy(true);
    try {
      // The cached allowance can be stale: joining the contest spends the
      // approval, but the query may still hold the pre-join value. Re-read it
      // before skipping approve, or the first paid message reverts on-chain.
      const refreshed = await allowance.refetch();
      const currentAllowance = refreshed.error ? 0n : refreshed.data ?? 0n;
      if (currentAllowance < fee) {
        setStep("approve");
        const desired = fee * 5n;
        const approvalAmount =
          balance.data !== undefined && balance.data < desired ? fee : desired;
        const approvalHash = await writeContractAsync({
          address: requireAddresses(addresses).rtm,
          abi: rtmAbi,
          functionName: "approve",
          args: [requireAddresses(addresses).arena, approvalAmount],
        });
        await trackTransaction(approvalHash, t("Approve message fees", "授权消息费"), "approve");
      }

      setStep("chain");
      const msgHash = keccak256(
        toHex(`${address}:${contest.id}:${Date.now()}:${newId()}:${text}`),
      );
      const attackHash = await writeContractAsync({
        address: requireAddresses(addresses).arena,
        abi: arenaAbi,
        functionName: "attack",
        args: [contest.id as `0x${string}`, msgHash],
      });
      const turn: PendingTurn = {
        content: text,
        msgHash,
        txHash: attackHash,
        createdAt: Math.floor(Date.now() / 1000),
      };
      setPendingTurn(turn);
      await trackTransaction(attackHash, t("Send paid message", "发送付费消息"), "attack");
      await runDelivery(turn);
    } catch (reason) {
      setError(errorText(reason));
      setStep("idle");
    } finally {
      setBusy(false);
    }
  }

  async function continuePending() {
    if (!pendingTurn) return;
    setError("");
    setBusy(true);
    try {
      await runDelivery(pendingTurn);
    } catch (reason) {
      setError(errorText(reason));
      toast({ title: t("Delivery failed", "送达失败"), description: errorText(reason), tone: "error" });
      setStep("idle");
    } finally {
      setBusy(false);
    }
  }

  const allowanceCount = fee > 0n && allowance.data ? allowance.data / fee : 0n;
  const lowBalance =
    balance.data !== undefined && balance.data < fee && fee > 0n;
  const lockedReason = !isConnected
    ? t("Connect your wallet to send messages", "连接钱包后发送消息")
    : !correctChain
      ? t("Switch networks to send messages", "切换网络后发送消息")
      : !addresses
        ? t(
            "Waiting for the platform API before messages can be sent",
            "正在等待平台 API，恢复后才能发送消息",
          )
        : !joined
          ? t("Join this contest before sending paid messages", "先加入这场战斗，才能发送付费消息")
          : !live
            ? t("The contest has ended; dialogue is closed", "比赛已结束，对话已关闭")
            : null;

  return (
    <section className="chat">
      <header className="chat__head">
        <div>
          <p className="eyebrow">{t("Paid dialogue", "付费对话")}</p>
          <h2 className="chat__title">{t("Paid chat", "付费对话")}</h2>
        </div>
        <div className="chat__head-meta">
          <Badge tone="accent" dot>
            {t(
              `${formatRtm(fee, { maxFraction: 4 })} tRTM per message`,
              `每条 ${formatRtm(fee, { maxFraction: 4 })} tRTM`,
            )}
          </Badge>
          {consent.data !== undefined && (
            <Badge tone={consent.data ? "success" : "neutral"}>
              {consent.data
                ? t("Data sellable · 30%", "数据可售 · 30%")
                : t("Not persisted · not sellable", "不落盘 · 不可售")}
            </Badge>
          )}
        </div>
      </header>

      <div className="chat__context">
        <span className="mono">{t("TARGET", "目标")} {contest.id.slice(0, 10)}…</span>
        <span className="chat__context-divider" aria-hidden="true" />
        <span>
          {t("Available tools", "唯一工具面")}{" "}
          <code>get_balance</code> / <code>transfer_rtm</code>
        </span>
      </div>

      <div
        className="chat__log"
        ref={logRef}
        aria-live="polite"
        aria-label={t("Attack dialogue log", "攻击对话记录")}
      >
        {messages.length === 0 && !pendingTurn && (
          <div className="chat__empty">
            <Bot size={22} />
            <div>
              <strong>{t("Waiting for the first paid message", "等待第一条付费消息")}</strong>
              <p>
                {t("Each message first requires a fee approval, then calls ", "每条消息先授权费用，再调用 ")}
                <code>attack</code>
                {t(
                  " on-chain; the platform runs the agent after the indexer confirms it. Trick it into calling ",
                  " 上链，索引器确认后平台运行 agent。诱导它调用 ",
                )}
                <code>transfer_rtm</code>
                {t(" to trigger settlement.", " 就能触发结算。")}
              </p>
            </div>
          </div>
        )}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {pendingTurn && (
          <div className="chat__pending">
            <CircleAlert size={15} />
            <div>
              <strong>
                {t(
                  "This message is on-chain but has not reached the agent yet",
                  "这笔消息已上链，但还没有送达 agent",
                )}
              </strong>
              <p>
                {t(
                  `Submitted ${timeAgo(pendingTurn.createdAt)} · content “`,
                  `${timeAgo(pendingTurn.createdAt)}提交 · 内容 “`,
                )}
                {pendingTurn.content.slice(0, 60)}
                {pendingTurn.content.length > 60 ? "…" : ""}”
              </p>
              <div className="chat__pending-actions">
                <Button
                  size="sm"
                  variant="secondary"
                  loading={busy}
                  onClick={() => void continuePending()}
                >
                  {t("Continue delivery", "继续送达")}
                </Button>
                <Button size="sm" variant="quiet" onClick={() => setDiscardOpen(true)}>
                  {t("Discard record", "丢弃记录")}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>

      {error && (
        <Alert tone="error" className="chat__alert">
          {error}
        </Alert>
      )}

      {lowBalance && (
        <Alert
          tone="warning"
          title={t("Insufficient tRTM balance", "tRTM 余额不足")}
          action={
            <Link className="btn btn--ghost btn--sm" to="/faucet">
              <Droplets size={13} />
              {t("Get test tRTM", "去领水")}
            </Link>
          }
        >
          {t(
            `Current balance ${formatRtm(balance.data)} tRTM; each message costs ${formatRtm(fee, { maxFraction: 4 })} tRTM.`,
            `当前余额 ${formatRtm(balance.data)} tRTM，单条消息需要 ${formatRtm(fee, { maxFraction: 4 })} tRTM。`,
          )}
        </Alert>
      )}

      {lockedReason ? (
        <div className="chat__locked">
          <LockKeyhole size={18} />
          <span>{lockedReason}</span>
        </div>
      ) : (
        <div className="chat__composer">
          <div className="chat__composer-top">
            <label htmlFor="chat-input" className="sr-only">
              {t("Message to the defender agent", "发送给守方 agent 的消息")}
            </label>
            <textarea
              id="chat-input"
              className="chat__input"
              value={content}
              maxLength={1_000}
              rows={3}
              placeholder={t(
                "Try to trick the agent into sending funds to your address. Do not share real sensitive information.",
                "尝试诱导 agent 把钱转给你的地址。不要发送真实敏感信息。",
              )}
              onChange={(event) => setContent(event.target.value)}
              disabled={busy}
            />
            <div className="chat__composer-meta">
              <span className="mono">{content.length} / 1000</span>
              <span className="chat__balance">
                <ShieldCheck size={11} />
                {t("Balance", "余额")} {formatRtm(balance.data)} tRTM
              </span>
            </div>
          </div>
          <div className="chat__composer-actions">
            <div className="chat__steps" aria-label={t("Send steps", "发送步骤")}>
              <StepDot label={t("Approve", "授权")} state={step === "approve" ? "active" : ""} done={step === "chain" || step === "deliver" || step === "done"} />
              <span className="chat__step-line" />
              <StepDot label={t("On-chain", "上链")} state={step === "chain" ? "active" : ""} done={step === "deliver" || step === "done"} />
              <span className="chat__step-line" />
              <StepDot label={t("Delivered", "送达")} state={step === "deliver" ? "active" : ""} done={step === "done"} />
            </div>
            <Button
              onClick={() => void send()}
              loading={busy}
              iconLeft={<Send size={14} />}
              disabled={!content.trim() || Boolean(pendingTurn)}
            >
              {t("Send paid message", "付费发送")}
            </Button>
          </div>
          <p className="chat__hint">
            {allowanceCount > 0n
              ? t(
                  `Message fees for about ${allowanceCount.toString()} messages have been approved; no repeat approval is needed until they run out.`,
                  `已授权约 ${allowanceCount.toString()} 条消息的费用；用完前无需重复 approve。`,
                )
              : t(
                  "The first send automatically approves up to 5 message fees to reduce wallet confirmations.",
                  "首次发送会自动授权最多 5 条消息的费用，减少钱包确认次数。",
                )}
            {" "}
            {t("dataConsent cannot be revoked after joining.", "dataConsent 在加入后不可撤回。")}
          </p>
        </div>
      )}

      <Dialog
        open={discardOpen}
        onClose={() => setDiscardOpen(false)}
        title={t("Discard undelivered record?", "丢弃未送达记录？")}
        description={t(
          "The on-chain fee has already been paid; discarding may make this reply unrecoverable.",
          "链上费用已经支付，丢弃后可能无法再取回这次回复。",
        )}
        size="sm"
        footer={
          <div className="dialog__footer-row">
            <Button variant="ghost" onClick={() => setDiscardOpen(false)}>
              {t("Cancel", "取消")}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setPendingTurn(null);
                setDiscardOpen(false);
                append({
                  role: "system",
                  text: t(
                    "Undelivered record discarded; the on-chain fee will not be refunded.",
                    "已丢弃未送达记录；链上费用不会退回。",
                  ),
                  tone: "danger",
                });
              }}
            >
              {t("Confirm discard", "确认丢弃")}
            </Button>
          </div>
        }
      >
        <p className="muted small">
          {t(
            "We recommend choosing “Continue delivery”; the indexer usually confirms this paid message within seconds.",
            "建议先点“继续送达”，索引器通常几秒内就会确认这笔付费消息。",
          )}
        </p>
      </Dialog>
    </section>
  );
}

function StepDot({ label, state, done }: { label: string; state: string; done: boolean }) {
  return (
    <span className={`chat-step ${state} ${done ? "is-done" : ""}`.trim()}>
      <span className="chat-step__dot" aria-hidden="true">
        {done ? <CheckCircle2 size={10} /> : null}
      </span>
      {label}
    </span>
  );
}

function MessageBubble({ message }: { message: ChatEntry }) {
  const { t, lang } = useI18n();
  if (message.role === "system") {
    return (
      <div className={`chat-system chat-system--${message.tone ?? "muted"}`}>
        {message.text}
      </div>
    );
  }
  const attacker = message.role === "attacker";
  return (
    <div className={`bubble-row ${attacker ? "bubble-row--attacker" : "bubble-row--agent"}`}>
      <span className="bubble-avatar" aria-hidden="true">
        {attacker ? <User size={13} /> : <Bot size={13} />}
      </span>
      <div className={`bubble bubble--${message.role}`}>
        <div className="bubble__meta">
          <span className="bubble__role">{attacker ? t("Attacker", "攻方") : t("Defender agent", "守方 agent")}</span>
          <span className="bubble__time">
            {new Date(message.at * 1000).toLocaleTimeString(
              lang === "en" ? "en-US" : "zh-CN",
              {
                hour: "2-digit",
                minute: "2-digit",
              },
            )}
          </span>
        </div>
        <p>{message.text}</p>
      </div>
    </div>
  );
}
