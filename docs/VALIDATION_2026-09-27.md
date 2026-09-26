# 本地验收记录：研究计划对齐（双入口 / 场景分级 / 攻击环 / RSI 泛化）

日期：2026-09-27

基线提交：`3828bb3`（origin/main）

工作分支：`feat/agentpay-plan-2026-09`

环境：Windows、仓库虚拟环境 Python 3.13.9、Node.js 24.15.0。仓库 CI 仍使用其原有 Python 3.12 / Node.js 22 配置；本地结果不能替代远端 CI。

依据：《智能体支付系统和方案的设计》（2026-09-24 提纲）；映射见 `docs/RESEARCH_PLAN_2026-09-27.md`。本轮**未配置任何真实模型调用**。

## 1. 回归验证

| 验证范围 | 命令/方法 | 本地结果 |
|---|---|---|
| SQLite/RSI 宿主（含 rsi_eval 8 项） | `python -m pytest -q` | 80 passed，27 subtests passed |
| 完整 Arena | `pytest tests/arena -q -o faulthandler_timeout=120` | 235 passed，8 skipped，156 subtests（最终全量，2026-09-27） |
| PayGate SUT | `sut/paygate`: `pytest tests -q` | 19 passed |
| PayAssist SUT | `sut/payassist`: `pytest tests -q` | 16 passed |
| PayChain SUT（新增） | `sut/paychain`: `pytest tests -q` | 7 passed |
| 本地 EVM/RTM | `npm test` | 55 passing |

## 2. 基准与实验证据

- A01 vs PayAssist 全系统基准（17 seeds，0 unsupported）连续两轮结果一致：11 pass / 6 fail，失败均为 seeded-v0 目标上的真实攻击成功（true positive），跨 run 结果可复现。
- RSI 泛化实验：`docs/RSI_EVAL_RESULTS_2026-09-27.json`；四个单维度攻击族、四臂学习曲线，held-out 新问题修复率 20→25→33→50→100（memory_narrow），族内变体一轮泛化 100%，经验驱动修复成本为通用不变量路线的 1/4，clean utility 全程 100%。
- 攻击投递：A01-X09（Crescendo 多轮）、A01-X10（ChatInject 伪装）实跑 true positive（wrong_recipient）。
- 实验报告与局限声明：`docs/EXPERIMENT_2026-09-27.md`。

## 3. 本轮修复的平台缺陷

- **SUT 进程身份混淆**：Windows 下 taskkill/端口释放窗口内，陈旧 uvicorn 进程可响应新 run 的健康检查，导致一次跨 run 账本污染（陈旧 surface 内容影响后续 seed）。修复：SUT 启动 nonce 注入 + `wait_healthy` 身份校验（paygate/payassist/paychain 三处 `/health` 均带 nonce）。修复后基准跨 run 稳定。

## 4. 已知边界

- A02 退款域与 B01/C01/D02/E04 的可信状态适配器仍 unsupported（21/43），原因在 bench 报告如实标注；B04 的审批请求证据适配器未实现（以"无授权 = payment_forbidden"判别替代）。
- RSI 泛化结果限于确定性目标与规则式提议器；真实模型五臂战役按 `docs/RSI_PREREGISTRATION.md` 预注册、未执行。
- RTM/BountyVault 维持独立研究组件；未接链上、未接真实资金。
