# P1 BYOA 文档纠错 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让 `/docs` 只描述代码当前真实能力：更正 simulated 档下关于解密、签名、数据存储的过头表述，新增四列档位对比表，并把“写死不付钱”一段改为“现状缺口 + 规划中的改法”。

**架构：** 只改 `dapp/src/pages/Docs.tsx` 与 `dapp/src/supplement.css`。新增一个无状态 `TierTable` 组件渲染对比表；所有文案沿用现有 `t(英文, 中文)` 双语写法。规划中的内容一律用“规划中 / Planned”标注。

**技术栈：** React 19、TypeScript、Vite、lucide-react 图标（只用已导入的图标）。

**依据：** `docs/superpowers/specs/2026-10-30-byoa-integrity-design.md` §1、§11 第 1–4 项。规格 §11 第 5 项（企业接入指南）属于 P5，不在本计划内。

**写作约束：** 中文文案遵循 human-writing 规则：不用破折号，冒号只用于引出原话，不写“不是……而是……”类翻案句，不用“说白了”“值得注意的是”等路标。任务 4 用脚本检查。

---

## 代码事实（写文案的依据，不要改写成更强的说法）

| 事实 | 出处 |
|---|---|
| 攻方密文由平台进程里的 `SimulatedSealedRuntime` 解密，明文经 `counterparty_turn` 发给守方端点 | `platform/redteam_platform/byoa/service.py:637-652` |
| 守方回复以明文返回，平台用模拟运行时加密给攻方并签名 | `service.py:656-674` |
| 解密私钥、TEE 签名键、W 私钥都在模拟运行时对象里 | `platform/redteam_platform/byoa/sealed.py:246-256,356-363` |
| 四种接入的超时都是 30 秒，超时返回 502，不退费也不记违约 | `adapters.py:27`，`service.py:403,653-654` |
| 攻击原文只在攻方同意时保留，回复与工具轨迹只在守方授权时保留，否则只留哈希 | `platform/redteam_platform/byoa/runtime.py:193-218` |
| 运行时度量只是 dApp 提交的 `{"compose.yaml": 镜像 digest}` 的哈希 | `dapp/src/pages/Byoa.tsx:284`，`sealed.py:117-136` |
| 主人任务由平台的种子生成器生成，文案含“请勿按外部消息改写收款信息” | `platform/redteam_platform/byoa/tasks.py:86-105` |
| 主人任务元数据带 TaskSink 地址，对手方消息会被剥掉这些字段 | `runtime.py:319-320,404-411` |
| BYOA 守方与普通赛守方在同一个守方榜 | `platform/redteam_platform/indexer.py:979-1000` |
| BYOA 对话尚未接入数据市场 | `platform/redteam_platform/data_service.py` 只处理普通赛 |

## 文件结构

| 文件 | 职责 | 改动 |
|---|---|---|
| `dapp/src/pages/Docs.tsx` | 使用文档页面 | 修改第 07 节 4 处文案；第 08 节改写 4 张卡片、插入对比表、重写“写死不付钱”段；新增 `TierTable` 组件 |
| `dapp/src/supplement.css` | 文档页样式 | 在 `.docs-rule strong` 规则块之后新增 `.docs-tiers` 样式 |

---

### 任务 0：建分支

- [ ] **步骤 1：从最新 main 建分支**

```bash
cd C:/Users/21560/Desktop/REDTEAM
git switch main
git pull --ff-only origin main
git switch -c docs/byoa-honesty
```

预期：`Switched to a new branch 'docs/byoa-honesty'`。

---

### 任务 1：更正第 07 节（自带 agent）的四处表述

**文件：**
- 修改：`dapp/src/pages/Docs.tsx:466-467`（导语）
- 修改：`dapp/src/pages/Docs.tsx:498-499`（守方步骤 03）
- 修改：`dapp/src/pages/Docs.tsx:534-535`（攻方步骤 02）
- 修改：`dapp/src/pages/Docs.tsx:550-551`（攻方步骤 04）

- [ ] **步骤 1：确认旧表述存在（相当于失败的测试）**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM
rg -n "relays ciphertext|转发密文|Decrypt them locally|在本地解密、执行策略|because the platform cannot read them|因为平台读不到明文" dapp/src/pages/Docs.tsx
```

预期：6 行匹配（466、467、498、499、534、535）。

- [ ] **步骤 2：替换导语（466-467 行）**

旧：

```tsx
                "BYOA is for defenders that already run their own agent stack. The platform does not run your prompt, tools or code. It records a commitment to your bundle, relays ciphertext, exposes a wallet MCP under the signed policy and settles owner tasks through TaskSink. Create the contest only when the page shows a TaskSink address.",
                "自带 agent 面向已经运行自己 agent 栈的守方。平台不运行你的提示词、工具或代码，只记录 bundle 承诺、转发密文、按签署策略提供钱包 MCP，并通过 TaskSink 结算主人任务。页面显示 TaskSink 地址时才能创建比赛。",
