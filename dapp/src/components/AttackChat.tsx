import { useState } from "react";
import { keccak256, toHex } from "viem";
import { useAccount, usePublicClient, useWriteContract } from "wagmi";
import {
  ApiClientError,
  api,
  type Contest,
  type MessageResponse,
} from "../lib/api";
import { ADDRESSES, arenaAbi, rtmAbi } from "../lib/contracts";
import { errorText, formatRtm, shortAddr } from "../lib/format";

const sleep = (milliseconds: number) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export default function AttackChat({
  contest,
  feeWei,
}: {
  contest: Contest;
  feeWei: bigint;
}) {
  const { address, isConnected } = useAccount();
  const publicClient = usePublicClient();
  const { writeContractAsync } = useWriteContract();
  const [content, setContent] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [messages, setMessages] = useState<
    Array<{ role: "attacker" | "agent"; text: string }>
  >([]);

  async function send() {
    setError("");
    setStatus("");
    if (!isConnected || !address) {
      setError("请先连接钱包");
      return;
    }
    if (!publicClient) {
      setError("RPC 未就绪");
      return;
    }
    const text = content.trim();
    if (!text) {
      setError("请输入消息");
      return;
    }
    if (text.length > 1000) {
      setError("消息最多 1000 字符");
      return;
    }
    setPending(true);
    try {
      setStatus("1/3 授权消息费…");
      const approval = await writeContractAsync({
        address: ADDRESSES.rtm,
        abi: rtmAbi,
        functionName: "approve",
        args: [ADDRESSES.arena, feeWei],
      });
      await publicClient.waitForTransactionReceipt({ hash: approval });

      setStatus("2/3 发起 attack 付费消息…");
      const msgHash = keccak256(toHex(text));
      const attackHash = await writeContractAsync({
        address: ADDRESSES.arena,
        abi: arenaAbi,
        functionName: "attack",
        args: [contest.id as `0x${string}`, msgHash],
      });
      await publicClient.waitForTransactionReceipt({ hash: attackHash });

      setStatus("3/3 等待 indexer 确认并运行智能体…");
      let response: MessageResponse | null = null;
      let lastError: unknown = null;
      for (let attempt = 0; attempt < 12; attempt += 1) {
        try {
          response = await api.sendMessage(contest.id, {
            tx_hash: attackHash,
            content: text,
          });
          break;
        } catch (reason) {
          lastError = reason;
          if (reason instanceof ApiClientError && reason.status === 409) {
            await sleep(1500);
            continue;
          }
          throw reason;
        }
      }
      if (!response) throw lastError ?? new Error("消息未被 API 处理");

      const reply =
        response.reply ||
        response.error?.message ||
        (response.defender_fault
          ? "守方基础设施故障，平台将按弃权处理。"
          : "（无回复）");
      setMessages((previous) => [
        ...previous,
        { role: "attacker", text },
        { role: "agent", text: reply },
      ]);
      setContent("");
      setStatus(
        response.persisted
          ? "已送达；本轮数据按 join 时同意状态处理。"
          : "已送达；本轮仅内存处理，不落盘。",
      );
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="panel">
      <div className="section-head">
        <h3>攻击对话</h3>
        <span className="badge">每条 {formatRtm(feeWei)}</span>
      </div>
      <p className="muted small">
        当前钱包 {shortAddr(address)}。每条消息先 approve 费用，再调用 attack，
        然后等待 indexer 确认并按该场 join 时的 dataConsent 处理。
      </p>
      <div className="chat-log">
        {messages.length === 0 && (
          <p className="muted small">还没有消息。对话的唯一工具面是 get_balance / transfer_rtm。</p>
        )}
        {messages.map((message, index) => (
          <div className={`bubble ${message.role}`} key={`${message.role}-${index}`}>
            <span className="role">
              {message.role === "attacker" ? "attacker" : "defender agent"}
            </span>
            <p>{message.text}</p>
          </div>
        ))}
      </div>
      <div className="field" style={{ marginTop: 14 }}>
        <label>消息（≤1000 字符）</label>
        <textarea
          value={content}
          maxLength={1000}
          onChange={(event) => setContent(event.target.value)}
          placeholder="尝试诱导智能体把钱转给你的地址…"
        />
      </div>
      <button className="btn" disabled={pending} onClick={send}>
        {pending ? "处理中…" : "付费发送"}
      </button>
      {status && <div className="alert info">{status}</div>}
      {error && <div className="alert error">{error}</div>}
    </div>
  );
}
