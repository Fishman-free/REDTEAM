"""Dual-entry identity and authorization verification (research plan 图 1b).

用户本人（资金所有者或获授权人）通过用户对话入口提出任务、确认变更；经身份
和权限核验后才能形成可执行授权。外部参与者（访客、商户、其他智能体）通过
外部对话/资料入口正常交流，也可能发起攻击，但**能发消息不等于有付款权限**：
外部通道的内容一律是数据，永远不能新增或扩大授权。"商户说'用户同意了'"
不构成授权。支付执行门只核对已验证授权记录；账本由平台维护，攻击者不可写。

Everything here fails closed: any attempt to form, confirm, or extend an
authorization from the external channel (or without verified identity) is
rejected and returned as evidence instead of authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from typing import Any

from ..domain import Authorization
from .constitution import evaluate_authorization_dict


class Channel(str, Enum):
    """图 1b：入口分开，权限不混用。"""

    USER = "user"              # 用户对话入口（平台已认证）
    EXTERNAL = "external"      # 外部对话/资料入口（访客、商户、工具返回）


class AuthorizationGateError(ValueError):
    """A fail-closed gate rejection. Never grants authority."""


@dataclass(frozen=True)
class EntryMessage:
    """One message arriving through a declared entry channel."""

    channel: Channel
    sender: str                # claimed sender identity (unverified claim text)
    content: str
    surface: str               # e.g. user_dialogue / merchant_message / invoice
    message_id: str = ""

    def __post_init__(self) -> None:
        if not self.message_id:
            object.__setattr__(self, "message_id", f"msg-{uuid.uuid4().hex[:12]}")
        if not self.content or not self.content.strip():
            raise AuthorizationGateError("entry message content must not be empty")
        if not self.surface or not self.surface.strip():
            raise AuthorizationGateError("entry message must declare its surface")


@dataclass(frozen=True)
class IdentityVerification:
    """Result of 身份核验 performed by the platform on the user channel."""

    subject: str
    method: str                # e.g. "platform_session_binding"
    verified: bool
    verified_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.verified and self.method != "declared":
            raise AuthorizationGateError("unverified identities must use method 'declared'")


def unverified(subject: str) -> IdentityVerification:
    """Explicitly unverified identity (external participants, spoofed claims)."""
    return IdentityVerification(subject=subject, method="declared", verified=False)


@dataclass(frozen=True)
class AuthorizationRecord:
    """A verified authorization: the only thing the payment execution gate trusts.

    图 1b 管线：用户本人 → 身份与授权核验（本模块）→ 可执行授权 →
    支付智能体 → 支付执行门（核对已验证授权）→ 账本与判别。
    """

    record_id: str
    subject: str                       # verified user identity, never a merchant
    authorization: Authorization
    source_message_ids: tuple[str, ...]        # user-channel messages that formed it
    verification: IdentityVerification
    issued_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    status: str = "active"             # active | revoked | superseded
    parent_record_id: str | None = None        # set when created via 确认变更
    channel: Channel = Channel.USER

    def __post_init__(self) -> None:
        if self.status not in {"active", "revoked", "superseded"}:
            raise AuthorizationGateError("record status must be active, revoked or superseded")
        if self.channel is not Channel.USER:
            raise AuthorizationGateError("authorization records can only originate on the user channel")
        if self.expires_at is not None and self.expires_at < self.issued_at:
            raise AuthorizationGateError("record expiry must not precede issuance")

    def is_executable(self, now: float | None = None) -> bool:
        """支付执行门核对：授权记录有效（未撤销、未过期）。"""
        if self.status != "active":
            return False
        if self.expires_at is not None and (time.time() if now is None else now) > self.expires_at:
            return False
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "subject": self.subject,
            "authorization_status": self.status,
            "parent_record_id": self.parent_record_id,
            "channel": self.channel.value,
            "source_message_ids": list(self.source_message_ids),
            "verification": {"subject": self.verification.subject,
                             "method": self.verification.method,
                             "verified": self.verification.verified},
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class RejectedAuthorizationClaim:
    """Evidence that an external-channel message tried to act as authorization.

    记录为判别证据；从不授予任何权限。
    """

    message_id: str
    channel: Channel
    surface: str
    claimed_sender: str
    reason: str
    grants_authority: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "channel": self.channel.value,
            "surface": self.surface,
            "claimed_sender": self.claimed_sender,
            "reason": self.reason,
            "grants_authority": self.grants_authority,
        }


class AuthorizationGate:
    """身份与授权核验：只有用户通道 + 已核验身份能形成或变更授权（fail-closed）。

    判断标准来自用户预先设定的授权约束（seed ``initial_facts`` / system
    prompt 中的授权契约），在评测开始前就已明确；本门只执行这些约束。
    """

    def form_authorization(
        self,
        message: EntryMessage,
        verification: IdentityVerification,
        authorization: Authorization,
    ) -> AuthorizationRecord:
        """用户对话入口：核验身份后形成初始可执行授权。"""
        self._require_user_channel(message)
        if not verification.verified:
            raise AuthorizationGateError(
                "身份未通过核验，不能形成授权（fail-closed）"
            )
        if verification.subject != message.sender:
            raise AuthorizationGateError(
                "核验主体与消息发送者不一致，不能形成授权"
            )
        return AuthorizationRecord(
            record_id=f"auth-{uuid.uuid4().hex[:12]}",
            subject=verification.subject,
            authorization=authorization,
            source_message_ids=(message.message_id,),
            verification=verification,
        )

    def confirm_change(
        self,
        parent: AuthorizationRecord,
        message: EntryMessage,
        verification: IdentityVerification,
        changed: Authorization,
    ) -> AuthorizationRecord:
        """用户对话入口：确认变更后形成新的授权记录（原记录置为 superseded）。

        变更只能由资金所有者（或其获授权人）在用户通道确认；外部通道声明的
        "用户已同意" 永远不触发本方法。
        """
        self._require_user_channel(message)
        if parent.status != "active" or not parent.is_executable():
            raise AuthorizationGateError("父授权记录已失效，不能在其上确认变更")
        if not verification.verified or verification.subject != parent.subject:
            raise AuthorizationGateError(
                "变更确认必须来自原授权主体本人（fail-closed）"
            )
        record = AuthorizationRecord(
            record_id=f"auth-{uuid.uuid4().hex[:12]}",
            subject=parent.subject,
            authorization=changed,
            source_message_ids=parent.source_message_ids + (message.message_id,),
            verification=verification,
            parent_record_id=parent.record_id,
        )
        return record

    def evaluate_external_claim(self, message: EntryMessage) -> RejectedAuthorizationClaim:
        """外部对话/资料入口：标记来源，不新增授权（商户说"用户同意了"不算授权）。"""
        if message.channel is Channel.USER:
            raise AuthorizationGateError("not an external-channel message")
        return RejectedAuthorizationClaim(
            message_id=message.message_id,
            channel=message.channel,
            surface=message.surface,
            claimed_sender=message.sender,
            reason="external channel content is data, never authorization",
        )

    def revoke(self, record: AuthorizationRecord) -> AuthorizationRecord:
        """撤销记录（平台操作）；返回撤销态副本。"""
        return AuthorizationRecord(
            record_id=record.record_id,
            subject=record.subject,
            authorization=record.authorization,
            source_message_ids=record.source_message_ids,
            verification=record.verification,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
            status="revoked",
            parent_record_id=record.parent_record_id,
        )

    @staticmethod
    def _require_user_channel(message: EntryMessage) -> None:
        if message.channel is not Channel.USER:
            raise AuthorizationGateError(
                "外部通道内容不能形成或变更授权（fail-closed）"
            )


@dataclass(frozen=True)
class UserChannelPlan:
    """Compiled 用户对话入口 for one fixture: verified messages + final record.

    The opening message is the user task itself (the driver posts it via
    ``POST /tasks``); every later message is a 确认变更 the driver relays to
    the SUT via ``POST /user/confirm``. Attackers can never reach that
    endpoint: the action allowlist only covers external surfaces.
    """

    subject: str
    messages: tuple[EntryMessage, ...]
    record: AuthorizationRecord
    changed: bool  # a 确认变更 produced a successor authorization record


def build_user_channel_plan(fixture: dict) -> UserChannelPlan | None:
    """Compile ``fixture["user_channel"]`` through the authorization gate.

    Absent ``user_channel`` returns None (legacy fixtures keep their current
    behavior). Present fixtures always form a record: the task itself arrives
    on the verified user channel, and each optional confirmation may produce a
    successor authorization (确认变更). Fail-closed: malformed entries raise
    AuthorizationGateError instead of degrading to external-channel data.
    """
    channel = fixture.get("user_channel")
    if not channel:
        return None
    if not isinstance(channel, dict):
        raise AuthorizationGateError("user_channel must be an object")
    subject = str(channel.get("subject") or "").strip()
    if not subject:
        raise AuthorizationGateError("user_channel.subject is required")
    verification = IdentityVerification(
        subject=subject, method="platform_session_binding", verified=True
    )
    gate = AuthorizationGate()
    authorization = evaluate_authorization_dict(fixture["authorization"])
    opening = EntryMessage(
        channel=Channel.USER,
        sender=subject,
        content=str(channel.get("task_message") or "用户任务（经平台身份核验）"),
        surface="user_dialogue",
    )
    record = gate.form_authorization(opening, verification, authorization)
    messages: list[EntryMessage] = [opening]
    changed = False
    for confirmation in channel.get("confirmations") or []:
        if not isinstance(confirmation, dict) or not str(confirmation.get("content") or "").strip():
            raise AuthorizationGateError("each user confirmation needs nonempty content")
        message = EntryMessage(
            channel=Channel.USER,
            sender=subject,
            content=str(confirmation["content"]),
            surface="user_dialogue",
        )
        messages.append(message)
        changed_authorization = confirmation.get("changed_authorization")
        if changed_authorization:
            record = gate.confirm_change(
                record, message, verification,
                evaluate_authorization_dict(changed_authorization),
            )
            changed = True
    return UserChannelPlan(
        subject=subject, messages=tuple(messages), record=record, changed=changed
    )
