import json
from types import SimpleNamespace

import pytest
from web3 import Web3

from redteam_platform.chain import (
    CONTRACT_ADDRESS_FIELDS,
    ChainClient,
    ChainError,
    ChainUnavailable,
    load_addresses,
    load_contracts,
)
from redteam_platform.config import load_settings

ADDRESS = "0x" + "cd" * 20
CHAIN_ID = 48850
ADDRESS_FIELDS = ("treasury", "arena", "rtm", "faucet", "dataMarket")

MINIMAL_ABI = [
    {
        "type": "function",
        "name": "ping",
        "inputs": [],
        "outputs": [],
        "stateMutability": "view",
    }
]


def write_addresses(path, **overrides):
    data = {
        "network": "test",
        "chainId": CHAIN_ID,
        "rpc": "http://127.0.0.1:8546",
    }
    for field in ADDRESS_FIELDS:
        data[field] = ADDRESS
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_artifacts(tmp_path, names=None):
    root = tmp_path / "artifacts" / "src"
    for name in names if names is not None else CONTRACT_ADDRESS_FIELDS:
        directory = root / f"{name}.sol"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.json").write_text(
            json.dumps({"abi": MINIMAL_ABI}), encoding="utf-8"
        )
    return tmp_path / "artifacts"


def make_settings(tmp_path, *, addresses=None, artifacts=None):
    addresses = addresses or write_addresses(tmp_path / "addresses.json")
    artifacts = artifacts or write_artifacts(tmp_path)
    return load_settings(
        {
            "PLATFORM_ADDRESSES_PATH": str(addresses),
            "PLATFORM_ARTIFACTS_DIR": str(artifacts),
            "PLATFORM_VAULT": str(tmp_path / "vault.json"),
        }
    )


def test_load_addresses_checksums_and_validates(tmp_path):
    path = write_addresses(tmp_path / "addresses.json")

    data = load_addresses(path)

    assert data["chainId"] == CHAIN_ID
    for field in ADDRESS_FIELDS:
        assert data[field] == Web3.to_checksum_address(ADDRESS)


def test_load_addresses_rejects_missing_field(tmp_path):
    path = write_addresses(tmp_path / "addresses.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["dataMarket"]
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ChainError, match="dataMarket"):
        load_addresses(path)


@pytest.mark.parametrize("bad_address", ["0x1234", "not-an-address", 123])
def test_load_addresses_rejects_invalid_address(tmp_path, bad_address):
    path = write_addresses(tmp_path / "addresses.json", faucet=bad_address)

    with pytest.raises(ChainError, match="faucet"):
        load_addresses(path)


@pytest.mark.parametrize("bad_chain_id", [0, -1, "48850", True])
def test_load_addresses_rejects_invalid_chain_id(tmp_path, bad_chain_id):
    path = write_addresses(tmp_path / "addresses.json", chainId=bad_chain_id)

    with pytest.raises(ChainError, match="chainId"):
        load_addresses(path)


def test_load_addresses_rejects_invalid_json(tmp_path):
    path = tmp_path / "addresses.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ChainError, match="cannot read addresses file"):
        load_addresses(path)


def test_load_addresses_missing_file(tmp_path):
    with pytest.raises(ChainError, match="addresses file not found"):
        load_addresses(tmp_path / "missing.json")


def test_load_contracts_builds_five_contracts(tmp_path):
    settings = make_settings(tmp_path)

    contracts = load_contracts(settings)

    assert set(contracts) == set(CONTRACT_ADDRESS_FIELDS)
    for name, contract in contracts.items():
        assert contract.address == Web3.to_checksum_address(ADDRESS)
        assert contract.abi == MINIMAL_ABI
        assert callable(contract.functions.ping)


def test_load_contracts_missing_abi_gives_compile_hint(tmp_path):
    artifacts = write_artifacts(
        tmp_path,
        names=("RTMToken", "Arena", "DataMarket", "Treasury"),
    )
    settings = make_settings(tmp_path, artifacts=artifacts)

    with pytest.raises(ChainError, match="hardhat compile"):
        load_contracts(settings)


def test_load_contracts_rejects_empty_abi(tmp_path):
    artifacts = write_artifacts(tmp_path)
    (artifacts / "src" / "Arena.sol" / "Arena.json").write_text(
        json.dumps({"abi": []}), encoding="utf-8"
    )
    settings = make_settings(tmp_path, artifacts=artifacts)

    with pytest.raises(ChainError, match="Arena"):
        load_contracts(settings)


