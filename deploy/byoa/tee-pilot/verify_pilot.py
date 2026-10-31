"""External verifier for the minimal RTM TEE pilot.

Run this on a trusted machine, outside the CVM:

    python verify_pilot.py --url https://<cvm-public-url>

Checks, in order:
1. the CVM signs the nonce/signer/wallet binding;
2. report_data contains the nonce plus the binding digest;
3. Phala's verifier accepts the TDX quote against Intel's chain;
4. the hardware-attested report_data matches the binding;
5. the attested compose hash matches /info.

Any missing field fails closed. This proves the pilot app runs on genuine TDX
with the expected compose; it does not implement the arena runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
import urllib.parse
import urllib.request
from typing import Any, Callable

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import is_address, to_checksum_address

from binding import binding_hash, signature_text

PHALA_VERIFY_URL = "https://cloud-api.phala.com/api/v1/attestations/verify"
HTTP_TIMEOUT_S = 45


class VerificationError(RuntimeError):
    pass


def strip_hex(value: str) -> str:
    if not isinstance(value, str):
        raise VerificationError("expected a hex string")
    return value[2:] if value.startswith(("0x", "0X")) else value


def http_json(url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {"Accept": "application/json", "User-Agent": "rtm-tee-pilot/0.1"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        body = response.read()
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{url} returned non-JSON") from exc


def check_binding(attestation: dict[str, Any], nonce: str) -> dict[str, str]:
    """Verify the signature and the report_data half that the app controls."""
    nonce = strip_hex(nonce).lower()
    if len(nonce) != 64:
        raise VerificationError("nonce must be 32 bytes")

    binding = attestation.get("binding")
    if not isinstance(binding, dict):
        raise VerificationError("attestation has no binding object")
    signer = binding.get("signer")
    wallet = binding.get("wallet")
    if not isinstance(signer, str) or not is_address(signer):
        raise VerificationError("binding signer is not an address")
    if not isinstance(wallet, str) or not is_address(wallet):
        raise VerificationError("binding wallet is not an address")
    signer = to_checksum_address(signer)
    wallet = to_checksum_address(wallet)
    if binding.get("domain") != "RTM TEE pilot v1":
        raise VerificationError("binding domain mismatch")
    if str(binding.get("nonce", "")).lower() != nonce:
        raise VerificationError("binding nonce mismatch")

    expected_digest = binding_hash(nonce, signer, wallet)
    claimed_digest = strip_hex(str(attestation.get("bindingHash", ""))).lower()
    if claimed_digest != expected_digest:
        raise VerificationError("binding hash mismatch")

    report_data = strip_hex(str(attestation.get("report_data", ""))).lower()
    expected_report_data = nonce + expected_digest
    if report_data != expected_report_data:
        raise VerificationError("report_data does not contain the nonce and binding")

    signature = attestation.get("signature")
    if not isinstance(signature, str) or not signature:
        raise VerificationError("attestation has no signature")
    try:
        recovered = Account.recover_message(
            encode_defunct(
                text=signature_text(nonce, signer, wallet, expected_digest)
            ),
            signature=signature,
        )
    except Exception as exc:
        raise VerificationError("binding signature is malformed") from exc
    if to_checksum_address(recovered) != signer:
        raise VerificationError("binding signature signer mismatch")

    return {
        "nonce": nonce,
        "signer": signer,
        "wallet": wallet,
        "bindingHash": "0x" + expected_digest,
        "reportData": report_data,
    }


def check_hardware(
    quote_hex: str,
    report_data: str,
    *,
    verify_url: str = PHALA_VERIFY_URL,
    post: Callable[[str, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Verify the quote with Phala's API and compare the hardware report_data."""
    post = post or http_json
    quote_hex = strip_hex(quote_hex)
    if not quote_hex:
        raise VerificationError("empty quote")
    response = post(verify_url, {"hex": quote_hex})
    if isinstance(response, dict) and isinstance(response.get("data"), dict):
        response = response["data"]
    quote = response.get("quote") if isinstance(response, dict) else None
    if not isinstance(quote, dict) or quote.get("verified") is not True:
        raise VerificationError("Phala rejected the TDX quote")
    body = quote.get("body")
    if not isinstance(body, dict):
        raise VerificationError("verify response omitted the quote body")
    hardware_report = strip_hex(str(body.get("report_data", ""))).lower()
    if not hardware_report:
        raise VerificationError("verify response omitted report_data")
    if hardware_report != strip_hex(report_data).lower():
        raise VerificationError("hardware report_data differs from the app binding")
    return {
        "verified": True,
        "teeTcbSvn": body.get("tee_tcb_svn"),
        "reportData": hardware_report,
    }


def check_compose(
    info: dict[str, Any],
    event_log_json: str,
    *,
    expected_hash: str | None = None,
) -> dict[str, str]:
    """Bind /info to the compose-hash event signed inside the quote."""
    tcb = info.get("tcb_info")
    if not isinstance(tcb, dict) or not isinstance(tcb.get("app_compose"), str):
        raise VerificationError("info has no tcb_info.app_compose")
    calculated = hashlib.sha256(tcb["app_compose"].encode("utf-8")).hexdigest()

    try:
        events = json.loads(event_log_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise VerificationError("event_log is not valid JSON") from exc
    event = next(
        (
            item
            for item in events
            if isinstance(item, dict) and item.get("event") == "compose-hash"
        ),
        None,
    )
    if event is None:
        raise VerificationError("event_log has no compose-hash event")
    attested = strip_hex(str(event.get("event_payload", ""))).lower()
    if attested != calculated:
        raise VerificationError("compose hash mismatch")

    if expected_hash is not None and strip_hex(expected_hash).lower() != calculated:
        raise VerificationError("compose hash does not match --expected-compose-hash")
    return {"composeHash": calculated}


def verify(
    url: str,
    *,
    expected_compose_hash: str | None = None,
    verify_url: str = PHALA_VERIFY_URL,
) -> dict[str, Any]:
    base = url.rstrip("/")
    nonce = secrets.token_hex(32)
    attestation = http_json(
        f"{base}/attestation?{urllib.parse.urlencode({'nonce': nonce})}"
    )
    if not isinstance(attestation, dict):
        raise VerificationError("attestation response is not an object")
    binding = check_binding(attestation, nonce)
    if not isinstance(attestation.get("quote"), str):
        raise VerificationError("attestation has no quote")
    hardware = check_hardware(
        attestation["quote"], binding["reportData"], verify_url=verify_url
    )
    info = http_json(f"{base}/info")
    if not isinstance(info, dict):
        raise VerificationError("info response is not an object")
    compose = check_compose(
        info,
        str(attestation.get("event_log", "")),
        expected_hash=expected_compose_hash,
    )
    return {
        "ok": True,
        "binding": binding,
        "hardware": hardware,
        "compose": compose,
        "appId": info.get("app_id"),
        "instanceId": info.get("instance_id"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="public URL of the pilot CVM")
    parser.add_argument("--expected-compose-hash", default=None)
    parser.add_argument(
        "--verify-url",
        default=PHALA_VERIFY_URL,
        help="quote verifier endpoint (default: Phala Cloud)",
    )
    args = parser.parse_args(argv)
    try:
        result = verify(
            args.url,
            expected_compose_hash=args.expected_compose_hash,
            verify_url=args.verify_url,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
