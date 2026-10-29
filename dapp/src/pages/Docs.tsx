import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BadgeCheck,
  BookOpen,
  Coins,
  Database,
  Droplets,
  Pickaxe,
  Shield,
  Swords,
  TriangleAlert,
  Wallet,
} from "lucide-react";
import { Badge } from "../components/ui/Badge";
import { Panel } from "../components/ui/Panel";
import { SectionHeader } from "../components/ui/SectionHeader";
import { formatRtm } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { usePlatform } from "../lib/platform";

function Section({
  id,
  index,
  title,
  children,
}: {
  id: string;
  index: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="docs-section" id={id}>
      <p className="docs-kicker mono">{index}</p>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function RoleCard({
  icon,
  title,
  tag,
  children,
  to,
}: {
  icon: ReactNode;
  title: string;
  tag: string;
  children: ReactNode;
  to: string;
}) {
  const { t } = useI18n();
  return (
    <div className="docs-role">
      <span className="docs-role__icon">{icon}</span>
      <div className="docs-role__head">
        <h3>{title}</h3>
        <Badge tone="neutral">{tag}</Badge>
      </div>
      <div className="docs-role__body">{children}</div>
      <Link to={to} className="docs-link">
        {t("Open workspace", "打开工作区")}
        <ArrowRight size={13} />
      </Link>
    </div>
  );
}

function Note({ tone, children }: { tone: "warn" | "info"; children: ReactNode }) {
  return <div className={`docs-note docs-note--${tone}`}>{children}</div>;
}

function Rule({ label, value }: { label: string; value: string }) {
  return (
    <div className="docs-rule">
      <span>{label}</span>
      <strong className="tabular">{value}</strong>
    </div>
  );
}

export default function Docs() {
  const { t } = useI18n();
  const { meta } = usePlatform();
  const drip = formatRtm(meta.faucet.dripAmountWei);

  return (
    <div className="docs-page">
      <SectionHeader
        eyebrow={t("Field manual / documentation", "现场手册 / 使用文档")}
        title={
          <>
            {t("Read the arena", "先读懂")} <em>{t("before you play", "再进场")}</em>
          </>
        }
        description={t(
          "A complete guide to the design philosophy, wallet setup, four roles, economics, data boundaries and recovery steps.",
          "完整说明设计理念、钱包配置、四种角色、经济规则、数据边界与故障恢复步骤。",
        )}
        actions={<Badge tone="warning">{t("TESTNET · NO REAL VALUE", "测试网 · 无真实价值")}</Badge>}
      />

      <div className="docs-layout">
        <nav className="docs-toc" aria-label={t("On this page", "本页目录")}>
          <p className="docs-toc__title mono">{t("ON THIS PAGE", "本页目录")}</p>
          {[
            ["philosophy", t("Design philosophy", "设计理念")],
            ["start", t("Start in three steps", "三步开始")],
            ["roles", t("Four roles", "四种角色")],
            ["map", t("Page map", "页面地图")],
            ["rules", t("Default rules", "默认规则")],
            ["data", t("Data and security", "数据与安全")],
            ["troubleshooting", t("Troubleshooting", "故障排查")],
            ["operator", t("For operators", "运营者说明")],
          ].map(([id, label], index) => (
            <a key={id} href={`#${id}`} className="docs-toc__item">
              <span className="mono">{String(index + 1).padStart(2, "0")}</span>
              {label}
            </a>
          ))}
          <Link to="/faucet" className="docs-toc__cta">
            <Droplets size={13} />
            {t("Get test tRTM", "领取测试 tRTM")}
          </Link>
        </nav>

        <article className="docs-body">
          <Section
            id="philosophy"
            index={t("01 // DESIGN PHILOSOPHY", "01 // 设计理念")}
            title={t("The agent is the target. The chain is the referee.", "agent 是靶子，链是裁判。")}
          >
            <p className="docs-lead">
              {t(
                "RTM Arena is a defensive-security research environment, not a betting product. A defender brings its own autonomous payment agent. Attackers pay per message to probe it. Every stake, fee, breach and payout is enforced by contracts, so an agent's behavior has a measurable economic consequence.",
                "RTM Arena 是一个防御性安全研究环境，不是投注产品。守方带来自己的自主支付 agent，攻方按消息付费进行试探。质押、消息费、攻破和赔付全部由合约执行，因此 agent 的行为会产生可度量的经济后果。",
              )}
            </p>
            <div className="docs-grid docs-grid--three">
              <div className="docs-card">
                <Coins size={17} />
                <h3>{t("Skin in the game", "真实约束")}</h3>
                <p>
                  {t(
                    "Defender stake, attacker stake and per-message fees make safety claims falsifiable instead of rhetorical.",
                    "守方质押、攻方质押和逐条消息费，让安全声明的真假可以被实际成本检验。",
                  )}
                </p>
              </div>
              <div className="docs-card">
                <Swords size={17} />
                <h3>{t("Adversarial by default", "默认对抗")}</h3>
                <p>
                  {t(
                    "The attacker is rewarded for reaching the target wallet; the defender is rewarded for refusing unauthorized transfers.",
                    "攻方以触达靶钱包为目标获得回报；守方以拒绝未授权转账获得回报。",
                  )}
                </p>
              </div>
              <div className="docs-card">
                <Database size={17} />
                <h3>{t("Failure becomes evidence", "失败成为证据")}</h3>
                <p>
                  {t(
                    "Mining contests turn successful attacks into RSI repair data, permanently retiring the breached defense hash.",
                    "挖矿赛把成功的攻击转化为 RSI 修复数据，并永久退役被攻破的防守版本。",
                  )}
                </p>
              </div>
            </div>
            <Note tone="warn">
              <TriangleAlert size={15} />
              <span>
                {t(
                  "The current network is a local single-validator Besu QBFT testnet (chain 48850). tRTM is a test token with no value and cannot be bought or sold. The bundled local-mock model is deliberately vulnerable and is not a security claim.",
                  "当前网络是本地单验证者 Besu QBFT 测试网（链 48850）。tRTM 是无价值测试币，不能买卖。内置 local-mock 模型是故意可被攻破的演示模型，不代表任何真实安全性。",
                )}
              </span>
            </Note>
          </Section>

          <Section id="start" index={t("02 // QUICK START", "02 // 快速开始")} title={t("Start in three steps", "三步开始")}>
            <ol className="docs-steps">
              <li>
                <span className="docs-step__num mono">01</span>
                <div>
                  <h3>{t("Sign once, receive test tRTM", "签一次，领取测试 tRTM")}</h3>
                  <p>
                    {t(
                      `Open the faucet and sign one short message. The platform submits the ${drip} tRTM credit on the correct chain; you do not send a wallet transaction, switch networks or pay gas.`,
                      `打开水龙头，签一条简短消息。平台会在正确的链上代发 ${drip} tRTM；你不需要发送钱包交易、切换网络或支付 gas。`,
                    )}
                  </p>
                </div>
              </li>
              <li>
                <span className="docs-step__num mono">02</span>
                <div>
                  <h3>{t("Enter gameplay with one network tap", "再点一次网络按钮进入游戏")}</h3>
                  <p>
                    {t(
                      "The faucet never needs a wallet network. For staking and paid messages, use the in-app Switch network button; the app checks the wallet chain against the arena before every signature.",
                      "水龙头完全不需要钱包网络。质押和付费消息前，使用站内的切换网络按钮；应用会在每次签名前比对钱包链与竞技场链。",
                    )}
                  </p>
                </div>
              </li>
              <li>
                <span className="docs-step__num mono">03</span>
                <div>
                  <h3>{t("Choose a role and enter", "选择角色进场")}</h3>
                  <p>
                    {t(
                      "Attack a live contest, register your own agent as a defender, mine the platform agent, or inspect the data market. Start with a small stake.",
                      "可以加入进行中的攻防赛、注册自己的守方 agent、挑战平台挖矿赛，或查看数据市场。建议先用小额质押熟悉流程。",
                    )}
                  </p>
                </div>
              </li>
            </ol>
            <div className="docs-action-row">
              <Link to="/faucet" className="docs-action">
                <Droplets size={15} />
                {t("Open faucet", "打开水龙头")}
                <ArrowRight size={13} />
              </Link>
              <Link to="/docs#troubleshooting" className="docs-action docs-action--ghost">
                {t("Transaction timed out?", "交易超时了？")}
                <ArrowRight size={13} />
              </Link>
            </div>
          </Section>

          <Section id="roles" index={t("03 // ROLES", "03 // 四种角色")} title={t("Four roles, four incentives", "四种角色，四种激励")}>
            <div className="docs-roles">
              <RoleCard
                icon={<Swords size={18} />}
                title={t("Attacker", "攻方")}
                tag={t("PAYS PER MESSAGE", "按消息付费")}
                to="/arena"
              >
                <p>
                  {t(
                    "Join a live standard contest by approving a stake. Each paid message is escrowed on-chain; successful breaches settle automatically. Data consent is optional and irreversible.",
                    "通过授权质押加入进行中的普通赛。每条付费消息在链上托管；攻破后自动结算。数据同意是可选项，但一旦确认不可撤销。",
                  )}
                </p>
                <p>
                  {t(
                    "If the contest expires without a breach, anyone can settle it and you can withdraw the remaining stake.",
                    "如果比赛到期仍未攻破，任何人都可以触发结算，你可以取回剩余质押。",
                  )}
                </p>
              </RoleCard>
              <RoleCard
                icon={<Shield size={18} />}
                title={t("Defender / BYOK", "守方 / BYOK")}
                tag={t("BRINGS THE AGENT", "自带 agent")}
                to="/defend"
              >
                <p>
                  {t(
                    "Register an OpenAI-compatible model, pass a 1 wei qualification transfer, then approve stake and create a standard contest. One registration creates one contest.",
                    "注册一个 OpenAI 兼容模型，完成 1 wei 资格转账，然后授权质押并创建普通赛。一次注册只能创建一场比赛。",
                  )}
                </p>
                <p>
                  {t(
                    "Set duration and attacker stake ratio. A breach or defender fault triggers the on-chain penalty; otherwise residual stake can be withdrawn after settlement.",
                    "设置比赛时长和攻方质押比例。被攻破或守方弃权会触发链上罚款；正常结束结算后可取回剩余质押。",
                  )}
                </p>
              </RoleCard>
              <RoleCard
                icon={<Pickaxe size={18} />}
                title={t("Miner", "矿工")}
                tag={t("NO STAKE", "无需质押")}
                to="/mine"
              >
                <p>
                  {t(
                    "Mining contests are created by the operator against the platform agent. Miners join without stake and pay 0.005 tRTM per message; a breach pays a fixed 1 tRTM reward.",
                    "挖矿赛由运营者针对平台 agent 创建。矿工无需质押，每条消息 0.005 tRTM；攻破后获得固定 1 tRTM 奖励。",
                  )}
                </p>
                <p>
                  {t(
                    "At most 3 mining contests are active at once. A breach permanently retires that defense hash; mining data is used only for the RSI repair loop.",
                    "平台最多同时开放 3 场挖矿赛。攻破后该防守版本永久退役；挖矿数据只用于 RSI 修复闭环。",
                  )}
                </p>
              </RoleCard>
              <RoleCard
                icon={<Database size={18} />}
                title={t("Dataset buyer", "数据买方")}
                tag={t("DEFENDER ONLY", "仅限守方")}
                to="/market"
              >
                <p>
                  {t(
                    "Only the defender of an ended standard contest may buy its dataset. Attacker slices exist only when that attacker opted in. One purchase per address, delivered as a time-limited ZIP.",
                    "只有已结束普通赛的守方可以购买该场数据集。攻方只有在加入时选择同意出售才会产生切片。每个地址限购一次，通过限时 ZIP 交付。",
                  )}
                </p>
                <p>
                  {t(
                    "Settlement is 70% to the protocol Treasury and 30% to the data provider. Mining data is never listed.",
                    "成交额 70% 进入协议 Treasury，30% 归数据提供方。挖矿数据永不上架。",
                  )}
                </p>
              </RoleCard>
            </div>
          </Section>

          <Section id="map" index={t("04 // PAGE MAP", "04 // 页面地图")} title={t("Where everything lives", "每个页面做什么")}>
            <div className="docs-map">
              {[
                ["/", t("Overview", "总览"), t("Live network status, active fronts, recent outcomes and shortcuts.", "实时网络状态、活跃战场、近期结果和快捷入口。")],
                ["/arena", t("Arena", "竞技场"), t("Browse, join and settle standard attacker-vs-defender contests.", "浏览、加入并结算普通攻防赛。")],
                ["/defend", t("Defend", "守方"), t("Register an agent, pass qualification and create a stake-backed contest.", "注册 agent、通过资格测试并创建带质押的比赛。")],
                ["/mine", t("Mine", "挖矿"), t("Join platform-operated mining contests for a fixed reward.", "加入平台运营的挖矿赛，争夺固定奖励。")],
                ["/leaderboard", t("Leaderboard", "排行榜"), t("Attacker, defender and miner rankings derived from on-chain events.", "基于链上事件的攻方、守方与矿工榜单。")],
                ["/market", t("Market", "数据市场"), t("Buy opt-in attack transcripts after a standard contest ends.", "普通赛结束后购买经攻方同意的对话数据。")],
                ["/faucet", t("Faucet", "水龙头"), t("Sign once and receive test tRTM relayed by the platform.", "签名一次，由平台代发测试 tRTM。")],
                ["/ops", t("Operations", "运营台"), t("Admin-only: indexer status, mining contest creation and dataset publishing.", "仅管理员：索引器状态、创建挖矿赛和发布数据集。")],
              ].map(([path, label, description]) => (
                <Link to={path} className="docs-map__row" key={path}>
                  <code>{path}</code>
                  <strong>{label}</strong>
                  <span>{description}</span>
                  <ArrowRight size={13} />
                </Link>
              ))}
            </div>
          </Section>

          <Section id="rules" index={t("05 // DEFAULT RULES", "05 // 默认规则")} title={t("Default testnet parameters", "测试网默认参数")}>
            <p>
              {t(
                "These values are read from the contracts and platform metadata. Operators can change network-level parameters in a future deployment; always check the numbers shown on the action panel before signing.",
                "以下数值来自合约与平台元数据。未来部署时运营者可调整网络级参数；签名前请以操作面板显示的数值为准。",
              )}
            </p>
            <div className="docs-rules">
              <Rule label={t("Faucet drip", "水龙头单次额度")} value={`${drip} tRTM`} />
              <Rule label={t("Faucet cooldown", "领取冷却")} value={t("24 hours", "24 小时")} />
              <Rule label={t("Signature validity", "签名有效期")} value={t("5 minutes", "5 分钟")} />
              <Rule label={t("Faucet delivery", "水龙头发放")} value={t("Platform relay", "平台代发")} />
              <Rule label={t("Standard contest duration", "普通赛时长")} value={t("6–168 hours", "6–168 小时")} />
              <Rule label={t("Attacker stake", "攻方质押")} value={t("2%–20% of S", "S × 2%–20%")} />
              <Rule label={t("Attack message fee", "攻方消息费")} value={t("0.5% of S / message", "S × 0.5% / 条")} />
              <Rule label={t("Mining message fee", "挖矿消息费")} value="0.005 tRTM" />
              <Rule label={t("Mining reward", "挖矿固定奖励")} value="1 tRTM" />
              <Rule label={t("Active mining contests", "活跃挖矿赛上限")} value="3" />
              <Rule label={t("Dataset split", "数据分账")} value={t("70% Treasury / 30% provider", "平台 70% / 提供方 30%")} />
            </div>
          </Section>

          <Section id="data" index={t("06 // DATA & SECURITY", "06 // 数据与安全")} title={t("What is recorded, sold and never touched", "记录什么、出售什么、不碰什么")}>
            <div className="docs-grid">
              <div className="docs-card">
                <BadgeCheck size={17} />
                <h3>{t("On-chain settlement", "链上结算")}</h3>
                <p>
                  {t(
                    "Stakes, fees, rewards, penalties and dataset payments are contract events. The platform indexer only mirrors them for display.",
                    "质押、费用、奖励、罚款和数据购买都是合约事件。平台索引器只负责镜像展示。",
                  )}
                </p>
              </div>
              <div className="docs-card">
                <Database size={17} />
                <h3>{t("Transcripts", "对话数据")}</h3>
                <p>
                  {t(
                    "Standard-contest transcripts are stored by the platform for settlement and optional sale. Attackers and miners must consciously opt in; opt-out slices are never listed.",
                    "普通赛对话由平台保存用于结算和可选出售。攻方和矿工必须主动同意；选择退出的数据不会上架。",
                  )}
                </p>
              </div>
              <div className="docs-card">
                <Shield size={17} />
                <h3>{t("Secrets", "密钥")}</h3>
                <p>
                  {t(
                    "Never use a production API key, seed phrase or private key. BYOK keys are held in the platform vault, but this is still a test environment.",
                    "不要使用生产环境 API Key、助记词或私钥。BYOK Key 存在平台 vault 中，但这里仍然是测试环境。",
                  )}
                </p>
              </div>
              <div className="docs-card">
                <Wallet size={17} />
                <h3>{t("Wallet boundary", "钱包边界")}</h3>
                <p>
                  {t(
                    "The browser never receives the platform API token. The web BFF injects it server-side. Your wallet signs; the platform never holds your private key.",
                    "浏览器永远拿不到平台 API token，由 Web BFF 在服务端注入。交易由钱包签名，平台不托管你的私钥。",
                  )}
                </p>
              </div>
            </div>
          </Section>

          <Section
            id="troubleshooting"
            index={t("07 // TROUBLESHOOTING", "07 // 故障排查")}
            title={t("When a transaction never confirms", "交易一直不确认怎么办")}
          >
            <div className="docs-faq">
              <details open>
                <summary>{t("Faucet claim did not credit", "水龙头没有到账")}</summary>
                <p>
                  {t(
                    "The faucet does not send a wallet transaction. The platform verifies your signed message and relays the mint on the chain used by this site, so a wallet RPC mismatch cannot delay the credit. Check that you signed the latest message, that the signature is less than five minutes old, and that this address has not claimed in the last 24 hours.",
                    "水龙头不会发送钱包交易。平台验证你的签名后，会在本站使用的正确链上代发到账，因此钱包 RPC 错链不会拖住领取。请确认签名的是最新消息、签名未超过 5 分钟，并且该地址最近 24 小时没有领取过。",
                  )}
                </p>
                <Note tone="info">
                  {t(
                    "If the platform API is offline, the relay cannot submit. Reconnect to the platform and retry; your signature expires after five minutes and a new one is created automatically.",
                    "如果平台 API 离线，代发无法提交。恢复连接后重试即可；旧签名 5 分钟后失效，重新领取会自动生成新签名。",
                  )}
                </Note>
              </details>
              <details>
                <summary>{t("A game transaction never confirms", "游戏交易一直不确认")}</summary>
                <p>
                  {t(
                    "Gameplay transactions still use your wallet, while the faucet does not. Use the in-app network button to switch to RTM Testnet before signing. The app checks the wallet chain against the app chain before every write and will not send a transaction to a different local chain.",
                    "游戏内的交易仍然使用你的钱包，水龙头则不需要。签名前请使用站内的网络按钮切换到 RTM Testnet。应用会在每次写入前比对钱包链和本站链，不会把交易发到另一条本地链。",
                  )}
                </p>
                <p>
                  {t(
                    "If a transaction is already pending in the wallet, open the transaction drawer and use Check again after the network is correct. Faucet credit does not depend on this step.",
                    "如果钱包里已有待处理交易，先修正网络，再在交易活动中点击重新检查。水龙头到账不依赖这一步。",
                  )}
                </p>
              </details>
              <details>
                <summary>{t("Faucet says cooldown active", "水龙头提示冷却中")}</summary>
                <p>
                  {t(
                    "Cooldown is measured from the last confirmed relay credit, not from the button click. Wait for the countdown to reach zero.",
                    "冷却从上次平台确认代发到账后开始计算，不是从点击按钮开始。等倒计时归零即可。",
                  )}
                </p>
              </details>
              <details>
                <summary>{t("API offline or contract calls fail", "API 离线或合约读取失败")}</summary>
                <p>
                  {t(
                    "Confirm the local stack is running, the API health endpoint responds, and the Besu RPC is producing blocks. Contract addresses come only from the API, so on-chain reads and writes pause while it is offline. If you reset the chain, also reset the registry volume: the stack refuses to start when the registry has no code on the chain.",
                    "确认本地栈正在运行、API 健康检查有响应、Besu RPC 在出块。合约地址只从 API 获取，API 离线时链上读写会暂停。如果重置了链，也必须同时重置 registry 数据卷：registry 里的地址在链上没有合约代码时，栈会拒绝启动。",
                  )}
                </p>
              </details>
              <details>
                <summary>{t("I signed but nothing happened", "签名后没有反应")}</summary>
                <p>
                  {t(
                    "For the faucet, the signature only authorizes one relayed credit. If no balance arrives, check the cooldown and API status; a rejected signature can be retried immediately. For a game transaction, open the transaction drawer and use Check again.",
                    "水龙头签名只授权一次平台代发。如果没有到账，请检查冷却和 API 状态；签名被拒绝时可以立即重试。若是游戏交易，请打开交易活动并点击重新检查。",
                  )}
                </p>
              </details>
            </div>
          </Section>

          <Section id="operator" index={t("08 // FOR OPERATORS", "08 // 运营者说明")} title={t("Running the arena", "运营竞技场")}>
            <Panel eyebrow="Server-side only" title={t("The /ops key is not a player credential", "/ops 密钥不是玩家凭证")}>
              <div className="docs-operator">
                <p>
                  {t(
                    "The operator console is protected by PLATFORM_ADMIN_KEY. It is generated into deploy/.env.stack on first boot and must never be sent to players or committed to git.",
                    "运营台由 PLATFORM_ADMIN_KEY 保护，首次启动时生成到 deploy/.env.stack，绝不能发给玩家或提交到 git。",
                  )}
                </p>
                <ul>
                  <li>{t("Start the stack with bash deploy/up.sh.", "使用 bash deploy/up.sh 启动完整栈。")}</li>
                  <li>{t("Read the admin key locally from deploy/.env.stack, then enter it at /ops.", "在本地从 deploy/.env.stack 读取管理密钥，再填入 /ops。")}</li>
                  <li>{t("Back up the Besu, registry and platform-data volumes before resetting anything.", "重置任何内容前，先备份 Besu、registry 和 platform-data 数据卷。")}</li>
                  <li>{t("Replace local-mock with a real HTTPS model before drawing security conclusions.", "在得出任何安全结论前，把 local-mock 替换为真实的 HTTPS 模型。")}</li>
                </ul>
              </div>
            </Panel>
            <div className="docs-action-row">
              <Link to="/ops" className="docs-action">
                <BookOpen size={15} />
                {t("Open operator console", "打开运营台")}
                <ArrowRight size={13} />
              </Link>
              <a
                href="https://github.com/Fishman-free/REDTEAM/blob/main/README.md"
                target="_blank"
                rel="noreferrer"
                className="docs-action docs-action--ghost"
              >
                {t("Full deployment guide", "完整部署指南")}
                <ArrowRight size={13} />
              </a>
            </div>
          </Section>
        </article>
      </div>
    </div>
  );
}
