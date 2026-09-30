"""RSI generalization experiments (research plan §04).

核心科学问题（研究计划 §04）：**修好这次错误，不等于以后更会修。** RSI 要
验证的是：积累经验后，系统解决**新问题**是否更有效、成本是否更低。

本包用确定性离线目标做两类测量：

- **Learning curve（主实验）**：在 k 个攻击族上训练防御（积累已验证经验），
  在 held-out 变体上评测——(a) 已见族的**新实体变体**（族内泛化）、
  (b) **未训练族的攻击**（跨族泛化）、(c) 正常任务（效用保持）。
  经验开/关对照，k 递增给出学习曲线。
- **五臂对照（演练）**：RSI_IMPROVEMENT_PLAN P3-2 的确定性预演，验证实验
  框架本身；真实模型战役按预注册协议另行执行（本轮不配置任何真实模型）。

一切度量来自宿主裁决（VerificationRecord），不来自模型自评。
"""
from .experiment import (
    GeneralizationConfig,
    GeneralizationReport,
    run_generalization,
)
from .families import FAMILY_LIBRARY, heldout_suite, training_family_ids

__all__ = [
    "GeneralizationConfig",
    "GeneralizationReport",
    "run_generalization",
    "FAMILY_LIBRARY",
    "heldout_suite",
    "training_family_ids",
]
