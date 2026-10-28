"""Platform settings loaded from environment variables and the address registry.

This module never reads private keys.  ``operator_key_entry`` and
``faucet_signer_entry`` are *keystore entry names* (references), not secrets.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CHAIN_RPC = "http://127.0.0.1:8546"
DEFAULT_CHAIN_ID = 48850
DEFAULT_REQUEST_TIMEOUT = 15.0
DEFAULT_OPERATOR_KEY_ENTRY = "operator"
DEFAULT_FAUCET_SIGNER_ENTRY = "faucet-signer"
DEFAULT_TREASURY_OWNER_ENTRY = "treasury-owner"
DEFAULT_PLATFORM_MODEL_ENTRY = "platform-model"

ENV_ADDRESSES_PATH = "PLATFORM_ADDRESSES_PATH"
ENV_ARTIFACTS_DIR = "PLATFORM_ARTIFACTS_DIR"
ENV_VAULT_PATH = "PLATFORM_VAULT"
ENV_DATA_DIR = "PLATFORM_DATA_DIR"
ENV_CHAIN_RPC = "CHAIN_RPC"
ENV_CHAIN_ID = "CHAIN_ID"
ENV_CHAIN_TIMEOUT = "CHAIN_TIMEOUT"
ENV_MODEL_ALLOWLIST = "MODEL_ALLOWLIST_JSON"
ENV_OPERATOR_KEY_ENTRY = "OPERATOR_KEY_ENTRY"
ENV_FAUCET_SIGNER_ENTRY = "FAUCET_SIGNER_ENTRY"
ENV_TREASURY_OWNER_ENTRY = "TREASURY_OWNER_KEY_ENTRY"
ENV_PLATFORM_MODEL_ENTRY = "PLATFORM_MODEL_KEY_ENTRY"
ENV_PLATFORM_MODEL_PROVIDER = "PLATFORM_MODEL_PROVIDER"
ENV_API_TOKEN = "PLATFORM_API_TOKEN"
ENV_FAUCET_CAPTCHA_REQUIRED = "FAUCET_CAPTCHA_REQUIRED"


class ConfigError(RuntimeError):
    """Raised when platform configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Validated, immutable platform settings."""

    chain_rpc: str
    chain_id: int
    addresses_path: Path
    artifacts_dir: Path
    vault_path: Path
    data_dir: Path = REPO_ROOT / "platform" / "data"
    model_allowlist: dict[str, dict[str, Any]] = field(default_factory=dict)
    operator_key_entry: str = DEFAULT_OPERATOR_KEY_ENTRY
    faucet_signer_entry: str = DEFAULT_FAUCET_SIGNER_ENTRY
    treasury_owner_entry: str = DEFAULT_TREASURY_OWNER_ENTRY
    platform_model_entry: str = DEFAULT_PLATFORM_MODEL_ENTRY
    platform_model_provider: str | None = None
    api_token: str | None = field(default=None, repr=False)
    faucet_captcha_required: bool = False
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    """Return a stripped non-empty environment value, else None."""
    raw = env.get(name)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _env_path(env: Mapping[str, str], name: str, default: Path) -> Path:
    raw = _env_value(env, name)
    path = Path(raw) if raw is not None else default
    return path.expanduser().resolve()


def _read_addresses(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"addresses file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read addresses file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"addresses file {path} must contain a JSON object")
    return data


def _resolve_chain_rpc(env: Mapping[str, str], addresses: dict[str, Any]) -> str:
    raw = _env_value(env, ENV_CHAIN_RPC)
    if raw is None:
        rpc = addresses.get("rpc")
        if rpc is None:
            raw = DEFAULT_CHAIN_RPC
        elif isinstance(rpc, str) and rpc.strip():
            raw = rpc.strip()
        else:
            raise ConfigError(f"'rpc' in addresses file must be a non-empty string, got {rpc!r}")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"chain RPC must be an http(s) URL, got {raw!r}")
    return raw


def _resolve_chain_id(env: Mapping[str, str], addresses: dict[str, Any]) -> int:
    raw = _env_value(env, ENV_CHAIN_ID)
    if raw is not None:
        try:
            value = int(raw, 0)
        except ValueError as exc:
            raise ConfigError(f"CHAIN_ID must be a positive integer, got {raw!r}") from exc
        if isinstance(value, bool) or value <= 0:
            raise ConfigError(f"CHAIN_ID must be a positive integer, got {raw!r}")
        return value

    value = addresses.get("chainId", DEFAULT_CHAIN_ID)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"'chainId' in addresses file must be a positive integer, got {value!r}")
    return value


def _resolve_timeout(env: Mapping[str, str]) -> float:
    raw = _env_value(env, ENV_CHAIN_TIMEOUT)
    if raw is None:
        return DEFAULT_REQUEST_TIMEOUT
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"CHAIN_TIMEOUT must be a positive number, got {raw!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise ConfigError(f"CHAIN_TIMEOUT must be a positive number, got {raw!r}")
    return value


def _resolve_allowlist(env: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    raw = env.get(ENV_MODEL_ALLOWLIST)
    if raw is None or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"MODEL_ALLOWLIST_JSON is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("MODEL_ALLOWLIST_JSON must be a JSON object")
    for provider, provider_config in data.items():
        if not isinstance(provider, str) or not provider.strip():
            raise ConfigError("MODEL_ALLOWLIST_JSON provider names must be non-empty strings")
        if not isinstance(provider_config, dict):
            raise ConfigError(f"MODEL_ALLOWLIST_JSON entry {provider!r} must be a JSON object")
    return data


def _resolve_entry_name(env: Mapping[str, str], name: str, default: str) -> str:
    raw = env.get(name)
    if raw is None:
        return default
    value = str(raw).strip()
    if not value:
        raise ConfigError(f"{name} must be a non-empty keystore entry name")
    return value


def _resolve_optional_visible(env: Mapping[str, str], name: str) -> str | None:
    raw = _env_value(env, name)
    if raw is None:
        return None
    if not 1 <= len(raw) <= 128 or any(
        not 0x20 <= ord(character) <= 0x7E for character in raw
    ):
        raise ConfigError(f"{name} must be 1-128 visible ASCII characters")
    return raw


def _resolve_api_token(env: Mapping[str, str]) -> str | None:
    raw = _env_value(env, ENV_API_TOKEN)
    if raw is None:
        return None
    if not 24 <= len(raw) <= 256 or any(
        not 0x21 <= ord(character) <= 0x7E for character in raw
    ):
        raise ConfigError(
            f"{ENV_API_TOKEN} must contain 24-256 visible non-space ASCII characters"
        )
    return raw


def _resolve_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _env_value(env, name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean (true/false)")


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Load and validate settings.

    ``env`` defaults to ``os.environ``.  Raises :class:`ConfigError` on any
    missing or malformed input.  No secret material is read here.
    """

    env_map: Mapping[str, str] = os.environ if env is None else env

    addresses_path = _env_path(
        env_map, ENV_ADDRESSES_PATH, REPO_ROOT / "contracts" / "deploy" / "addresses.json"
    )
    artifacts_dir = _env_path(env_map, ENV_ARTIFACTS_DIR, REPO_ROOT / "contracts" / "artifacts")
    vault_path = _env_path(env_map, ENV_VAULT_PATH, REPO_ROOT / "platform" / "vault.json")
    data_dir = _env_path(env_map, ENV_DATA_DIR, REPO_ROOT / "platform" / "data")

    addresses = _read_addresses(addresses_path)
    chain_rpc = _resolve_chain_rpc(env_map, addresses)
    chain_id = _resolve_chain_id(env_map, addresses)
    request_timeout = _resolve_timeout(env_map)
    model_allowlist = _resolve_allowlist(env_map)
    operator_key_entry = _resolve_entry_name(
        env_map, ENV_OPERATOR_KEY_ENTRY, DEFAULT_OPERATOR_KEY_ENTRY
    )
    faucet_signer_entry = _resolve_entry_name(
        env_map, ENV_FAUCET_SIGNER_ENTRY, DEFAULT_FAUCET_SIGNER_ENTRY
    )
    treasury_owner_entry = _resolve_entry_name(
        env_map, ENV_TREASURY_OWNER_ENTRY, DEFAULT_TREASURY_OWNER_ENTRY
    )
    platform_model_entry = _resolve_entry_name(
        env_map, ENV_PLATFORM_MODEL_ENTRY, DEFAULT_PLATFORM_MODEL_ENTRY
    )
    platform_model_provider = _resolve_optional_visible(
        env_map, ENV_PLATFORM_MODEL_PROVIDER
    )
    api_token = _resolve_api_token(env_map)
    faucet_captcha_required = _resolve_bool(
        env_map, ENV_FAUCET_CAPTCHA_REQUIRED, False
    )

    # Directory paths: artifacts may be absent until `npx hardhat compile`
    # runs, but if present they must be directories.  The vault parent may be
    # created later by Custody, but an existing non-directory is an error.
    if artifacts_dir.exists() and not artifacts_dir.is_dir():
        raise ConfigError(f"artifacts path is not a directory: {artifacts_dir}")
    vault_parent = vault_path.parent
    if vault_parent.exists() and not vault_parent.is_dir():
        raise ConfigError(f"vault parent path is not a directory: {vault_parent}")
    if data_dir.exists() and not data_dir.is_dir():
        raise ConfigError(f"data path is not a directory: {data_dir}")

    return Settings(
        chain_rpc=chain_rpc,
        chain_id=chain_id,
        addresses_path=addresses_path,
        artifacts_dir=artifacts_dir,
        vault_path=vault_path,
        data_dir=data_dir,
        model_allowlist=model_allowlist,
        operator_key_entry=operator_key_entry,
        faucet_signer_entry=faucet_signer_entry,
        treasury_owner_entry=treasury_owner_entry,
        platform_model_entry=platform_model_entry,
        platform_model_provider=platform_model_provider,
        api_token=api_token,
        faucet_captcha_required=faucet_captcha_required,
        request_timeout=request_timeout,
    )
