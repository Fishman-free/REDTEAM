"""CVM-internal wallet MCP endpoint.

The defender harness receives this URL and bearer token through the sealed
driver; the platform API never exposes these routes.  Two wire shapes are
accepted to keep the simulator and real MCP clients on the same code:

* MCP JSON-RPC: ``tools/call`` with ``name``/``arguments``;
* the simulator's flat ``{"name": ..., "arguments": ...}`` request.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .wallet import WalletRegistry, WalletSession

TOOL_NAMES = ("get_balance", "transfer_rtm")


def _fail(reason: str = "transfer failed") -> dict[str, Any]:
    return {"result": {"status": "failed", "reason": reason}}


def create_wallet_mcp_app(registry: WalletRegistry) -> FastAPI:
    if not isinstance(registry, WalletRegistry):
        raise ValueError("registry must be a WalletRegistry")
    app = FastAPI(title="RTM BYOA wallet sidecar", docs_url=None, redoc_url=None)

    def session_for(authorization: str = Header(default="")) -> WalletSession:
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            raise HTTPException(status_code=401, detail="missing wallet token")
        session = registry.resolve(authorization[len(prefix) :])
        if session is None:
            raise HTTPException(status_code=401, detail="invalid wallet token")
        return session

    def execute(
        session: WalletSession, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        if name == "get_balance":
            balance = session.balance()
            if balance is None:
                return _fail("balance unavailable")
            return {"result": {"balance": str(balance)}}
        if name == "transfer_rtm":
            return session.transfer(
                arguments.get("to"), arguments.get("amount")
            ).agent_receipt
        return _fail("unknown tool")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/tools")
    def tools(_session: WalletSession = Depends(session_for)) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_balance",
                        "description": "Read the contest wallet balance in wei.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "transfer_rtm",
                        "description": (
                            "Transfer tRTM from the contest wallet. "
                            "Policy failures return a generic transfer failed."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "to": {"type": "string"},
                                "amount": {"type": "string"},
                            },
                            "required": ["to", "amount"],
                        },
                    },
                },
            ]
        }

    @app.post("/mcp")
    def mcp(
        payload: dict[str, Any],
        _session: WalletSession = Depends(session_for),
    ) -> Any:
        session = _session
        if payload.get("jsonrpc") == "2.0":
            request_id = payload.get("id")
            if payload.get("method") != "tools/call":
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": "method not found"},
                    },
                    status_code=200,
                )
            params = payload.get("params")
            if not isinstance(params, dict):
                params = {}
            name = params.get("name")
            arguments = params.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            receipt = execute(session, name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(receipt, ensure_ascii=False)}
                    ],
                    "isError": receipt.get("result", {}).get("status") != "ok"
                    and name == "transfer_rtm",
                },
            }

        name = payload.get("name")
        arguments = payload.get("arguments")
        if not isinstance(name, str) or name not in TOOL_NAMES:
            raise HTTPException(status_code=400, detail="unknown tool")
        if not isinstance(arguments, dict):
            raise HTTPException(status_code=400, detail="arguments must be an object")
        return execute(session, name, arguments)

    return app
