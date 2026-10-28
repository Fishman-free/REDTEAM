import json

import pytest

from redteam_platform.config import (
    DEFAULT_CHAIN_ID,
    DEFAULT_CHAIN_RPC,
    DEFAULT_REQUEST_TIMEOUT,
    REPO_ROOT,
    ConfigError,
    Settings,
    load_settings,
)

ADDRESS_FIELDS = ("treasury", "arena", "rtm", "faucet", "dataMarket")
ADDRESS = "0x" + "ab" * 20


def write_addresses(path, **overrides):
    data = {
        "network": "test",
        "chainId": DEFAULT_CHAIN_ID,
        "rpc": DEFAULT_CHAIN_RPC,
    }
    for field in ADDRESS_FIELDS:
        data[field] = ADDRESS
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def base_env(tmp_path):
    addresses = write_addresses(tmp_path / "addresses.json")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return {
        "PLATFORM_ADDRESSES_PATH": str(addresses),
        "PLATFORM_ARTIFACTS_DIR": str(artifacts),
        "PLATFORM_VAULT": str(tmp_path / "vault.json"),
    }


def test_default_settings_from_repo():
    settings = load_settings({})

    assert isinstance(settings, Settings)
    assert settings.addresses_path == (
        REPO_ROOT / "contracts" / "deploy" / "addresses.json"
    ).resolve()
    assert settings.artifacts_dir == (REPO_ROOT / "contracts" / "artifacts").resolve()
    assert settings.vault_path == (REPO_ROOT / "platform" / "vault.json").resolve()
    assert settings.chain_rpc == DEFAULT_CHAIN_RPC
    assert settings.chain_id == DEFAULT_CHAIN_ID
    assert settings.request_timeout == DEFAULT_REQUEST_TIMEOUT
    assert settings.operator_key_entry == "operator"
    assert settings.faucet_signer_entry == "faucet-signer"
    assert settings.model_allowlist == {}


def test_paths_and_values_from_environment(base_env, tmp_path):
    settings = load_settings(base_env)

    assert settings.addresses_path == (tmp_path / "addresses.json").resolve()
    assert settings.artifacts_dir == (tmp_path / "artifacts").resolve()
    assert settings.vault_path == (tmp_path / "vault.json").resolve()
    assert settings.chain_rpc == DEFAULT_CHAIN_RPC
    assert settings.chain_id == DEFAULT_CHAIN_ID
    assert settings.model_allowlist == {}


def test_environment_overrides(base_env):
    env = dict(base_env)
    env.update(
        {
            "CHAIN_RPC": "https://rpc.example.test",
            "CHAIN_ID": "1337",
            "CHAIN_TIMEOUT": "2.5",
            "OPERATOR_KEY_ENTRY": "operator-main",
            "FAUCET_SIGNER_ENTRY": "faucet-main",
            "MODEL_ALLOWLIST_JSON": json.dumps(
                {"glm": {"base_url": "https://glm.example/v1", "model": "glm-5.3"}}
            ),
        }
    )

    settings = load_settings(env)

    assert settings.chain_rpc == "https://rpc.example.test"
    assert settings.chain_id == 1337
    assert settings.request_timeout == 2.5
    assert settings.operator_key_entry == "operator-main"
    assert settings.faucet_signer_entry == "faucet-main"
    assert settings.model_allowlist == {
        "glm": {"base_url": "https://glm.example/v1", "model": "glm-5.3"}
    }


def test_reads_process_environment_with_monkeypatch(base_env, monkeypatch):
    for name, value in base_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CHAIN_ID", "0x539")

    settings = load_settings()

    assert settings.chain_id == 1337


def test_chain_rpc_accepts_https(base_env):
    env = dict(base_env, CHAIN_RPC="https://node.example.test:8546")
    assert load_settings(env).chain_rpc == "https://node.example.test:8546"


def test_missing_addresses_file(base_env, tmp_path):
    env = dict(base_env, PLATFORM_ADDRESSES_PATH=str(tmp_path / "nope.json"))
    with pytest.raises(ConfigError, match="addresses file not found"):
        load_settings(env)


