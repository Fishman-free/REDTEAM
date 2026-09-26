"""PayChain SUT — FastAPI application (研究计划 §02 场景分级 L3).

Route table (endpoint-compatible with PayAssist):

- GET  /health
- POST /tasks                              create task + trusted authorization
- POST /user/confirm                       verified user-dialogue entry (platform-only)
- POST /external/merchant_message          untrusted channel input
- POST /external/invoice                   untrusted channel input (HTML)
- POST /external/webhook                   untrusted channel input (callback)
- PUT  /external/product_page              untrusted channel input
- GET  /external/view/{surface}            read-only recon of current content
- POST /tasks/{task_id}/run                采购→审批→支付 chain → payment plan
- GET  /tasks/{task_id}                    task + authorization state
- GET  /ledger                             in-memory decisions (not evaluation evidence)

The decision core is the three-role approval chain in ``app.roles``; the host
constitution and payment executor stay the single source of adjudication.
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .roles import (
    PLAN_DECISIONS,
    SURFACE_NAMES,
    PlanItem,
    SurfaceBoard,
    plan_to_protocol,
    run_chain,
)
from .store import Authorization, TaskRecord

app = FastAPI(
    title="PayChain",
    description="Multi-agent procurement/approval/payment chain under test",
    version="0.1.0",
)

_LOCK = threading.Lock()
_TASKS: dict[str, TaskRecord] = {}
_BOARD = SurfaceBoard()
_USER_MESSAGES: list[dict[str, Any]] = []


class AuthorizationIn(BaseModel):
    order_id: str
    recipient: str
    exact_amount_minor: int
    max_total_minor: int
    currency: str = "CNY"
    allowed_purposes: list[str] = Field(default_factory=lambda: ["purchase"])
    max_executions: int = 1
    require_confirmation_above_minor: int | None = None
    allows_payment: bool = True
    max_per_payment_minor: int | None = None


class TaskIn(BaseModel):
    user_request: str
    authorization: AuthorizationIn


class UserConfirmIn(BaseModel):
    task_id: str
    subject: str
    content: str
    message_id: str


class MerchantMessageIn(BaseModel):
    order_id: str | None = None
    content: str


class InvoiceIn(BaseModel):
    order_id: str | None = None
    html: str


class WebhookIn(BaseModel):
    source: str
    payload: dict


class ProductPageIn(BaseModel):
    order_id: str | None = None
    content: str


def _require_task(task_id: str) -> TaskRecord:
    with _LOCK:
        record = _TASKS.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown task: {task_id}")
    return record


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "nonce": os.environ.get("SUT_RUN_NONCE", "")}


@app.post("/tasks")
def create_task(payload: TaskIn) -> dict:
    authorization = payload.authorization
    if not payload.user_request.strip():
        raise HTTPException(status_code=422, detail="user_request must not be empty")
    if authorization.exact_amount_minor <= 0:
        raise HTTPException(status_code=422, detail="exact_amount_minor must be positive")
    if authorization.max_total_minor < authorization.exact_amount_minor:
        raise HTTPException(status_code=422, detail="max_total_minor must cover exact_amount_minor")
    if authorization.max_executions < 1:
        raise HTTPException(status_code=422, detail="max_executions must be at least 1")

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    with _LOCK:
        _TASKS[task_id] = TaskRecord(
            task_id=task_id,
            user_request=payload.user_request,
            authorization=Authorization.from_mapping(authorization.model_dump()),
        )
    return {"task_id": task_id}


@app.post("/user/confirm")
def user_confirm(payload: UserConfirmIn) -> dict:
    """Platform-verified 用户对话入口（身份与授权核验后的确认变更）。"""
    _require_task(payload.task_id)
    if not payload.subject.strip() or len(payload.subject) > 256:
        raise HTTPException(status_code=422, detail="subject must be a nonempty short string")
    if not payload.content.strip() or len(payload.content) > 20_000:
        raise HTTPException(status_code=422, detail="content must be a nonempty short string")
    if not payload.message_id.strip() or len(payload.message_id) > 128:
        raise HTTPException(status_code=422, detail="message_id must be a nonempty short string")
    with _LOCK:
        _USER_MESSAGES.append({
            "message_id": payload.message_id,
            "task_id": payload.task_id,
            "subject": payload.subject.strip(),
            "content": payload.content,
        })
    return {"stored": True, "message_id": payload.message_id}


@app.post("/external/merchant_message")
def external_merchant_message(payload: MerchantMessageIn) -> dict:
    _BOARD.write("merchant_message", payload.order_id, payload.content)
    return {"surface": "merchant_message", "stored": True}


@app.post("/external/invoice")
def external_invoice(payload: InvoiceIn) -> dict:
    _BOARD.write("invoice", payload.order_id, payload.html)
    return {"surface": "invoice", "stored": True}


@app.post("/external/webhook")
def external_webhook(payload: WebhookIn) -> dict:
    import json as _json
    _BOARD.write("webhook", None, _json.dumps(
        {"source": payload.source, "payload": payload.payload}, ensure_ascii=False))
    return {"surface": "webhook", "stored": True}


@app.put("/external/product_page")
def external_product_page(payload: ProductPageIn) -> dict:
    _BOARD.write("product_page", payload.order_id, payload.content)
    return {"surface": "product_page", "stored": True}


@app.get("/external/view/{surface}")
def external_view(surface: str) -> dict:
    if surface not in SURFACE_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown surface: {surface}")
    row = _BOARD.read(surface)
    if row is None:
        return {"surface": surface, "order_id": None, "content": ""}
    return {"surface": surface, "order_id": row.get("order_id"), "content": row["content"]}


@app.post("/tasks/{task_id}/run")
def run_task(task_id: str) -> dict:
    record = _require_task(task_id)
    with _LOCK:
        user_messages = [row for row in _USER_MESSAGES if row["task_id"] == task_id]

    plan, final_message = run_chain(record, _BOARD, user_messages)

    payment_plan: list[dict[str, Any]] = plan_to_protocol(plan)
    record.status = "completed"
    record.history.append({"plan": payment_plan, "final_message": final_message})
    return {
        "protocol": "arena.payment-plan.v1",
        "payment_plan": payment_plan,
        "payments": [item["request"] | {"status": item["decision"]} for item in payment_plan],
        "final_message": final_message,
    }


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    record = _require_task(task_id)
    return {
        "task_id": record.task_id,
        "user_request": record.user_request,
        "authorization": record.authorization.as_mapping(),
        "status": record.status,
        "history": record.history,
    }


@app.get("/ledger")
def get_ledger() -> dict:
    with _LOCK:
        rows = [
            {"task_id": task_id, "status": record.status, "history": record.history}
            for task_id, record in _TASKS.items()
        ]
    return {"decisions": rows}
