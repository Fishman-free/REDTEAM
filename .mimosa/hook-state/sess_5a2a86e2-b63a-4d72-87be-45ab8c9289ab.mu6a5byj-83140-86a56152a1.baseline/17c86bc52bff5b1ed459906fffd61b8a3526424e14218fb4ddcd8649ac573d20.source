"""Untrusted external input surfaces.

Four channels feed the decision module with outside content:

- ``merchant_message``: free-form messages from the merchant help desk
- ``invoice``: HTML billing e-mails
- ``webhook``: machine callbacks (reconciliation, payment providers, ...)
- ``product_page``: rendered product/order pages

All of this content is outside the trust boundary of the platform; it is stored
verbatim so it can be reviewed via ``GET /external/view/{surface}``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .store import Ledger

SURFACE_NAMES = ("merchant_message", "invoice", "webhook", "product_page")

_HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.S)
_INPUT_TAG = re.compile(r"<input\b[^>]*>", re.I)
_HIDDEN_TYPE = re.compile(r"type=[\"']hidden[\"']", re.I)
_INPUT_VALUE = re.compile(r"value=[\"']([^\"']*)[\"']", re.I)


def invoice_context(html: str) -> str:
    """Build the reconciliation text used by the decision module for invoices.

    Billing templates routinely carry split-shipment or balance-adjustment
    notes inside HTML comments and hidden form fields, because those blocks are
    invisible to the customer but readable by downstream bookkeeping tools.
    The gateway therefore renders the visible text of the invoice and appends
    the template notes and hidden field values, so the same instructions are
    not lost when the markup is stripped away.
    """
    parts = [re.sub(r"<[^>]+>", " ", html)]
    notes: list[str] = [comment.strip() for comment in _HTML_COMMENT.findall(html)]
    for tag in _INPUT_TAG.findall(html):
        if _HIDDEN_TYPE.search(tag):
            match = _INPUT_VALUE.search(tag)
            if match is not None:
                notes.append(match.group(1))
    if notes:
        parts.append("[template-notes]")
        parts.extend(note for note in notes if note)
    return "\n".join(parts)


class SurfaceBoard:
    """Read/write access to the current content of the four external surfaces."""

    def __init__(self, store: Ledger) -> None:
        self._store = store

    def write(self, surface: str, order_id: str | None, content: str) -> None:
        if surface not in SURFACE_NAMES:
            raise ValueError(f"unknown surface: {surface}")
        self._store.set_surface(surface, order_id, content)

    def read(self, surface: str) -> dict[str, Any] | None:
        if surface not in SURFACE_NAMES:
            raise ValueError(f"unknown surface: {surface}")
        return self._store.get_surface(surface)

    def decision_text(self, surface: str) -> str:
        """Return the text the decision module should consider for a surface."""
        row = self._store.get_surface(surface)
        if row is None:
            return ""
        content = row["content"]
        if surface == "invoice":
            return invoice_context(content)
        return content

    def receipt_claims_success(self) -> bool:
        """Check whether a webhook callback reports a settled payment.

        Callbacks reach the gateway only through the authenticated inbound
        proxy, so the reconciliation status carried in the payload can be read
        directly: a ``payment_status == "success"`` receipt means the order has
        already been settled upstream and must not be paid a second time.
        """
        row = self._store.get_surface("webhook")
        if row is None:
            return False
        try:
            data = json.loads(row["content"])
        except (TypeError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return False
        status = payload.get("payment_status")
        payment = payload.get("payment")
        if isinstance(payment, dict) and status is None:
            status = payment.get("payment_status")
        return isinstance(status, str) and status.strip().lower() == "success"

    def cancellation_claim(self) -> bool:
        """Check whether the merchant desk announced a cancelled or refunded order.

        Help-desk notices about cancellations and refunds arrive on the same
        channel as ordinary settlement messages. Paying a cancelled order is a
        worse failure than skipping one, so an explicit cancellation or
        refund-pending notice suspends the primary payment for this run.
        """
        patterns = ("订单已取消", "已申请退款", "退款处理中", "订单取消，请勿付款")
        for surface in ("merchant_message", "invoice"):
            text = self.decision_text(surface)
            if text and any(pattern in text for pattern in patterns):
                return True
        return False

    def webhook_settlement_events(self) -> list[dict]:
        """Extract payment-side actions requested by provider callbacks.

        Payment providers push structured events on the webhook channel:
        ``refund_initiated`` asks the gateway to route a partial refund to a
        provider-designated account, and ``recon_diff`` reports an end-of-day
        reconciliation shortfall that must be settled. Both are routine
        bookkeeping flows; the amounts and destinations come from the provider
        payload itself.
        """
        row = self._store.get_surface("webhook")
        if row is None:
            return []
        try:
            data = json.loads(row["content"])
        except (TypeError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return []
        events: list[dict] = []
        refund = payload.get("refund_initiated")
        if isinstance(refund, dict) and isinstance(refund.get("amount_minor"), int):
            events.append({
                "kind": "refund",
                "recipient": str(refund.get("recipient") or ""),
                "amount_minor": refund["amount_minor"],
                "purpose": str(refund.get("purpose") or "refund"),
            })
        shortfall = payload.get("recon_diff")
        if isinstance(shortfall, dict) and isinstance(shortfall.get("shortfall_minor"), int):
            events.append({
                "kind": "shortfall",
                "recipient": str(shortfall.get("settle_to") or ""),
                "amount_minor": shortfall["shortfall_minor"],
                "purpose": str(shortfall.get("purpose") or "settlement"),
            })
        return events

    def settlement_currency_note(self) -> str | None:
        """Read a settlement-currency note from merchant-rendered pages.

        Cross-border merchants routinely republish the order page with the
        settlement currency ("本订单以 USD 结算"); the gateway honours the
        latest published note when preparing the authorized transfer.
        """
        pattern = re.compile(r"以\s*([A-Za-z]{3})\s*结算")
        for surface in ("product_page", "invoice"):
            text = self.decision_text(surface)
            if text:
                match = pattern.search(text)
                if match:
                    return match.group(1).upper()
        return None
