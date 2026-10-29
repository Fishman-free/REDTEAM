"""BYOA: sealed defender runtime, wallet policy and transport adapters.

The package deliberately keeps three boundaries separate:

* :mod:`redteam_platform.byoa.policy` — L3 wallet rules, enforced by the
  wallet sidecar (never by the agent's prompt);
* :mod:`redteam_platform.byoa.adapters` — the four defender transports behind
  one :class:`~redteam_platform.byoa.ports.DefenderPort`;
* :mod:`redteam_platform.byoa.sealed` — bundle commitments, measurements and
  attestation tiers.  The local simulator is always labelled ``simulated``.
"""

from .models import Channel, InboundMessage, OutboundReply, TaskSpec
from .policy import (
    PolicyDecision,
    PolicyOutcome,
    WalletPolicy,
    validate_byoa_floor,
)
from .ports import DefenderPort, DefenderUnavailable
from .wallet import SessionToken, WalletSession, WalletTransfer

__all__ = [
    "Channel",
    "DefenderPort",
    "DefenderUnavailable",
    "InboundMessage",
    "OutboundReply",
    "PolicyDecision",
    "PolicyOutcome",
    "SessionToken",
    "TaskSpec",
    "WalletPolicy",
    "WalletSession",
    "WalletTransfer",
    "validate_byoa_floor",
]
