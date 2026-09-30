# 合约与本地支付实验

本模块与 [RSI4Safety](../rsi4safety/README.md) 并列，包含合约、支付执行和相应验证。完整研究目标及未连接部分见[总研究方案](../docs/RESEARCH_PLAN.md)。

| 目录 | 内容 |
|---|---|
| [src/](src/) | 五份 Solidity 合约 |
| [scripts/](scripts/) | 本地部署、付款执行、事件核验与单轮/多轮演示 |
| [redteam/](redteam/) | 支付决策、SQLite/HTTP 实验与模型传输 |
| [test/](test/) / [tests/](tests/) | 合约/JS 测试与支付 Python 测试 |
| [scenarios/](scenarios/) / [prompts/](prompts/) | 场景、可信采购输入、独立评估真相和提示词 |

[PaymentAgent](src/PaymentAgent.sol) 约束付款；[ExperimentalToken](src/ExperimentalToken.sol) 提供预铸合成资产；[RewardSettlement](src/RewardSettlement.sol) 结算演示奖励。[RTMToken](src/RTMToken.sol) 与 [BountyVault](src/BountyVault.sol) 实现另一套发行与悬赏预算，尚未接入 payment-agent 演示或 Arena。本版已合入 `6394fc2`：金库支持显式续期与可配置累计结算上限，禁用放弃所有权；付款操作与发票分别防重放，三个实验合约增加部署参数校验。累计上限默认不收紧，须由 owner 配置；过期续期仍受当前年预算限制，不保证兑付。两种奖励机制均保留，详见 [RTM 设计](../docs/references/research/RTM_BOUNTY_DESIGN.md)。

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

本模块依赖与编译产物保留在 `node_modules/`、`artifacts/`、`cache/` 并由 Git 忽略。测试结果统一记录在[项目 README](../README.md)。
