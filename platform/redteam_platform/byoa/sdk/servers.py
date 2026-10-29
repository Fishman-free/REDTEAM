"""Reference HTTP endpoints for hosted-mcp, webhook, a2a and mcp-pull."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable, Mapping

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from ..adapters import PullInbox

AgentHandler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _run(agent: AgentHandler, payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        result = agent(payload)
    except Exception:
        raise HTTPException(status_code=500, detail="agent failed") from None
    if not isinstance(result, Mapping):
        raise HTTPException(status_code=500, detail="agent returned no object")
    reply = result.get("reply")
    calls = result.get("tool_calls", [])
    if not isinstance(reply, str) or not isinstance(calls, list):
        raise HTTPException(status_code=500, detail="agent reply is invalid")
    return {"reply": reply, "tool_calls": calls}


def create_hosted_mcp_app(agent: AgentHandler) -> FastAPI:
    if not callable(agent):
        raise ValueError("agent must be callable")
    app = FastAPI(title="BYOA hosted-mcp reference", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/arena/turn")
    def turn(payload: dict[str, Any]) -> dict[str, Any]:
        return _run(agent, payload)

    return app


def create_webhook_app(agent: AgentHandler, *, secret: str) -> FastAPI:
    if not callable(agent):
        raise ValueError("agent must be callable")
    if not isinstance(secret, str) or len(secret) < 16:
        raise ValueError("webhook secret must be at least 16 characters")
    secret_bytes = secret.encode("utf-8")
    app = FastAPI(title="BYOA webhook reference", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/arena/turn")
    async def turn(
        request: Request,
        x_rtm_signature: str = Header(default=""),
    ) -> dict[str, Any]:
        body = await request.body()
        expected = "sha256=" + hmac.new(
            secret_bytes, body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(x_rtm_signature, expected):
            raise HTTPException(status_code=401, detail="bad signature")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="invalid JSON") from None
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="payload must be an object")
        return _run(agent, payload)

    return app


def create_a2a_app(agent: AgentHandler) -> FastAPI:
    if not callable(agent):
        raise ValueError("agent must be callable")
    app = FastAPI(title="BYOA A2A reference", docs_url=None, redoc_url=None)

    def handle(payload: Mapping[str, Any]) -> dict[str, Any]:
        request_id = payload.get("id")
        if payload.get("method") != "message/send":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "method not found"},
            }
        params = payload.get("params")
        message = params.get("message") if isinstance(params, Mapping) else None
        if not isinstance(message, Mapping):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "message is required"},
            }
        parts = message.get("parts")
        texts = [
            part.get("text", "")
            for part in parts or []
            if isinstance(part, Mapping) and part.get("kind") == "text"
        ]
        metadata = message.get("metadata") if isinstance(message.get("metadata"), Mapping) else {}
        turn_payload = {
            "contest_id": metadata.get("contestId"),
            "seq": metadata.get("seq"),
            "channel": metadata.get("channel"),
            "kind": metadata.get("kind"),
            "content": "\n".join(texts),
            "metadata": dict(metadata),
        }
        result = _run(agent, turn_payload)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "kind": "message",
                "role": "agent",
                "parts": [{"kind": "text", "text": result["reply"]}],
            },
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/")
    def root(payload: dict[str, Any]) -> dict[str, Any]:
        return handle(payload)

    @app.post("/a2a")
    def a2a(payload: dict[str, Any]) -> dict[str, Any]:
        return handle(payload)

    return app


def create_pull_app(inbox: PullInbox, *, token: str) -> FastAPI:
    """CVM-side long-poll endpoints for a mcp-pull defender."""

    if not isinstance(inbox, PullInbox):
        raise ValueError("inbox must be a PullInbox")
    if not isinstance(token, str) or len(token) < 16:
        raise ValueError("pull token must be at least 16 characters")
    app = FastAPI(title="BYOA mcp-pull reference", docs_url=None, redoc_url=None)

    def authorize(authorization: str = Header(default="")) -> None:
        expected = "Bearer " + token
        if not authorization or not hmac.compare_digest(
            authorization.encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="invalid pull token")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/next_message", dependencies=[Depends(authorize)])
    def next_message() -> dict[str, Any]:
        return inbox.next_message() or {"message": None}

    @app.post("/reply", dependencies=[Depends(authorize)])
    def reply(payload: dict[str, Any]) -> dict[str, Any]:
        accepted = inbox.submit_reply(
            seq=payload.get("seq"),
            text=payload.get("text"),
            tool_calls=tuple(payload.get("tool_calls") or ()),
            metadata=payload.get("metadata"),
        )
        return {"accepted": bool(accepted)}

    return app
