from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
import hashlib
from importlib.resources import files
import json
import re
from typing import Any

LEVEL_PACKAGES = {"L0": "L0_readonly", "L1": "L1_single_payment"}
MAX_AMOUNT = 2**63 - 1
PAYMENT_FIELDS = ("order_id", "recipient", "amount_minor", "currency", "purpose")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def require_text(value: Any, name: str, limit: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} must be nonempty text, at most {limit} characters")
    return value


def require_amount(value: Any) -> int:
    if type(value) is not int or not 0 < value <= MAX_AMOUNT:
        raise ValueError("amount_minor must be a positive integer in minor currency units")
    return value


@dataclass(frozen=True)
class PaymentMandate:
    order_id: str
    recipient: str
    amount_minor: int
    currency: str
    purpose: str

    @classmethod
    def parse(cls, raw: dict) -> PaymentMandate:
        if not isinstance(raw, dict) or set(raw) != set(PAYMENT_FIELDS):
            raise ValueError("payment mandate must specify exact order, recipient, amount, currency and purpose")
        for key in PAYMENT_FIELDS:
            require_amount(raw[key]) if key == "amount_minor" else require_text(raw[key], key)
        if not re.fullmatch(r"[A-Z]{3}", raw["currency"]):
            raise ValueError("currency must use three uppercase letters")
        return cls(**raw)


@dataclass(frozen=True)
class Scenario:
    id: str
    level: str
    persona: str
    owner_id: str
    owner_instruction: str
    mandate: PaymentMandate | None
    _world_json: str
    _task_json: str = "{}"

    @property
    def policy(self) -> dict:
        return {"payment": asdict(self.mandate) if self.mandate else None}

    @property
    def world(self) -> dict:
        return json.loads(self._world_json)

    @property
    def task(self) -> dict:
        """Owner-declared work, independent of evaluation's expected results."""
        return json.loads(self._task_json)

    @property
    def contract(self) -> dict:
        return {"scenario_id": self.id, "level": self.level, "persona": self.persona,
                "owner_id": self.owner_id, "owner_instruction": self.owner_instruction,
                "policy": self.policy, "task": self.task,
                "max_new_payments": 0 if self.level == "L0" else 1}

    @classmethod
    def parse(cls, raw: dict) -> Scenario:
        if raw.get("level") not in LEVEL_PACKAGES or raw.get("persona") not in {"personal", "merchant"}:
            raise ValueError("supported levels: L0/L1; personas: personal/merchant")
        for key in ("id", "owner_id", "owner_instruction"):
            require_text(raw.get(key), key, 12000 if key == "owner_instruction" else 128)
        policy = raw.get("policy", {})
        if not isinstance(policy, dict) or set(policy) != {"payment"}:
            raise ValueError("policy requires a payment field (null for no outgoing authorization)")
        mandate = PaymentMandate.parse(policy["payment"]) if policy["payment"] is not None else None
        if raw["level"] == "L0" and mandate:
            raise ValueError("L0 cannot grant outgoing payment authority")
        world = copy.deepcopy(raw.get("world", {}))
        for key in ("products", "orders", "invoices"):
            if not isinstance(world.get(key, {}), dict):
                raise ValueError(f"world.{key} must be an object")
            world.setdefault(key, {})
        if not isinstance(world.get("payments", []), list):
            raise ValueError("world.payments must be a list")
        world.setdefault("payments", [])
        for key, product in world["products"].items():
            require_text(key, "product_id")
            require_amount(product.get("price_minor"))
            if type(product.get("stock")) is not int or product["stock"] < 0:
                raise ValueError("stock must be a nonnegative integer")
        for key, order in world["orders"].items():
            require_text(key, "order_id")
            require_amount(order.get("amount_minor"))
            for field in ("recipient", "currency", "purpose"):
                require_text(order.get(field), field)
        payment_ids = set()
        for payment in world["payments"]:
            if not isinstance(payment, dict):
                raise ValueError("initial payments must be host records")
            identifier = require_text(payment.get("payment_id"), "payment_id")
            if identifier in payment_ids or payment.get("status") != "executed":
                raise ValueError("initial payments require unique IDs and executed status")
            payment_ids.add(identifier)
            require_amount(payment.get("amount_minor"))
            for key in PAYMENT_FIELDS:
                if key != "amount_minor":
                    require_text(payment.get(key), key)
        if mandate:
            order = world["orders"].get(mandate.order_id)
            if order is None or any(order.get(k) != v for k, v in asdict(mandate).items() if k != "order_id"):
                raise ValueError("initial payment mandate must match the trusted order")
        task = copy.deepcopy(raw.get("task", {"steps": []}))
        allowed = {"get_product": "product_id", "get_order": "order_id",
                   "get_payment_status": "order_id", "create_invoice": "order_id", "pay_order": "order_id"}
        if not isinstance(task, dict) or set(task) - {"steps", "references"} or not isinstance(task.get("steps"), list) or len(task["steps"]) > 12:
            raise ValueError("task requires at most twelve owner-declared steps")
        references = task.get("references", [])
        if not isinstance(references, list) or len(references) > 6:
            raise ValueError("task permits at most six reference questions")
        for ref in references:
            if not isinstance(ref, dict) or set(ref) != {"source_id", "field", "question"}:
                raise ValueError("reference question requires source_id, field and question; never an answer")
            for key in ref:
                require_text(ref[key], "reference." + key, 1000 if key == "question" else 128)
        for step in task["steps"]:
            if not isinstance(step, dict) or set(step) != {"tool", "args"} or step["tool"] not in allowed:
                raise ValueError("task step must name an implemented business tool")
            field = allowed[step["tool"]]
            if not isinstance(step["args"], dict) or set(step["args"]) != {field}:
                raise ValueError("task step must select one business object")
            identifier = require_text(step["args"][field], field)
            collection = "products" if field == "product_id" else "orders"
            if identifier not in world[collection]:
                raise ValueError("task references an unknown business object")
            if step["tool"] == "pay_order" and (not mandate or identifier != mandate.order_id):
                raise ValueError("task payment must match the frozen mandate")
            if step["tool"] == "create_invoice" and (raw["persona"] != "merchant" or not world["orders"][identifier].get("customer_id")):
                raise ValueError("invoice task requires a merchant sales order")
        return cls(raw["id"], raw["level"], raw["persona"], raw["owner_id"],
                   raw["owner_instruction"], mandate, json.dumps(world, ensure_ascii=False, sort_keys=True),
                   json.dumps(task, ensure_ascii=False, sort_keys=True))


def all_scenarios() -> dict[str, Scenario]:
    found = {}
    for level, package in LEVEL_PACKAGES.items():
        directory = files(package).joinpath("scenarios")
        for path in sorted(directory.iterdir(), key=lambda p: p.name):
            if path.name.endswith(".json"):
                scenario = Scenario.parse(json.loads(path.read_text(encoding="utf-8")))
                if scenario.level != level or scenario.id in found:
                    raise ValueError("scenario level mismatch or duplicate id")
                found[scenario.id] = scenario
    return found


def load_scenario(scenario_id: str) -> Scenario:
    try:
        return all_scenarios()[scenario_id]
    except KeyError:
        raise ValueError("unknown scenario_id") from None


def all_cases() -> list[dict]:
    cases = []
    for package in LEVEL_PACKAGES.values():
        raw = json.loads(files(package).joinpath("cases.json").read_text(encoding="utf-8"))
        cases.extend(raw["cases"] if isinstance(raw, dict) else raw)
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("duplicate benchmark case id")
    return cases
