# 合约与本地支付实验

本模块与 [RSI4Safety](../rsi4safety/README.md) 并列，包含合约、支付执行和相应验证。完整研究目标及未连接部分见[总研究方案](../docs/RESEARCH_PLAN.md)。

| 目录 | 内容 |
|---|---|
| [src/](src/) | 支付/历史奖励合约与独立 Flower NFT 原型 |
| [scripts/](scripts/) | 本地部署、付款执行、事件核验与单轮/多轮演示 |
| [redteam/](redteam/) | 支付决策、SQLite/HTTP 实验与模型传输 |
| [test/](test/) / [tests/](tests/) | 合约/JS 测试与支付 Python 测试 |
| [scenarios/](scenarios/) / [prompts/](prompts/) | 场景、可信采购输入、独立评估真相和提示词 |

[PaymentAgent](src/PaymentAgent.sol) 约束付款；[ExperimentalToken](src/ExperimentalToken.sol) 提供预铸合成资产；[RewardSettlement](src/RewardSettlement.sol) 结算演示奖励。[RTMToken](src/RTMToken.sol) 与 [BountyVault](src/BountyVault.sol) 实现独立历史 ERC-20 发行与悬赏预算；旧 Arena 已有本地 RTM 证据桥，尚未接入当前 PayAssist campaign 或 payment-agent 演示，不是 Flower NFT，仍排除商业版。本版已合入 `6394fc2`：金库支持显式续期与可配置累计结算上限，禁用放弃所有权；付款操作与发票分别防重放，三个实验合约增加部署参数校验。累计上限默认不收紧，须由 owner 配置；过期续期仍受当前年预算限制，不保证兑付。两种奖励机制均保留，详见 [RTM 设计](../docs/references/research/RTM_BOUNTY_DESIGN.md)。

以下命令从 `contracts/` 执行，需要 Node.js 22 和 Python 3.11+：

```bash
npm ci --no-audit --no-fund
npm test
npm run demo:agent
npm run demo:multiround

# 使用仓库现有 Python 环境
../rsi4safety/.venv/bin/python -m pytest tests -q
../rsi4safety/.venv/bin/python -m redteam.cli --replay
../rsi4safety/.venv/bin/python -m redteam.server --port 8765 --db ./redteam.sqlite3
```

本地交互页由 `redteam.server` 提供，地址为 `http://127.0.0.1:8765`。根 `docs/site/index.html` 是独立静态研究展示页。

默认演示采用 mock 和本地合成资产。`redteam` 网络模型后端需要显式 `REDTEAM_LLM_ENABLED=1` 及对应端点、模型、密钥；与 RSI 的模型配置独立。严格区分提议、执行阻止、实际付款、评价失败和奖励失败。付款事实核验指定 Payment/Transfer 事件；奖励失败不抹去已经发生的付款。SQLite 与 EVM 的唯一性/额度约束不同，结果按后端分别解释。

## 独立 REDTEAM Flower 本地 NFT 原型

[技术协议与审核限制](../docs/FLOWER_RECOGNITION.md)、[静态展示页](../docs/site/flower.html)与[当前商业 Markdown](../docs/business/redteam-business-plan.md)为当前说明。Flower 使用 ERC-721 + ERC-5192，受信任发行者审核贡献后，经 EOA 接收者 EIP-712 同意免费发行；永久不可转让，转让授权也禁用。无定价、销售、赎回、收益、算力效用或所有权特权。撤销仅改标志，保留原 token/owner，不设代理接收、管理员换钱包或重新分配。

```bash
# 从 contracts/ 执行；无分叉 Hardhat 31337，合成材料/测试钱包
npm test
npm run flower:demo
```

演示只支持本地链；拒绝非 Hardhat、非31337、分叉配置。导出的 `../docs/site/flower-demo.json` 显示同一 token 的有效与撤销快照，不是两枚 NFT或实时链查询。网页无钱包连接、私钥导入、交易或发行入口；缺少文件必须显示尚未生成，不伪造成功。

普通钱包控制不是真实身份认证；审核声明由可信链下控制者提供，不是身份密码学认证或事实 oracle。digest只校验字节，不证明贡献真实。展示 metadata省略wallet/digest，但ERC-721 owner/events仍公开recipient/contributionId，hash不匿名、撤销不擦除历史，公开发行须另做隐私/法律/安全审查。免费指发行价格，不保证公共链gas免费；钱包转卖风险仍在。NFT术语或锁定不保证合法，口头建议不是监管批准或正式法律意见。PayAssist主线与历史RTM不变，不与Flower自动接线。

本模块依赖与编译产物保留在 `node_modules/`、`artifacts/`、`cache/` 并由 Git 忽略。测试结果按实际运行单独报告。现存商业PDF未重新生成，是Flower更新前旧快照，产品说明已由当前商业Markdown替代。
