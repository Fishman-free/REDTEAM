import { useEffect, useState } from "react";
import { api, type Leaderboards } from "../lib/api";
import { errorText, formatRtm, shortAddr } from "../lib/format";

export default function Leaderboard() {
  const [boards, setBoards] = useState<Leaderboards | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    api
      .leaderboards()
      .then((value) => {
        if (live) setBoards(value);
      })
      .catch((reason) => {
        if (live) setError(errorText(reason));
      });
    return () => {
      live = false;
    };
  }, []);

  if (error) return <div className="alert error">{error}</div>;
  if (!boards) return <div className="alert info">正在读取链上事件…</div>;

  const attackerRows = Object.entries(boards.attackers).sort(
    (a, b) => b[1].wins - a[1].wins || b[1].difficulty - a[1].difficulty,
  );
  const defenderRows = Object.entries(boards.defenders).sort(
    (a, b) => b[1].contests_survived - a[1].contests_survived,
  );
  const minerRows = Object.entries(boards.miners).sort(
    (a, b) => b[1].wins - a[1].wins || b[1].difficulty - a[1].difficulty,
  );

  return (
    <>
      <section className="hero">
        <p className="eyebrow">Leaderboards / {boards.network}</p>
        <h1>三榜与挖矿统计</h1>
        <p className="lead">
          由链上事件计算；烟测赛与部署注水不计入。难度 = 攻破前该靶承受的付费消息数，
          防止刷软靶。
        </p>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>攻方榜</h2>
          <span className="badge">{attackerRows.length} 个地址</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>攻方</th>
                <th>胜场</th>
                <th>赢得</th>
                <th>难度</th>
                <th>当前连胜</th>
                <th>最长连胜</th>
              </tr>
            </thead>
            <tbody>
              {attackerRows.map(([address, entry]) => (
                <tr key={address}>
                  <td className="mono">{shortAddr(address)}</td>
                  <td>{entry.wins}</td>
                  <td className="mono">{formatRtm(entry.rtm_won)}</td>
                  <td>{entry.difficulty}</td>
                  <td>{entry.current_streak}</td>
                  <td>{entry.longest_streak}</td>
                </tr>
              ))}
              {attackerRows.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    暂无记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>守方榜</h2>
          <span className="badge">{defenderRows.length} 个地址</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>守方</th>
                <th>守住</th>
                <th>承受消息</th>
                <th>罚款</th>
                <th>被破损失</th>
                <th>净收入</th>
                <th>最长存活</th>
              </tr>
            </thead>
            <tbody>
              {defenderRows.map(([address, entry]) => (
                <tr key={address}>
                  <td className="mono">{shortAddr(address)}</td>
                  <td>{entry.contests_survived}</td>
                  <td>{entry.msgs_withstood}</td>
                  <td className="mono">{formatRtm(entry.penalties)}</td>
                  <td className="mono">{formatRtm(entry.breach_loss)}</td>
                  <td className="mono">{formatRtm(entry.net_income)}</td>
                  <td>{entry.longest_survival}s</td>
                </tr>
              ))}
              {defenderRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">
                    暂无记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>矿工榜</h2>
          <span className="badge">{minerRows.length} 个地址</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>矿工</th>
                <th>加入</th>
                <th>已决</th>
                <th>攻破</th>
                <th>固定奖励</th>
                <th>难度</th>
                <th>攻破率</th>
              </tr>
            </thead>
            <tbody>
              {minerRows.map(([address, entry]) => (
                <tr key={address}>
                  <td className="mono">{shortAddr(address)}</td>
                  <td>{entry.joined}</td>
                  <td>{entry.decided_joined}</td>
                  <td>{entry.wins}</td>
                  <td className="mono">{formatRtm(entry.rtm_won_fixed)}</td>
                  <td>{entry.difficulty}</td>
                  <td>{(entry.breach_rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
              {minerRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">
                    暂无记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>挖矿</h2>
          <span className="badge mining">固定 1 RTM / 攻破</span>
        </div>
        <div className="kv">
          <div>
            <span>创建</span>
            <strong>{boards.mining.created}</strong>
          </div>
          <div>
            <span>已攻破</span>
            <strong>{boards.mining.settled}</strong>
          </div>
          <div>
            <span>未攻破退役</span>
            <strong>{boards.mining.retired}</strong>
          </div>
          <div>
            <span>攻破率</span>
            <strong>{(boards.mining.breach_rate * 100).toFixed(1)}%</strong>
          </div>
          <div>
            <span>固定奖励总额</span>
            <strong>{formatRtm(boards.mining.total_fixed_reward)}</strong>
          </div>
          <div>
            <span>活跃赛</span>
            <strong>{boards.mining.active_contests}</strong>
          </div>
        </div>
        <div className="panel">
          <h3>当前活跃版本</h3>
          {boards.mining.active_versions.length === 0 ? (
            <p className="muted small">当前没有活跃挖矿赛。</p>
          ) : (
            <div className="list">
              {boards.mining.active_versions.map((version) => (
                <div className="row-item" key={version.contest_id}>
                  <div className="row-main">
                    <span className="mono small">{version.contest_id}</span>
                    <span className="muted tiny">hash {shortAddr(version.defense_hash)}</span>
                  </div>
                  <div className="row-actions">
                    <span className="badge">{version.paid_messages} 条付费消息</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="panel">
          <h3>已决历史</h3>
          {boards.mining.history.length === 0 ? (
            <p className="muted small">暂无已结算/退役记录。</p>
          ) : (
            <div className="table-wrap" style={{ marginTop: 10 }}>
              <table>
                <thead>
                  <tr>
                    <th>赛</th>
                    <th>结果</th>
                    <th>hash</th>
                    <th>付费消息</th>
                    <th>胜者</th>
                  </tr>
                </thead>
                <tbody>
                  {boards.mining.history.map((item) => (
                    <tr key={item.contest_id}>
                      <td className="mono">{shortAddr(item.contest_id)}</td>
                      <td>{item.outcome === "settled" ? "攻破" : "退役"}</td>
                      <td className="mono">{shortAddr(item.defense_hash)}</td>
                      <td>{item.paid_messages}</td>
                      <td className="mono">{shortAddr(item.winner)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
