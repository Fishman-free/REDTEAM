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
import { keccak256, toHex, type Address } from "viem";
import { useAccount, useChainId, useWriteContract } from "wagmi";
import {
  api,
  ApiClientError,
  type Contest,
  type MessageResponse,
} from "../../lib/api";
import { attackFeeWei, isContestLive } from "../../lib/contest";
import { arenaAbi, rtmAbi } from "../../lib/contracts";
import { errorText, formatRtm, timeAgo } from "../../lib/format";
import { useLocalStorage, useNow } from "../../lib/hooks";
import {
  useAllowance,
  useDataConsent,
  usePlatform,
  useRtmBalance,
} from "../../lib/platform";
import { isSupportedChain } from "../../lib/chain";
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

function replyText(response: MessageResponse): string {
  if (response.reply && response.reply.trim()) return response.reply;
  if (response.error?.message) return `智能体返回错误：${response.error.message}`;
  if (response.defender_fault) return "守方基础设施故障，平台将按弃权处理。";
  return "（没有回复）";
}

export function PaidChat({ contest, joined, onAfterSend }: PaidChatProps) {
  const { address, isConnected } = useAccount();
  const chainId = useChainId();
  const { writeContractAsync } = useWriteContract();
  const { meta } = usePlatform();
  const { trackTransaction } = useActivity();
  const { toast } = useToast();
  const balance = useRtmBalance(address);
  const allowance = useAllowance(address, meta.addresses.arena);
  const consent = useDataConsent(contest.id, address);
  const now = useNow(15_000);
  const live = isContestLive(contest, now);
  const correctChain = isSupportedChain(chainId);
  const fee = attackFeeWei(contest, meta);

  const storageSuffix = useMemo(() => {
    const who = address?.toLowerCase() ?? "guest";
    return `${chainId}:${contest.id.toLowerCase()}:${who}`;
  }, [address, chainId, contest.id]);

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
    throw lastError ?? new Error("消息未被平台处理");
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
      text: replyText(response),
      tone: response.defender_fault ? "warning" : "muted",
    });
    if (!response.persisted) {
      append({
        role: "system",
        text: "本轮内容按 opt-out 处理，只在内存中运行，没有落盘、不可出售。",
        tone: "muted",
      });
    }
    if (response.defender_fault) {
      append({
        role: "system",
        text: "守方基础设施故障已记录；平台会按弃权路径结算。",
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
      title: "消息已送达",
      description: `第 ${response.turn} 轮回复已返回。`,
      tone: response.defender_fault ? "warning" : "success",
    });
    window.setTimeout(() => setStep("idle"), 2_000);
  }

  async function send() {
    setError("");
    if (!isConnected || !address) {
      setError("请先连接钱包。");
      return;
    }
    if (!correctChain) {
      setError("请先切换到 RTM Testnet（48850）。");
      return;
    }
    if (!joined) {
      setError("你需要先加入这场比赛。");
      return;
    }
    if (!live) {
      setError("比赛已经结束，不能再发送付费消息。");
      return;
    }
    if (pendingTurn) {
      setError("还有一笔消息未送达，请先继续送达或丢弃记录。");
      return;
    }
    const text = content.trim();
    if (!text) {
      setError("请输入要发送的消息。");
      return;
    }
    if (text.length > 1_000) {
      setError("消息最多 1000 个字符。");
      return;
    }
    if (balance.data !== undefined && balance.data < fee) {
      setError("RTM 余额不足，请先去水龙头领取测试 RTM。");
      return;
    }
    setBusy(true);
    try {
      const currentAllowance = allowance.data ?? 0n;
      if (currentAllowance < fee) {
        setStep("approve");
        const desired = fee * 5n;
        const approvalAmount =
          balance.data !== undefined && balance.data < desired ? fee : desired;
        const approvalHash = await writeContractAsync({
          address: meta.addresses.rtm as Address,
          abi: rtmAbi,
          functionName: "approve",
          args: [meta.addresses.arena as Address, approvalAmount],
        });
        await trackTransaction(approvalHash, "授权消息费", "approve");
      }

      setStep("chain");
      const msgHash = keccak256(
        toHex(`${address}:${contest.id}:${Date.now()}:${newId()}:${text}`),
      );
      const attackHash = await writeContractAsync({
        address: meta.addresses.arena as Address,
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
      await trackTransaction(attackHash, "发送付费消息", "attack");
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
      toast({ title: "送达失败", description: errorText(reason), tone: "error" });
      setStep("idle");
    } finally {
      setBusy(false);
    }
  }

  const allowanceCount = fee > 0n && allowance.data ? allowance.data / fee : 0n;
  const lowBalance =
    balance.data !== undefined && balance.data < fee && fee > 0n;
  const lockedReason = !isConnected
    ? "连接钱包后发送消息"
    : !correctChain
      ? "切换网络后发送消息"
      : !joined
        ? "先加入这场战斗，才能发送付费消息"
        : !live
          ? "比赛已结束，对话已关闭"
          : null;

  return (
    <section className="chat">
      <header className="chat__head">
        <div>
          <p className="eyebrow">Paid dialogue</p>
          <h2 className="chat__title">付费对话</h2>
        </div>
        <div className="chat__head-meta">
          <Badge tone="accent" dot>
            每条 {formatRtm(fee, { maxFraction: 4 })} RTM
          </Badge>
          {consent.data !== undefined && (
            <Badge tone={consent.data ? "success" : "neutral"}>
              {consent.data ? "数据可售 · 30%" : "不落盘 · 不可售"}
            </Badge>
          )}
        </div>
      </header>

      <div className="chat__context">
        <span className="mono">TARGET {contest.id.slice(0, 10)}…</span>
        <span className="chat__context-divider" aria-hidden="true" />
        <span>
          唯一工具面 <code>get_balance</code> / <code>transfer_rtm</code>
        </span>
      </div>

      <div className="chat__log" ref={logRef} aria-live="polite" aria-label="攻击对话记录">
        {messages.length === 0 && !pendingTurn && (
          <div className="chat__empty">
            <Bot size={22} />
            <div>
              <strong>等待第一条付费消息</strong>
              <p>
                每条消息先授权费用，再调用 <code>attack</code> 上链，索引器确认后平台运行智能体。
                诱导它调用 <code>transfer_rtm</code> 就能触发结算。
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
              <strong>这笔消息已上链，但还没有送达智能体</strong>
              <p>
                {timeAgo(pendingTurn.createdAt)}提交 · 内容 “{pendingTurn.content.slice(0, 60)}
                {pendingTurn.content.length > 60 ? "…" : ""}”
              </p>
              <div className="chat__pending-actions">
                <Button
                  size="sm"
                  variant="secondary"
                  loading={busy}
                  onClick={() => void continuePending()}
                >
                  继续送达
                </Button>
                <Button size="sm" variant="quiet" onClick={() => setDiscardOpen(true)}>
                  丢弃记录
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
          title="RTM 余额不足"
          action={
            <Link className="btn btn--ghost btn--sm" to="/faucet">
              <Droplets size={13} />
              去领水
            </Link>
          }
        >
          当前余额 {formatRtm(balance.data)} RTM，单条消息需要{" "}
          {formatRtm(fee, { maxFraction: 4 })} RTM。
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
              发送给守方智能体的消息
            </label>
            <textarea
              id="chat-input"
              className="chat__input"
              value={content}
              maxLength={1_000}
              rows={3}
              placeholder="尝试诱导智能体把钱转给你的地址。不要发送真实敏感信息。"
              onChange={(event) => setContent(event.target.value)}
              disabled={busy}
            />
            <div className="chat__composer-meta">
              <span className="mono">{content.length} / 1000</span>
              <span className="chat__balance">
                <ShieldCheck size={11} />
                余额 {formatRtm(balance.data)} RTM
              </span>
            </div>
          </div>
          <div className="chat__composer-actions">
            <div className="chat__steps" aria-label="发送步骤">
              <StepDot label="授权" state={step === "approve" ? "active" : ""} done={step === "chain" || step === "deliver" || step === "done"} />
              <span className="chat__step-line" />
              <StepDot label="上链" state={step === "chain" ? "active" : ""} done={step === "deliver" || step === "done"} />
              <span className="chat__step-line" />
              <StepDot label="送达" state={step === "deliver" ? "active" : ""} done={step === "done"} />
            </div>
            <Button
              onClick={() => void send()}
              loading={busy}
              iconLeft={<Send size={14} />}
              disabled={!content.trim() || Boolean(pendingTurn)}
            >
              付费发送
            </Button>
          </div>
          <p className="chat__hint">
            {allowanceCount > 0n
              ? `已授权约 ${allowanceCount.toString()} 条消息；用完前无需重复 approve。`
              : "首次发送会自动授权最多 5 条消息的费用，减少钱包确认次数。"}
            {" "}dataConsent 在加入后不可撤回。
          </p>
        </div>
      )}

      <Dialog
        open={discardOpen}
        onClose={() => setDiscardOpen(false)}
        title="丢弃未送达记录？"
        description="链上费用已经支付，丢弃后可能无法再取回这次回复。"
        size="sm"
        footer={
          <div className="dialog__footer-row">
            <Button variant="ghost" onClick={() => setDiscardOpen(false)}>
              取消
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setPendingTurn(null);
                setDiscardOpen(false);
                append({
                  role: "system",
                  text: "已丢弃未送达记录；链上费用不会退回。",
                  tone: "danger",
                });
              }}
            >
              确认丢弃
            </Button>
          </div>
        }
      >
        <p className="muted small">
          建议先点“继续送达”，索引器通常几秒内就会确认这笔付费消息。
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
          <span className="bubble__role">{attacker ? "攻方" : "守方智能体"}</span>
          <span className="bubble__time">
            {new Date(message.at * 1000).toLocaleTimeString("zh-CN", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
        <p>{message.text}</p>
      </div>
    </div>
  );
}
