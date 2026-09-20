from __future__ import annotations

import json
from pathlib import Path

from .config import ArenaConfig


def write_report(config: ArenaConfig, report: dict) -> None:
    config.state_dir.mkdir(parents=True, exist_ok=True)
    (config.state_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (config.state_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")


def _session_line(session: dict | None) -> str:
    if not session:
        return "—"
    state = "ok" if session.get("ok") else f"error({session.get('error_subtype')})"
    refusal = " ⚠️疑似安全对齐拒绝" if session.get("refusal_suspected") else ""
    return f"{state}, turns={session.get('num_turns')}{refusal}"


def _score_row(label: str, scores: dict) -> str:
    if not scores:
        return f"| {label} | — | — | — | — | — |"
    return (f"| {label} | {scores.get('benign_completed')}/{scores.get('benign_total')} | "
            f"{scores.get('attack_completed')}/{scores.get('attack_total')} | "
            f"{scores.get('actual_violations')} | {scores.get('attempted_violations')} | "
            f"{'PASS' if scores.get('passed') else 'FAIL'} |")


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    config = report.get("config", {})
    lines.append(f"# Arena 审计报告：{report.get('campaign_id')}")
    lines.append("")
    lines.append(f"- 状态：**{report.get('status')}**"
                 + (f"（{report.get('stop_reason')}）" if report.get("stop_reason") else ""))
    started = report.get("started_at")
    finished = report.get("finished_at")
    if started and finished:
        lines.append(f"- 时长：{round(finished - started, 1)} 秒")
    lines.append(f"- 配置：rounds={config.get('rounds')}, repetitions={config.get('repetitions')}, "
                 f"dry_run={config.get('dry_run')}, models={config.get('models')}")
    lines.append(f"- 审计链头：`{report.get('chain_head', '')[:16]}…`"
                 f"（完整链见 audit/chain.jsonl，可用 `arena verify` 校验）")
    if report.get("initial_tree_sha256"):
        lines.append(f"- SUT 初始树哈希：`{report['initial_tree_sha256'][:16]}…` → "
                     f"最终 `{str(report.get('final_tree_sha256', ''))[:16]}…`")
    lines.append("")
    for round_report in report.get("rounds", []):
        lines.append(f"## 第 {round_report.get('round')} 轮")
        lines.append("")
        lines.append("| 会话 | 状态 |")
        lines.append("|---|---|")
        for role in ("attacker", "judge", "defender"):
            lines.append(f"| {role} | {_session_line(round_report.get(f'{role}_session'))} |")
        lines.append("")
        for role in ("attacker", "judge", "defender"):
            session = round_report.get(f"{role}_session") or {}
            if session.get("refusal_suspected"):
                lines.append(f"> **{role} 疑似因安全对齐拒绝执行**："
                             f"“{session.get('refusal_evidence', '')[:200]}”")
                lines.append("")
        verdicts = round_report.get("verdicts", [])
        if verdicts:
            lines.append("| 证据 | 有效发现 | 严重度 |")
            lines.append("|---|---|---|")
            for verdict in verdicts:
                lines.append(f"| `{verdict['evidence_id']}` | "
                             f"{'是' if verdict['valid_finding'] else '否'} | {verdict['severity']} |")
            lines.append("")
        promotion = round_report.get("promotion", {})
        if promotion:
            lines.append(f"**晋级**：{'✅ 晋级' if promotion.get('promoted') else '❌ 未晋级'}"
                         + (f" — {', '.join(promotion.get('reasons', []))}" if promotion.get("reasons") else ""))
            if promotion.get("candidate_scores"):
                lines.append("")
                lines.append("| 版本 | 正常完成 | 攻击下完成 | 实际越权 | 越权请求 | 门禁 |")
                lines.append("|---|---|---|---|---|---|")
                lines.append(_score_row("父版本", promotion.get("parent_scores")))
                lines.append(_score_row("候选", promotion.get("candidate_scores")))
            lines.append("")
    final = report.get("final_evaluation")
    if final:
        lines.append("## 冻结最终对照")
        lines.append("")
        lines.append("| 版本 | 正常完成 | 攻击下完成 | 实际越权 | 越权请求 | 门禁 |")
        lines.append("|---|---|---|---|---|---|")
        for label in ("initial", "evolved", "fixed_guard"):
            lines.append(_score_row(label, final.get(label, {}).get("scores")))
        if final.get("reverted_to_initial"):
            lines.append("")
            lines.append("最终门禁未通过，活动版本已回滚到初始版本。")
        lines.append("")
    benchmark_report = report.get("benchmark")
    if benchmark_report:
        lines.append(f"## Benchmark（{benchmark_report.get('benchmark_version')}，全程序化）")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 初始版本可利用性（攻击家族成功率） | {benchmark_report.get('exploitability_initial_pct')}% |")
        lines.append(f"| 演化版本残余风险 | {benchmark_report.get('residual_evolved_pct')}% |")
        lines.append(f"| 修复有效性（相对下降） | {benchmark_report.get('fix_effectiveness_pct')}% |")
        lines.append(f"| 残余攻击家族 | {', '.join(benchmark_report.get('residual_families') or []) or '无'} |")
        lines.append(f"| 达到固定防御基线水平 | {benchmark_report.get('guard_parity_reached')} |")
        efficiency = benchmark_report.get("research_efficiency", {})
        lines.append(f"| 有效发现 / 证据总数 | {efficiency.get('valid_findings')}/{efficiency.get('evidence_total')} |")
        lines.append(f"| 每百轮次有效发现数 | {efficiency.get('findings_per_100_turns')} |")
        lines.append(f"| 晋级次数 | {efficiency.get('promotions')} |")
        lines.append("")
    usage = report.get("usage", {})
    if usage:
        lines.append("## 模型用量（按角色累计）")
        lines.append("")
        lines.append("| 角色 | 会话数 | 轮数 | 输入 token | 输出 token |")
        lines.append("|---|---|---|---|---|")
        for role, bucket in usage.items():
            lines.append(f"| {role} | {bucket.get('sessions')} | {bucket.get('turns')} | "
                         f"{bucket.get('input_tokens')} | {bucket.get('output_tokens')} |")
        lines.append("")
    limitations = report.get("limitations", [])
    if limitations:
        lines.append("## 边界声明")
        lines.append("")
        for item in limitations:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("## 原始证据索引")
    lines.append("")
    lines.append("- 逐调用审计链：`audit/chain.jsonl`")
    lines.append("- 证据束：`evidence/<evidence_id>/manifest.json`")
    lines.append("- 补丁：`patches/<submission_id>/`")
    lines.append("- 每轮工作区快照：`snapshots/round-<n>/`")
    lines.append("- 会话转录：`sessions/<role>/round-<n>.stream.jsonl`")
    lines.append("")
    return "\n".join(lines)
