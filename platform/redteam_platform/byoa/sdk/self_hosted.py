"""Self-hosted reply sealing and v2 signing helpers.

The platform relay forwards the attack plaintext to the defender endpoint and
never sees the reply.  The SDK seals the reply to the attacker's X25519 key,
hashes the envelope, and signs the v2 payload (including configHash) with the
defender's reply key.  The platform verifies the signature against the
on-chain ``replySigner`` and only then marks the turn delivered.
"""

from __future__ import annotations

from typing import Any, Mapping

from eth_account import Account
from eth_account.messages import encode_defunct

from ..envelope import envelope_hash, reply_context, seal
from ..sealed import reply_signature_payload_v2


class SelfHostedSignerError(ValueError):
    """Raised when the reply context or reply key is invalid."""


def sign_reply(
    *,
    text: str,
    contest_id: str,
    attacker: str,
    msg_hash: str,
    seq: int,
    attacker_pubkey: str,
    config_hash: str,
    reply_signer_key: str,
) -> dict[str, Any]:
    """Seal and sign one self-hosted reply; returns the metadata to return."""

    if not isinstance(text, str):
        raise SelfHostedSignerError("text must be a string")
    try:
        envelope = seal(
            attacker_pubkey,
            text.encode("utf-8"),
            context=reply_context(contest_id, attacker, msg_hash, seq),
        )
    except Exception as exc:
        raise SelfHostedSignerError("cannot seal the reply") from exc
    reply_hash = envelope_hash(envelope)
    payload = reply_signature_payload_v2(
        contest_id=contest_id,
        attacker=attacker,
        msg_hash=msg_hash,
        reply_hash=reply_hash,
        seq=seq,
        config_hash=config_hash,
    )
    try:
        signature = Account.sign_message(
            encode_defunct(text=payload), private_key=reply_signer_key
        ).signature.to_0x_hex()
    except Exception as exc:
        raise SelfHostedSignerError("cannot sign the reply") from exc
    return {
        "reply_envelope": envelope,
        "reply_hash": reply_hash,
        "reply_signature": signature,
        "config_hash": config_hash,
    }


class SignedReplyAgent:
    """Wrap an agent handler and sign replies when the driver supplies a context."""

    def __init__(self, handler, *, reply_signer_key: str, config_hash: str) -> None:
        if not callable(handler):
            raise SelfHostedSignerError("handler must be callable")
        if not isinstance(reply_signer_key, str) or not reply_signer_key:
            raise SelfHostedSignerError("reply_signer_key is required")
        if not isinstance(config_hash, str) or not config_hash.startswith("0x"):
            raise SelfHostedSignerError("config_hash must be hex")
        self.handler = handler
        self._reply_signer_key = reply_signer_key
        self.config_hash = config_hash

    def __call__(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = self.handler(payload)
        if not isinstance(result, Mapping):
            raise SelfHostedSignerError("handler returned no object")
        output = dict(result)
        metadata = payload.get("metadata") if isinstance(payload, Mapping) else {}
        context = (
            metadata.get("reply_context")
            if isinstance(metadata, Mapping)
            else None
        )
        if not isinstance(context, Mapping):
            return output
        text = output.get("reply")
        if not isinstance(text, str):
            raise SelfHostedSignerError("reply text is missing")
        signed = sign_reply(
            text=text,
            contest_id=str(payload.get("contest_id") or ""),
            attacker=str(context.get("attacker") or ""),
            msg_hash=str(context.get("msg_hash") or ""),
            seq=int(payload.get("seq") or 0),
            attacker_pubkey=str(context.get("attacker_pubkey") or ""),
            config_hash=str(context.get("config_hash") or self.config_hash),
            reply_signer_key=self._reply_signer_key,
        )
        merged = dict(output.get("metadata") or {})
        merged.update(signed)
        output["metadata"] = merged
        return output
