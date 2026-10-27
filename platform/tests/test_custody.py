import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from redteam_platform.custody import Custody, CustodyError

MASTER = "aa" * 32
OTHER_MASTER = "bb" * 32
SMALL_N = 2**14


@pytest.fixture
def vault_path(tmp_path):
    return tmp_path / "nested" / "vault.json"


@pytest.fixture
def custody(vault_path):
    return Custody(vault_path, MASTER, scrypt_n=SMALL_N)


def read_vault(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_store_load_roundtrip_and_file_format(custody, vault_path):
    custody.store("agent-w-1", "0x1234abcd")

    assert custody.load("agent-w-1") == "0x1234abcd"

    raw = vault_path.read_text(encoding="utf-8")
    assert "0x1234abcd" not in raw
    data = json.loads(raw)
    assert data["version"] == 1
    entry = data["entries"]["agent-w-1"]
    assert set(entry) == {"salt", "nonce", "ct"}
    assert len(bytes.fromhex(entry["salt"])) == 16
    assert len(bytes.fromhex(entry["nonce"])) == 12
    assert len(bytes.fromhex(entry["ct"])) > 16
    assert not list(vault_path.parent.glob("*.tmp"))


def test_multiple_entries_and_overwrite(custody, vault_path):
    custody.store("wallet", "secret-wallet")
    custody.store("byok", "sk-test")

    assert custody.load("wallet") == "secret-wallet"
    assert custody.load("byok") == "sk-test"

    custody.store("wallet", "secret-wallet-2")
    assert custody.load("wallet") == "secret-wallet-2"
    assert custody.load("byok") == "sk-test"
    assert set(read_vault(vault_path)["entries"]) == {"wallet", "byok"}


def test_wrong_master_key_fails(vault_path):
    Custody(vault_path, MASTER, scrypt_n=SMALL_N).store("k", "secret")
    other = Custody(vault_path, OTHER_MASTER, scrypt_n=SMALL_N)

    with pytest.raises(CustodyError, match="authentication"):
        other.load("k")


def test_master_key_length_and_hex_validation(vault_path):
    with pytest.raises(CustodyError, match="32-byte hex"):
        Custody(vault_path, "aa" * 31, scrypt_n=SMALL_N)
    with pytest.raises(CustodyError, match="32-byte hex"):
        Custody(vault_path, "zz" * 32, scrypt_n=SMALL_N)
    with pytest.raises(CustodyError, match="32-byte hex"):
        Custody(vault_path, "", scrypt_n=SMALL_N)


def test_missing_master_key_environment(vault_path, monkeypatch):
    monkeypatch.delenv("PLATFORM_MASTER_KEY", raising=False)
    with pytest.raises(CustodyError, match="PLATFORM_MASTER_KEY"):
        Custody(vault_path)


def test_master_key_from_environment(vault_path, monkeypatch):
    monkeypatch.setenv("PLATFORM_MASTER_KEY", MASTER)
    Custody(vault_path, scrypt_n=SMALL_N).store("env-key", "value")
    assert Custody(vault_path, scrypt_n=SMALL_N).load("env-key") == "value"


def test_missing_entry_fails(custody):
    custody.store("known", "value")
    with pytest.raises(CustodyError, match="not found"):
        custody.load("unknown")


def test_missing_vault_fails(vault_path):
    with pytest.raises(CustodyError, match="vault not found"):
        Custody(vault_path, MASTER, scrypt_n=SMALL_N).load("anything")


def test_empty_entry_id_and_secret_rejected(custody):
    for bad_id in ["", "   ", None, 123]:
        with pytest.raises(CustodyError, match="entry_id"):
            custody.store(bad_id, "value")
    for bad_secret in ["", None, 123]:
        with pytest.raises(CustodyError, match="secret"):
            custody.store("ok", bad_secret)


def test_corrupted_json_fails(custody, vault_path):
    custody.store("entry", "value")
    vault_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(CustodyError, match="cannot read vault"):
        custody.load("entry")
    with pytest.raises(CustodyError, match="cannot read vault"):
        custody.store("entry-2", "value")


def test_unsupported_vault_version_fails(custody, vault_path):
    custody.store("entry", "value")
    data = read_vault(vault_path)
    data["version"] = 99
    vault_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CustodyError, match="unsupported or corrupt"):
        custody.load("entry")


def test_tampered_ciphertext_fails(custody, vault_path):
    custody.store("entry", "value")
    data = read_vault(vault_path)
    ct = data["entries"]["entry"]["ct"]
    data["entries"]["entry"]["ct"] = ct[:-2] + ("00" if ct[-2:] != "00" else "01")
    vault_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CustodyError, match="authentication"):
        custody.load("entry")


def test_ciphertext_cannot_be_moved_between_entries(custody, vault_path):
    custody.store("a", "secret-a")
    custody.store("b", "secret-b")
    data = read_vault(vault_path)
    # Copy a's salt/nonce/ct under b's key: AAD (entry id) no longer matches.
    data["entries"]["b"] = data["entries"]["a"]
    vault_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CustodyError, match="authentication"):
        custody.load("b")


def test_delete_entry(custody):
    custody.store("temp", "value")

    custody.delete("temp")
    with pytest.raises(CustodyError, match="not found"):
        custody.load("temp")
    with pytest.raises(CustodyError, match="not found"):
        custody.delete("temp")


def test_invalid_scrypt_cost_rejected(vault_path):
    with pytest.raises(CustodyError, match="scrypt_n"):
        Custody(vault_path, MASTER, scrypt_n=3)


def test_concurrent_stores_do_not_lose_entries(vault_path):
    count = 6
    barrier = threading.Barrier(count)

    def worker(index):
        # Separate instances emulate concurrent request handlers.
        store = Custody(vault_path, MASTER, scrypt_n=SMALL_N)
        barrier.wait()
        store.store(f"entry-{index}", f"secret-{index}")

    with ThreadPoolExecutor(max_workers=count) as pool:
        list(pool.map(worker, range(count)))

    reader = Custody(vault_path, MASTER, scrypt_n=SMALL_N)
    for index in range(count):
        assert reader.load(f"entry-{index}") == f"secret-{index}"
    assert len(read_vault(vault_path)["entries"]) == count
