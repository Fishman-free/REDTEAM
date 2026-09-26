"""In-memory task state for PayChain.

Each benchmark repetition runs a fresh SUT process, so an in-memory store is
sufficient; the authoritative evidence is the host-side payment ledger, never
this state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Authorization:
    """Trusted authorization facts injected by the platform (same shape as PayAssist)."""

    order_id: str
    recipient: str
    exact_amount_minor: int
    max_total_minor: int
    currency: str = "CNY"
    allowed_purposes: tuple[str, ...] = ("purchase",)
    max_executions: int = 1
    require_confirmation_above_minor: int | None = None
    allows_payment: bool = True
    max_per_payment_minor: int | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Authorization":
        purposes = data.get("allowed_purposes") or ["purchase"]
        threshold = data.get("require_confirmation_above_minor")
        per_payment = data.get("max_per_payment_minor")
        return cls(
            order_id=str(data["order_id"]),
            recipient=str(data["recipient"]),
            exact_amount_minor=int(data["exact_amount_minor"]),
            max_total_minor=int(data["max_total_minor"]),
            currency=str(data.get("currency") or "CNY"),
            allowed_purposes=tuple(str(p) for p in purposes),
            max_executions=int(data.get("max_executions") or 1),
            require_confirmation_above_minor=int(threshold) if threshold is not None else None,
            allows_payment=bool(data.get("allows_payment", True)),
            max_per_payment_minor=int(per_payment) if per_payment is not None else None,
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "recipient": self.recipient,
            "exact_amount_minor": self.exact_amount_minor,
            "max_total_minor": self.max_total_minor,
            "currency": self.currency,
            "allowed_purposes": list(self.allowed_purposes),
            "max_executions": self.max_executions,
            "require_confirmation_above_minor": self.require_confirmation_above_minor,
            "allows_payment": self.allows_payment,
            "max_per_payment_minor": self.max_per_payment_minor,
        }


@dataclass
class TaskRecord:
    task_id: str
    user_request: str
    authorization: Authorization
    status: str = "pending"
    history: list[dict[str, Any]] = field(default_factory=list)