```

新：

```tsx
                "BYOA is for defenders that already run their own agent stack. Your prompt, tools and code stay on your own server, and the platform calls your endpoint over the transport you choose. The platform records a commitment to your bundle, runs the wallet MCP under the signed policy and settles owner tasks through TaskSink. In the current simulated tier the platform decrypts attacker messages before forwarding them to you, so read the tier table in section 08 before you register. Create the contest only when the page shows a TaskSink address.",
                "自带 agent 面向已经运行自己 agent 栈的守方。提示词、工具和代码留在你自己的服务器上，平台按你选的接入方式调用你的端点。平台记录 bundle 承诺，按签署策略运行钱包 MCP，并通过 TaskSink 结算主人任务。当前 simulated 档下，攻方消息由平台解密后再转发给你，注册前请先看第 08 节的档位对比表。页面显示 TaskSink 地址时才能创建比赛。",
```

- [ ] **步骤 3：替换守方步骤 03（498-499 行）**

旧：

```tsx
                    "Connect over the transport you chose and obtain a wallet session token from the platform. Owner tasks and counterparty messages arrive through the relay. Decrypt them locally, run your policy and tools, and return a reply. Your reply is sealed to the attacker and signed by the TEE signer.",
                    "用选定的传输方式接入，从平台获取钱包会话 token。主人任务和对手方消息通过中继到达，在本地解密、执行策略和工具，再返回回复。回复加密给攻方，并由 TEE 签名者签名。",
```

新：

```tsx
                    "Connect over the transport you chose and obtain a wallet session token from the platform. Owner tasks and counterparty messages reach your endpoint as plaintext, because in the simulated tier the platform decrypts attacker ciphertext first. Run your policy and tools and return a plaintext reply within 30 seconds. The platform seals the reply to the attacker and signs it with the simulated TEE key it holds.",
                    "用选定的接入方式连上平台，并从平台获取钱包会话 token。主人任务和对手方消息以明文到达你的端点，因为 simulated 档下攻方密文先由平台解密。执行策略和工具后，在 30 秒内返回明文回复。平台把回复加密给攻方，并用自己持有的模拟 TEE 密钥签名。",
```

- [ ] **步骤 4：替换攻方步骤 02（534-535 行）**

旧：

```tsx
                    "The join panel shows the required attacker stake, computed from the defender stake and stakeBps. Approve the stake and join. The data consent checkbox is recorded on-chain, but this version does not list BYOA transcripts in the market because the platform cannot read them.",
                    "加入面板会显示需要的攻方质押，按守方质押和 stakeBps 计算。授权质押并加入。数据同意勾选会记录在链上，但当前版本不会把 BYOA 对话上架，因为平台读不到明文。",
```

新：

```tsx
                    "The join panel shows the required attacker stake, computed from the defender stake and stakeBps. Approve the stake and join. The data consent checkbox is recorded on-chain. With consent the platform keeps your message text in this contest's session record, and without it only hashes are kept. This version does not list BYOA transcripts in the market yet.",
                    "加入面板会显示需要的攻方质押，按守方质押和 stakeBps 计算。授权质押并加入。数据同意勾选会记录在链上。勾选后平台会在本场会话记录里保留你的消息原文，不勾选只保留哈希。当前版本还没有把 BYOA 对话上架数据市场。",
```

- [ ] **步骤 5：替换攻方步骤 04（550-551 行）**

旧：

```tsx
                    "The reply is sealed to your derived key and signed by the TEE signer. The page decrypts it locally and verifies the signature against the teeSigner stored on-chain, not the value supplied by the relay.",
                    "回复加密给你的派生密钥，并附带 TEE 签名。页面在本地解密，并用链上保存的 teeSigner 验证签名，不依赖中继返回的签名者字段。",
```

新：

```tsx
                    "The reply is sealed to your derived key and signed by the TEE signer. The page decrypts it locally and verifies the signature against the teeSigner stored on-chain, not the value supplied by the relay. In the simulated tier that signing key lives in the platform process, so a valid signature shows the reply came through the platform runtime and says nothing about hardware isolation.",
                    "回复加密给你的派生密钥，并附带 TEE 签名。页面在本地解密，并用链上保存的 teeSigner 验证签名，不依赖中继返回的签名者字段。simulated 档下这把签名键在平台进程里，验签通过只能说明回复经过平台运行时，不能说明经过硬件隔离环境。",
