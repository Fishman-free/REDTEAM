# RSI 子项目参考资料

本目录保留 RSI/Arena 的设计、研究计划与实验记录。运行入口见 [RSI README](../README.md)；跨模块结论见 [总研究方案](../../docs/RESEARCH_PLAN.md)，区块链与支付执行资料见 [全项目参考索引](../../docs/INDEX.md)。本页只作目录。

原稿保留当时的路径、数量与结论；日期化报告不能替代当前验证。尤其 2026-09-27 RSI 未见族曲线存在分母随训练缩小的问题，不能据其上升认定跨族泛化，详见总研究方案。未执行的计划与待修实验继续保留。

| 类别 | 资料 | 用途与状态 |
|---|---|---|
| 原始提纲 | [智能体支付系统和方案的设计](references/智能体支付系统和方案的设计.pdf) | 双入口、场景分级、攻防修复与修复能力研究 |
| 研究计划 | [PDF 落地计划（2026-09-27）](references/research/RESEARCH_PLAN_2026-09-27.md)、[RSI 改进计划](references/research/RSI_IMPROVEMENT_PLAN.md) | 里程碑、改进动机与诊断依据；完成状态需结合当前实现核对 |
| 待执行研究规格 | [修复者三条件对照](references/research/REPAIRER_COMPARISON_SPEC.md)、[五臂预注册](references/research/RSI_PREREGISTRATION.md) | 分别检验修复方法、经验与反馈的贡献；预注册不代表实验已执行 |
| 基准与文献 | [基准设计](references/research/BENCHMARK_SPEC.md)、[相关工作映射](references/research/SURVEY.md) | 任务规格与设计来源；规格数不同于可执行数，论文效果不同于本仓库实测 |
| 实现与运行参考 | [基础架构](references/research/ARCHITECTURE.md)、[Arena 手册](references/research/ARENA.md)、[模型实验](references/research/GLM_EXPERIMENTS.md) | 策略级 RSI 与 Arena 的原始技术背景；运行命令以当前 README 为准 |
| 协议与靶标 | [Arena 内部契约](references/research/ARENA_SPEC.md)、[进化机制契约](references/research/ARENA_EVOLUTION_SPEC.md)、[预置漏洞](references/research/arena/SEEDED_VULNS.md) | 协议、信任边界和靶标来源；两份契约各有范围 |
| 日期化实验 | [2026-09-16 GLM 攻防实验](references/research/EXPERIMENT_2026-09-16.md)、[2026-09-27 确定性实验](references/research/EXPERIMENT_2026-09-27.md)、[对应 RSI 原始结果](references/research/RSI_EVAL_RESULTS_2026-09-27.json) | 已知反例修复与确定性观测；不背书已发现统计问题的泛化结论 |
| 日期化验收 | [2026-09-27 研究计划对齐验收](references/research/VALIDATION_2026-09-27.md) | 双入口、场景、攻击环与 RSI 实验当时的验证；跨模块验收另见全项目索引 |
