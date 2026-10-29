"""The single defender transport seam used by the sealed runtime driver."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import InboundMessage, OutboundReply


class DefenderUnavailable(RuntimeError):
    """Raised when a defender transport cannot deliver or answer in time."""


@runtime_checkable
class DefenderPort(Protocol):
    """All four transports (hosted-mcp, a2a, webhook, mcp-pull) implement this."""

    kind: str

    def start(self) -> None: ...

    def send(self, message: InboundMessage) -> OutboundReply: ...

    def stop(self) -> None: ...
