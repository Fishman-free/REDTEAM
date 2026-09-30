# Survey：相关工作与本项目的对应关系（研究计划 §05）

> 对应《智能体支付系统和方案的设计》§05。蓝图为提纲中的条目；每条给出原文、
> 一句话介绍、本仓库已借鉴的部分与后续采纳任务。核对日期：2026-09-27。
> 定位：这些工作支撑本项目的**支付安全评测与对抗修复**方法论；Arena 与 SAGE
> 是本项目的攻防流程与策略进化原型。

## 直接相关的链上案例

| 工作 | 原文/出处 | 一句话介绍 | 本仓库对应 |
|---|---|---|---|
| Freysa | [freysa.ai](https://www.freysa.ai)（2024-11 案例） | 参与者付费发消息，试图说服链上智能体转出奖池；第 195 次尝试经"管理上下文注入"骗过守卫转出 ~$47k。展示了对话攻击的资金风险，但不构成 RSI 的证据。 | 动机案例与威胁模型来源：`sut/payassist`（外部渠道不可信内容）、`docs/THREAT_MODEL`（研究计划 §01 角色边界） |

## 研究内容 → 本仓库映射

| 研究内容 | 工作 | 原文 | 一句话介绍 | 已借鉴 | 后续采纳任务 |
|---|---|---|---|---|---|
| Web3 智能体安全 | CrAIBench | [arXiv:2503.16248](https://arxiv.org/abs/2503.16248)（Real AI Agents with Fake Memories） | 在转账、交易等 150+ Web3 任务中测恶意输入与记忆污染，提出 CrAIBench 评测。 | 攻击场景分类与判别标准思路（benchmark registry 的 seed/期望结构） | 记忆污染类攻击 seed（E04 系统的可执行适配器） |
| 多轮对话攻击 | Crescendo | [arXiv:2404.01833](https://arxiv.org/abs/2404.01833)（Russinovich et al., USENIX Security） | 从看似正常的问题开始，利用模型先前的回答逐步诱导越界。 | —（本轮实现） | Phase 3：`sut_driver` 多轮会话执行 + Crescendo 式攻击器（打用户对话入口） |
| 外部内容伪装成对话 | ChatInject | [arXiv:2509.22830](https://arxiv.org/abs/2509.22830)（ICLR 2026） | 把恶意载荷格式化成原生聊天模板轮次（伪 user/assistant 消息），在 AgentDojo 上把 ASR 从 5.18% 提到 32.05%。 | 来源标记设计（`[商家客服对话·不可信]` 等前缀即其反命题） | Phase 3：ChatInject 式伪装攻击器（测来源与权限混淆，X05 的自动化版） |
| 寻找多样化攻击 | Rainbow Teaming | [arXiv:2402.16822](https://arxiv.org/abs/2402.16822)（Samvelyan et al., Meta FAIR） | 把对抗提示生成建模为质量-多样性（MAP-Elites）问题，同时搜索有效且多样的攻击。 | 经验库的攻击指纹（`experience.py` 的 identity fingerprints） | Phase 3：手法指纹聚类 + 多样性配额进 attacker brief，避免攻击环反复同一手法 |
| 评测智能体安全 | AgentDojo | [arXiv:2406.13352](https://arxiv.org/abs/2406.13352)（Huang, Debenedetti et al.） | 在带工具调用的真实感任务中测工具返回注入，同时评估攻击效果与正常任务完成。 | "攻击效果 + 正常任务完成"双指标（constitution 的 attempted/actual/utility 三事实、四态结果） | 工具返回注入面扩展（tool_result 表面已在 registry，适配器补齐） |
| 改进提示 | GEPA | [arXiv:2507.19457](https://arxiv.org/abs/2507.19457)（Agrawal et al.） | LLM 反思自身执行轨迹并进化提示，Pareto 候选选择；样本效率远超 RL。 | `ReflectiveCandidateProposer`（反思式候选提议，白名单字段约束） | 把 GEPA 式 Pareto 候选选择引入防御修复的候选归档（`CandidateArchive`） |
| 积累经验 | ACE | Agentic Context Engineering（Stanford/SambaNova/Berkeley，2025-10） | 把执行经验整理成可增量更新的"策略手册"（generator–reflector–curator），避免整写覆盖。 | `ExperienceStore`（append-only 已验证经验 + 回归场景回馈） | 经验条目结构升级：触发条件→违反边界→有效修复→合法例外→适用版本（RSI_IMPROVEMENT_PLAN P3-1） |
| 修改自身代码 | Darwin Gödel Machine | [arXiv:2505.22954](https://arxiv.org/abs/2505.22954)（Sakana AI） | 智能体修改自身代码、用任务测试检验效果并保留不同版本（archive + 增长式自改进）。 | `VersionStore`（worktree 隔离候选、父版本绑定、晋级/回滚）、`defender_scope=full_agent` 路线 | 修复经验跨版本继承的量化报告（Phase 4 learning curve） |

## 本项目原型

- **Arena（攻防流程）**：将攻击提交、执行判别、反例交付和代码修复串成流程，验证通过后更新防御版本——`src/rsi4safety/arena/orchestrator.py`，协议见 `docs/ARENA.md` 与 `docs/ARENA_EVOLUTION_SPEC.md`。
- **SAGE（策略进化）**：通过变异、组合和筛选探索提示、记忆及工具规则的改进——单进程原型在 `learning.py`（规则式 + 反思式提议器、经验库、晋级门），外层进化设计见 `docs/RSI_IMPROVEMENT_PLAN.md` P3-1。

## 与提纲的对应结论

1. 提纲 §04 的五步修复循环（确认防守失败 → 交付攻击方案 → 防御智能体改进 → 换例子测试 → 通过后保留）与 GEPA（反思改提示）、ACE（经验手册）、DGM（改代码 + 版本保留）三者一一对应：反思来源是执行轨迹，记忆载体是经验库，版本载体是 VersionStore。
2. 提纲 §03 的两个攻击入口在本仓库的落法：用户对话入口 = 平台核验的用户通道（`authorization.py`）+ 多轮攻击器（Phase 3，Crescendo 式）；外部对话/内容入口 = 四个不可信 surface + ChatInject 式伪装攻击器（Phase 3）。
3. 提纲 §05 的判别标准要求（"判断标准基于用户预先设定的 system prompt 或其他约束，提前明确规定清晰"）由预注册判据实现：`benchmark_seeds.RULE_CRITERIA` + 每 seed 的 `adjudication`，评测前冻结。