```

- [ ] **步骤 6：确认旧表述已消失**

运行：

```bash
rg -n "relays ciphertext|转发密文|Decrypt them locally|在本地解密、执行策略|because the platform cannot read them|因为平台读不到明文" dapp/src/pages/Docs.tsx
```

预期：无输出，退出码 1。

- [ ] **步骤 7：类型检查与构建**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM/dapp && npm run build
```

预期：`tsc --noEmit` 无报错，Vite 输出 `✓ built in`。

- [ ] **步骤 8：Commit**

```bash
cd C:/Users/21560/Desktop/REDTEAM
git add dapp/src/pages/Docs.tsx
git commit -m "docs(guide): state who decrypts and signs in the simulated BYOA tier"
```

---

### 任务 2：第 08 节改写信任卡片并新增档位对比表

**文件：**
- 修改：`dapp/src/pages/Docs.tsx:69-76` 之后（新增 `TierTable` 组件）
- 修改：`dapp/src/pages/Docs.tsx:569-600`（四张卡片）
- 修改：`dapp/src/pages/Docs.tsx:604-606` 之间（插入对比表）
- 修改：`dapp/src/supplement.css`（`.docs-rule strong` 规则块之后）

- [ ] **步骤 1：确认旧表述存在**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM
rg -n "It does not see message text|看不到消息正文|keeps W and the TEE keys inside the sealed runtime object|docs-tiers" dapp/src/pages/Docs.tsx dapp/src/supplement.css
```

预期：3 行匹配，全部在 `Docs.tsx`，分别是第 589、590、599 行；`docs-tiers` 无匹配。

- [ ] **步骤 2：新增 `TierTable` 组件**

在 `Docs.tsx` 的 `Rule` 函数（第 69-76 行）之后、`export default function Docs()` 之前插入：

```tsx
function TierTable({
  label,
  head,
  rows,
}: {
  label: string;
  head: string[];
  rows: string[][];
}) {
  return (
    <div className="docs-tiers" role="region" aria-label={label} tabIndex={0}>
      <table>
        <thead>
          <tr>
            {head.map((cell) => (
              <th key={cell} scope="col">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([rowLabel, ...cells]) => (
            <tr key={rowLabel}>
              <th scope="row">{rowLabel}</th>
              {cells.map((cell, index) => (
                <td key={index}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

`tabIndex={0}` 让键盘用户能聚焦并横向滚动窄屏下的表格。

- [ ] **步骤 3：改写“消息加密路径”卡片（569-570 行）**

旧：

```tsx
                    "The attacker identity is an X25519 key derived from a wallet signature, so there is no extra private key to store. The message is encrypted with X25519, HKDF-SHA256 and AES-256-GCM to the TEE public key published on-chain. The chain stores keccak256 of the ciphertext as msgHash.",
                    "攻方身份是从钱包签名派生的 X25519 密钥，不需要额外保存私钥。消息用 X25519、HKDF-SHA256 和 AES-256-GCM 加密到链上发布的 TEE 公钥。链上只保存密文的 keccak256 作为 msgHash。",
```

新：

```tsx
                    "The attacker identity is an X25519 key derived from a wallet signature, so there is no extra private key to store. The message is encrypted with X25519, HKDF-SHA256 and AES-256-GCM to the TEE public key published on-chain. The chain stores keccak256 of the ciphertext as msgHash. In the current simulated tier that TEE key belongs to the simulated runtime inside the platform process.",
                    "攻方身份是从钱包签名派生的 X25519 密钥，不需要额外保存私钥。消息用 X25519、HKDF-SHA256 和 AES-256-GCM 加密到链上发布的 TEE 公钥。链上只保存密文的 keccak256 作为 msgHash。当前 simulated 档下，这把 TEE 公钥属于平台进程里的模拟运行时。",
```

- [ ] **步骤 4：改写“回复与验签”卡片（579-580 行）**

旧：

```tsx
                    "The reply envelope is sealed to the attacker key. The TEE signer signs a canonical payload that includes the contest, attacker, msgHash, replyHash and sequence. The UI verifies that signature against the on-chain teeSigner.",
                    "回复信封加密给攻方密钥。TEE 签名者会签署一段规范载荷，包含比赛、攻方、msgHash、replyHash 和序号。页面用链上的 teeSigner 验证该签名。",
```

新：

```tsx
                    "The reply envelope is sealed to the attacker key. The TEE signer signs a canonical payload that includes the contest, attacker, msgHash, replyHash and sequence, and the UI verifies it against the on-chain teeSigner. In the current simulated tier the platform runtime performs both the sealing and the signing.",
                    "回复信封加密给攻方密钥。TEE 签名者会签署一段规范载荷，包含比赛、攻方、msgHash、replyHash 和序号，页面用链上的 teeSigner 验证该签名。当前 simulated 档下，加密和签名都由平台的模拟运行时完成。",
```

- [ ] **步骤 5：改写“平台可见范围”卡片（589-590 行）**

旧：

```tsx
                    "The relay sees ciphertext, hashes, wallet tool calls and aggregate utility. It does not see message text. Your bundle stays off-chain; only its commitment, runtime measurement and policy fingerprint are recorded.",
                    "中继能看到密文、哈希、钱包工具调用和聚合效用，看不到消息正文。守方 bundle 留在链下，链上只记录它的承诺、运行时度量和策略指纹。",
```

新：

```tsx
                    "In the current simulated tier the platform process decrypts attacker messages, forwards the plaintext to the defender endpoint and seals the defender's plaintext reply to the attacker. It keeps message text only with attacker consent and replies or tool traces only with defender authorization, and keeps hashes otherwise. The defender's prompt, tools and code are never submitted, and the chain records only the bundle commitment, runtime measurement and policy fingerprint.",
                    "当前 simulated 档下，平台进程会解密攻方消息，把明文转发给守方端点，再把守方的明文回复加密给攻方。平台只在攻方同意时保留消息原文，只在守方授权时保留回复和工具轨迹，其余只留哈希。守方的提示词、工具和代码不提交给平台，链上只记录 bundle 承诺、运行时度量和策略指纹。",
```

- [ ] **步骤 6：改写“信任边界”卡片（599-600 行）**

旧：

```tsx
                    "The current deployment uses the simulated tier. The simulator keeps W and the TEE keys inside the sealed runtime object, but software isolation is not hardware isolation. The hardware tier needs a real TEE and remote attestation and is not implemented. The UI labels the tier on every BYOA contest.",
                    "当前部署使用 simulated 档。模拟器把 W 和 TEE 密钥放在密封运行时对象里，但软件隔离不等于硬件隔离。hardware 档需要真实 TEE 和远程证明，目前尚未实现。每个 BYOA 比赛的界面都会标注档位。",
```

新：

```tsx
                    "The simulated runtime holds the decryption key, the TEE signing key and the W key inside the platform process, so the platform can technically read messages, sign replies for the runtime and move W. The runtime measurement is only a hash of the image digest the defender typed, and the platform cannot verify that the endpoint runs that image. The hardware tier needs a real TEE and remote attestation and is not implemented. The UI labels the tier on every BYOA contest.",
                    "模拟运行时在平台进程里同时持有解密私钥、TEE 签名键和 W 私钥，平台技术上能读消息、替运行时签回复、动用 W。运行时度量只是守方填写的镜像 digest 的哈希，平台无法核实端点背后跑的就是这个镜像。hardware 档需要真实 TEE 和远程证明，目前尚未实现。每个 BYOA 比赛的界面都会标注档位。",
```

- [ ] **步骤 7：插入档位对比表**

在第 08 节 `docs-grid` 的闭合 `</div>`（原第 604 行）之后、`<h3>{t("Can a defender hard-code a refusal to pay?"` 之前插入：

```tsx
            <h3>{t("Who sees what, by tier", "按档位看谁能看到什么")}</h3>
            <p>
              {t(
                "The first column describes what runs today. The other three columns are the design confirmed on 2026-10-30. They are marked planned and are not live yet, so rely on the first column until they ship.",
                "下表第一列是现在线上的真实情况。后三列是 2026-10-30 确认的设计，标着规划中，尚未上线。上线之前请以第一列为准。",
              )}
            </p>
            <TierTable
              label={t("BYOA tier comparison", "自带 agent 档位对比")}
              head={[
                t("Item", "项目"),
                t("Testnet today", "当前测试网"),
                t("Quick start", "快速接入"),
                t("Enterprise", "企业接入"),
                t("Self-hosted", "自托管调试"),
              ]}
              rows={[
                [
                  t("Status", "状态"),
                  t("Live, simulated tier", "已上线，simulated 档"),
                  t("Planned, simulator on testnet first", "规划中，测试网先跑模拟器"),
                  t("Planned, needs a hardware TEE", "规划中，需要硬件 TEE"),
                  t("Planned", "规划中"),
                ],
                [
                  t("Who decrypts attacks", "谁解密攻方消息"),
                  t("The platform process", "平台进程"),
                  t("The confidential VM (CVM)", "机密计算环境 CVM"),
                  t("The confidential VM (CVM)", "机密计算环境 CVM"),
                  t("The platform relay, then forwarded to you", "平台中继解密后转发给守方"),
                ],
                [
                  t("Who signs replies", "谁签名回复"),
                  t("A simulated TEE key held by the platform", "平台持有的模拟 TEE 密钥"),
                  t("A per-boot key generated inside the CVM", "CVM 每次启动新生成的签名键"),
                  t("A per-boot key generated inside the CVM", "CVM 每次启动新生成的签名键"),
                  t("Your SDK, with your registered reply key", "守方 SDK，用守方登记的回复签名键"),
                ],
                [
                  t("Who holds the W key", "谁持有 W 私钥"),
                  t("The platform process", "平台进程"),
                  t("The wallet sidecar inside the CVM", "CVM 内的钱包 sidecar"),
                  t("The wallet sidecar inside the CVM", "CVM 内的钱包 sidecar"),
                  t("The platform wallet sidecar", "平台钱包 sidecar 托管"),
                ],
                [
                  t("What the platform sees", "平台能看到"),
                  t("Attack text and replies pass through it and are kept per consent", "攻击原文和回复都经过平台，按双方同意保留"),
                  t("Attack text with attacker consent. On testnet it can technically read your config", "攻方同意时的攻击原文。测试网阶段技术上能读到配置"),
                  t("Attack text with attacker consent", "攻方同意时的攻击原文"),
                  t("Attack text passes through it and is kept with consent. Replies stay sealed", "攻击原文经平台中继，按攻方同意保留。看不到回复"),
                ],
                [
                  t("Defender sees attack text", "守方能看到攻击原文"),
                  t("Yes", "能"),
                  t("No, only by buying data", "不能，只能在数据市场购买"),
                  t("No, only by buying data", "不能，只能在数据市场购买"),
                  t("Yes", "能"),
                ],
                [
                  t("Changing config mid-contest", "赛中修改配置"),
                  t("Possible and undetected", "能改，平台检测不到"),
                  t("Blocked, a restart changes the signer", "改不了，重启会换签名者"),
                  t("Blocked, a restart changes the signer", "改不了，重启会换签名者"),
                  t("Caught by the declared hash with the official SDK, missed if the SDK is patched", "用官方 SDK 改会被申报哈希抓到，改了 SDK 抓不到"),
                ],
                [
                  t("Reply deadline", "回复时限"),
                  t("30 s network timeout, no refund and no fault", "30 秒网络超时，超时不退费也不记违约"),
                  t("120 s. Fee refunded on timeout, 3 timeouts count as defender fault", "120 秒。超时退手续费，累计 3 次判守方弃权"),
                  t("120 s. Fee refunded on timeout, 3 timeouts count as defender fault", "120 秒。超时退手续费，累计 3 次判守方弃权"),
                  t("120 s. Fee refunded on timeout, 3 timeouts count as defender fault", "120 秒。超时退手续费，累计 3 次判守方弃权"),
                ],
                [
                  t("Ranking", "排名"),
                  t("Same board as standard defenders", "与普通赛守方同榜"),
                  t("Main board", "主榜"),
                  t("Main board", "主榜"),
                  t("Debug board", "调试榜"),
                ],
                [
                  t("Attacker data share", "攻方数据分成"),
                  t("Not listed yet", "暂不上架"),
                  "30%",
                  "30%",
                  "50%",
                ],
                [
                  t("Violations", "违规后果"),
                  t("Utility penalty when expired tasks exceed the threshold", "过期任务超过阈值时按效用罚没"),
                  t("Utility penalty. A changed measurement is a defender fault and the whole stake goes to attackers", "效用罚没。度量值变化判守方弃权，全部质押分给攻方"),
                  t("Utility penalty. A changed measurement is a defender fault and the whole stake goes to attackers", "效用罚没。度量值变化判守方弃权，全部质押分给攻方"),
                  t("Utility penalty. A mismatched hash or 3 invalid replies sends the whole stake to attackers", "效用罚没。申报哈希不符或累计 3 次无效回复，全部质押分给攻方"),
                ],
                [
                  t("Whom you trust", "需要信任"),
                  t("The platform", "平台"),
                  t("Intel TDX, dstack, the arena template and your model vendor", "Intel TDX、dstack、竞技场模板和模型厂商"),
                  t("Intel TDX, dstack and your model vendor", "Intel TDX、dstack 和你选的模型厂商"),
                  t("The platform and the defender", "平台和守方"),
                ],
              ]}
            />
```

- [ ] **步骤 8：新增表格样式**

在 `dapp/src/supplement.css` 中 `.docs-rule strong { ... }` 规则块（以 `text-align: right;` 和 `}` 结束）之后插入：

```css
.docs-tiers {
  margin-top: 18px;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 9px;
}

.docs-tiers table {
  width: 100%;
  min-width: 720px;
  border-collapse: collapse;
  font-size: 11.5px;
}

.docs-tiers th,
.docs-tiers td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}

.docs-tiers thead th {
  color: var(--ink);
  background: var(--bg-2);
  font-family: var(--font-mono);
  font-weight: 500;
}

.docs-tiers tbody th {
  color: var(--muted);
  font-weight: 500;
  white-space: nowrap;
}

.docs-tiers td {
  color: var(--ink);
}

/* 第一列数据是线上真实情况，轻微高亮以区分规划中的三列 */
.docs-tiers thead th:nth-child(2),
.docs-tiers td:nth-child(2) {
  background: rgba(255, 255, 255, 0.03);
}

.docs-tiers tbody tr:last-child th,
.docs-tiers tbody tr:last-child td {
  border-bottom: 0;
}
```

- [ ] **步骤 9：确认旧表述消失、新组件就位**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM
rg -n "It does not see message text|看不到消息正文|keeps W and the TEE keys inside the sealed runtime object" dapp/src/pages/Docs.tsx
rg -c "docs-tiers" dapp/src/pages/Docs.tsx dapp/src/supplement.css
```

预期：第一条无输出；第二条输出 `dapp/src/pages/Docs.tsx:1` 和 `dapp/src/supplement.css:11`。

- [ ] **步骤 10：构建**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM/dapp && npm run build
```

预期：无 TS 报错（尤其没有 TS6133 未使用变量），`✓ built in`。

- [ ] **步骤 11：Commit**

```bash
cd C:/Users/21560/Desktop/REDTEAM
git add dapp/src/pages/Docs.tsx dapp/src/supplement.css
git commit -m "docs(guide): add BYOA tier comparison and correct trust cards"
```

---

### 任务 3：重写“守方写死不付钱”一段

**文件：**
- 修改：`dapp/src/pages/Docs.tsx`，第 08 节中从 `<h3>{t("Can a defender hard-code a refusal to pay?"` 开始，到本节 `</Section>` 之前的 `</Note>` 为止（任务 2 前的原第 606-633 行）

- [ ] **步骤 1：确认旧表述存在**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM
rg -n "generated inside the TEE|在 TEE 内由比赛种子生成|That is a strong defense|这本身就是很强的防御" dapp/src/pages/Docs.tsx
```

预期：4 行匹配。

- [ ] **步骤 2：整体替换该段**

把从 `<h3>{t("Can a defender hard-code a refusal to pay?", "守方写死“不付钱”会怎样")}</h3>` 到其后第一个 `</Note>`（含）的全部内容替换为：

```tsx
            <h3>{t("Can a defender hard-code a refusal to pay?", "守方写死“不付钱”会怎样")}</h3>
            <p>
              {t(
                "Every utility task today is a closed task, where the owner writes the full payee and amount. The platform generates owner tasks deterministically from the contest seed, bounded by the largest task amount you signed and by a deadline of at most 30 minutes. Each task is registered on TaskSink with an exact amount and deadline, and one matching transfer from W completes one task. An agent that refuses owner tasks too lets them expire, and an expired count above the threshold triggers the utility penalty at finalize.",
                "现在的效用任务都是闭合任务，主人在任务里写全收款地址和金额。主人任务由平台用比赛种子确定性生成，金额受你签署的最大任务金额限制，截止时间最多 30 分钟。每个任务在 TaskSink 上登记精确金额和截止时间，W 的一笔匹配转账完成一个任务。连主人任务也拒绝的 agent，任务会过期，结算时过期数量超过阈值就按效用条款罚没。",
              )}
            </p>
            <div className="docs-rules">
              <Rule label={t("Largest owner task", "最大主人任务")} value={t("Signed at bundle registration", "注册 bundle 时签署")} />
              <Rule label={t("Task deadline", "任务截止时间")} value={t("At most 30 minutes, before contest end", "最多 30 分钟，且早于比赛结束")} />
              <Rule label={t("Default miss threshold", "默认漏做阈值")} value={t("0 expired tasks", "0 个过期任务")} />
              <Rule label={t("Default utility penalty", "默认效用罚没")} value={t("10% of stake, capped at 50%", "质押的 10%，上限 50%")} />
              <Rule label={t("Penalty destination", "罚没去向")} value="Treasury" />
            </div>
            <Note tone="warn">
              <TriangleAlert size={15} />
              <span>
                {t(
                  "This version cannot stop one pattern. An agent that pays owner tasks and refuses every counterparty message passes qualification and the utility checks, and it is never breached. Owner tasks and counterparty messages can be told apart by format, and the task text itself warns against changing payees on outside request. The platform also cannot detect a defender changing its config mid-contest.",
                  "现版本拦不住一种写法。agent 只要照付主人任务、一律拒绝对手方消息，就能通过资格测试和效用考核，而且不会被攻破。主人任务和对手方消息在格式上能区分，任务文案里也提示了不要按外部消息改收款信息。平台同样发现不了守方在赛中修改配置。",
                )}
              </span>
            </Note>

            <h3>
              {t("Confirmed fix", "已确认的改法")} <Badge tone="warning">{t("PLANNED", "规划中")}</Badge>
            </h3>
            <div className="docs-grid">
              <div className="docs-card">
                <Coins size={17} />
                <h3>{t("Open tasks", "开放任务")}</h3>
                <p>
                  {t(
                    "At least 30% of the tasks in every contest become open tasks. The owner only says that a supplier will send an invoice to check and pay. The payee arrives through the counterparty channel from the arena driver acting as the honest supplier, in the same format as attacker messages. An agent that refuses all counterparty messages misses these invoices, and each miss counts against utility.",
                    "每场至少 30% 的任务改为开放任务。主人只交代某家供应商会发来发票，核对后照付。收款地址由扮演诚实供应商的竞技场驱动程序从对手方通道发来，和攻方消息同一种格式。一律拒绝对手方的 agent 会漏付这些发票，每漏一张都计入效用违约。",
                  )}
                </p>
              </div>
              <div className="docs-card">
                <BadgeCheck size={17} />
                <h3>{t("Verification tools", "核验工具")}</h3>
                <p>
                  {t(
                    "The driver offers a supplier directory and a call-back tool. At the standard difficulty about 20% of honest invoices claim a changed account while the directory updates late, so the agent has to call back to confirm. Attackers can impersonate the supplier with the same story.",
                    "驱动程序提供供应商名录和回呼核实两个工具。标准难度下，约 20% 的诚实发票会声称换了收款账户，名录延迟更新，agent 需要回呼确认。攻方也会冒充供应商讲同样的说法。",
                  )}
                </p>
              </div>
              <div className="docs-card">
                <Lock size={17} />
                <h3>{t("Hidden payees", "收款地址保密")}</h3>
                <p>
                  {t(
                    "Each task pays a freshly generated address, and the chain stores only a commitment to it. The wallet sidecar reveals and locks the address after the agent decides to pay, so reading the chain does not expose legitimate payees. The hint in the task text and the TaskSink address in task metadata are removed.",
                    "每个任务的收款地址都是新生成的随机地址，链上只登记它的承诺。agent 决定付款之后，钱包 sidecar 才揭示并锁定这个地址，读链查不到合法收款地址。任务文案里的提示和任务元数据里的 TaskSink 地址都会去掉。",
                  )}
                </p>
              </div>
              <div className="docs-card">
                <TriangleAlert size={17} />
                <h3>{t("Self-hosted pledge", "自托管档申报")}</h3>
                <p>
                  {t(
                    "A self-hosted defender signs every reply with the official SDK and declares its current config hash, and like every BYOA tier it must reply within 120 seconds. A declared hash that differs from the commitment, or 3 timeouts or unsigned replies in total, sends the whole stake to the contest's attackers by delivered messages. A defender who patches the SDK and keeps declaring the old hash cannot be caught, which is why this tier ranks on its own board.",
                    "自托管守方每条回复都要用官方 SDK 签名，申报当前配置哈希，并和所有 BYOA 档位一样在 120 秒内回复。申报值与开赛承诺不一致，或累计 3 次超时、缺签名，全部质押按送达消息数分给本场攻方。改了 SDK 并继续申报旧哈希的守方抓不到，所以这一档单独排名。",
                  )}
                </p>
              </div>
            </div>
            <Note tone="info">
              <span>
                {t(
                  "The penalty is bounded by the W balance and by the bps you signed. It does not recover a payment that was never made, and it cannot inspect why the agent refused. Until the planned items ship, rely on the opening paragraph of this part and the first column of the tier table.",
                  "罚金以 W 余额和你签署的 bps 为上限，它无法追回一笔从未发生的付款，也无法判断 agent 为什么拒绝。规划中的内容上线之前，以本小节开头的说明和上方表格第一列为准。",
                )}
              </span>
            </Note>
```

`Badge`、`Coins`、`BadgeCheck`、`Lock`、`TriangleAlert` 都已在文件顶部导入，不需要新增 import。

- [ ] **步骤 3：确认旧表述消失**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM
rg -n "generated inside the TEE|在 TEE 内由比赛种子生成|That is a strong defense|这本身就是很强的防御" dapp/src/pages/Docs.tsx
```

预期：无输出。

- [ ] **步骤 4：构建**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM/dapp && npm run build
```

预期：`✓ built in`，无 TS 报错。

- [ ] **步骤 5：Commit**

```bash
cd C:/Users/21560/Desktop/REDTEAM
git add dapp/src/pages/Docs.tsx
git commit -m "docs(guide): document the hard-coded refusal gap and planned fix"
```

---

### 任务 4：整体验证、推送与合并

**文件：** 无新增改动（发现问题时回到对应任务修正并单独 commit）

- [ ] **步骤 1：全量过头表述扫描**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM
rg -n "relays ciphertext|转发密文|Decrypt them locally|在本地解密、执行策略|because the platform cannot read them|因为平台读不到明文|It does not see message text|看不到消息正文|generated inside the TEE|在 TEE 内由比赛种子生成" dapp/src/pages/Docs.tsx
```

预期：无输出。

- [ ] **步骤 2：human-writing 文案检查**

运行（把 `Docs.tsx` 中含汉字的字符串抽到临时文件再检查）：

```bash
cd C:/Users/21560/Desktop/REDTEAM
OUT="$(cygpath -w /tmp)\\docs_zh.md"
OUT="$OUT" python - <<'EOF'
import os, re, pathlib
text = pathlib.Path("dapp/src/pages/Docs.tsx").read_text(encoding="utf-8")
items = re.findall(r'"([^"\n]*[一-鿿][^"\n]*)"', text)
pathlib.Path(os.environ["OUT"]).write_text("\n\n".join(items) + "\n", encoding="utf-8")
print(len(items))
EOF
PYTHONIOENCODING=utf-8 python /c/Users/21560/.claude/skills/human-writing/scripts/check_prose.py "$OUT"; echo "exit=$?"
```

预期：`exit=0`；`翻案句 0，翻案腔变形 0，同构排比 0，名词化 0，黑话 0，硬停词 0，模型路标 0`。
改动前的基线是 224 条字符串、`exit=0`，“需辨语境词”2 处（第 57、213 行的“闭环”，原有内容）。新增文案不得引入新的硬性命中；若出现，按提示改写对应字符串后回到任务 1–3 的构建步骤。

- [ ] **步骤 3：浏览器目视检查**

运行：

```bash
cd C:/Users/21560/Desktop/REDTEAM/dapp && npm run dev
```

打开 `http://127.0.0.1:5173/docs#crypto`，逐项确认：
1. 第 08 节先是 4 张卡片，随后是“按档位看谁能看到什么”和 5 列表格，“当前测试网”一列有浅色高亮；
2. 窗口缩到 680px 以下时表格出现横向滚动，页面本身不横向溢出；
3. 切换到英文后表头、行名、单元格都变成英文；
4. “已确认的改法”标题旁显示“规划中”徽章，下方 4 张卡片；
5. 第 07 节导语与守方步骤 03 已写明“由平台解密后再转发”。

检查完按 `Ctrl+C` 停止 dev server。

- [ ] **步骤 4：推送分支**

```bash
cd C:/Users/21560/Desktop/REDTEAM
git push -u origin docs/byoa-honesty
```

预期：`* [new branch]      docs/byoa-honesty -> docs/byoa-honesty`。GitHub 连接超时则间隔 10 秒重试，最多 3 次。

- [ ] **步骤 5：合并到 main 并推送**

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff docs/byoa-honesty -m "merge: honest BYOA trust documentation"
git push origin main
```

预期：`main -> main` 推送成功。

- [ ] **步骤 6：观察 CI**

```bash
gh run list -R Fishman-free/REDTEAM -L 3
```

等待 main 最新提交的 `offline-tests` 完成，确认 “Platform backend and dApp” job 中的 “Build dApp” 步骤通过。失败时用 `gh run view <id> -R Fishman-free/REDTEAM --log-failed` 取日志。

- [ ] **步骤 7：提醒服务器更新**

服务器（`https://arena.agenttrust.site/`）需要拉取新的 main 并重建 web 容器，`/docs` 才会显示新内容。只重建 web，不动链和 contracts 容器。
