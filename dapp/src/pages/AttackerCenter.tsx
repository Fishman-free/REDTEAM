import { useEffect, useState } from "react";
import { useAccount, usePublicClient, useWriteContract } from "wagmi";
import AttackChat from "../components/AttackChat";
import { api, type Contest } from "../lib/api";
import { ADDRESSES, arenaAbi, rtmAbi } from "../lib/contracts";
import { errorText, formatRtm, shortAddr, stateLabel } from "../lib/format";

export default function AttackerCenter() {
  const { address, isConnected } = useAccount();
  const publicClient = usePublicClient();
  const { writeContractAsync } = useWriteContract();
  const [contests, setContests] = useState<Contest[]>([]);
  const [selected, setSelected] = useState<Contest | null>(null);
  const [maxStake, setMaxStake] = useState("5");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);

  async function load() {
    setError("");
    try {
      const all = await api.contests();
      setContests(all.filter((contest) => !contest.is_mining));
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function join(contest: Contest) {
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
    setPending(true);
    try {
      const intent = await api.joinIntent(contest.id, {
        max_stake: maxStake,
        data_consent: consent,
      });
      setStatus("1/2 授权质押…");
      const approval = await writeContractAsync({
        address: ADDRESSES.rtm,
        abi: rtmAbi,
        functionName: "approve",
        args: [intent.approve.spender as `0x${string}`, BigInt(intent.approve.amount)],
      });
      await publicClient.waitForTransactionReceipt({ hash: approval });

      setStatus("2/2 加入比赛…");
      const hash = await writeContractAsync({
        address: ADDRESSES.arena,
        abi: arenaAbi,
        functionName: "join",
        args: [
          contest.id as `0x${string}`,
          BigInt(intent.args[1]),
          intent.args[2],
        ],
      });
      await publicClient.waitForTransactionReceipt({ hash });
      setStatus(
        consent
          ? "已加入；同意数据留存，赛后守方可购买，平台 70% / 攻方 30%。"
          : "已加入；选择不落盘，content 只在内存处理、不可售。",
      );
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <section className="hero">
        <p className="eyebrow">Attacker center</p>
        <h1>付费进攻，拿下奖池</h1>
        <p className="lead">
          加入时一次性选择 dataConsent，之后不可撤回。每条消息费 = S × 0.5%；
          攻破后按剩余质押与 delivered 消息结算。连接钱包后从下方比赛开始。
        </p>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>普通比赛</h2>
          <div className="row-actions">
            <span className="badge">{contests.length} 场</span>
            <button className="btn ghost small" onClick={() => void load()}>
              刷新
            </button>
          </div>
        </div>
        {error && <div className="alert error">{error}</div>}
        {!isConnected && <div className="alert info">连接钱包后可加入与发送消息。</div>}
        <div className="list">
          {contests.map((contest) => (
            <div className="row-item" key={contest.id}>
              <div className="row-main">
                <span className="mono small">{contest.id}</span>
                <span className="muted tiny">
                  守方 {shortAddr(contest.defender)} · W {shortAddr(contest.wallet)} ·{" "}
                  {contest.paid_count} 条付费消息
                </span>
              </div>
              <div className="row-actions">
                <span className="badge">{formatRtm(contest.stake)}</span>
                <span className="badge">{contest.stake_bps / 100}% 质押</span>
                <span className={contest.state === "live" ? "badge live" : "badge ended"}>
                  {stateLabel(contest.state)}
                </span>
                <button
                  className="btn ghost small"
                  onClick={() => setSelected(selected?.id === contest.id ? null : contest)}
                >
                  {selected?.id === contest.id ? "收起" : "加入 / 对话"}
                </button>
              </div>
            </div>
          ))}
          {contests.length === 0 && <p className="muted small">暂无普通比赛。</p>}
        </div>
      </section>

      {selected && (
        <section className="section split">
          <div className="panel">
            <h3>加入 {shortAddr(selected.id)}</h3>
            <div className="field-row">
              <div className="field">
                <label>maxStake（RTM）</label>
                <input value={maxStake} onChange={(event) => setMaxStake(event.target.value)} />
              </div>
              <div className="kv" style={{ flex: 1 }}>
                <div>
                  <span>奖池 S</span>
                  <strong>{formatRtm(selected.stake)}</strong>
                </div>
                <div>
                  <span>攻方质押</span>
                  <strong>
                    {formatRtm((BigInt(selected.stake) * BigInt(selected.stake_bps)) / 10000n)}
                  </strong>
                </div>
              </div>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={consent}
                onChange={(event) => setConsent(event.target.checked)}
              />
              <span>
                我同意平台在赛后留存并出售我的进攻数据（平台 70% / 我 30%）。
                不勾选则不落盘、不可售；选择在 join 后不可撤回。
              </span>
            </label>
            <button
              className="btn"
              style={{ marginTop: 12 }}
              disabled={pending}
              onClick={() => void join(selected)}
            >
              {pending ? "处理中…" : consent ? "同意并加入" : "不同意并加入"}
            </button>
            {status && <div className="alert success">{status}</div>}
          </div>
          <AttackChat
            contest={selected}
            feeWei={(BigInt(selected.stake) * 50n) / 10000n}
          />
        </section>
      )}
    </>
  );
}
