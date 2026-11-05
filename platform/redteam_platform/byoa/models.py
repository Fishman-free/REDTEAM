"""Transport-neutral BYOA message and task models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class Channel(str, Enum):
    """Who authored a message delivered to the defender agent."""

    OWNER = "owner"
    COUNTERPARTY = "counterparty"


class ContentKind(str, Enum):
    """Counterparty injection surfaces listed in the BYOA spec §5.3."""

    DIALOGUE = "dialogue"
    INVOICE = "invoice"
    PAYMENT_REQUIRED = "payment_required"
    TOOL_RESULT = "tool_result"


@dataclass(frozen=True)
class InboundMessage:
    """One message delivered through a :class:`DefenderPort`.

    ``seq`` is per contest and monotonic.  ``metadata`` carries structured
    payloads (invoice JSON, 402 body, tool result) without parsing free text.
    """

    contest_id: str
    seq: int
    channel: Channel
    kind: ContentKind
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.contest_id, str) or not self.contest_id:
            raise ValueError("contest_id must be a non-empty string")
        if isinstance(self.seq, bool) or not isinstance(self.seq, int) or self.seq < 0:
            raise ValueError("seq must be a non-negative integer")
        if not isinstance(self.content, str):
            raise ValueError("content must be a string")
        if len(self.content) > 16_000:
            raise ValueError("content must be at most 16000 characters")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")

    def as_envelope(self) -> dict[str, Any]:
        """The JSON object handed to defender harnesses."""

        return {
            "contest_id": self.contest_id,
            "seq": self.seq,
            "channel": self.channel.value,
            "kind": self.kind.value,
            "content": self.content,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class OutboundReply:
    """A defender reply plus optional tool trace supplied by the harness."""

    text: str
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("reply text must be a string")
        if len(self.text) > 50_000:
            raise ValueError("reply text must be at most 50000 characters")
        if not isinstance(self.tool_calls, tuple):
            raise ValueError("tool_calls must be a tuple")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")


@dataclass(frozen=True)
class TaskSpec:
    """A task issued to the defender and mirrored on TaskSink.

    ``kind`` is ``closed`` (owner channel) or ``open`` (counterparty invoice).
    ``payee``/``salt`` are private to the driver until ``armTask`` reveals the
    payee right before the transfer. ``payee_commit`` is the on-chain promise.
    """

    task_id: str
    amount: int
    deadline: int
    text: str
    task_hash: str
    kind: str = "closed"
    payee: str | None = None
    salt: str | None = None
    payee_commit: str | None = None
    vendor: str | None = None
    invoice: str | None = None
    directory_account: str | None = None
    account_changed: bool = False

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id is required")
        if isinstance(self.amount, bool) or not isinstance(self.amount, int):
            raise ValueError("amount must be an integer number of wei")
        if self.amount <= 0:
            raise ValueError("amount must be positive")
        if isinstance(self.deadline, bool) or not isinstance(self.deadline, int):
            raise ValueError("deadline must be an integer timestamp")
        if not self.task_hash.startswith("0x") or len(self.task_hash) != 66:
            raise ValueError("task_hash must be a bytes32 hex string")
        if self.kind not in {"closed", "open"}:
            raise ValueError("kind must be closed or open")
        for name in ("payee", "salt", "payee_commit"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.startswith("0x")
            ):
                raise ValueError(f"{name} must be a hex string")
