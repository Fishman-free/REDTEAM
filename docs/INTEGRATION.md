# REDTEAM 分支整合记录

日期：2026-09-21。本文记录本地整合分支 `integrate/agent-evolution` 的来源和验证，不是远端发布声明。

## 来源

- `origin/main` 在本次整合前为 `c777113`：旧 payment-agent/EVM 闭环、合约 SafeERC20/配置事件加固、RTMToken/BountyVault 与安全审查文档。
- `origin/codex/agent-evolution` 与 `origin/safety/windows-portability` 指向 `32d445c`：RSI4Safety 基础改进闭环、PayGate/PayAssist SUT、Arena、Windows 进程树和 CI 修复。
- `origin/rsi4safety` 的研究计划已在 evolution 祖先链中；未把旧 README 整篇覆盖当前实现。
- 三个最初 payment-agent 功能分支已由 GitHub PR 1–3 合入 main；没有重新 cherry-pick。

## 冲突处理

合并只在三个文件产生冲突：

- `.gitignore`：取并集，保留 EVM、SQLite、RSI、机器本地状态和环境文件忽略规则。
- `README.md`：重写为双轨入口，保留 legacy/EVM 的真实限制，明确 Arena 尚未接入链上支付或 RTM 奖励。
- `tests/test_core.py`：保留 `redteam.core.Store` 的 4 个 legacy 用例；RSI 版本另存为 `tests/test_rsi4safety_core.py`，避免不同协议测试互相覆盖。

为保持双轨可重复执行，增加：

- `requirements-dev.txt`：宿主 editable package、FastAPI/uvicorn、httpx、pytest。
- `pyproject.toml` 的 pytest 根目录和 `pythonpath` 配置。
- `scenarios/payment-delivery-v1/`：场景配置、agent trusted feed、evaluator truth 三个独立文件。
- `redteam/scenario.py`：加载版本和限额常量的薄适配层。
- `docs/EXPERIMENT_PROTOCOL.md`：指标分母、证据、候选晋级和奖励边界。

## CI 政策

`.github/workflows/tests.yml` 分为：

1. Python/SUT 矩阵（Ubuntu + Windows），宿主 `tests/`、两个 SUT、离线 RSI demo、Arena dry-run/audit verify。
2. Ubuntu EVM job，`npm ci`、Hardhat 全套、legacy demo 与多轮 demo。

SUT 的 `app` 顶层包分别在 `sut/paygate` 和 `sut/payassist` 工作目录测试，避免导入串线。默认环境 `REDTEAM_LLM_ENABLED=0`，不进行真实模型请求。

Pages 从测试工作流拆出：只有 `main` 的 `offline-tests` 成功、仓库变量 `REDTEAM_PAGES_ENABLED=true` 且管理员已配置 GitHub Pages Actions source 时才部署。变量默认为空，Pages 权限配置问题不会把代码测试标为失败。

## 验证口径

本次本地已确认：

- legacy Python 基线：19/19。
- legacy + 主线合约 Hardhat：35/35。
- PayGate：19/19；PayAssist：16/16。
- Arena Windows 进程树清理回归：5/5（含 2 个单元子测试；实际 Windows SUT 生命周期验证受平台运行权限/时间限制时应看完整套件）。

远端 CI 仍需在推送此整合分支后重新生成结果。`SECURITY_REVIEW_2026-09-18.md` 中的历史计数仅作背景，不能替代本次运行。

## 保留的限制

- `RTMToken/BountyVault` 没有接入旧 `agent-flow` 或 Arena；A2A/commit-reveal/公开领奖仍是设计。
- Arena 容器当前不能承诺完全断网；进程内 SUT 不是恶意代码沙箱。
- EVM 多轮状态仅在一次 Hardhat 进程内存在；不声明跨进程恢复或主网资金安全。
- 真正的 LLM、外部 RPC、部署、推送和 Pages 发布均不在本次整合中执行。
