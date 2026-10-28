import type { Page } from "../lib/nav";

export default function Home({ onNavigate }: { onNavigate: (page: Page) => void }) {
  return (
    <>
      <section className="hero">
        <p className="eyebrow">Red-team arena / defensive research</p>
        <h1>
          让智能体在<em>真实资金</em>
          <br />
          与真实对手之间被检验
        </h1>
        <p className="lead">
          守方自带智能体与 BYOK 模型；攻方付费诱导真实链上转账。普通层是零和攻防，
          挖矿层由平台自持智能体、每次攻破固定 1 RTM，并把矿工数据只用于 RSI 修复。
          测试网资产无价值，所有行为仅用于防御研究。
        </p>
        <div className="row-actions" style={{ marginTop: 22 }}>
          <button className="btn" onClick={() => onNavigate("defender")}>
            注册守方
          </button>
          <button className="btn ghost" onClick={() => onNavigate("attacker")}>
            加入进攻
          </button>
          <button className="btn ghost" onClick={() => onNavigate("mining")}>
            查看挖矿
          </button>
        </div>
      </section>

      <section className="grid">
        <article className="card">
          <p className="eyebrow">01 / defender</p>
          <h3>自带智能体，平台只做托管</h3>
          <p>
            守方提交 provider + 自带 API Key + DefensePackage + mandate。平台固定底座
            提示词与工具面（只有 <span className="mono">get_balance</span> /{" "}
            <span className="mono">transfer_rtm</span>），不会泄露链上靶策略。
          </p>
          <button className="btn ghost small" onClick={() => onNavigate("defender")}>
            打开守方中心
          </button>
        </article>
        <article className="card">
          <p className="eyebrow">02 / attacker</p>
          <h3>付费对话，赢家拿走奖池</h3>
          <p>
            攻方在 join 时一次性选择数据同意；每条消息收取 S 的 0.5%。攻破后按质押
            与送达消息结算；不同意留存的数据只在内存处理，不落盘、不可售。
          </p>
          <button className="btn ghost small" onClick={() => onNavigate("attacker")}>
            打开攻方中心
          </button>
        </article>
        <article className="card">
          <p className="eyebrow">03 / mining</p>
          <h3>固定 1 RTM，只修复不出售</h3>
          <p>
            矿工无质押，每条消息 0.005 RTM。攻破后比赛立即停止、hash 永久退役；
            矿工数据仅进入 RSI 修复闭环，不进入 DataMarket。
          </p>
          <button className="btn ghost small" onClick={() => onNavigate("mining")}>
            打开挖矿中心
          </button>
        </article>
        <article className="card">
          <p className="eyebrow">04 / data</p>
          <h3>同意才可售，70 / 30 分账</h3>
          <p>
            守方可以购买己方数据或已同意出售的攻方数据；平台 70%、数据提供方 30%。
            没有 approveSale，没有 accrue，没有随时间累积的奖池。
          </p>
          <button className="btn ghost small" onClick={() => onNavigate("market")}>
            打开数据市场
          </button>
        </article>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>运行边界</h2>
          <span className="badge">Besu 48850 · 8546</span>
        </div>
        <div className="grid two">
          <div className="panel">
            <h3>链上不变式</h3>
            <p className="muted small">
              活跃靶钱包的转出只有两个出口：转给本场注册攻方（触发原子结算）或由
              Arena 控制器划转。任何失败原因都不会回传给模型，避免泄露靶策略。
            </p>
          </div>
          <div className="panel">
            <h3>数据与隐私</h3>
            <p className="muted small">
              普通攻方 opt-out 的内容只在内存；矿工数据强制留存但仅用于 RSI。
              custody 审计只记录元数据，不记录密钥或对话内容。
            </p>
          </div>
        </div>
      </section>
    </>
  );
}
