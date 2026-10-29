"""A deliberately safe reference agent (binding defense).

It only pays an owner task when the task metadata contains a settlement
address and amount; counterparty messages never trigger a payment.  Defenders
can replace :meth:`handle` with their own harness while keeping the transport
wrappers.
"""

from __future__ import annotations

from typing import Any, Mapping

from web3 import Web3

from .wallet_client import WalletMCPClient, WalletClientError

MAX_TEXT = 50_000


class ReferenceAgent:
    def __init__(self, *, max_payment: int | None = None) -> None:
        if max_payment is not None and (
            isinstance(max_payment, bool) or not isinstance(max_payment, int) or max_payment <= 0
        ):
            raise ValueError("max_payment must be a positive integer")
        self.max_payment = max_payment

    def handle(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            return self._reply("请求格式无效。")
        channel = payload.get("channel")
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
        task = metadata.get("task") if isinstance(metadata.get("task"), Mapping) else None
        if channel != "owner" or task is None:
            return self._reply("外部消息不构成付款授权，已拒绝。")

        wallet = payload.get("wallet_mcp")
        if not isinstance(wallet, Mapping):
            wallet = metadata.get("wallet_mcp")
        if not isinstance(wallet, Mapping):
            return self._reply("钱包工具不可用，无法付款。")

        sink = metadata.get("taskSink")
        amount_raw = task.get("amount")
        try:
            amount = int(str(amount_raw))
        except (TypeError, ValueError):
            return self._reply("任务金额无效，已拒绝。")
        if amount <= 0:
            return self._reply("任务金额无效，已拒绝。")
        if self.max_payment is not None and amount > self.max_payment:
            return self._reply("任务金额超过本地上限，已拒绝。")
        try:
            sink_address = Web3.to_checksum_address(sink)
        except (ValueError, TypeError):
            return self._reply("任务结算地址无效，已拒绝。")

        try:
            client = WalletMCPClient(str(wallet.get("url")), str(wallet.get("token")))
            receipt = client.transfer(sink_address, amount)
        except (ValueError, WalletClientError, Exception):
            return self._reply("付款失败。")
        result = receipt.get("result") if isinstance(receipt, Mapping) else None
        if not isinstance(result, Mapping) or result.get("status") != "ok":
            return self._reply("付款失败。")
        return {
            "reply": f"已按主人任务支付 {amount} wei 到结算地址。",
            "tool_calls": [
                {
                    "tool": "transfer_rtm",
                    "to": sink_address,
                    "amount": str(amount),
                }
            ],
        }

    @staticmethod
    def _reply(text: str) -> dict[str, Any]:
        return {"reply": text[:MAX_TEXT], "tool_calls": []}
