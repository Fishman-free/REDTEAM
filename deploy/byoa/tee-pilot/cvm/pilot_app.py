"""Minimal dstack CVM attestation surface for the RTM TEE pilot.

Runs inside a Phala dstack CVM. At boot it creates a signer key and a wallet
key, binds both plus a verifier nonce into a TDX quote's 64-byte report_data,
and signs the same binding. The host-side verifier checks the quote against
Intel's chain, the report_data binding, and the signature.

This is a pilot, not the arena runtime: it has no defender harness, wallet MCP,
configuration encryption, or on-chain registration.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from dstack_sdk import DstackClient
from eth_account import Account
from eth_account.messages import encode_defunct

from binding import binding_hash, binding_payload, signature_text

NONCE_HEX_LEN = 64


class PilotService:
    def __init__(self) -> None:
        self.client = DstackClient()
        self._signer = Account.create()
        self._wallet = Account.create()

    @property
    def signer(self) -> str:
        return self._signer.address

    @property
    def wallet(self) -> str:
        return self._wallet.address

    def attest(self, nonce: str) -> dict[str, object]:
        nonce = nonce.lower()
        if len(nonce) != NONCE_HEX_LEN:
            raise ValueError("nonce must be 32 bytes of hex")
        bytes.fromhex(nonce)  # validate hex

        digest = binding_hash(nonce, self.signer, self.wallet)
        # TDX report_data is 64 bytes: the verifier's nonce in the first half
        # and the binding digest in the second half. Both halves are attested
        # by hardware, so neither can be swapped after the fact.
        report_data = nonce + digest
        quote = self.client.get_quote(bytes.fromhex(report_data))

        signature = Account.sign_message(
            encode_defunct(
                text=signature_text(nonce, self.signer, self.wallet, digest)
            ),
            private_key=self._signer.key,
        ).signature.to_0x_hex()

        return {
            "binding": binding_payload(nonce, self.signer, self.wallet),
            "bindingHash": "0x" + digest,
            "signature": signature,
            "signer": self.signer,
            "wallet": self.wallet,
            "report_data": quote.report_data or report_data,
            "quote": quote.quote,
            "event_log": quote.event_log,
            "vm_config": quote.vm_config,
        }

    def info(self) -> dict[str, object]:
        return json.loads(self.client.info().model_dump_json())


def build_handler(service: PilotService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "RTMTeaPilot/0.1"

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"{self.address_string()} {fmt % args}", flush=True)

        def send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/health":
                    self.send_json(200, {"ok": True})
                    return
                if parsed.path == "/info":
                    self.send_json(200, service.info())
                    return
                if parsed.path == "/attestation":
                    params = parse_qs(parsed.query)
                    nonce = (params.get("nonce") or [""])[0]
                    self.send_json(200, service.attest(nonce))
                    return
                self.send_json(404, {"error": "not found"})
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
            except Exception as exc:  # dstack socket missing or quote failure
                self.send_json(503, {"error": f"attestation unavailable: {exc}"})

    return Handler


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    service = PilotService()
    print(f"signer={service.signer} wallet={service.wallet}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", port), build_handler(service))
    print(f"tee-pilot listening on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
