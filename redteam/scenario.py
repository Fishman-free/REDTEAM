"""Versioned local fixture inputs; agent and evaluator records stay separate."""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent / 'scenarios' / 'payment-delivery-v1'


def _load(name):
    return json.loads((_ROOT / name).read_text(encoding='utf-8'))


CONFIG = _load('config.json')
SCENARIO_VERSION = CONFIG['scenario_version']
EVIDENCE_VERSION = CONFIG['evidence_version']
MAX_TRANSFER = CONFIG['max_transfer_tokens']
INITIAL_TOKENS = CONFIG['initial_tokens']
RECIPIENT_ALLOWLIST = frozenset(CONFIG['recipient_allowlist'])


def load_trusted_feed():
    return _load('trusted-feed.json')


def load_evaluator_truth():
    return _load('evaluator-truth.json')
