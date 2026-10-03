# 全项目研究资料索引

当前实现与研究判断以 [项目入口](../README.md)、[总研究方案](RESEARCH_PLAN.md) 为准。本页只导航原始资料：根目录保存区块链、支付执行和跨模块方案；RSI 专项资料与支付系统 PDF 放在 [RSI 参考目录](../rsi4safety/docs/INDEX.md)。

原稿保留当时的路径、术语和数量。日期化记录用于追溯对应版本，不代替当前测试；未接入、未完成或存在待修问题，都不足以判定过时。原稿中的研究假设与拟议接口不能视为已实现功能。

| 类别 | 资料 | 用途与状态 |
|---|---|---|
| 总研究方案 | [区块链攻击悬赏与 RSI 持续评估研究构想](references/research/RSI攻击悬赏与持续评估机制_研究构想.md) | 总机制原稿：协议控制目标、外部反例、独立验证、奖励与持续改进 |
| 区块链设计 | [RTM 悬赏代币与金库设计](references/research/RTM_BOUNTY_DESIGN.md) | RTMToken/BountyVault 当前预算预留、累计上限与认领/续期生命周期；与 Arena 的连接仍待实现 |
| 外部参与接口 | [攻击接口设计](references/ATTACK_INTERFACE_DESIGN.md) | 会话配额、承诺、验证和领奖的设计草案；拟议 round/commit–reveal/pull 接口不是当前合约 API |
| 跨模块研究协议 | [实验协议](references/research/EXPERIMENT_PROTOCOL.md) | SQLite、EVM、RSI/Arena 的证据、指标分母与奖励边界；后端结果分别解释 |
| 跨模块路线 | [开发路线（2026-09-23）](references/research/DEVELOPMENT_ROADMAP.md) | 可信裁决、领域适配、证据与本地奖励对接；阶段性暂缓不等于废弃 |
| 日期化证据 | [整合记录](references/research/INTEGRATION.md)、[2026-09-18 安全审查](references/research/SECURITY_REVIEW_2026-09-18.md)、[2026-09-23 全项目验收](references/research/VALIDATION_2026-09-23.md) | 双轨整合、合约/支付/RSI 回归与当时风险；旧结果不能替代当前验证 |
| 合约审计记录 | [2026-09-27 合约审计](references/research/SECURITY_AUDIT_2026-09-27.md) | 远端 `6394fc2` 的审计与修复来源；原环境、结论和统计按原文保留，本次合并验证见项目 README |
| RSI 子项目 | [RSI 参考索引](../rsi4safety/docs/INDEX.md)、[支付系统 PDF](../rsi4safety/docs/references/智能体支付系统和方案的设计.pdf) | 支付场景、Arena、策略进化、修复者对照、预注册、专项实验及原始提纲 |

资料按职责分目录；总研究范围仍包括区块链经济约束、支付执行、外部反例、独立验证和持续改进。
