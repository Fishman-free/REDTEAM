# 资料索引

当前设计和结果判断统一在[研究方案](RESEARCH_PLAN.md)，运行从[PayAssist 指南](../rsi4safety/payment_agents/README.md)进入。本页导航独立研究与历史证据，不另列统计。

| 资料 | 状态 |
|---|---|
| [区块链攻击悬赏与持续评估总构想](references/research/RSI攻击悬赏与持续评估机制_研究构想.md) | 原始研究目标，保留 |
| [RTM 悬赏预算与合约设计](references/research/RTM_BOUNTY_DESIGN.md)、[合约入口](../contracts/README.md) | 独立研究/实现，尚未接入当前 PayAssist |
| [外部攻击接口设计](references/ATTACK_INTERFACE_DESIGN.md)、[旧Arena会话原型](../rsi4safety/execution/src/rsi4safety/arena/interface/)、[BountyRound](../contracts/src/BountyRound.sol) | 草案与独立HTTP/commit–reveal原型；当前PayAssist没有公开提交到链上判奖的端到端接线 |
| [证据与奖励协议v1](EVIDENCE_REWARD_PROTOCOL.md)、[RTM桥](../contracts/scripts/rtm-reward-bridge.js) | 旧Arena已登记claim，JS桥驱动本地BountyVault；不是当前PayAssist campaign的奖励实现 |
| [研究论文](paper/payment-agent-security-rsi.md)（[PDF](paper/payment-agent-security-rsi.pdf)） | 历史确定性研究稿，不含当前真实模型结果；20%→100%曲线受未见族分母缩小影响，不能证明跨族泛化 |
| [商业计划](business/redteam-business-plan.md)（[PDF](business/redteam-business-plan.pdf)） | 讨论稿，客户/收入为待验证假设；由[构建脚本](../scripts/build_documents.py)生成PDF |
| [跨模块实验协议](references/research/EXPERIMENT_PROTOCOL.md)、[开发路线](references/research/DEVELOPMENT_ROADMAP.md) | 独立后端、证据和整合研究，保留 |
| [整合记录](references/research/INTEGRATION.md)、[2026-09-18 审查](references/research/SECURITY_REVIEW_2026-09-18.md)、[2026-09-23 验收](references/research/VALIDATION_2026-09-23.md)、[2026-09-27 合约审计](references/research/SECURITY_AUDIT_2026-09-27.md) | 跨模块/合约的来源记录，结果只对应当时版本 |
| [支付系统原始 PDF](../rsi4safety/docs/references/智能体支付系统和方案的设计.pdf)、[RSI 独立规格索引](../rsi4safety/docs/INDEX.md) | 三环、身份和修复能力研究依据 |
| [宿主证据复核](../rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.md)、[原始模型实验](../archieve/experiments/payassist-v2/README.md) | 当前解读与未改原件分开保存 |
| [远端历史评估原件](../archieve/docs/2026-10-03-origin-main/docs/RESEARCH_PLAN.md)、[远端日期验证原件](../archieve/docs/2026-10-03-origin-main/README.md) | origin/main合入前原字节保留，旧操作/统计不作为当前运行说明 |
| [归档清单](../archieve/manifest.json) | 去向、替代关系、字节 hash |
