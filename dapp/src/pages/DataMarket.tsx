import { useEffect, useState } from "react";
import { useAccount, usePublicClient, useReadContract, useWriteContract } from "wagmi";
import { api, ApiClientError, type Contest, type ContestDetail } from "../lib/api";
import { ADDRESSES, ZERO_HASH, dataMarketAbi, rtmAbi } from "../lib/contracts";
import { errorText, formatRtm, shortAddr, stateLabel } from "../lib/format";

const sleep = (milliseconds: number) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export default function DataMarket() {
  const { address, isConnected } = useAccount();
  const publicClient = usePublicClient();
  const { writeContractAsync } = useWriteContract();
  const [contests, setContests] = useState<Contest[]>([]);
  const [selected, setSelected] = useState<Contest | null>(null);
  const [detail, setDetail] = useState<ContestDetail | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);

  const { data: dataPriceBps } = useReadContract({
    address: ADDRESSES.dataMarket,
    abi: dataMarketAbi,
    functionName: "dataPriceBps",
  });
  const { data: attackerDataPrice } = useReadContract({
    address: ADDRESSES.dataMarket,
    abi: dataMarketAbi,
    functionName: "attackerDataPrice",
  });
  const { data: datasetRoot, refetch: refetchRoot } = useReadContract({
    address: ADDRESSES.dataMarket,
    abi: dataMarketAbi,
    functionName: "datasetRoot",
    args: selected ? [selected.id as `0x${string}`] : undefined,
    query: { enabled: Boolean(selected) },
  });

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

  async function select(contest: Contest) {
    setError("");
    setStatus("");
    setSelected(contest);
    setDetail(null);
    try {
      setDetail(await api.contest(contest.id));
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function publishDataset() {
    if (!selected) return;
    setError("");
    setStatus("");
    if (selected.state === "live") {
      setError("比赛尚未结束，不能发布数据集");
      return;
    }
    setPending(true);
    try {
      setStatus("打包 consent-aware 数据集并由 operator 发布到 DataMarket…");
      const result = await api.publishDataSet(selected.id);
      setStatus(`已发布；root ${result.root}`);
      await refetchRoot();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  async function deliverAndDownload(txHash: `0x${string}`) {
    if (!selected) return;
    setStatus("等待 indexer 确认 DataSold 并准备切片…");
    let grant = null;
    let lastError: unknown = null;
    for (let attempt = 0; attempt < 12; attempt += 1) {
      try {
        grant = await api.deliver(selected.id, txHash);
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
    if (!grant) throw lastError ?? new Error("交付未就绪");
    setStatus(`已生成切片；root ${grant.root}；开始下载…`);
    await api.download(grant.token, `${selected.id.slice(0, 10)}-${grant.kind}.zip`);
    setStatus("下载已开始。");
  }

  async function buyOwn() {
    if (!selected || !address) return;
    setError("");
    setStatus("");
    if (selected.defender.toLowerCase() !== address.toLowerCase()) {
      setError("只有该场守方可以购买");
      return;
    }
    if (!publicClient) {
      setError("RPC 未就绪");
      return;
    }
    setPending(true);
    try {
      const price = (BigInt(selected.stake) * (dataPriceBps ?? 1000n)) / 10000n;
      setStatus("approve 数据费用到 DataMarket…");
      const approval = await writeContractAsync({
        address: ADDRESSES.rtm,
        abi: rtmAbi,
        functionName: "approve",
        args: [ADDRESSES.dataMarket, price],
      });
      await publicClient.waitForTransactionReceipt({ hash: approval });
      setStatus("购买守方自有数据…");
      const hash = await writeContractAsync({
        address: ADDRESSES.dataMarket,
        abi: dataMarketAbi,
        functionName: "buyOwn",
        args: [selected.id as `0x${string}`],
      });
      await publicClient.waitForTransactionReceipt({ hash });
      await deliverAndDownload(hash);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  async function buyFromAttacker(attacker: string) {
    if (!selected || !address) return;
    setError("");
    setStatus("");
    if (selected.defender.toLowerCase() !== address.toLowerCase()) {
      setError("只有该场守方可以购买");
      return;
    }
    if (!publicClient) {
      setError("RPC 未就绪");
      return;
    }
    setPending(true);
    try {
      const price = attackerDataPrice ?? 10n ** 18n;
      setStatus("approve 数据费用到 DataMarket…");
      const approval = await writeContractAsync({
        address: ADDRESSES.rtm,
        abi: rtmAbi,
        functionName: "approve",
        args: [ADDRESSES.dataMarket, price],
      });
      await publicClient.waitForTransactionReceipt({ hash: approval });
      setStatus("购买该攻方数据…");
      const hash = await writeContractAsync({
        address: ADDRESSES.dataMarket,
        abi: dataMarketAbi,
        functionName: "buyFromAttacker",
        args: [selected.id as `0x${string}`, attacker as `0x${string}`],
      });
      await publicClient.waitForTransactionReceipt({ hash });
      await deliverAndDownload(hash);
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setPending(false);
    }
  }

  const isDefender =
    Boolean(address) &&
    Boolean(selected) &&
    selected!.defender.toLowerCase() === address!.toLowerCase();
  const published = Boolean(datasetRoot && datasetRoot !== ZERO_HASH);
  const ownPrice =
    selected && dataPriceBps !== undefined
      ? (BigInt(selected.stake) * dataPriceBps) / 10000n
      : null;

  return (
    <>
      <section className="hero">
        <p className="eyebrow">Data market</p>
        <h1>只为已同意出售的数据付费</h1>
        <p className="lead">
          数据集只包含普通赛、已同意攻方数据与守方自有数据；opt-out 与矿工数据永不
          进入。平台 70% / 数据提供方 30%。没有 approveSale；每份数据每地址仅可购买一次。
        </p>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>普通比赛</h2>
          <button className="btn ghost small" onClick={() => void load()}>
            刷新
          </button>
        </div>
        {error && <div className="alert error">{error}</div>}
        {!isConnected && <div className="alert info">连接守方钱包后可购买。</div>}
        <div className="list">
          {contests.map((contest) => (
            <div className="row-item" key={contest.id}>
              <div className="row-main">
                <span className="mono small">{contest.id}</span>
                <span className="muted tiny">
                  守方 {shortAddr(contest.defender)} · {stateLabel(contest.state)} ·{" "}
                  {contest.paid_count} 条消息
                </span>
              </div>
              <div className="row-actions">
                <span className="badge">{formatRtm(contest.stake)}</span>
                <button className="btn ghost small" onClick={() => void select(contest)}>
                  打开
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
            <h3>数据集 {shortAddr(selected.id)}</h3>
            <div className="kv">
              <div>
                <span>守方</span>
                <strong>{shortAddr(selected.defender)}</strong>
              </div>
              <div>
                <span>状态</span>
                <strong>{stateLabel(selected.state)}</strong>
              </div>
              <div>
                <span>datasetRoot</span>
                <strong>{datasetRoot ? shortAddr(datasetRoot) : "未发布"}</strong>
              </div>
              <div>
                <span>买己方数据</span>
                <strong>{ownPrice !== null ? formatRtm(ownPrice) : "—"}</strong>
              </div>
              <div>
                <span>买攻方数据</span>
                <strong>{formatRtm(attackerDataPrice ?? 10n ** 18n)}</strong>
              </div>
            </div>
            <button
              className="btn"
              disabled={pending || selected.state === "live" || published}
              onClick={() => void publishDataset()}
            >
              {published ? "已发布" : "发布数据集"}
            </button>
            {published && (
              <button
                className="btn ghost small"
                style={{ marginLeft: 8 }}
                onClick={() => void refetchRoot()}
              >
                刷新根
              </button>
            )}
            {published && (
              <button
                className="btn ghost small"
                style={{ marginLeft: 8 }}
                disabled={pending || !isDefender}
                onClick={() => void buyOwn()}
              >
                购买己方数据
              </button>
            )}
            {!isDefender && address && (
              <div className="alert info">只有该场守方可以购买。</div>
            )}
            {status && <div className="alert info">{status}</div>}
          </div>

          <div className="panel">
            <h3>攻方数据</h3>
            {!detail ? (
              <p className="muted small">读取中…</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>攻方</th>
                      <th>dataConsent</th>
                      <th>已付费消息</th>
                      <th>攻破</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(detail.attackers).map(([attacker, info]) => (
                      <tr key={attacker}>
                        <td className="mono">{shortAddr(attacker)}</td>
                        <td>
                          {info.data_consent === null
                            ? "未记录"
                            : info.data_consent
                              ? "同意"
                              : "拒绝"}
                        </td>
                        <td>{info.paid}</td>
                        <td>{info.won ? "是" : "否"}</td>
                        <td>
                          <button
                            className="btn ghost small"
                            disabled={pending || !isDefender || info.data_consent !== true}
                            onClick={() => void buyFromAttacker(attacker)}
                          >
                            购买
                          </button>
                        </td>
                      </tr>
                    ))}
                    {Object.keys(detail.attackers).length === 0 && (
                      <tr>
                        <td colSpan={5} className="muted">
                          暂无攻方
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
            <p className="muted small" style={{ marginTop: 10 }}>
              挖矿数据强制留存但只用于 RSI，不在此展示、不可购买。
            </p>
          </div>
        </section>
      )}
    </>
  );
}
