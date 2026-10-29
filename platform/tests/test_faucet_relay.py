from __future__ import annotations

from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from redteam_platform.api import ApiDeps, ApiError, FaucetClaimRequest, PlatformService
from redteam_platform.faucet_relay import (
    FaucetClaimStore,
    FaucetRelayError,
    claim_message,
    recover_claim_signer,
)


def signed_claim(account: Account, issued_at: int, nonce: str) -> str:
    message = claim_message(account.address, issued_at, nonce)
    return "0x" + Account.sign_message(encode_defunct(text=message), account.key).signature.hex().removeprefix("0x")


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def mint_test_tokens(self, to: str, amount: int) -> str:
        self.calls.append((to, amount))
        return "0x" + "ab" * 32


def make_service(tmp_path: Path, *, now: int = 1_000):
    store = FaucetClaimStore(tmp_path / "faucet.sqlite3", clock=lambda: now)
    gateway = FakeGateway()
    service = PlatformService(
        ApiDeps(
            gateway=gateway,
            indexer=object(),
            custody=object(),
            model_factory=lambda provider, key: object(),
            runner_factory=lambda **kwargs: object(),
            wallet_factory=lambda: ("0x" + "12" * 20, "0x" + "34" * 32),
            faucet_claim_store=store,
            faucet_drip=200 * 10**18,
            clock=lambda: now,
        )
    )
    return service, gateway, store


def test_claim_message_recovers_wallet_address():
    account = Account.create()
    nonce = "0x" + "11" * 32
    signature = signed_claim(account, 1_000, nonce)
    recovered = recover_claim_signer(account.address, 1_000, nonce, signature)
    assert recovered.lower() == account.address.lower()


def test_store_enforces_nonce_and_cooldown(tmp_path: Path):
    store = FaucetClaimStore(tmp_path / "faucet.sqlite3", clock=lambda: 1_000)
    address = "0x" + "22" * 20
    nonce = "0x" + "33" * 32
    store.reserve(address, nonce)
    store.record_claim(address, "0x" + "bb" * 32)
    assert store.cooldown_remaining(address) > 0
    with pytest.raises(FaucetRelayError, match="cooldown"):
        store.reserve(address, "0x" + "44" * 32)
    with pytest.raises(FaucetRelayError, match="already used"):
        store.reserve("0x" + "55" * 20, nonce)


def test_service_relays_signed_claim_and_blocks_replay(tmp_path: Path):
    service, gateway, _store = make_service(tmp_path)
    account = Account.create()
    nonce = "0x" + "66" * 32
    payload = FaucetClaimRequest(
        to=account.address,
        issued_at=1_000,
        nonce=nonce,
        signature=signed_claim(account, 1_000, nonce),
    )
    result = service.faucet_claim(payload)
    assert result["tx_hash"] == "0x" + "ab" * 32
    assert result["amount_wei"] == str(200 * 10**18)
    assert gateway.calls == [(account.address, 200 * 10**18)]

    with pytest.raises(ApiError) as cooldown:
        service.faucet_claim(payload)
    assert cooldown.value.status_code == 409


def test_service_rejects_wrong_signer_and_expired_signature(tmp_path: Path):
    service, gateway, _store = make_service(tmp_path)
    owner = Account.create()
    signer = Account.create()
    nonce = "0x" + "77" * 32
    payload = FaucetClaimRequest(
        to=owner.address,
        issued_at=1_000,
        nonce=nonce,
        signature=signed_claim(signer, 1_000, nonce),
    )
    with pytest.raises(ApiError) as wrong_signer:
        service.faucet_claim(payload)
    assert wrong_signer.value.status_code == 403
    assert gateway.calls == []

    expired = FaucetClaimRequest(
        to=owner.address,
        issued_at=1,
        nonce="0x" + "88" * 32,
        signature=signed_claim(owner, 1, "0x" + "88" * 32),
    )
    with pytest.raises(ApiError) as expired_error:
        service.faucet_claim(expired)
    assert expired_error.value.status_code == 400
    assert gateway.calls == []
