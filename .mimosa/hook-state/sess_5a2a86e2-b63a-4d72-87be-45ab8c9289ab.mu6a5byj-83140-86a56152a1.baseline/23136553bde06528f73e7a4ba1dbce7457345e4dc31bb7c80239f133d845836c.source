"""PayGate SUT — FastAPI application.

Route table (all JSON):

- GET  /health
- POST /tasks                              create task + trusted authorization
- POST /external/merchant_message          untrusted channel input
- POST /external/invoice                   untrusted channel input (HTML)
- POST /external/webhook                   untrusted channel input (callback)
- PUT  /external/product_page              untrusted channel input
- GET  /external/view/{surface}            read-only recon of current content
- POST /tasks/{task_id}/run                decision pipeline: plan -> policy -> ledger
- GET  /tasks/{task_id}                    task + authorization + execution state
- GET  /ledger                             full payment ledger (?trace=1 adds HTTP trace)

Every HTTP request/response pair is recorded in an in-memory trace and can be
exported alongside the ledger for evidence collection.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .llm_agent import PaymentDecisionAgent
from .policy import PolicyGuard
from .store import Authorization, Ledger, TaskRecord
from .surfaces import SURFACE_NAMES, SurfaceBoard

app = FastAPI(
    title="PayGate",
    description="Payment authorization gateway under test",
    version="0.1.0",
)

STORE = Ledger()
TRACE: list[dict[str, Any]] = []
_TRACE_LOCK = threading.Lock()
_TRACE_BODY_LIMIT = 4000


class TraceMiddleware:
    """Pure ASGI middleware that records method/path/body/status per request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body += message.get("body", b"")
                if not message.get("more_body"):
                    break
            else:
                break

        replayed = False

        async def wrapped_receive() -> dict:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        status_holder = {"status": None}

        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message.get("status")
            await send(message)

        try:
            await self.app(scope, wrapped_receive, wrapped_send)
        finally:
            path = scope.get("path", "")
            query = scope.get("query_string", b"")
            if query:
                path = f"{path}?{query.decode('latin-1')}"
            entry = {
                "seq": len(TRACE) + 1,
                "ts": time.time(),
                "method": scope.get("method", ""),
                "path": path,
                "body": body.decode("utf-8", errors="replace")[:_TRACE_BODY_LIMIT],
                "status": status_holder["status"],
            }
            with _TRACE_LOCK:
                TRACE.append(entry)


app.add_middleware(TraceMiddleware)


# --------------------------------------------------------------------- models


class AuthorizationIn(BaseModel):
    order_id: str
    recipient: str
    exact_amount_minor: int
    max_total_minor: int
    currency: str = "CNY"
    allowed_purposes: list[str] = Field(default_factory=lambda: ["purchase"])
    max_executions: int = 1
    require_confirmation_above_minor: int | None = None


class TaskIn(BaseModel):
    user_request: str
    authorization: AuthorizationIn


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


# -------------------------------------------------------------------- helpers


def _require_task(task_id: str) -> TaskRecord:
    record = STORE.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"unknown task: {task_id}")
    return record


def _public_payment(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": row["request_id"],
        "order_id": row["order_id"],
        "recipient": row["recipient"],
        "amount_minor": row["amount_minor"],
        "purpose": row["purpose"],
        "currency": row["currency"],
        "status": row["status"],
        "reason": row["reason"],
    }


# -------------------------------------------------------------------- routes


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


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
    if not authorization.currency.strip():
        raise HTTPException(status_code=422, detail="currency must not be empty")
    if not authorization.allowed_purposes or any(
        not purpose.strip() for purpose in authorization.allowed_purposes
    ):
        raise HTTPException(status_code=422, detail="allowed_purposes must be non-empty strings")

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    STORE.create_task(
        task_id,
        payload.user_request,
        Authorization.from_mapping(authorization.model_dump()),
    )
    return {"task_id": task_id}


@app.post("/external/merchant_message")
def external_merchant_message(payload: MerchantMessageIn) -> dict:
    SurfaceBoard(STORE).write("merchant_message", payload.order_id, payload.content)
    return {"surface": "merchant_message", "stored": True}


@app.post("/external/invoice")
def external_invoice(payload: InvoiceIn) -> dict:
    SurfaceBoard(STORE).write("invoice", payload.order_id, payload.html)
    return {"surface": "invoice", "stored": True}


@app.post("/external/webhook")
def external_webhook(payload: WebhookIn) -> dict:
    content = json.dumps(
        {"source": payload.source, "payload": payload.payload}, ensure_ascii=False
    )
    SurfaceBoard(STORE).write("webhook", None, content)
    return {"surface": "webhook", "stored": True}


@app.put("/external/product_page")
def external_product_page(payload: ProductPageIn) -> dict:
    SurfaceBoard(STORE).write("product_page", payload.order_id, payload.content)
    return {"surface": "product_page", "stored": True}


@app.get("/external/view/{surface}")
def external_view(surface: str) -> dict:
    if surface not in SURFACE_NAMES:
        raise HTTPException(status_code=404, detail=f"unknown surface: {surface}")
    row = SurfaceBoard(STORE).read(surface)
    if row is None:
        return {"surface": surface, "order_id": None, "content": ""}
    return {"surface": surface, "order_id": row.get("order_id"), "content": row["content"]}


@app.post("/tasks/{task_id}/run")
def run_task(task_id: str) -> dict:
    record = _require_task(task_id)
    board = SurfaceBoard(STORE)
    policy = PolicyGuard.from_env(STORE)
    agent = PaymentDecisionAgent(policy)

    plan, final_message = agent.build_plan(record, board)
    policy.begin_run(record, board)

    payments: list[dict[str, Any]] = []
    for item in plan:
        prior = STORE.prior_state(task_id)
        allowed, reason = policy.allow(item, record, prior)
        row = STORE.pay(task_id, item, allowed, reason)
        payments.append(_public_payment(row))

    STORE.set_task_status(task_id, "completed")
    return {"payments": payments, "final_message": final_message}


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    record = _require_task(task_id)
    return {
        "task_id": record.task_id,
        "user_request": record.user_request,
        "authorization": record.authorization.as_mapping(),
        "status": record.status,
        "spent_minor": record.spent_minor,
        "executed_count": record.executed_count,
    }


@app.get("/ledger")
def get_ledger(trace: bool = False) -> dict:
    result: dict[str, Any] = {"payments": STORE.all_payments()}
    if trace:
        with _TRACE_LOCK:
            result["trace"] = list(TRACE)
    return result
