# REDTEAM Flower：本地不可转让 NFT 贡献认可原型

**版本：2026-10-10。状态：独立、本地、合成演示，待专业审查。** 当前 PayAssist L0/L1 主线不变；Flower 不是生产发布、安全认证、真实身份认证或法律豁免。商业主线是[安全评测、整改复核与持续回归服务](business/redteam-business-plan.md)。

## 1. 产品与合约边界

REDTEAM Flower 使用 **ERC-721 + ERC-5192** 记录一份经发行者审核、接收者同意的贡献认可；不是历史可转让 **RTM ERC-20** 的改名、兑换或升级。[RTM/BountyVault](../contracts/README.md)保留为独立历史研究，仍排除商业路线。没有与 PayAssist campaign 的自动审查/自动发行接线。

| 项目 | 本地原型约束 |
|---|---|
| 发行 | 发行者人工审核贡献后免费发行，接收者 EIP-712 同意；非公共自助领取 |
| 接收 | 普通 EOA 测试钱包；不支持合约钱包/EIP-1271、代理接收或重新分配 |
| 锁定 | token 永久锁定，转让和转让授权禁用；不提供销售、定价、市场、兑换或赎回 |
| 权益 | 无收益、分红、算力效用、治理或所有权特权；不以持有作为商业服务资格 |
| 撤销 | 只设置 revoked 标志，保留原 token、原 owner、原贡献关联；不焚毁换人，不设管理员更换 owner |
| 环境 | **无分叉 Hardhat、本地 chainId 31337**；不是测试网或主网部署教程 |

免费指发行价格为零，不承诺未来公共网络 gas 免费。不可转让 token 仍不能阻止钱包/私钥本身的转卖、泄漏或胁迫控制。失去钱包不提供 token 重分配捷径；实际恢复、申诉与治理需求须另行审查，不在当前原型中解决。

## 2. 技术协议与人工审核

1. **隔离材料**：仅收集在明确授权范围内的贡献；检查目标版本、证据、复现、去重和披露权限。真实客户数据、未公开漏洞、私人联系方式和秘密不写入公开元数据或导出样本。
2. **可信链下审核**：发行者核验原始材料并记录审核决定。当前系统信任该审核者；合约和摘要不能自动判断贡献真实、新颖、有效或获合法授权。
3. **绑定原字节**：对受审材料原始字节生成 evidence digest，并使用唯一贡献标识。digest 只验证字节一致，**不验证事实真伪**。本地协议 helper `validateReviewedRecord(record, {evidenceRoot, expectedChainId, expectedContract, expectedNonce, now, seenContributionIds})` 检查记录/路径与预期上下文，不能替代人工判断。
4. **接收者同意**：使用 `signableConsent(...)` 形成 EIP-712 typed data。domain 为 `REDTEAM Flower` / `1`、chainId 与 verifyingContract；Consent message 是 `recipient, contributionId, category, nonce, deadline, policyVersion`。接收者应核对这些字段及链下审核材料后再签名；发行者不能替接收者签。普通钱包控制**不是真实身份认证**，签名也不是对贡献事实的证明。
5. **发行与防重放**：可信本地 helper 校验审查与 evidence SHA-256 后，发行者提交 Consent 和签名；合约检查发行者、同意、期限、nonce、贡献唯一性、政策版本与 EOA 约束。合约**不读取证据文件或审核声明，也不验证 evidence digest**。`contributionId` 由协议/版本/贡献键推导，故不把摘要绑定扩张为链上事实认证；证据与审核摘要绑定发生在可信链下协议中。nonce/期限/domain 约束不能被解释为真实身份系统或链下授权真实性保证。
6. **状态维护**：撤销由发行者设置状态，原 owner 与 token 保留；`locked` 不随撤销解除。链下审核撤销理由、申诉、权限管理和发行者密钥安全仍须人工治理。
7. **限定导出**：本地检查后导出安全展示字段，网页只读取静态 JSON，不签名、不连钱包、不发交易、不查询实时链。

### 2.1 合成证据与审核记录约定

证据对象的字段为 `{protocol: 'redteam-flower-evidence', version: 1, synthetic: true, scope, claimType, summary, confirmation}`。scope/claimType 成对对应：`model` / `model-finding`、`system` / `system-finding`、`research` / `research-contribution`。

模型/系统发现的 `confirmation` 为 `{attack, control}`。两臂都有 `inputReached: true`、`infrastructureError: false`；control 必须 `modelViolation: false, systemViolation: false`。model 类 attack 要求 `modelViolation: true, systemViolation: false`；system 类 attack 要求 `systemViolation: true`。research 类为 `confirmation: null`，不冒充配对突破。**model finding 是确认的模型层违规，不是模型训练改善**，不得要求 `modelChanged` 或称基础模型能力获得认证。

