# 跨模块证据与奖励协议（冻结 v1）

本协议把 Arena 中**通过独立验证的发现**绑定到链上悬赏 claim，使同一攻击机制无法通过换
claim ID 重复领奖。它是 [RESEARCH_PLAN](RESEARCH_PLAN.md) §8 P0「冻结跨模块证据与奖励协议」
的实现文档；实现落点为 [claim_protocol.py](../rsi4safety/execution/src/rsi4safety/claim_protocol.py)
（Python/Arena 侧）与 [claim-id.js](../contracts/scripts/claim-id.js)（JS/合约侧），两侧对同一
输入必须推导出相同 `claim_id`，由两侧各自的单元测试以同一常量锚定。

## 1. 两条结算流程，不得混用

| 流程 | 合约 | 资产 | 评估者角色 | 用途 |
| --- | --- | --- | --- | --- |
| 支付演示结算 | `PaymentAgent` + `RewardSettlement` | `ExperimentalToken`（XEXP，预充资） | evaluator = 部署者，`configureSettlement`/`settle` | [agent-flow.js](../contracts/scripts/agent-flow.js) 的单轮/多轮支付演示奖励 |
| RTM 悬赏结算 | `BountyVault` + `RTMToken` | RTM（按年减半铸造） | evaluator（owner 可轮换），`configureClaim`/`settleClaim`/`cancelClaim`/`renewClaim` | 面向外部发现的本协议主流程 |

两条流程的通过率、成本与事件**分别报告**。演示流程的 `settlementId = ethers.id(runId:bounty:turn)`
按轮次派生、与内容无关，不满足去重要求；接入 RTM 流程的发现一律使用本协议的
`claim_id`，不得回落到演示流程的 ID 规则。

## 2. 绑定五元组

一个可结算的 claim 必须同时绑定以下五组事实；缺任何一组不得 `configureClaim`：

| 组 | 字段 | 来源 |
| --- | --- | --- |
| 目标版本 | `sut_version`（标签）、`sut_digest`（SUT 树 `tree_hash`）、`package_digest`（版本库 `AgentPackage`） | orchestrator 证据 manifest（`sut_version`/`sut_digest`）与 `versions.active()` |
| 任务与授权 | `fixture_digest = digest(task_fixture.brief_form())` | 证据 manifest 的 `task_fixture` |
| 反例与执行证据 | `evidence_id`、`manifest_digest = digest(manifest)`、`dedup_key = attack_digest` | 证据 bundle 与 [experience.attack_identity](../rsi4safety/execution/src/rsi4safety/arena/experience.py) |
| 验证规则版本 | `protocol` = `arena-trusted-execution-v2`（`PROTOCOL_VERSION`）与本文 `rtm-claim-binding-v1` | `arena/control.py` |
| 奖励 | `beneficiary`（0x 小写地址）、`amount`（最小单位十进制字符串） | evaluator 审定后写入 claim request |

`manifest_digest` 与 `evidence_id` 的自洽性由 `control.verify_evidence` 复核；claim request
登记时必须记录 `manifest["files"]` 的 sha256 摘要表，供领奖审计重放。

## 3. 去重键与 claim_id 推导

**去重键 = `attack_digest`**：`attack_identity()` 对（任务授权 + 攻击动作）做规范化（只抹掉
可变序列化与临时 ID）后取 sha256，是内容级机制指纹。Arena 侧已有的 `regression_key`
（`orchestrator._append_regression`）是同一思想的现成先例；两者不一致时以 `attack_digest`
为准。合约层不做内容去重（`claims[id]` 只有一次配置约束），去重完全由本协议的
`claim_id` 派生规则 + 链下登记承担。

`claim_id` 推导（两侧实现必须逐字节一致）：

