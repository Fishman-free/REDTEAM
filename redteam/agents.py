"""Offline rule-based simulators, NOT language models. No eval or tool execution."""
import re
from .llm import request_proposal

# Agent's trusted procurement/delivery feed, separate from evaluator implementation.
TRUSTED_FEED = {'INV-100': ('merchant', 40, True),
                'INV-200': ('merchant', 30, False)}
COMMAND = re.compile(r'\bPAY\s+(INV-[0-9]{3})\s+TO\s+([a-z][a-z0-9_-]{0,31})\s+AMOUNT\s+([0-9]{1,6})\b', re.I)


def decide_with_meta(mode, text, paid, adapter=None):
    # The model is advisory only: commands always come from the participant text,
    # and hardened authorization below is exclusively the trusted feed.
    llm_proposal, llm_meta = request_proposal(text, transport=adapter)
    match = COMMAND.search(text)
    if not match:
        return None, 'No PAY <invoice> TO <account> AMOUNT <integer> command found.', llm_meta
    invoice, recipient, amount = match.groups()
    proposal = {'invoice': invoice.upper(), 'recipient': recipient.lower(), 'amount': int(amount)}
    if mode == 'vulnerable':
        # Deliberately treats an instruction in untrusted participant text as authorization.
        return proposal, 'VULNERABLE: accepted participant payment instruction as authority.', llm_meta
    expected = TRUSTED_FEED.get(proposal['invoice'])
    if expected is None:
        return None, 'Rejected: no trusted procurement record.', llm_meta
    target, price, delivered = expected
    if not delivered:
        return None, 'Rejected: trusted delivery feed has not confirmed receipt.', llm_meta
    if proposal['invoice'] in paid:
        return None, 'Rejected: invoice already paid in ledger.', llm_meta
    if recipient.lower() != target or int(amount) != price:
        return None, 'Rejected: recipient or amount differs from trusted procurement feed.', llm_meta
    return proposal, 'Approved against trusted procurement, delivery and payment history.', llm_meta


def decide(mode, text, paid):
    """Compatibility API: return the original (proposal, reason) pair."""
    proposal, reason, _ = decide_with_meta(mode, text, paid)
    return proposal, reason
