"""SQLite-compatible facade over the shared payment runtime.

Only the trusted-feed fixture is loaded here; evaluator truth is independently
loaded by policy.py. Participant text never populates either source.
"""
from .agent_runtime import (AGENT_VERSION, TrustedState, default_llm,
                            decide as runtime_decide)
from .llm import PROMPT_VERSION
from .scenario import (EVIDENCE_VERSION, MAX_TRANSFER, RECIPIENT_ALLOWLIST,
                       SCENARIO_VERSION, load_trusted_feed)

# Preserve the historical tuple-valued constant without sharing evaluator dicts.
TRUSTED_FEED = {invoice: (record['recipient'], record['amount'], record['delivered'])
                for invoice, record in load_trusted_feed().items()}


def build_trusted(paid):
    return TrustedState(
        invoices={invoice: {'recipient': target, 'amount': amount, 'delivered': delivered}
                  for invoice, (target, amount, delivered) in TRUSTED_FEED.items()},
        paid=set(paid or ()), recipient_allowlist=set(RECIPIENT_ALLOWLIST),
        max_transfer=MAX_TRANSFER)


class _CallableAdapter:
    name = 'openai-compatible'

    def __init__(self, adapter):
        self.adapter = adapter

    def complete(self, system_prompt, trusted_block, participant_text):
        return self.adapter(system_prompt, trusted_block, participant_text)


def resolve_llm(adapter=None, backend=None):
    """Retain three-argument fake callables, and accept complete()-style adapters."""
    if adapter is not None:
        # A callable fake (including unittest.mock.Mock) is the legacy adapter
        # shape; object adapters expose complete() but are not themselves callable.
        return _CallableAdapter(adapter) if callable(adapter) else adapter
    return default_llm(backend)


def decide_proposal(mode, text, paid, adapter=None, *, backend=None):
    """Full decision; selects the exact same backend as the CLI and HTTP paths."""
    return runtime_decide(mode, text, build_trusted(paid),
                          llm=resolve_llm(adapter, backend))


def decide_with_meta(mode, text, paid, adapter=None, *, backend=None):
    """Return the legacy (proposal, reason, meta) tuple, now retaining evidence."""
    decision = decide_proposal(mode, text, paid, adapter, backend=backend)
    meta = dict(decision['evidence']['llm'])
    meta.update(prompt_version=PROMPT_VERSION, agent_version=AGENT_VERSION,
                scenario_version=SCENARIO_VERSION, evidence_version=EVIDENCE_VERSION,
                evidence=decision['evidence'])
    return decision['proposal'], decision['reason'], meta


def decide(mode, text, paid):
    """Compatibility API: return the original (proposal, reason) pair."""
    proposal, reason, _ = decide_with_meta(mode, text, paid)
    return proposal, reason
