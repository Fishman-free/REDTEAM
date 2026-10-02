from __future__ import annotations
import copy
import json
import re
import threading
import time
import uuid

from .model_client import ModelError
from .models import Scenario, canonical_hash, require_text
from .prompts import system_prompt
from .tools import HostTools, tool_definitions


class PaymentAgent:
    """A persistent dialogue with a bounded, native function-calling loop per turn."""
    def __init__(self, scenario: Scenario, client, *, max_steps: int = 10,
                 max_turns: int = 40, turn_timeout: float = 120,
                 instructions: str | None = None):
        if not 1 <= max_steps <= 24 or not 1 <= max_turns <= 100 or not 1 <= turn_timeout <= 300:
            raise ValueError("agent budgets are outside supported bounds")
        self.scenario, self.client = scenario, client
        self.id = uuid.uuid4().hex
        self.tools = HostTools(scenario)
        self.messages = [{"role": "system", "content": system_prompt(scenario, instructions)}]
        self.instructions_sha256 = canonical_hash(self.messages[0]["content"])
        self.turns, self.model_calls, self.errors = [], [], []
        self.execution_request_turn = None
        self.max_steps, self.max_turns, self.turn_timeout = max_steps, max_turns, turn_timeout
        self._lock = threading.RLock()
        self._halted = False

    def add_tool_override(self, override: dict):
        with self._lock:
            self.tools.add_override(override)

    def turn(self, content: str, *, channel: str = "owner", claimed_sender: str = "",
             requests_execution: bool = False) -> dict:
        """channel is assigned by the trusted caller/route, never parsed from content.

        requests_execution is likewise control-side declared semantics for the
        trusted owner channel: the host attests "this owner turn demands
        execution of the authorized action". It never derives from text and
        external turns can never set it.
        """
        require_text(content, "content", 16000)
        if channel not in {"owner", "external"}:
            raise ValueError("channel must be owner or external")
        if not isinstance(claimed_sender, str) or len(claimed_sender) > 256:
            raise ValueError("claimed_sender must be bounded text")
        if not isinstance(requests_execution, bool) or (requests_execution and channel != "owner"):
            raise ValueError("only a trusted owner turn may request execution")
        with self._lock:
            if self._halted:
                raise ValueError("session halted after model/protocol failure; create a fresh session")
            if len(self.turns) >= self.max_turns:
                raise ValueError("dialogue turn budget exhausted")
            envelope = {"channel": "verified_owner" if channel == "owner" else "external_dialogue",
                        "authenticated_principal": self.scenario.owner_id if channel == "owner" else None,
                        "claimed_sender": claimed_sender, "content": content}
            if channel == "owner":
                envelope["owner_requests_execution"] = requests_execution
                if requests_execution and self.execution_request_turn is None:
                    self.execution_request_turn = len(self.turns) + 1
            self.turns.append(copy.deepcopy(envelope))
            self.messages.append({"role": "user", "content": json.dumps(envelope, ensure_ascii=False)})
            turn_number = len(self.turns)
            start_event = len(self.tools.events)
            started = time.monotonic()
            text, error = "", None
            for step in range(self.max_steps):
                try:
                    remaining = self.turn_timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise ModelError("turn deadline exhausted")
                    if len(json.dumps(self.messages, ensure_ascii=False)) > 200000:
                        raise ModelError("conversation context budget exhausted")
                    response = self.client.complete(copy.deepcopy(self.messages), tool_definitions(), timeout=remaining)
                    if not isinstance(response, dict):
                        raise ModelError("model response must be an object")
                    self.model_calls.append({"turn": turn_number, "step": step+1,
                                             "model": response.get("model"), "usage": response.get("usage", {})})
                    message = response["message"]
                    if not isinstance(message, dict) or message.get("role") != "assistant":
                        raise ModelError("invalid assistant role")
                    calls = message.get("tool_calls") or []
                    if not isinstance(calls, list) or len(calls) > 4:
                        raise ModelError("invalid tool call batch")
                    text = message.get("content") or ""
                    if not isinstance(text, str) or len(text) > 50000:
                        raise ModelError("invalid assistant text")
                    parsed = []
                    ids = set()
                    for call in calls:
                        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
                            raise ModelError("invalid function call object")
                        identifier = require_text(call.get("id"), "tool_call_id", 256)
                        if identifier in ids or call.get("type") != "function":
                            raise ModelError("duplicate or invalid tool call")
                        ids.add(identifier)
                        name = require_text(call["function"].get("name"), "tool_name", 128)
                        raw_args = call["function"]["arguments"]
                        if not isinstance(raw_args, str) or len(raw_args) > 32000:
                            raise ModelError("tool arguments must be a bounded JSON string")
                        parsed.append((identifier, name, json.loads(raw_args)))
                    if any(name == "finish_task" for _, name, _ in parsed[:-1]):
                        raise ModelError("finish_task must end the batch")
                    clean_message = {"role": "assistant", "content": text or None}
                    if calls:
                        clean_message["tool_calls"] = [{"id": identifier, "type": "function", "function": {
                            "name": name, "arguments": json.dumps(args, ensure_ascii=False)}} for identifier, name, args in parsed]
                    self.messages.append(clean_message)
                    if not parsed:
                        # Some OpenAI-compatible runtimes emit terminal report JSON
                        # as content rather than a function call. Accept only this
                        # exact, read-only report schema; never execute payment JSON.
                        try:
                            terminal = json.loads(text)
                        except ValueError:
                            terminal = None
                            # A single JSON code block is a presentation variant,
                            # not permission to interpret arbitrary prose as tools.
                            blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
                            if len(blocks) == 1:
                                try:
                                    terminal = json.loads(blocks[0])
                                except ValueError:
                                    pass
                        if isinstance(terminal, dict) and set(terminal) == {"status", "summary", "facts"}:
                            result = self.tools.call("finish_task", terminal, turn_number)
                            self.tools.events[-1]["transport"] = "structured_final"
                            if result["status"] != "ok":
                                raise ModelError("invalid structured final report")
                            text = terminal["summary"]
                        break  # a natural-language clarification also remains a valid turn
                    finished = False
                    for identifier, name, args in parsed:
                        result = self.tools.call(name, args, turn_number)
                        self.messages.append({"role": "tool", "tool_call_id": identifier,
                                              "content": json.dumps(result, ensure_ascii=False)})
                        if name == "finish_task" and result["status"] == "ok":
                            text, finished = args["summary"], True
                    if finished:
                        # A final assistant message follows the tool receipt for the next turn.
                        self.messages.append({"role": "assistant", "content": text})
                        break
                except (ModelError, ValueError, KeyError, TypeError) as exc:
                    error = {"turn": turn_number, "kind": type(exc).__name__, "message": str(exc)[:300]}
                    self.errors.append(error)
                    self._halted = True
                    break
            else:
                error = {"turn": turn_number, "kind": "step_budget", "message": "agent tool-loop budget exhausted"}
                self.errors.append(error)
                self._halted = True
            return {"session_id": self.id, "turn": turn_number, "reply": text, "error": error,
                    "tool_calls": len(self.tools.events)-start_event}

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy({"schema_version": "payassist.multiturn.v1", "session_id": self.id,
                "scenario_id": self.scenario.id, "level": self.scenario.level,
                "persona": self.scenario.persona, "owner_id": self.scenario.owner_id,
                "policy": self.scenario.policy, "contract": self.scenario.contract,
                "contract_sha256": canonical_hash(self.scenario.contract),
                "instructions_sha256": self.instructions_sha256,
                "initial_world": self.tools.initial_world, "world": self.tools.world,
                "payments": self.tools.world["payments"], "events": self.tools.events,
                "reports": self.tools.reports, "errors": self.errors,
                "execution_request_turn": self.execution_request_turn,
                "turns": self.turns, "messages": self.messages, "model_calls": self.model_calls})
