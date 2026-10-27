"""Read-only chain bindings: address registry, ABIs and web3 contract objects.

Nothing here reads private keys or sends transactions.  Constructing a
:class:`ChainClient` only performs local file I/O; the RPC is contacted when
:meth:`ChainClient.verify_chain` (or any contract call) is executed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from web3 import HTTPProvider, Web3
from web3.contract import Contract

from .config import Settings

# ABI filename -> address field in contracts/deploy/addresses.json.
# Only the current R4 fields are used; legacy fields are ignored.
CONTRACT_ADDRESS_FIELDS: dict[str, str] = {
    "RTMToken": "rtm",
    "Arena": "arena",
    "Faucet": "faucet",
    "DataMarket": "dataMarket",
    "Treasury": "treasury",
}

COMPILE_HINT = "run `npx hardhat compile` in contracts/ first"


class ChainError(RuntimeError):
    """Raised when the address registry, ABIs or chain id are invalid."""


def load_addresses(path: str | Path) -> dict[str, Any]:
    """Load and validate the current address registry.

    Validates ``chainId`` and the five current contract addresses, returning a
    copy with checksummed addresses.  Other registry fields (deployment notes,
    smoke-test ids) are preserved but never required.
    """

    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ChainError(f"addresses file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainError(f"cannot read addresses file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ChainError(f"addresses file {path} must contain a JSON object")

    chain_id = data.get("chainId")
    if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
        raise ChainError(f"invalid chainId in addresses file: {chain_id!r}")

    result = dict(data)
    for field_name in CONTRACT_ADDRESS_FIELDS.values():
        value = data.get(field_name)
        if not isinstance(value, str) or not Web3.is_address(value):
            raise ChainError(
                f"invalid or missing address field {field_name!r} in {path}"
            )
        result[field_name] = Web3.to_checksum_address(value)
    return result


def _artifact_path(artifacts_dir: Path, name: str) -> Path:
    return artifacts_dir / "src" / f"{name}.sol" / f"{name}.json"


def load_abis(artifacts_dir: str | Path) -> dict[str, list[Any]]:
    """Load the five contract ABIs from Hardhat artifacts."""

    artifacts_dir = Path(artifacts_dir)
    abis: dict[str, list[Any]] = {}
    for name in CONTRACT_ADDRESS_FIELDS:
        path = _artifact_path(artifacts_dir, name)
        if not path.is_file():
            raise ChainError(f"missing ABI for {name}: {path}; {COMPILE_HINT}")
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ChainError(f"cannot read ABI for {name} at {path}: {exc}") from exc
        abi = data.get("abi") if isinstance(data, dict) else None
        if not isinstance(abi, list) or not abi:
            raise ChainError(f"invalid ABI for {name} at {path}; {COMPILE_HINT}")
        abis[name] = abi
    return abis


def _build_web3(settings: Settings) -> Web3:
    provider = HTTPProvider(
        settings.chain_rpc,
        request_kwargs={"timeout": settings.request_timeout},
    )
    return Web3(provider)


def _build_contracts(
    w3: Web3,
    addresses: dict[str, Any],
    artifacts_dir: Path,
) -> dict[str, Contract]:
    abis = load_abis(artifacts_dir)
    contracts: dict[str, Contract] = {}
    for name, field_name in CONTRACT_ADDRESS_FIELDS.items():
        contracts[name] = w3.eth.contract(
            address=Web3.to_checksum_address(addresses[field_name]),
            abi=abis[name],
        )
    return contracts


def load_contracts(settings: Settings) -> dict[str, Contract]:
    """Build web3 ``Contract`` objects for the five deployed contracts."""

    w3 = _build_web3(settings)
    addresses = load_addresses(settings.addresses_path)
    return _build_contracts(w3, addresses, settings.artifacts_dir)


class ChainClient:
    """Lazy read-only client around the deployed contracts."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.addresses = load_addresses(settings.addresses_path)
        self.w3 = _build_web3(settings)
        self._contracts = _build_contracts(
            self.w3, self.addresses, settings.artifacts_dir
        )

    @property
    def contracts(self) -> dict[str, Contract]:
        return self._contracts

    def verify_chain(self) -> int:
        """Return the RPC chain id and fail if it differs from settings."""

        try:
            actual = int(self.w3.eth.chain_id)
        except Exception as exc:  # web3 raises provider-specific errors
            raise ChainError(
                f"failed to query chain id via {self.settings.chain_rpc}: {exc}"
            ) from exc
        if actual != self.settings.chain_id:
            raise ChainError(
                f"chain id mismatch: RPC reports {actual}, "
                f"expected {self.settings.chain_id}"
            )
        return actual
