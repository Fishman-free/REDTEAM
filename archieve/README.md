# 已替代版本归档

归档依据是有明确替代版本。尚未接入、尚未完成、存在缺陷或日期较早，都不构成归档理由。当前合约、支付执行、RSI 与跨域实验已全部在活动目录；研究原稿、有效规格、预注册和日期化证据见 [全项目资料索引](../docs/INDEX.md)。

| 归档对象 | 原因 | 当前入口 |
|---|---|---|
| [history/README.md](history/README.md) | 原项目说明已由两份核心文档接替；旧路径、覆盖计数和 RSI 泛化结论需按当前评估校正 | [README](../README.md)、[RESEARCH_PLAN](../docs/RESEARCH_PLAN.md) |
| [history/.github/workflows/tests.yml](history/.github/workflows/tests.yml) | 原布局的 CI 快照，已被适配当前模块目录的现行工作流替代；不是停用任何测试模块 | [当前测试 CI](../.github/workflows/tests.yml) |
| `local-residue/`（Git 忽略） | 原目录残留的 Python 字节码和旧可编辑安装元数据，源码与安装位置已更新 | 活动 `contracts/`、`rsi4safety/execution/`、`rsi4safety/payment_agents/` 与现有虚拟环境 |

[manifest.json](manifest.json) 保存 191 个原受版本控制文件的路径映射和 SHA-256：190 个活动文件、1 个被替代的原 README；另记录 1 份被替代的 CI 快照。原 README 和 CI 快照按原字节保留。当前代码中的路径、包配置、测试配置及工作流修改有显式标记。

基线字段记录目录整理时的状态；后续远端安全修复另记于 `upstream_merges`，包含新文件去向与来源摘要。该清单用于追溯，不要求活动代码永远保持基线字节。

合约、RTM 设计、总研究方案以及研究实验均不属于归档。新增归档时应同时记录原位置、替代位置和理由；无明确替代关系的有用材料继续保留在活动或参考目录。