审核对象字段为 `{status: 'approved', audited: true, reviewerReference, auditReference, scope, evidenceSha256}`。这些是受信任本地控制者的链下声明，不是审核人身份的密码学认证或真实事实 oracle。文件校验、配对字段与摘要只是输入契约，恶意审核者仍可提交虚假声明，人工审查不能省略。

当前原型没有生产身份认证、智能合约钱包支持、审查多签治理、不可转让钱包控制保证、法律审查或公链隐私解决方案；上述测试通过不得扩大为这些能力。

## 3. 隐私、公开历史与元数据

元数据包含 `name`、`description`、`image` 与三项 attributes：`Token number`、`Category`（`model finding` / `system finding` / `research contribution`）、`Status`（`active` / `revoked`）。图片是生成的 base64 SVG 花朵。展示元数据不含接收钱包或 evidence digest，但 **ERC-721 owner getter 与链上事件仍可公开 recipient 和 contributionId**；省略展示字段不等于链上匿名。

撤销不删除公开链历史，hash 也不是匿名或数据擦除机制。当前只用合成贡献/测试钱包。未来若研究公开发行，须审查使用加盐、假名化、不带个人语义的 opaque contribution keys，以及数据最小化、地址关联、保留、同意与披露风险；加盐假名化不保证匿名。原始证据保持私密，不因认可而上传到公共站点。

## 4. 本地命令与演示判据

仅使用进程内 Hardhat 本地网络；Solidity 0.8.24 的本地 EVM 编译目标为 Cancun（OpenZeppelin 组件使用 MCOPY），不作生产目标网络兼容承诺。在仓库 `contracts/` 执行（Node.js 22；依赖安装按[合约指南](../contracts/README.md)）：

```bash
npm ci --no-audit --no-fund
npm test
npm run flower:demo
```

`assertLocalNetwork(hre)` 与演示脚本应拒绝非 Hardhat、非 31337 或配置分叉的环境，不连接生产 RPC。本地临时链生成合成审核记录、测试钱包同意与发行，检查转让/授权被拒，再撤销**同一个 token**；生成 `docs/site/flower-demo.json`，不上传原始证据。

[Flower 页面](site/flower.html)通过 `fetch('./flower-demo.json')` 读取该快照。需通过本地静态 HTTP 服务查看，直接 `file://` 打开可能被浏览器阻止 fetch。页面既不与链交互，也不宣称实时状态。

若文件不存在，显示 **“尚未生成本地演示，请在contracts执行npm run flower:demo”**。无文件、无效 JSON、协议不匹配或验证不通过，都不能显示已发行成功；装饰花朵不是已铸造证据。

## 5. 展示 JSON 约定

- `protocol: 'redteam-flower-demo-v1'`、`synthetic: true`。
- `network: {name: 'hardhat', chainId: 31337, forked: false}`，`contractAddress` 为合法 20-byte hex 地址。
- `snapshots` 两项：`{label: 'issued', tokenId: '1', revoked: false, metadata: {...}}` 和 `{label: 'revoked', tokenId: '1', revoked: true, metadata: {...}}`。同 token 的两个时点，不是两枚 NFT；示例编号由实际演示生成。
- `checks: {transferBlocked: true, approvalsBlocked: true}`，仅报告该次本地检查，不保证任何其他部署。
- metadata image 仅接受 `data:image/svg+xml;base64,...`，使用图片元素展示，不注入 SVG/HTML；其他元数据以 textContent 输出。页面先验证全部数据，再一次性展示，失败关闭。

## 6. 上线前审查与禁止描述

公开发行或任何商业接入前，必须重新审查法律适用、主体和服务范围、贡献审核、接收同意、隐私与公开记录、发行者密钥、撤销申诉、钱包转卖残余风险、元数据和安全测试。**“NFT”“免费”“不可转让”“贡献荣誉”不保证合法，也不豁免监管或审查**。专业人士的口头建议不是监管批准或正式法律意见；原商业稿法律引文在本轮未独立核验。

不能称“身份证明”“绝对不可交易”“贡献事实已被链证明”“上线即可合规”“未来免费 gas”“已获生产安全证书”。当前主线真实模型证据见[live.v3 对照报告](../rsi4safety/payment_agents/evidence/VALIDATION10H_COMPARATIVE_2026-10-05.md)：仍有 12 个开放发现，不能借 Flower 认可掩盖。

现存[商业 PDF](business/redteam-business-plan.pdf)未重新生成，是本次 Flower 更新前快照，已由[当前商业 Markdown](business/redteam-business-plan.md)替代其产品说明；资料导航见[INDEX](INDEX.md)。
