# RSI4Safety

本轮开发和运行统一从 **[payment_agents/README.md](payment_agents/README.md)** 进入：PayAssist 的 L0/L1、四种外部输入、防御包、低预算攻防闭环及宿主证据。研究设计与真实结果只在[总研究方案](../docs/RESEARCH_PLAN.md)维护。

## 安装

从 `rsi4safety/` 执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest payment_agents/tests -q
```

支付模型的本机服务由 Studio SSH 隧道连接，默认 `Qwen/Qwen3-4B-Instruct-2507`：

```bash
python3 execution/scripts/studio_model.py start
python3 execution/scripts/studio_model.py status
# 结束连接时，只关闭本项目隧道
python3 execution/scripts/studio_model.py stop
```

`SUT_MODEL/SUT_BASE_URL/SUT_API_KEY` 配置被测支付模型；默认接口 `http://127.0.0.1:18081/v1`。第三方研究角色使用 `glm-5.3`。凭据和 `.rsi4safety/` 状态保持 Git 忽略，不提交访问 token。

## 当前路径与保留路径

| 路径 | 用途 |
|---|---|
| `payment_agents/payassist_agent/` | 当前多轮自主工具支付实验、攻防编排和规则评判 |
| `payment_agents/L0_readonly/`、`L1_single_payment/` | 宿主固定场景与权限夹具 |
| `execution/src/rsi4safety/arena/` | 当前复用的预算/审计/版本组件，以及保留的旧 Arena 原型 |
| `execution/src/rsi4safety/rsi_eval/`、策略与 engineering 原型 | 独立研究资产；不作为当前支付实验默认入口 |
| `payment_agents/paygate/`、`payassist/`、`paychain/` | 旧靶标和协作原型，源码与测试继续保留 |

保留路径的历史操作说明在[归档](../archieve/README.md)，独立契约和未执行研究设计在[参考索引](docs/INDEX.md)。它们没有因尚未接入主线而删除。

历史 campaign 冻结了运行时指纹；当前源码变化后应创建新 state 目录，不能把旧 state 当成可无条件续跑的新实验。
