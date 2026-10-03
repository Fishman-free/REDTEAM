# 历史结果与替代版本

当前操作入口是[根 README](../README.md)、[PayAssist 指南](../rsi4safety/payment_agents/README.md)；当前判断统一在[研究方案](../docs/RESEARCH_PLAN.md)。历史材料完整保留，不能用旧版通过率或拟议功能替代当前验证。

| 位置 | 保存内容 | 替代关系 |
|---|---|---|
| [experiments/payassist-v2](experiments/payassist-v2/README.md) | 2026-10-01 至 10-03 的两暴露面、prompt-only 原始模型结果与报告 | 当前结论以 raw host [复核](../rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.md)解释；原数字原字节未改 |
| [experiments/legacy-rsi](experiments/legacy-rsi/README.md) | 旧 Arena/策略实验与日期化验收 | 原结果用于对应历史实现，不为当前防御包背书 |
| `docs/legacy-rsi/` | 旧落地计划、基础架构、操作手册与模型实验说明 | 被当前 README 和研究方案替代的操作/实现叙述；独立原型源码保留 |
| `docs/2026-10-03-pre-consolidation/` | 本次收敛前的 README、研究方案和索引快照 | 保留原说明与迁移上下文 |
| [远端合入前文档](docs/2026-10-03-origin-main/docs/RESEARCH_PLAN.md) | origin/main的原始入口、实施评估和日期验证 | 当前PayAssist路径与独立RTM/接口原型分别解释；原论文/商业计划保留在docs |
| [history/README.md](history/README.md) | 2026-09-30 之前的原项目入口 | 由当前入口和研究方案替代 |
| [history/.github/workflows/tests.yml](history/.github/workflows/tests.yml) | 旧目录布局的 CI | [当前 CI](../.github/workflows/tests.yml) |
| `local-residue/`（Git 忽略） | 原目录字节码和安装元数据 | 仅本机残留，不是当前源码 |

[manifest.json](manifest.json)记录原位置、保留位置、原字节 SHA-256 和替代位置。`files/summary` 的数量为 2026-09-30 基线；`reorganizations` 追加本次迁移，历史原始 hash 不随活动源码更新。归档原件中的路径和链接按当时文本保留；当前索引提供可用入口。

独立契约、原始总构想、RTM/合约设计、预注册、修复者对照和基准规格仍在参考目录；未接入或日期较早不足以删除这些资产。没有搬走生产源码。

完整宿主 state 位于 `rsi4safety/.rsi4safety/payassist-v2/`，保持 Git 忽略且未改。提交的[五份关键 trial](../rsi4safety/payment_agents/evidence/samples/manifest.json)只用于核查典型行为；完整4158次分母和链验证需要本地原始 state。
