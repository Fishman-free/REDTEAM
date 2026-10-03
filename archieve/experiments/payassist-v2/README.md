# PayAssist v2 原始实验

此目录保存原报告原字节。实验使用当时的 prompt-only 修复包、dialogue/tool_return 两暴露面和冻结历史套件。当前四暴露面、防御包、transfer 切分、预算与门禁语义已改变；不能直接把新旧通过率相减作为改进证明。

| 日期/实验 | 原始结果 | 原报告 |
|---|---|---|
| 2026-10-01 多轮开发基线 | [STUDIO_4B_MULTITURN](STUDIO_4B_MULTITURN_2026-10-01.json)、[后处理复核](STUDIO_4B_MULTITURN_2026-10-01_AUDIT.json) | 原解释在收敛前研究方案快照 |
| 2026-10-02 L0 小闭环 | [LIVE_L0_CAMPAIGN](LIVE_L0_CAMPAIGN_2026-10-02.json) | 原解释在收敛前 PayAssist 指南快照 |
| 2026-10-02 L0 全量 | [JSON](LIVE_L0_FULL_CAMPAIGN_2026-10-02.json) | [MD](L0_FULL_CAMPAIGN_REPORT_2026-10-02.md) |
| 2026-10-02 L1 全量 | [JSON](LIVE_L1_FULL_CAMPAIGN_2026-10-02.json) | [MD](L1_FULL_CAMPAIGN_REPORT_2026-10-02.md) |
| 2026-10-03 L0 多数门禁 | [JSON](LIVE_L0_CAMPAIGN_2026-10-03.json) | [MD](L0_CAMPAIGN_REPORT_2026-10-03.md) |
| 2026-10-03 L1 多数门禁 | [JSON](LIVE_L1_CAMPAIGN_2026-10-03.json) | [MD](L1_CAMPAIGN_REPORT_2026-10-03.md) |

2026-10-03 原报告的权限文案、晋级字段、提前中止原因展示，以及后续解读的 cohort 分母需要校正。当前依据是[宿主复核 JSON](../../../rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.json)与[可读复核](../../../rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.md)，不回写原报告。

重跑审计（从仓库根目录，不调用模型）：

```bash
python3 scripts/audit_payassist_evidence.py \
  --state-dir rsi4safety/.rsi4safety/payassist-v2/campaign-L0-20261003 \
  --state-dir rsi4safety/.rsi4safety/payassist-v2/campaign-L1-20261003 \
  --output rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.json \
  --markdown rsi4safety/payment_agents/evidence/HOST_EVIDENCE_REVIEW_2026-10-03.md
```

脚本独立校验链条与每个 trial 的字节 checksum，再按用例/版本/总体计数；原始完整 state 必须存在。哈希链说明记录内部一致，不能单独证明宿主或来源身份可信。
