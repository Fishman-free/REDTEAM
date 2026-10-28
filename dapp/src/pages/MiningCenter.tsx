import { useEffect, useState } from "react";
import { useAccount, usePublicClient, useWriteContract } from "wagmi";
import AttackChat from "../components/AttackChat";
import { api, type Contest, type MiningJoinIntent } from "../lib/api";
import { ADDRESSES, arenaAbi } from "../lib/contracts";
import { errorText, formatRtm, shortAddr, stateLabel } from "../lib/format";

const MINING_FEE = 5n * 10n ** 15n; // 0.005 RTM

export default function MiningCenter() {
  const { isConnected } = useAccount();
  const publicClient = usePublicClient();
  const { writeContractAsync } = useWriteContract();
  const [contests, setContests] = useState<Contest[]>([]);
  const [selected, setSelected] = useState<Contest | null>(null);
  const [intent, setIntent] = useState<MiningJoinIntent | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);

  async function load() {
    setError("");
    try {
      const all = await api.contests();
      setContests(all.filter((contest) => contest.is_mining));
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function prepare(contest: Contest) {
    setError("");
    setStatus("");
    setIntent(null);
    setSelected(contest);
    try {
      const value = await api.miningJoinIntent(contest.id);
      setIntent(value);
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function join() {
    setError("");
    setStatus("");
    if (!selected || !intent) return;
    if (!isConnected) {
      setError("请先连接钱包");
      return;
    }
    if (!accepted) {
      setError("必须先阅读并同意矿工数据条款");
      return;
    }
    if (!publicClient) {
      setError("RPC 未就绪");
      return;
    }
    setPending(true);
    try {
      const hash = await writeContractAsync({
        address: ADDRESSES.arena,
        abi: arenaAbi,
        functionName: "joinMining",
        args: [selected.id as `0x${string}`, true],
      });
      await publicClient.waitForTransactionReceipt({ hash });
      setStatus("已加入挖矿赛；数据将仅用于 RSI，不进入 DataMarket。");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <section className="hero">
        <p className="eyebrow">Mining center</p>
        <h1>攻破平台智能体，固定 1 RTM</h1>
        <p className="lead">
          矿工无质押；每条消息 0.005 RTM。攻破后比赛立即停止、defenseHash 永久退役，
          平台补铸 1 RTM 到 Treasury。矿工数据强制留存，仅用于 RSI 修复，不进入
          DataMarket。没有 accrue、没有随时间累积的奖池。
        </p>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>活跃与历史挖矿赛</h2>
          <div className="row-actions">
            <span className="badge mining">每条 0.005 RTM</span>
            <button className="btn ghost small" onClick={() => void load()}>
              刷新
            </button>
          </div>
        </div>
        {error && <div className="alert error">{error}</div>}
        <div className="list">
          {contests.map((contest) => (
            <div className="row-item" key={contest.id}>
              <div className="row-main">
                <span className="mono small">{contest.id}</span>
                <span className="muted tiny">
                  hash {shortAddr(contest.defense_hash)} · {contest.paid_count} 条付费消息
                </span>
              </div>
              <div className="row-actions">
                <span className="badge mining">{formatRtm(contest.reward || "1000000000000000000")} 固定奖励</span>
                <span className={contest.state === "live" ? "badge live" : "badge ended"}>
                  {stateLabel(contest.state)}
                </span>
                <button
                  className="btn ghost small"
                  onClick={() => void prepare(contest)}
                >
                  加入 / 对话
                </button>
              </div>
            </div>
          ))}
          {contests.length === 0 && <p className="muted small">暂无挖矿赛。</p>}
        </div>
      </section>

      {selected && (
        <section className="section split">
          <div className="panel">
            <h3>加入挖矿赛 {shortAddr(selected.id)}</h3>
            <div className="kv">
              <div>
                <span>固定奖励</span>
                <strong>1 RTM</strong>
              </div>
              <div>
                <span>每条消息</span>
                <strong>0.005 RTM</strong>
              </div>
              <div>
                <span>defenseHash</span>
                <strong>{shortAddr(selected.defense_hash)}</strong>
              </div>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={accepted}
                onChange={(event) => setAccepted(event.target.checked)}
              />
              <span>{intent?.terms || "加入前必须同意平台强制留存矿工数据，仅用于 RSI 修复。"}</span>
            </label>
            <button
              className="btn"
              style={{ marginTop: 12 }}
              disabled={pending || !accepted}
              onClick={() => void join()}
            >
              {pending ? "加入中…" : "同意条款并 joinMining(id, true)"}
            </button>
            {status && <div className="alert success">{status}</div>}
          </div>
          <AttackChat contest={selected} feeWei={MINING_FEE} />
        </section>
      )}
    </>
  );
}