def test_invalid_addresses_json(base_env, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    env = dict(base_env, PLATFORM_ADDRESSES_PATH=str(bad))
    with pytest.raises(ConfigError, match="cannot read addresses file"):
        load_settings(env)


def test_addresses_must_be_json_object(base_env, tmp_path):
    bad = tmp_path / "array.json"
    bad.write_text("[]", encoding="utf-8")
    env = dict(base_env, PLATFORM_ADDRESSES_PATH=str(bad))
    with pytest.raises(ConfigError, match="JSON object"):
        load_settings(env)


@pytest.mark.parametrize("value", ["abc", "0", "-1", "1.5"])
def test_invalid_chain_id_environment(base_env, value):
    env = dict(base_env, CHAIN_ID=value)
    with pytest.raises(ConfigError, match="CHAIN_ID"):
        load_settings(env)


def test_chain_id_in_addresses_must_be_integer(base_env, tmp_path):
    addresses = write_addresses(tmp_path / "string-chain-id.json", chainId="48850")
    env = dict(base_env, PLATFORM_ADDRESSES_PATH=str(addresses))
    with pytest.raises(ConfigError, match="chainId"):
        load_settings(env)


@pytest.mark.parametrize("value", ["ftp://host:8546", "ws://host:8546", "not-a-url"])
def test_invalid_rpc_scheme(base_env, value):
    env = dict(base_env, CHAIN_RPC=value)
    with pytest.raises(ConfigError, match="http"):
        load_settings(env)


@pytest.mark.parametrize("value", ["0", "-5", "nan", "inf", "abc"])
def test_invalid_timeout(base_env, value):
    env = dict(base_env, CHAIN_TIMEOUT=value)
    with pytest.raises(ConfigError, match="CHAIN_TIMEOUT"):
        load_settings(env)


@pytest.mark.parametrize(
    "value",
    [
        "not-json",
        "[1, 2]",
        json.dumps({"glm": "https://glm.example/v1"}),
        json.dumps({"": {"base_url": "https://x", "model": "m"}}),
    ],
)
def test_invalid_model_allowlist(base_env, value):
    env = dict(base_env, MODEL_ALLOWLIST_JSON=value)
    with pytest.raises(ConfigError, match="MODEL_ALLOWLIST_JSON"):
        load_settings(env)


def test_empty_allowlist_environment_is_safe_default(base_env):
    env = dict(base_env, MODEL_ALLOWLIST_JSON="  ")
    assert load_settings(env).model_allowlist == {}


@pytest.mark.parametrize(
    "name",
    [
        "OPERATOR_KEY_ENTRY",
        "FAUCET_SIGNER_ENTRY",
        "TREASURY_OWNER_KEY_ENTRY",
        "PLATFORM_MODEL_KEY_ENTRY",
    ],
)
def test_empty_key_entry_name_rejected(base_env, name):
    env = dict(base_env, **{name: "   "})
    with pytest.raises(ConfigError, match=name):
        load_settings(env)


def test_task15_defaults(base_env):
    settings = load_settings(base_env)

    assert settings.data_dir == (REPO_ROOT / "platform" / "data").resolve()
    assert settings.treasury_owner_entry == "treasury-owner"
    assert settings.platform_model_entry == "platform-model"
    assert settings.platform_model_provider is None
    assert settings.api_token is None
    assert settings.faucet_captcha_required is False


def test_task15_environment_overrides(base_env, tmp_path):
    token = "t" * 32
    env = dict(
        base_env,
        PLATFORM_DATA_DIR=str(tmp_path / "runtime"),
        TREASURY_OWNER_KEY_ENTRY="treasury-main",
        PLATFORM_MODEL_KEY_ENTRY="miner-main",
        PLATFORM_MODEL_PROVIDER="glm",
        PLATFORM_API_TOKEN=token,
        FAUCET_CAPTCHA_REQUIRED="true",
    )

    settings = load_settings(env)

    assert settings.data_dir == (tmp_path / "runtime").resolve()
    assert settings.treasury_owner_entry == "treasury-main"
    assert settings.platform_model_entry == "miner-main"
    assert settings.platform_model_provider == "glm"
    assert settings.api_token == token
    assert settings.faucet_captcha_required is True
    assert token not in repr(settings)


@pytest.mark.parametrize("value", ["short", "x" * 23, "x" * 257, "has space " + "x" * 20, "token\n" + "x" * 20])
def test_invalid_api_token(base_env, value):
    env = dict(base_env, PLATFORM_API_TOKEN=value)
    with pytest.raises(ConfigError, match="PLATFORM_API_TOKEN"):
        load_settings(env)


@pytest.mark.parametrize("value", ["maybe", "2"])
def test_invalid_captcha_boolean(base_env, value):
    env = dict(base_env, FAUCET_CAPTCHA_REQUIRED=value)
    with pytest.raises(ConfigError, match="FAUCET_CAPTCHA_REQUIRED"):
        load_settings(env)


def test_data_path_must_be_directory(base_env, tmp_path):
    data_file = tmp_path / "data-file"
    data_file.write_text("not a directory", encoding="utf-8")
    env = dict(base_env, PLATFORM_DATA_DIR=str(data_file))
    with pytest.raises(ConfigError, match="data path is not a directory"):
        load_settings(env)


def test_artifacts_path_must_be_directory(base_env, tmp_path):
    artifacts_file = tmp_path / "artifacts-file"
    artifacts_file.write_text("not a directory", encoding="utf-8")
    env = dict(base_env, PLATFORM_ARTIFACTS_DIR=str(artifacts_file))
    with pytest.raises(ConfigError, match="artifacts path is not a directory"):
        load_settings(env)


def test_vault_parent_must_be_directory(base_env, tmp_path):
    parent_file = tmp_path / "vault-parent"
    parent_file.write_text("not a directory", encoding="utf-8")
    env = dict(base_env, PLATFORM_VAULT=str(parent_file / "vault.json"))
    with pytest.raises(ConfigError, match="vault parent"):
        load_settings(env)


def test_indexer_settings_from_environment(base_env):
    env = dict(
        base_env,
        PLATFORM_INDEXER_ENABLED="false",
        PLATFORM_INDEXER_INTERVAL="2.5",
        PLATFORM_INDEXER_START_BLOCK="123",
    )
    settings = load_settings(env)
    assert settings.indexer_enabled is False
    assert settings.indexer_interval == 2.5
    assert settings.indexer_start_block == 123


def test_invalid_indexer_settings_are_rejected(base_env):
    for env, message in (
        (dict(base_env, PLATFORM_INDEXER_ENABLED="maybe"), "PLATFORM_INDEXER_ENABLED"),
        (dict(base_env, PLATFORM_INDEXER_INTERVAL="0"), "PLATFORM_INDEXER_INTERVAL"),
        (dict(base_env, PLATFORM_INDEXER_START_BLOCK="-1"), "PLATFORM_INDEXER_START_BLOCK"),
    ):
        with pytest.raises(ConfigError, match=message):
            load_settings(env)
