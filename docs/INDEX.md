# 资料索引

**当前产品说明优先阅读 [商业计划 Markdown](business/redteam-business-plan.md) 与 [REDTEAM Flower 协议](FLOWER_RECOGNITION.md)。** 企业安全服务是商业主线；Flower 是独立、可选、待审查的本地 NFT 原型，历史 RTM ERC-20 仍不属于商业路线。现存 PDF 未重新生成：商业 PDF 是 Flower 更新前快照，产品说明已由当前 Markdown 替代；论文 PDF/Markdown 保留历史研究，不作为当前结果。

当前 PayAssist 主线设计与判断在[研究方案](RESEARCH_PLAN.md)，运行从[PayAssist 指南](../rsi4safety/payment_agents/README.md)进入。2026-10-05 live.v3 验收通过仍有12开放发现，不是生产安全证书。

| 资料 | 状态 |
|---|---|
| [当前商业计划 Markdown](business/redteam-business-plan.md) | 2026-10-10 讨论稿；安全评测/整改复核/持续回归为主，Flower 独立本地旁路；客户收入待验证，法律引文未独立核验 |
| [REDTEAM Flower 技术协议](FLOWER_RECOGNITION.md)、[静态演示页](site/flower.html)、[合约入口](../contracts/README.md) | ERC-721 + ERC-5192；可信审核 + EOA 接收同意、免费且锁定、撤销留原 token；无分叉 Hardhat 31337 合成演示，非生产或法律批准 |
| [Flower 本地实现与验证记录](FLOWER_IMPLEMENTATION_VERIFICATION.md) | 267 项合约与 478 项相关 Python 回归通过；浏览器加载、移动几何与五类失败关闭检查；公开发行、法律审查和全面图像美术验收未完成 |
| [历史商业 PDF](business/redteam-business-plan.pdf) | **未重新生成，本次 Flower 更新前旧快照；产品内容已由上方当前 Markdown 替代**，不能单独作为当前说明 |
| [2026-10-05 live.v3 对照报告](../rsi4safety/payment_agents/evidence/VALIDATION10H_COMPARATIVE_2026-10-05.md) | 真实模型预算验证轮；L0/L1 分列，12开放发现、修复容量与有限验收边界披露 |
| [区块链攻击悬赏与持续评估总构想](references/research/RSI攻击悬赏与持续评估机制_研究构想.md) | 原始研究目标，保留 |
| [RTM 悬赏预算与合约设计](references/research/RTM_BOUNTY_DESIGN.md) | 独立历史研究/实现，不是 Flower，尚未接入当前 PayAssist，排除商业路线 |
| [外部攻击接口设计](references/ATTACK_INTERFACE_DESIGN.md)、[旧 Arena 会话原型](../rsi4safety/execution/src/rsi4safety/arena/interface/)、[BountyRound](../contracts/src/BountyRound.sol) | 独立 HTTP/commit–reveal 原型；当前 PayAssist 无公共提交到链上判奖端到端接线 |
| [证据与奖励协议 v1](EVIDENCE_REWARD_PROTOCOL.md)、[RTM 桥](../contracts/scripts/rtm-reward-bridge.js) | 旧 Arena claim 与本地 BountyVault 桥；不是当前 PayAssist 奖励实现 |
| [历史研究论文 Markdown](paper/payment-agent-security-rsi.md)、[历史论文 PDF](paper/payment-agent-security-rsi.pdf) | 历史确定性研究稿；20%→100%受未见族分母缩小影响，逐点成功项始终2，不能证明跨族泛化；不含当前 live.v3 结果，PDF未更新 |
| [跨模块协议](references/research/EXPERIMENT_PROTOCOL.md)、[开发路线](references/research/DEVELOPMENT_ROADMAP.md) | 独立后端/证据/整合研究，保留 |
| [整合记录](references/research/INTEGRATION.md)、[2026-09-18审查](references/research/SECURITY_REVIEW_2026-09-18.md)、[2026-09-23验收](references/research/VALIDATION_2026-09-23.md)、[2026-09-27合约审计](references/research/SECURITY_AUDIT_2026-09-27.md) | 来源记录，结果仅对应当时版本，不是 Flower 审计 |
| [支付系统原始 PDF](../rsi4safety/docs/references/智能体支付系统和方案的设计.pdf)、[RSI 独立规格](../rsi4safety/docs/INDEX.md) | 三环、身份与修复能力研究依据 |
| [真实模型工程筛查包](../rsi4safety/payment_agents/evidence/v3-smoke-2026-10-03/README.md) | 同提示工程对照、截断复测、角色包有限筛查；不冒充规范闭环晋级 |
| [宿主证据复核](../rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.md)、[原始实验](../archieve/experiments/payassist-v2/README.md) | 当前解读与未改原件分开 |
| [远端历史研究原件](../archieve/docs/2026-10-03-origin-main/docs/RESEARCH_PLAN.md)、[远端历史 README](../archieve/docs/2026-10-03-origin-main/README.md) | 原字节保留，不作为当前操作或统计 |
| [归档清单](../archieve/manifest.json) | 去向、替代关系、字节 hash |
