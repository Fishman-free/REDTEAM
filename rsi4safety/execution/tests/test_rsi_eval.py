"""RSI generalization experiment tests (research plan §04).

修好这次错误 ≠ 以后更会修：本模块验证确定性实验框架给出的可复现结论——
经验驱动的窄补丁随训练族数量单调提升 held-out 新问题修复率，族内变体
全部泛化，且修复成本（候选评估数）低于通用不变量路线。
"""
import json
import tempfile
import unittest
from pathlib import Path

from rsi4safety.rsi_eval import (
    GeneralizationConfig,
    run_generalization,
)
from rsi4safety.rsi_eval.experiment import write_report
from rsi4safety.rsi_eval.families import FAMILY_LIBRARY, TRAINABLE_FAMILIES


class GeneralizationExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        report = run_generalization(GeneralizationConfig(
            state_dir=Path(cls._temp.name), curve_sizes=(0, 2, 4)))
        cls.report = report

    @classmethod
    def tearDownClass(cls):
        cls._temp.cleanup()

    def test_every_trainable_family_is_single_dimension_trainable(self):
        # 每个训练攻击必须真实落地（actual_unauthorized），否则实验是空转。
        from rsi4safety.core import run_scenario
        from rsi4safety.domain import DefensePolicy, GatewayMode
        from rsi4safety.scenarios import default_challenge
        for family_id in TRAINABLE_FAMILIES:
            family = FAMILY_LIBRARY[family_id]
            policy = DefensePolicy(policy_id=f"probe-{family_id}")
            task_seed = f"probe-{family_id}"
            from rsi4safety.rsi_eval.families import _task
            task = _task(task_seed)
            attack = family.train_attack(task.task_id)
            record = run_scenario(task, policy, attack=attack,
                                  challenge=default_challenge(policy.policy_id),
                                  gateway_mode=GatewayMode.RESEARCH)
            self.assertTrue(record.actual_unauthorized, family_id)
            self.assertEqual(len({v.code for v in record.violations}), 1,
                             f"{family_id} must teach exactly one dimension")

    def test_memory_arm_learning_curve_is_monotonically_improving(self):
        curve = self.report.learning_curve("memory_narrow", "new_family_fix_rate")
        self.assertEqual(curve, sorted(v for v in curve if v is not None) + 
                        [v for v in curve if v is None])
        self.assertEqual(curve[-1], 100.0)

    def test_intra_family_variants_generalize_after_training(self):
        for point in self.report.points:
            if point["arm"] == "memory_narrow" and point["k"] >= 2:
                self.assertEqual(point["metrics"]["seen_family_variant_fix_rate"], 100.0,
                                 point["metrics"]["seen_families"])

    def test_experience_arm_is_cheaper_than_generic_arm(self):
        def total_evals(arm):
            return sum(p["metrics"]["candidate_evaluations"] for p in self.report.points
                       if p["arm"] == arm)
        self.assertLess(total_evals("memory_narrow"), total_evals("with_contract"))

    def test_no_memory_arm_reaches_full_coverage_but_overconstrains(self):
        by_k = {p["k"]: p["metrics"] for p in self.report.points if p["arm"] == "no_memory"}
        self.assertEqual(by_k[4]["new_family_fix_rate"], 100.0)
        memory_by_k = {p["k"]: p["metrics"] for p in self.report.points
                       if p["arm"] == "memory_narrow"}
        self.assertLess(memory_by_k[4]["restrictiveness"], by_k[4]["restrictiveness"])

    def test_clean_utility_never_regresses_in_any_arm(self):
        for point in self.report.points:
            self.assertEqual(point["metrics"]["clean_utility_rate"], 100.0,
                             (point["arm"], point["k"]))

    def test_report_declares_deterministic_limitation(self):
        self.assertTrue(self.report.config["deterministic"])
        self.assertIn("不等于真实大模型抗攻击率", self.report.config["limitation"])

    def test_report_writes_learning_curves(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "curve.json"
            write_report(self.report, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("learning_curves", payload)
            self.assertIn("memory_narrow", payload["learning_curves"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
