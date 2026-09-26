"""Limited-feedback protocol between the attack loop and the defense loop.

研究计划 §03/§04：攻击侧按实验规则获得**有限反馈**；确认攻击成功后，才把
攻击方式、手段、完整对话/输入及执行记录交给防御智能体。两侧的信息不对称
是实验协议的一部分，由本模块显式化并可测试：

- ``attacker_feedback``：bounty 式结果反馈——每份提交只有程序化判定摘要与
  有限错误摘录；**永不包含**账本行、HTTP 轨迹、授权内部细节或防御方信息。
- ``defender_package``：确认有效的发现（防守失败）才生成完整交付包：攻击
  动作、任务夹具、程序化判定、结构化诊断。

The orchestrator is the only caller; agents cannot widen their own view.
"""
from __future__ import annotations

from typing import Any

# Keys that must never appear in the attacker's view. The ledger and HTTP
# trace belong to the platform; handing them over would let the attacker
# read authorization internals and platform decisions directly.
ATTACKER_FORBIDDEN_KEYS = ("ledger_rows", "http_trace", "actual_ledger",
                           "defender", "patch", "promotion")


def attacker_feedback(findings: list[dict]) -> list[dict]:
    """Reduced per-submission outcome view for the attacker's next round."""
    feedback = []
    for finding in findings:
        submission = finding["manifest"]["attack_submission"]
        item: dict[str, Any] = {
            "submission_id": submission["submission_id"],
            "title": submission["title"],
            "hypothesis": submission["hypothesis"][:300],
            "programmatic_outcome": finding["summary"]["programmatic_verdict"],
            # Execution errors must reach the attacker: a util=False result
            # without them reads as "attack disrupted the task" when the
            # attack in fact never ran (e.g. action outside the allowlist).
            "repetition_errors": [
                str(rep.get("error"))[:240]
                for rep in finding["manifest"]["programmatic_verdict"].get("per_repetition", [])
                if rep.get("error")
            ][:4],
        }
        if "verdict" in finding:
            item["adjudication"] = {
                "valid_finding": finding["verdict"].valid_finding,
                "severity": finding["verdict"].severity,
                "category": ("adjudication_unavailable" if finding.get("adjudication_missing")
                             else finding["verdict"].category),
                "rationale": finding["verdict"].rationale[:400],
            }
        else:
            item["adjudication"] = {"valid_finding": False, "severity": "none",
                                    "category": "not_reproduced", "rationale": ""}
        feedback.append(item)
    return feedback


def assert_feedback_bounded(feedback: list[dict], payload_digests: set[str] | None = None) -> None:
    """Raise if any attacker-visible item leaks platform-owned evidence."""
    import json

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).lower()
                if any(forbidden in lowered for forbidden in ATTACKER_FORBIDDEN_KEYS):
                    raise ValueError(f"attacker feedback leaks platform evidence: {key}")
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(feedback)
    if payload_digests:
        blob = json.dumps(feedback, ensure_ascii=False, default=str)
        for digest in payload_digests:
            if digest and digest in blob:
                raise ValueError("attacker feedback contains a platform evidence digest")


def defender_package(finding: dict) -> dict:
    """Complete hand-off for one confirmed failure (确认防守失败后交付)."""
    submission = finding["manifest"]["attack_submission"]
    verdict = finding.get("verdict")
    return {
        "evidence_id": finding["evidence_id"],
        "severity": verdict.severity if verdict else "unknown",
        "category": verdict.category if verdict else "unknown",
        "rationale": verdict.rationale if verdict else "",
        "affects_authorized_utility": verdict.affects_authorized_utility if verdict else False,
        "programmatic_verdict": finding["summary"]["programmatic_verdict"],
        "attack_actions": submission["actions"],
        "attack_title": submission["title"],
        "attack_hypothesis": submission.get("hypothesis", ""),
        "task_fixture": finding["manifest"]["task_fixture"],
        "diagnosis": finding.get("diagnosis"),
    }
