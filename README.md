# REDTEAM

当前主线是 **PayAssist L0/L1 支付智能体的攻击、修复与独立验证**。从[运行指南](rsi4safety/payment_agents/README.md)开始；三环设计、信任边界和真实实验判断统一在[研究方案](docs/RESEARCH_PLAN.md)。

```text
rsi4safety/payment_agents/   当前 PayAssist 运行、四暴露面、防御包和评判
rsi4safety/execution/        共享宿主组件与保留的独立研究原型
contracts/                  独立支付合约、RTM 悬赏预算与本地链实验
scripts/                    历史宿主证据审计
archieve/                   原始结果与已被当前指南替代的历史说明
```

## 开始

从仓库根目录执行。已有环境可以复用：

```bash
python3 -m venv rsi4safety/.venv
source rsi4safety/.venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

线上模型实验按[PayAssist 指南](rsi4safety/payment_agents/README.md)另行启动。离线测试通过和模型实验通过是不同结论；当前资金均为宿主模拟资金。

## 证据与其他研究

本轮4B真实模型[工程筛查证据](rsi4safety/payment_agents/evidence/v3-smoke-2026-10-03/README.md)：同提示裸对照DEV2/8，工程包DEV8/8、transfer8/8、acceptance7/8；截断反例复测3/3、角色包有限换例筛查10/10分别保留。它们不构成规范攻击发现、独立晋级或未见族推广；原失败、费用缺口及可复算原始包均在链接中。

2026-10-03 的旧版 L0/L1 原始运行共 4158 次。当前[宿主证据复核](rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.md)校正了版本、分母和报告解释；原报告原字节见[实验归档](archieve/experiments/payassist-v2/README.md)。这些旧版 prompt-only、两暴露面实验与当前防御包/四暴露面协议不可直接比较。

[合约模块](contracts/README.md)、[总构想与独立规格](docs/INDEX.md)继续保留。旧Arena已有本地RTM证据奖励桥和公开提交原型；当前PayAssist campaign尚未接入这条桥，见[证据与奖励协议](docs/EVIDENCE_REWARD_PROTOCOL.md)。

[研究论文](docs/paper/payment-agent-security-rsi.md)（[PDF](docs/paper/payment-agent-security-rsi.pdf)）与[商业计划](docs/business/redteam-business-plan.md)（[PDF](docs/business/redteam-business-plan.pdf)）是保留的讨论稿。论文历史泛化统计和商业收入假设不替代当前验证。归档去向、替代关系和 SHA-256 见[归档清单](archieve/manifest.json)。
