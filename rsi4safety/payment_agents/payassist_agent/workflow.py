"""Small agent-side operators for data trust, task execution and delivery.

Only public task steps and observed tool receipts enter this module. It never
reads evaluation expectations or the host's private ledger. The same operators
apply to every order, amount and scenario.
"""
from __future__ import annotations

from copy import deepcopy

from .models import PAYMENT_FIELDS


class AgentWorkflow:
    def __init__(self, package, contract):
        self.rules = package.runtime
        self.task = deepcopy(contract.get("task", {"steps": []}))
        self.mandate = deepcopy(contract["policy"]["payment"])
        self.observed = {}
        self.completed_steps = set()
        self.blocks = []

    @staticmethod
    def step_key(tool, args):
        return (tool, args.get("product_id", args.get("order_id")))

    def receive(self, receipt):
        """Strip untrusted prose while preserving authenticated API data."""
        visible = deepcopy(receipt)
        data = visible.get("result")
        if isinstance(data, dict) and "external_text" in data:
            data = data.get("data")
            if self.rules["project_tool_data"]:
                visible["result"] = (deepcopy(data) if isinstance(data, dict) else
                                     {"error": "untrusted_presentation", "detail": "retrieve a fresh business record"})
        if visible.get("status") != "ok" or not isinstance(data, dict):
            return visible
        # Overlay-only prose is never copied into authenticated memory.
        tool = visible["tool"]
        event_id = visible["event_id"]
        if tool == "get_product":
            self._remember("product", data.get("product_id", data.get("id")), data, event_id)
        elif tool == "get_order":
            self._remember("order", data.get("order_id"), data, event_id)
        elif tool == "search_catalog":
            for product in data.get("products", []):
                self._remember("product", product.get("product_id", product.get("id")), product, event_id)
        elif tool == "get_payment_status":
            self._remember("order", data.get("order_id"), data, event_id)
            for payment in data.get("payments", []):
                self._remember("payment", payment.get("payment_id"), payment, event_id)
                # A status lookup can recover a successful action whose receipt
                # presentation was lost or replaced. Never issue it a second time.
                if (self.mandate and payment.get("status") == "executed"
                        and all(type(payment.get(field)) is type(self.mandate[field])
                                and payment.get(field) == self.mandate[field] for field in PAYMENT_FIELDS)):
                    self.completed_steps.add(("pay_order", payment["order_id"]))
        elif tool == "pay_order" and data.get("payment_id"):
            self._remember("payment", data["payment_id"], data, event_id)
            # An earlier unpaid observation cannot describe the current state.
            prior = self.observed.get(("order", data.get("order_id")))
            if prior:
                for field in ("status", "total_paid_minor"):
                    prior.pop(field, None)
        elif tool == "create_invoice":
            self._remember("invoice", data.get("invoice_id"), data, event_id)
        return visible

    def _remember(self, kind, identifier, data, event_id):
        if not isinstance(identifier, str):
            return
        fields = self.observed.setdefault((kind, identifier), {})
        for name, value in data.items():
            if type(value) in {str, int}:
                fields[name] = (value, event_id)

    def mark(self, tool, args, visible):
        data = visible.get("result", {})
        if visible.get("status") == "ok" and isinstance(data, dict) and not data.get("error"):
            self.completed_steps.add(self.step_key(tool, args))

    def before_payment(self, args, *, execution_open, invoke):
        """Agent wrapper decisions; the host independently enforces authorization."""
        reasons = []
        if self.rules["enforce_execution_release"] and not execution_open:
            reasons.append("execution_not_released")
        if self.rules["preflight_payments"]:
            if not self.mandate or any(type(args.get(k)) is not type(self.mandate[k]) or args.get(k) != self.mandate[k]
                                       for k in PAYMENT_FIELDS):
                reasons.append("proposal_outside_mandate")
            elif not reasons:
                order_id = args["order_id"]
                for tool in ("get_order", "get_payment_status"):
                    # A fresh status prevents paying again after a timeout/retry.
                    if tool == "get_payment_status" or (tool, order_id) not in self.completed_steps:
                        result = invoke(tool, {"order_id": order_id})
                        if result.get("status") != "ok" or result.get("result", {}).get("error"):
                            reasons.append("precheck_unavailable")
                order = self.observed.get(("order", order_id), {})
                if order.get("status", (None,))[0] == "paid":
                    reasons.append("already_paid")
                if any(field not in order or order[field][0] != self.mandate[field]
                       for field in ("recipient", "amount_minor", "currency", "purpose")):
                    reasons.append("precheck_terms_unverified")
        if reasons:
            self.blocks.append({"tool": "pay_order", "args": deepcopy(args), "reasons": sorted(set(reasons))})
            return {"status": "blocked", "tool": "pay_order", "result": {
                "error": "agent_preflight_block", "violations": sorted(set(reasons))}}
        return None

    def complete(self, *, execution_open, invoke):
        if not self.rules["complete_workflow"]:
            return
        for step in self.task["steps"]:
            tool, args = step["tool"], deepcopy(step["args"])
            if self.step_key(tool, args) in self.completed_steps:
                continue
            if tool == "pay_order":
                if not execution_open or not self.mandate:
                    continue
                args = {**self.mandate, "request_id": self.mandate["order_id"] + ":payment"}
            invoke(tool, args)

    def report(self, proposed, *, execution_open):
        """Ground the delivered report in observations, without inventing receipts."""
        result = deepcopy(proposed)
        if self.rules["repair_report_schema"] and isinstance(result.get("facts"), list):
            for fact in result["facts"]:
                if isinstance(fact, dict) and fact.get("object_type") == "payment_status":
                    fact["object_type"] = "order"
        if not self.rules["ground_reports"]:
            return result
        fields = {
            "product": ("name", "price_minor", "stock"),
            "order": ("amount_minor", "recipient", "currency", "purpose", "status"),
            "payment": ("order_id", "amount_minor", "recipient", "currency", "purpose", "status"),
            "invoice": ("order_id", "amount_minor", "recipient", "currency", "status"),
        }
        facts = [{"object_type": kind, "object_id": identifier, "field": field,
                  "value": values[field][0], "source_event_id": values[field][1]}
                 for (kind, identifier), values in self.observed.items()
                 for field in fields[kind] if field in values]
        task_objects = {("product" if step["tool"] == "get_product" else
                         "invoice" if step["tool"] == "create_invoice" else "order",
                         step["args"].get("product_id", step["args"].get("order_id")))
                        for step in self.task["steps"]}
        task_orders = {step["args"]["order_id"] for step in self.task["steps"] if "order_id" in step["args"]}
        # Bound reports without letting optional catalog reads displace the
        # registered task's facts. Receipt identity is linked by its order_id.
        def task_fact(fact):
            key = (fact["object_type"], fact["object_id"])
            if key in task_objects:
                return True
            values = self.observed[key]
            order_id = values.get("order_id", (None,))[0]
            return fact["object_type"] in {"payment", "invoice"} and order_id in task_orders

        facts.sort(key=lambda fact: not task_fact(fact))
        due = [step for step in self.task["steps"] if step["tool"] != "pay_order" or execution_open]
        done = bool(due) and all(self.step_key(step["tool"], step["args"]) in self.completed_steps for step in due)
        result = {"status": "completed" if done else "needs_clarification",
                  "summary": "已完成本轮允许的业务步骤，结果见核验事实。" if done else "业务步骤尚未完成，保留已核验事实。",
                  "facts": facts[:32]}
        if "reference_answers" in proposed:
            # Preserve the model's source reading; never fill answers from an
            # oracle, infer them from task metadata, or certify them as facts.
            result["reference_answers"] = deepcopy(proposed["reference_answers"])
        return result
