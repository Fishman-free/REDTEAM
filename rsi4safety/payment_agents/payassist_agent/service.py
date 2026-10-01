"""Local experiment API. Trusted and adversarial channels have different capabilities."""
from __future__ import annotations
import hmac
import secrets
import threading

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .model_client import ModelConfig, OpenAICompatibleClient
from .models import load_scenario
from .runtime import PaymentAgent


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1, max_length=128)
    allow_attacks: bool = False


class OwnerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=16000)


class ExternalTurn(OwnerTurn):
    claimed_sender: str = Field(default="", max_length=256)


class ToolOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    match: dict = Field(default_factory=dict)
    text: str = Field(min_length=1, max_length=16000)
    mode: str = "append"
    times: int = Field(default=1, ge=1, le=20)


def create_app(control_token: str, client=None) -> FastAPI:
    if not isinstance(control_token, str) or len(control_token) < 24:
        raise ValueError("a private controller token of at least 24 characters is required")
    model_client = client or OpenAICompatibleClient(ModelConfig.from_env())
    app = FastAPI(title="PayAssist L0/L1 multi-turn lab", version="0.2.0")
    sessions: dict[str, tuple[PaymentAgent, str | None]] = {}
    lock = threading.Lock()

    def authenticate(header: str | None, token: str):
        if not header or not hmac.compare_digest(header.encode(), ("Bearer " + token).encode()):
            raise HTTPException(status_code=401, detail="invalid capability")

    def get_session(session_id: str):
        with lock:
            found = sessions.get(session_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown session")
        return found

    def run(agent, payload, *, channel):
        try:
            return agent.turn(payload.content, channel=channel,
                              claimed_sender=getattr(payload, "claimed_sender", ""))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.get("/health")
    def health():
        return {"status": "ok", "protocol": "payassist.multiturn.v1"}

    @app.post("/sessions", status_code=201)
    def create(payload: CreateSession, authorization: str | None = Header(default=None)):
        authenticate(authorization, control_token)
        try:
            agent = PaymentAgent(load_scenario(payload.scenario_id), model_client)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        attacker_token = secrets.token_urlsafe(32) if payload.allow_attacks else None
        with lock:
            if len(sessions) >= 128:
                raise HTTPException(status_code=429, detail="session capacity reached")
            sessions[agent.id] = (agent, attacker_token)
        return {"session_id": agent.id, "contract": agent.scenario.contract,
                "attacker_token": attacker_token}

    @app.post("/sessions/{session_id}/owner-turn")
    def owner_turn(session_id: str, payload: OwnerTurn, authorization: str | None = Header(default=None)):
        authenticate(authorization, control_token)
        agent, _ = get_session(session_id)
        return run(agent, payload, channel="owner")

    @app.post("/sessions/{session_id}/external-turn")
    def external_turn(session_id: str, payload: ExternalTurn, authorization: str | None = Header(default=None)):
        agent, attacker_token = get_session(session_id)
        if attacker_token is None:
            raise HTTPException(status_code=403, detail="attack surface not enabled for this session")
        authenticate(authorization, attacker_token)
        return run(agent, payload, channel="external")

    @app.post("/sessions/{session_id}/tool-overrides")
    def override(session_id: str, payload: ToolOverride, authorization: str | None = Header(default=None)):
        agent, attacker_token = get_session(session_id)
        if attacker_token is None:
            raise HTTPException(status_code=403, detail="attack surface not enabled for this session")
        authenticate(authorization, attacker_token)
        try:
            agent.add_tool_override(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {"queued": True}

    @app.get("/sessions/{session_id}")
    def snapshot(session_id: str, authorization: str | None = Header(default=None)):
        authenticate(authorization, control_token)
        return get_session(session_id)[0].snapshot()

    @app.delete("/sessions/{session_id}")
    def close(session_id: str, authorization: str | None = Header(default=None)):
        authenticate(authorization, control_token)
        with lock:
            if sessions.pop(session_id, None) is None:
                raise HTTPException(status_code=404, detail="unknown session")
        return {"closed": True}

    return app
