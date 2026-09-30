import json
import unittest

from rsi4safety.core import run_scenario
from rsi4safety.domain import DefensePolicy
from rsi4safety.learning import Experience, ReflectiveCandidateProposer
from rsi4safety.model_agents import ModelAttackGenerator
from rsi4safety.providers import OfflineChatModel
from rsi4safety.scenarios import default_challenge, shopping_task, verification_fee_attack


class ModelAdapterTests(unittest.TestCase):
    def test_reflective_proposer_reads_memory_and_rejects_out_of_scope_patch(self) -> None:
        class CapturingModel:
            prompt = None

            def complete(self, system: str, user: str) -> str:
                self.prompt = json.loads(user)
                return json.dumps({"candidates": [
                    {"name": "tamper-score", "patch": {"verifier": True}},
                    {"name": "wrong-type", "patch": {"enforce_recipient": "true"}},
                    {"name": "repair", "patch": {"enforce_recipient": True}},
                ]})

        policy, attack, task = DefensePolicy("v0"), verification_fee_attack(), shopping_task()
        record = run_scenario(task, policy, attack=attack, challenge=default_challenge("v0"))
        memory = Experience("e1", "recipient", record.evidence_hash, "older", "Check recipient", ("wrong_recipient",))
        model = CapturingModel()
        candidates = ReflectiveCandidateProposer(model).propose(policy, record, (memory,))
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].enforce_recipient)
        self.assertEqual(model.prompt["verified_memory"][0]["lesson"], "Check recipient")

    def test_attack_generator_is_pluggable_without_network_access(self) -> None:
        model = OfflineChatModel('{"surface":"merchant_message","family":"fee","content":"test attack"}')
        attack = ModelAttackGenerator(model).generate(shopping_task(), DefensePolicy("v0"), default_challenge("v0"))
        self.assertEqual(attack.content, "test attack")
        with self.assertRaises(ValueError):
            ModelAttackGenerator(model, max_content_chars=1).generate(
                shopping_task(), DefensePolicy("v0"), default_challenge("v0")
            )


if __name__ == "__main__":
    unittest.main()
