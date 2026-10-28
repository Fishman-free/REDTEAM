import { useEffect, useState } from "react";
import { useAccount, usePublicClient, useReadContract, useWriteContract } from "wagmi";
import { api, type FaucetTicket } from "../lib/api";
import { ADDRESSES, faucetAbi } from "../lib/contracts";
import { errorText, formatRtm, shortAddr } from "../lib/format";

export default function Faucet() {
  const { address, isConnected } = useAccount();
  const publicClient = usePublicClient();
  const { writeContractAsync } = useWriteContract();
  const [recipient, setRecipient] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [ticket, setTicket] = useState<FaucetTicket | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (address && !recipient) setRecipient(address);
  }, [address, recipient]);

  const { data: dripAmount } = useReadContract({
    address: ADDRESSES.faucet,
    abi: faucetAbi,
    functionName: "dripAmount",
  });
  const { data: nonce } = useReadContract({
    address: ADDRESSES.faucet,
    abi: faucetAbi,
    functionName: "nonces",
    args: address ? [address] : undefined,
    query: { enabled: Boolean(address) },
  });

  async function issueTicket() {
    setError("");
    setStatus("");
    if (!recipient || !/^0x[0-9a-fA-F]{40}$/.test(recipient)) {
      setError("请输入有效的 0x 地址");
      return;
    }
    setPending(true);
    try {
      const value = await api.faucetTicket(recipient, captchaToken.trim() || undefined);
      setTicket(value);
      setStatus("票据已签发。领取时必须由 to 本人调用 claim。");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  async function claim() {
    setError("");
    setStatus("");
    if (!ticket) return;
    if (!isConnected || !address) {
      setError("请先连接钱包");
      return;
    }
    if (ticket.to.toLowerCase() !== address.toLowerCase()) {
      setError("票据与当前钱包不匹配：只有 ticket.to 本人可领取");
      return;
    }
    if (!publicClient) {
      setError("RPC 未就绪");
      return;
    }
    setPending(true);
    try {
      const hash = await writeContractAsync({
        address: ADDRESSES.faucet,
        abi: faucetAbi,
        functionName: "claim",
        args: [
          {
            to: ticket.to as `0x${string}`,
            nonce: BigInt(ticket.nonce),
            deadline: BigInt(ticket.deadline),
          },
          ticket.signature as `0x${string}`,
        ],
      });
      setStatus(`claim 已提交：${hash.slice(0, 12)}…`);
      await publicClient.waitForTransactionReceipt({ hash });
      setStatus("领取成功。");
      setTicket(null);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <section className="hero">
        <p className="eyebrow">Testnet faucet</p>
        <h1>领取测试 RTM</h1>
        <p className="lead">
          平台签发 EIP-712 票据，票据与领取地址绑定；同一地址两次领取至少间隔 24 小时。
          测试网资产无价值。
        </p>
      </section>

      <section className="split section">
        <div className="panel">
          <h2>签发票据</h2>
          <div className="kv">
            <div>
              <span>单次额度</span>
              <strong>{formatRtm(dripAmount ?? 0n)}</strong>
            </div>
            <div>
              <span>当前 nonce</span>
              <strong>{nonce !== undefined ? String(nonce) : "—"}</strong>
            </div>
            <div>
              <span>已连接</span>
              <strong>{shortAddr(address)}</strong>
            </div>
          </div>
          <div className="field">
            <label>领取地址 to</label>
            <input
              value={recipient}
              onChange={(event) => setRecipient(event.target.value)}
              placeholder="0x…"
            />
          </div>
          <div className="field">
            <label>Captcha token（生产必填，开发可为空）</label>
            <input
              value={captchaToken}
              onChange={(event) => setCaptchaToken(event.target.value)}
              placeholder="hCaptcha token / 开发留空"
            />
          </div>
          <button className="btn" disabled={pending} onClick={issueTicket}>
            {pending ? "处理中…" : "签发票据"}
          </button>
          {error && <div className="alert error">{error}</div>}
          {status && <div className="alert success">{status}</div>}
        </div>

        <div className="panel">
          <h2>领取</h2>
          {ticket ? (
            <>
              <div className="kv">
                <div>
                  <span>to</span>
                  <strong className="mono">{shortAddr(ticket.to)}</strong>
                </div>
                <div>
                  <span>nonce</span>
                  <strong>{ticket.nonce}</strong>
                </div>
                <div>
                  <span>deadline</span>
                  <strong>{ticket.deadline}</strong>
                </div>
              </div>
              <div className="field">
                <label>签名</label>
                <textarea readOnly value={ticket.signature} className="mono small" />
              </div>
              <button className="btn" disabled={pending} onClick={claim}>
                {pending ? "领取中…" : "调用 Faucet.claim"}
              </button>
            </>
          ) : (
            <p className="muted">
              先签发票据；票据只绑定 to 地址，不能转卖或代领。连接钱包并确认地址一致后再领取。
            </p>
          )}
        </div>
      </section>
    </>
  );
}
