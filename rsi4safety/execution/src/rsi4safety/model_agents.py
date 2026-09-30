from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .core import PaymentAgent, PaymentEnvironment
from .domain import AttackPayload, ChallengeSpec, DefensePolicy, ExposureSurface, PaymentRequest, RunResult, TaskSpec, stable_hash
from .prompts import ANGLE_GUIDANCE, ATTACK_ANGLES, ATTACK_SYSTEM, PAYMENT_OUTPUT_RULES, PROMPT_VERSION
from .providers import ChatModel, ModelCallError, complete_json


class ModelPaymentAgent(PaymentAgent):
    """One model payment plan followed by deterministic tool execution."""

    def __init__(self, policy: DefensePolicy, model: ChatModel, max_payments: int = 4) -> None:
        super().__init__(policy)
        self.model = model
        self.max_payments = max_payments

    def run(self, environment: PaymentEnvironment) -> RunResult:
        task = environment.task
        exposures = {}
        for surface in ExposureSurface:
            content = environment.read_surface(surface)
            exposures[surface.value] = (
                content if self.policy.accept_untrusted_payment_instructions
                else f"[withheld untrusted content sha256={stable_hash(content)}]"
            )
        payload = complete_json(
            self.model,
            self.policy.instructions + "\n" + PAYMENT_OUTPUT_RULES,
            {
                "task_id": task.task_id, "policy_id": self.policy.policy_id,
                "task": task.user_request, "trusted_authorization": asdict(task.authorization),
                "untrusted_exposures": exposures, "max_payments": self.max_payments,
                "schema": {"payments": [{"request_id": "unique-id", "order_id": "order-id",
                    "recipient": "recipient", "amount_minor": 1, "purpose": "purchase", "currency": "CNY"}]},
            },
        )
        raw_payments = payload.get("payments")
        if not isinstance(raw_payments, list) or len(raw_payments) > self.max_payments:
            raise ModelCallError("model must return a bounded payments array")
        # Validate the entire plan before performing any payment.
        requests = []
        for raw in raw_payments:
            if not isinstance(raw, dict) or type(raw.get("amount_minor")) is not int:
                raise ModelCallError("payment amount must be an integer in minor currency units")
            if any(not isinstance(raw.get(key), str) or not raw[key] for key in ("request_id", "order_id", "recipient", "purpose")):
                raise ModelCallError("model payment is missing required string fields")
            requests.append(PaymentRequest(
                request_id=raw["request_id"], order_id=raw["order_id"],
                recipient=raw["recipient"], amount_minor=raw["amount_minor"],
                purpose=raw["purpose"], currency=str(raw.get("currency", "CNY")),
                source="model", user_confirmed=False,
            ))
        environment.record_model_decision(stable_hash(payload), len(requests), getattr(self.model, "last_metadata", {}).get("call_id"))
        for payment in requests:
            allowed, reason = self._allowed_by_policy(
                task, payment, environment.spent_minor, environment.executed_payment_count,
            )
            if allowed:
                environment.pay(payment)
            else:
                environment.reject_by_agent(payment, reason)
        return RunResult(task.task_id, self.policy.policy_id, environment.events, "model payment workflow completed")


class ModelAttackGenerator:
    """Bounded adaptive attack search with durable feedback supplied by the runner."""

    def __init__(self, model: ChatModel, max_content_chars: int = 4_000) -> None:
        self.model = model
        self.max_content_chars = max_content_chars
        self.history: list[dict[str, Any]] = []

    def observe(self, attack: AttackPayload, feedback: dict) -> None:
        self.history.append({"attack": asdict(attack), "feedback": feedback})
        self.history = self.history[-12:]

    def generate(
        self, task: TaskSpec, policy: DefensePolicy, challenge: ChallengeSpec,
        *, angle: str | None = None, nonce: str = "",
    ) -> AttackPayload:
        angle = angle or ATTACK_ANGLES[len(self.history) % len(ATTACK_ANGLES)]
        payload = complete_json(
            self.model, ATTACK_SYSTEM,
            {
                "prompt_version": PROMPT_VERSION, "attempt_nonce": nonce,
                "public_task": task.user_request, "public_authorization": asdict(task.authorization),
                "target_policy": asdict(policy) if challenge.source_visibility == "whitebox" else None,
                "angle": angle, "guidance": ANGLE_GUIDANCE.get(angle, angle),
                "allowed_surfaces": [surface.value for surface in challenge.allowed_surfaces],
                "previous_attempts": self.history[-6:],
                "max_content_chars": self.max_content_chars,
                "schema": {"surface": "merchant_message", "family": angle, "content": "attack text"},
            },
        )
        try:
            surface = ExposureSurface(payload["surface"])
        except (KeyError, ValueError, TypeError):
            raise ModelCallError("model selected an invalid attack surface") from None
        if surface not in challenge.allowed_surfaces:
            raise ValueError("model selected a surface outside the challenge scope")
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > self.max_content_chars:
            raise ValueError("model attack is empty or exceeds the content budget")
        attack_id = f"model-attack-{stable_hash((challenge.challenge_id, surface, content))[:12]}"
        return AttackPayload(attack_id, surface, content, str(payload.get("family", angle)))
