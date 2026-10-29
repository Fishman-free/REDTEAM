"""Egress allowlist for the sealed runtime.

A defender agent leaks attack data if it can call any defender-controlled
service.  The CVM proxy therefore forwards only:

1. the in-CVM wallet MCP (handled locally, not by this module);
2. declared third-party model endpoints;
3. optional structured oracles that receive only schema-approved fields.

Everything else is denied and recorded (spec §8).
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Mapping

from .adapters import HttpJsonClient


class EgressError(ValueError):
    """Malformed or unsafe egress declaration."""


def _host(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 253:
        raise EgressError("egress host must be a non-empty hostname")
    candidate = value.strip().lower()
    if "://" in candidate or "/" in candidate or "@" in candidate:
        raise EgressError("egress hosts must not contain a scheme, path or credentials")
    return candidate


@dataclass(frozen=True)
class OracleRule:
    """A structured oracle: only ``fields`` survive redaction."""

    name: str
    host: str
    path_prefix: str = "/"
    fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise EgressError("oracle name is required")
        object.__setattr__(self, "host", _host(self.host))
        if not isinstance(self.path_prefix, str) or not self.path_prefix.startswith("/"):
            raise EgressError("oracle path_prefix must start with /")
        if not isinstance(self.fields, tuple) or not self.fields:
            raise EgressError("oracle fields must be a non-empty tuple")
        if any(not isinstance(item, str) or not item for item in self.fields):
            raise EgressError("oracle fields must be non-empty strings")

    def redact(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise EgressError("oracle payload must be a mapping")
        return {key: payload[key] for key in self.fields if key in payload}


@dataclass(frozen=True)
class EgressDeclaration:
    model_hosts: frozenset[str] = frozenset()
    oracles: tuple[OracleRule, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "model_hosts", frozenset(_host(item) for item in self.model_hosts)
        )
        if not isinstance(self.oracles, tuple):
            raise EgressError("oracles must be a tuple")
        for rule in self.oracles:
            if not isinstance(rule, OracleRule):
                raise EgressError("oracles must contain OracleRule values")

    def as_public_dict(self) -> dict[str, Any]:
        """Public declaration shown to attackers (spec §5.1)."""

        return {
            "models": sorted(self.model_hosts),
            "oracles": [
                {
                    "name": rule.name,
                    "host": rule.host,
                    "pathPrefix": rule.path_prefix,
                    "fields": list(rule.fields),
                }
                for rule in self.oracles
            ],
        }


def load_declaration(data: Mapping[str, Any]) -> EgressDeclaration:
    if not isinstance(data, Mapping):
        raise EgressError("egress declaration must be an object")
    models = data.get("models", [])
    oracles = data.get("oracles", [])
    if not isinstance(models, list) or any(not isinstance(item, str) for item in models):
        raise EgressError("models must be a list of hostnames")
    if not isinstance(oracles, list):
        raise EgressError("oracles must be a list")
    rules: list[OracleRule] = []
    for item in oracles:
        if not isinstance(item, Mapping):
            raise EgressError("oracle rule must be an object")
        fields_value = item.get("fields", [])
        if not isinstance(fields_value, list) or any(
            not isinstance(field, str) for field in fields_value
        ):
            raise EgressError("oracle fields must be a list of strings")
        rules.append(
            OracleRule(
                name=str(item.get("name", "")),
                host=str(item.get("host", "")),
                path_prefix=str(item.get("pathPrefix", "/")),
                fields=tuple(fields_value),
            )
        )
    return EgressDeclaration(model_hosts=frozenset(models), oracles=tuple(rules))


@dataclass(frozen=True)
class EgressDecision:
    allowed: bool
    reason: str
    kind: str
    host: str
    oracle: OracleRule | None = None


class EgressPolicy:
    """Evaluates and records every outbound attempt."""

    def __init__(self, declaration: EgressDeclaration) -> None:
        if not isinstance(declaration, EgressDeclaration):
            raise EgressError("declaration must be an EgressDeclaration")
        self.declaration = declaration
        self._audit: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def check(self, url: str, *, kind: str = "model") -> EgressDecision:
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError:
            return self._record(EgressDecision(False, "invalid_url", kind, ""))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return self._record(EgressDecision(False, "invalid_url", kind, ""))
        host = parsed.hostname.lower()
        if kind == "model":
            decision = EgressDecision(
                host in self.declaration.model_hosts, "model_allowlist", kind, host
            )
        elif kind == "oracle":
            matched = next(
                (
                    rule
                    for rule in self.declaration.oracles
                    if rule.host == host
                    and parsed.path.startswith(rule.path_prefix)
                ),
                None,
            )
            decision = EgressDecision(
                matched is not None,
                "oracle_allowlist" if matched is not None else "oracle_not_allowed",
                kind,
                host,
                matched,
            )
        else:
            decision = EgressDecision(False, "unknown_egress_kind", kind, host)
        return self._record(decision)

    def redact(
        self, decision: EgressDecision, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not decision.allowed:
            raise EgressError("cannot redact a denied egress")
        if decision.kind == "model":
            return dict(payload)
        if decision.oracle is None:
            raise EgressError("oracle decision is missing its rule")
        return decision.oracle.redact(payload)

    def audit(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in self._audit]

    def _record(self, decision: EgressDecision) -> EgressDecision:
        with self._lock:
            self._audit.append(
                {
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "kind": decision.kind,
                    "host": decision.host,
                }
            )
        return decision


@dataclass
class EgressProxy:
    """Minimal forwarding proxy used by the local simulator and tests."""

    policy: EgressPolicy
    client: HttpJsonClient = field(default_factory=HttpJsonClient)

    def forward(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        kind: str = "model",
    ) -> dict[str, Any]:
        decision = self.policy.check(url, kind=kind)
        if not decision.allowed:
            raise EgressError(f"egress denied: {decision.reason}")
        body = self.policy.redact(decision, payload)
        return self.client.post(url, body)

    def forward_json(self, url: str, payload: Mapping[str, Any], *, kind: str) -> str:
        return json.dumps(self.forward(url, payload, kind=kind), ensure_ascii=False)