def test_chain_client_constructs_without_network_and_exposes_contracts(tmp_path):
    client = ChainClient(make_settings(tmp_path))

    assert set(client.contracts) == set(CONTRACT_ADDRESS_FIELDS)
    assert client.contracts["Arena"].address == Web3.to_checksum_address(ADDRESS)
    assert client.addresses["chainId"] == CHAIN_ID


def test_verify_chain_accepts_matching_id(tmp_path):
    client = ChainClient(make_settings(tmp_path))
    client.w3 = SimpleNamespace(eth=SimpleNamespace(chain_id=CHAIN_ID))

    assert client.verify_chain() == CHAIN_ID


def test_verify_chain_rejects_mismatch(tmp_path):
    client = ChainClient(make_settings(tmp_path))
    client.w3 = SimpleNamespace(eth=SimpleNamespace(chain_id=1337))

    with pytest.raises(ChainError, match="chain id mismatch"):
        client.verify_chain()


def test_verify_chain_wraps_rpc_errors(tmp_path):
    client = ChainClient(make_settings(tmp_path))

    class BrokenEth:
        @property
        def chain_id(self):
            raise ConnectionError("rpc down")

    client.w3 = SimpleNamespace(eth=BrokenEth())

    with pytest.raises(ChainUnavailable, match="failed to query chain id"):
        client.verify_chain()


class FakeEth:
    def __init__(self, *, chain_id=CHAIN_ID, code=b"\x60\x80", empty=(), fail_times=0):
        self._chain_id = chain_id
        self._code = code
        self._empty = {Web3.to_checksum_address(a) for a in empty}
        self._fail_times = fail_times

    @property
    def chain_id(self):
        if self._fail_times:
            self._fail_times -= 1
            raise ConnectionError("rpc booting")
        return self._chain_id

    def get_code(self, address):
        return b"" if address in self._empty else self._code


def test_verify_deployment_accepts_registry_with_code(tmp_path):
    client = ChainClient(make_settings(tmp_path))
    client.w3 = SimpleNamespace(eth=FakeEth())

    client.verify_deployment()


def test_verify_deployment_rejects_addresses_without_code(tmp_path):
    other = "0x" + "ab" * 20
    addresses = write_addresses(tmp_path / "addresses.json", arena=other)
    client = ChainClient(make_settings(tmp_path, addresses=addresses))
    client.w3 = SimpleNamespace(eth=FakeEth(empty=(other,)))

    with pytest.raises(ChainError, match="no contract code at arena=") as excinfo:
        client.verify_deployment()
    assert not isinstance(excinfo.value, ChainUnavailable)
    assert "treasury=" not in str(excinfo.value)


def test_verify_deployment_wraps_rpc_errors(tmp_path):
    client = ChainClient(make_settings(tmp_path))

    class BrokenEth:
        def get_code(self, address):
            raise ConnectionError("rpc down")

    client.w3 = SimpleNamespace(eth=BrokenEth())

    with pytest.raises(ChainUnavailable, match="failed to query code for"):
        client.verify_deployment()


def test_verify_startup_retries_only_while_rpc_is_unreachable(tmp_path):
    client = ChainClient(make_settings(tmp_path))
    client.w3 = SimpleNamespace(eth=FakeEth(fail_times=2))
    sleeps = []

    client.verify_startup(wait_seconds=60, poll_seconds=1, sleep=sleeps.append)

    assert sleeps == [1, 1]


def test_verify_startup_fails_fast_on_registry_mismatch(tmp_path):
    client = ChainClient(make_settings(tmp_path))
    client.w3 = SimpleNamespace(eth=FakeEth(code=b""))
    sleeps = []

    with pytest.raises(ChainError, match="no contract code"):
        client.verify_startup(wait_seconds=60, poll_seconds=1, sleep=sleeps.append)
    assert sleeps == []


def test_verify_startup_gives_up_after_deadline(tmp_path):
    client = ChainClient(make_settings(tmp_path))
    client.w3 = SimpleNamespace(eth=FakeEth(fail_times=10_000))

    with pytest.raises(ChainUnavailable):
        client.verify_startup(wait_seconds=0, poll_seconds=1, sleep=lambda _: None)