```text
payload = {
  "protocol":    "rtm-claim-binding-v1",        # 常量
  "dedup_key":   <attack_digest, 64 hex 小写>,
  "sut_digest":  <SUT 树哈希, 64 hex 小写>,
  "beneficiary": <0x + 40 hex 小写>,
  "amount":      <十进制字符串>,
}
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)  # UTF-8
claim_id  = sha256(utf8(canonical))            # 32 字节，直接作 bytes32
```

约束：payload 只允许字符串字段（数量用十进制字符串，禁止 JSON 数值，避免两侧数字序列化
差异）；地址一律小写；`claim_id` 只依赖内容，与轮次、运行、时间无关。

**同一 `dedup_key` + `sut_digest` + `beneficiary` + `amount` 只允许登记一份 claim request**；
修复后的新版本上发现的新机制（`sut_digest` 变化）是新 claim；同一机制重复提交、换 ID、
换会话复述均为重复，拒登。

## 4. claim request 记录（Arena → 合约桥）

Arena 在发现通过独立裁决并去重通过后，写一条 claim request（JSON Lines，附录 schema），
包含五元组全字段 + `claim_id` + 状态机
（`pending → configured → settled`，旁路 `cancelled` / `renewed`）。桥接器消费 request，
调用 `configureClaim(bytes32(claim_id), beneficiary, amount)` 与 `settleClaim(bytes32(claim_id))`。

重试语义由合约保证：`configureClaim` 一次有效（重复配置同 id 回滚），
`settleClaim` 一次结算、mint 失败原子回滚，跨年未结算走 `renewClaim` 或 `cancelClaim`
后按新 ID 重新登记。`maxPerClaim`/`maxTotalSettled`/年预算不足/暂停时，request 保持
`pending` 并记录失败原因，不得静默丢弃。

## 5. 未接线处（本协议冻结 ≠ 已全部实现）

1. 合约层无内容去重映射：同内容派生相同 `claim_id` 后，链上重复 `configureClaim` 会回滚，
   但不同 evaluator/不同部署实例之间没有跨实例去重。
2. `beneficiary` 与外部攻击者身份没有绑定机制（无钱包证明流程）；当前由 evaluator 登记。
3. commit–reveal 公开提交的**最小合约层已落地**（2026-10-02，`contracts/src/BountyRound.sol`：
   先承诺后揭示、同材料先到先得、关线后裁决、pull 模式领奖），HTTP 会话/配额原型见
   `rsi4safety/execution/src/rsi4safety/arena/interface/`；但"会话提交 → 复现验证 →
   链上判奖"的端到端链路与外部身份绑定仍未接线。
4. 攻击价值量化（新颖性/独立增益/边际贡献分档奖励）未实现，当前一律单一金额。
5. evaluator 轮换与治理只有合约层 `setEvaluator`，无链下多方复核流程。

## 6. 验收对照（RESEARCH_PLAN §8 P0 行）

- 任务/目标/规则摘要、实际执行证据、去重键、受益人 → §2/§3。
- 区分两条流程、不混用通过率 → §1。
- 未接线处显式列出 → §5。
- 两侧 ID 一致性 → `rsi4safety/execution/tests/test_claim_protocol.py` 与
  `contracts/test/claim-id.test.js` 锚定同一常量。

## 附录：claim request 记录 schema

```json
{
  "schema_version": 1,
  "protocol": "rtm-claim-binding-v1",
  "claim_id": "<sha256 hex, 64>",
  "dedup_key": "<attack_digest hex, 64>",
  "fixture_digest": "<digest hex, 64>",
  "evidence_id": "ev-<12 hex>",
  "manifest_digest": "<sha256 hex, 64>",
  "evidence_files": {"<file>": "sha256:<hex>"},
  "sut_version": "<label>",
  "sut_digest": "<sha256 hex, 64>",
  "protocol_version": "arena-trusted-execution-v2",
  "beneficiary": "0x<40 hex 小写>",
  "amount": "<十进制字符串>",
  "created_round": 0,
  "status": "pending",
  "history": [{"at": "<iso8601>", "event": "registered", "detail": ""}]
}
```
