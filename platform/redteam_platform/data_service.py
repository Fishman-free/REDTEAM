"""Consent-aware dataset bundles and deliveries for DataMarket (task 14).

A bundle contains only:

* defender-owned metadata (the contest row and, when present, the task-12
  session snapshot);
* transcripts of normal-contest attackers whose join-time ``dataConsent`` is
  ``true`` on chain (indexer) and whose records are marked
  ``purpose=defender_dataset`` / ``rsi_only=false`` / ``consent=true``.

Opted-out attackers and mining (``rsi_only``) data are excluded even if a file
somehow exists on disk.  Bundle roots use the spec-allowed simplification:
sorted leaf hashes (sha256 of each file) concatenated, then sha256.  The
manifest lists every file hash so a buyer can recompute the root and compare
it with the on-chain ``datasetRoot``.

Deliveries are ZIP slices: ``buyOwn`` receives defender files;
``buyFromAttacker`` receives that attacker's transcript plus the full manifest.
The full manifest is included (not other buyers' content) so the slice can be
verified against the published root.  Download tokens are in-memory,
single-process capabilities with a TTL; task 15/API serves the ZIP.

The operator key used by :class:`ChainDataMarketWriter` is loaded through
``AuditedCustody`` for every publish and is never retained.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import tempfile
import threading
import time
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from eth_account import Account
from web3 import Web3

from ._jsonl import ensure_directory, write_text_atomic
from .indexer import IndexerError, normalize_contest_id
from .transcripts import PURPOSE_DATASET

ZERO_ROOT = "0x" + "00" * 32
MANIFEST_NAME = "manifest.json"
PUBLISH_GAS = 200_000
DEFAULT_RECEIPT_TIMEOUT = 60.0
DEFAULT_DELIVERY_TTL = 600.0


class DataServiceError(RuntimeError):
    """Raised when a bundle, publish or delivery cannot be produced."""


class IndexerPort(Protocol):
    network: str

    def contest(self, contest_id: str) -> dict[str, Any] | None: ...

    def contest_attackers(self, contest_id: str) -> dict[str, dict[str, Any]]: ...

    def data_consent(self, contest_id: str, attacker: str) -> bool | None: ...

    def is_excluded(self, contest_id: str) -> bool: ...


class DataMarketWriterPort(Protocol):
    def dataset_root(self, contest_id: str) -> str: ...

    def publish(self, contest_id: str, root: str) -> str: ...


@dataclass(frozen=True)
class BundleFile:
    path: str
    sha256: str
    size: int
    kind: str
    attacker: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.size,
            "kind": self.kind,
        }
        if self.attacker is not None:
            value["attacker"] = self.attacker
        return value


@dataclass(frozen=True)
class Bundle:
    contest_id: str
    root: str
    directory: Path
    manifest_path: Path
    files: tuple[BundleFile, ...]
    excluded: dict[str, Any]


@dataclass(frozen=True)
class PublishResult:
    contest_id: str
    root: str
    tx_hash: str
    bundle: Bundle


@dataclass(frozen=True)
class Delivery:
    token: str
    path: Path
    contest_id: str
    buyer: str
    kind: str
    attacker: str | None
    root: str
    files: tuple[str, ...]
    expires_at: float


def _normalize_address(value: Any, field: str) -> str:
    try:
        address = Web3.to_checksum_address(value)
    except (ValueError, TypeError):
        raise DataServiceError(f"{field} must be a valid address") from None
    if int(address, 16) == 0:
        raise DataServiceError(f"{field} must not be the zero address")
    return address


def _contest_id(value: Any) -> str:
    try:
        return normalize_contest_id(value)
    except IndexerError as exc:
        raise DataServiceError(str(exc)) from None


def _root(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        if len(value) != 32:
            raise DataServiceError("dataset root must be 32 bytes")
        return "0x" + bytes(value).hex()
    if isinstance(value, str):
        text = value.lower()
        if text.startswith("0x") and len(text) == 66:
            try:
                bytes.fromhex(text[2:])
            except ValueError:
                raise DataServiceError("dataset root must be bytes32 hex") from None
            return text
    raise DataServiceError("dataset root must be 32 bytes")


def _tx_hex(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    text = str(value)
    return text if text.startswith("0x") else "0x" + text


def _bundle_root(files: Iterable[tuple[str, bytes]]) -> tuple[str, list[str]]:
    ordered = sorted(files, key=lambda item: item[0])
    leaves = [hashlib.sha256(payload).hexdigest() for _path, payload in ordered]
    root = "0x" + hashlib.sha256("".join(leaves).encode("ascii")).hexdigest()
    return root, leaves


def _filter_transcript(path: Path, attacker: str) -> tuple[list[dict], int]:
    """Return only consented normal-contest turn records, plus a skip count."""

    allowed: list[dict] = []
    skipped = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DataServiceError(f"cannot read transcript {path}: {exc}") from exc
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            skipped += 1
            continue
        if (
            not isinstance(record, dict)
            or record.get("kind") != "turn"
            or str(record.get("attacker", "")).lower() != attacker.lower()
            or record.get("purpose") != PURPOSE_DATASET
            or record.get("consent") is not True
            or record.get("rsi_only") is not False
        ):
            skipped += 1
            continue
        allowed.append(record)
    return allowed, skipped


class DataService:
    """Build/publish bundles and prepare per-buyer delivery slices."""

    def __init__(
        self,
        indexer: IndexerPort,
        transcript_root: str | Path,
        bundle_root: str | Path,
        *,
        writer: DataMarketWriterPort | None = None,
        clock: Callable[[], float] = time.time,
        delivery_ttl: float = DEFAULT_DELIVERY_TTL,
    ) -> None:
        self.indexer = indexer
        self.transcript_root = Path(transcript_root).expanduser()
        self.bundle_root = Path(bundle_root).expanduser()
        if writer is not None and not (
            callable(getattr(writer, "dataset_root", None))
            and callable(getattr(writer, "publish", None))
        ):
            raise DataServiceError("writer must expose dataset_root and publish")
        self.writer = writer
        if not callable(clock):
            raise DataServiceError("clock must be callable")
        self._clock = clock
        if isinstance(delivery_ttl, bool) or not isinstance(delivery_ttl, (int, float)):
            raise DataServiceError("delivery_ttl must be a positive number")
        ttl = float(delivery_ttl)
        if not math.isfinite(ttl) or not 0 < ttl <= 86_400:
            raise DataServiceError("delivery_ttl must be positive and at most 86400")
        self.delivery_ttl = ttl
        self._lock = threading.RLock()
        self._bundles: dict[str, Bundle] = {}
        self._deliveries: dict[str, Delivery] = {}

    # -- bundle ---------------------------------------------------------

    def bundle(self, contest_id: str) -> Bundle:
        cid = _contest_id(contest_id)
        with self._lock:
            cached = self._bundles.get(cid)
            if cached is not None:
                return cached

            contest = self.indexer.contest(cid)
            if contest is None:
                raise DataServiceError(f"contest not indexed: {cid}")
            if self.indexer.is_excluded(cid):
                raise DataServiceError("contest is excluded from datasets")
            if contest["is_mining"]:
                raise DataServiceError("mining data is RSI-only and cannot be bundled")
            if contest["state"] == "live":
                raise DataServiceError("contest has not ended")

            excluded: dict[str, Any] = {
                "opt_out_attackers": [],
                "mining_attackers": [],
                "missing_transcripts": [],
                "empty_transcripts": [],
                "skipped_records": 0,
            }
            staged: dict[str, bytes] = {}

            defender_payload = {
                "schema_version": "redteam.dataset.defender.v1",
                "contest": contest,
            }
            staged["defender/contest.json"] = (
                json.dumps(defender_payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n"
            ).encode("utf-8")

            session_path = self.transcript_root / cid / "session.json"
            if session_path.is_file():
                try:
                    session = json.loads(session_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, UnicodeDecodeError):
                    session = None
                if isinstance(session, dict) and session.get("is_mining") is not True:
                    staged["defender/session.json"] = (
                        json.dumps(session, ensure_ascii=False, indent=2, sort_keys=True)
                        + "\n"
                    ).encode("utf-8")

            for attacker, info in sorted(
                self.indexer.contest_attackers(cid).items()
            ):
                if info.get("is_mining"):
                    excluded["mining_attackers"].append(attacker)
                    continue
                if info.get("data_consent") is not True:
                    excluded["opt_out_attackers"].append(attacker)
                    continue
                source = self.transcript_root / cid / f"{attacker.lower()}.jsonl"
                if not source.is_file():
                    excluded["missing_transcripts"].append(attacker)
                    continue
                allowed, skipped = _filter_transcript(source, attacker)
                excluded["skipped_records"] += skipped
                if not allowed:
                    excluded["empty_transcripts"].append(attacker)
                    continue
                text = "".join(
                    json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                    for record in allowed
                )
                staged[
                    f"attackers/{attacker.lower()}/transcript.jsonl"
                ] = text.encode("utf-8")

            ensure_directory(self.bundle_root)
            directory = Path(
                tempfile.mkdtemp(prefix=f"{cid[:10]}-", dir=str(self.bundle_root))
            )
            written: dict[str, bytes] = {}
            files: list[BundleFile] = []
            for relative_path in sorted(staged):
                write_text_atomic(
                    directory / relative_path, staged[relative_path].decode("utf-8")
                )
                payload = (directory / relative_path).read_bytes()
                written[relative_path] = payload
                kind = (
                    "defender_session"
                    if relative_path == "defender/session.json"
                    else "defender_contest"
                    if relative_path == "defender/contest.json"
                    else "attacker_transcript"
                )
                attacker = (
                    Web3.to_checksum_address(relative_path.split("/")[1])
                    if kind == "attacker_transcript"
                    else None
                )
                files.append(
                    BundleFile(
                        path=relative_path,
                        sha256=hashlib.sha256(payload).hexdigest(),
                        size=len(payload),
                        kind=kind,
                        attacker=attacker,
                    )
                )

            root, leaves = _bundle_root(written.items())
            if len(leaves) != len(written):
                raise DataServiceError("bundle root computation failed")

            manifest = {
                "schema_version": "redteam.dataset.v1",
                "network": self.indexer.network,
                "contest_id": cid,
                "root": root,
                "created_at": int(self._clock()),
                "files": [item.as_dict() for item in files],
                "excluded": excluded,
            }
            manifest_path = directory / MANIFEST_NAME
            write_text_atomic(
                manifest_path,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            bundle = Bundle(
                contest_id=cid,
                root=root,
                directory=directory,
                manifest_path=manifest_path,
                files=tuple(files),
                excluded=excluded,
            )
            self._bundles[cid] = bundle
            return bundle

    # -- publish --------------------------------------------------------

    def publish(self, contest_id: str) -> PublishResult:
        cid = _contest_id(contest_id)
        if self.writer is None:
            raise DataServiceError("data market writer is not configured")
        with self._lock:
            bundle = self.bundle(cid)
            current = _root(self.writer.dataset_root(cid))
            if current != ZERO_ROOT:
                raise DataServiceError("dataset is already published")
            tx_hash = self.writer.publish(cid, bundle.root)
            if not isinstance(tx_hash, str) or not tx_hash:
                raise DataServiceError("publisher returned no transaction hash")
            return PublishResult(
                contest_id=cid,
                root=bundle.root,
                tx_hash=tx_hash,
                bundle=bundle,
            )

    # -- delivery -------------------------------------------------------

    def deliver_own(self, contest_id: str, buyer: str) -> Delivery:
        cid = _contest_id(contest_id)
        buyer = _normalize_address(buyer, "buyer")
        with self._lock:
            bundle, contest = self._published_bundle(cid)
            if buyer != contest["defender"]:
                raise DataServiceError("only the defender may buy this dataset")
            selected = tuple(
                item for item in bundle.files if item.path.startswith("defender/")
            )
            if not selected:
                raise DataServiceError("defender data is not available")
            return self._make_delivery(
                bundle, selected, buyer=buyer, kind="own", attacker=None
            )

    def deliver_attacker(
        self, contest_id: str, buyer: str, attacker: str
    ) -> Delivery:
        cid = _contest_id(contest_id)
        buyer = _normalize_address(buyer, "buyer")
        attacker = _normalize_address(attacker, "attacker")
        with self._lock:
            bundle, contest = self._published_bundle(cid)
            if buyer != contest["defender"]:
                raise DataServiceError("only the defender may buy this dataset")
            if self.indexer.data_consent(cid, attacker) is not True:
                raise DataServiceError("attacker did not consent to data sales")
            selected = tuple(
                item
                for item in bundle.files
                if item.kind == "attacker_transcript" and item.attacker == attacker
            )
            if not selected:
                raise DataServiceError("attacker transcript is not available")
            return self._make_delivery(
                bundle,
                selected,
                buyer=buyer,
                kind="attacker",
                attacker=attacker,
            )

    def resolve_delivery(self, token: str) -> Delivery | None:
        if not isinstance(token, str) or not token:
            return None
        with self._lock:
            delivery = self._deliveries.get(token)
            if delivery is None:
                return None
            if self._clock() >= delivery.expires_at or not delivery.path.is_file():
                del self._deliveries[token]
                return None
            return delivery

    def _published_bundle(self, cid: str) -> tuple[Bundle, dict[str, Any]]:
        bundle = self.bundle(cid)
        if self.writer is None:
            raise DataServiceError("data market writer is not configured")
        current = _root(self.writer.dataset_root(cid))
        if current == ZERO_ROOT:
            raise DataServiceError("dataset is not published")
        if current != bundle.root:
            raise DataServiceError("bundle root does not match the published root")
        contest = self.indexer.contest(cid)
        if contest is None:
            raise DataServiceError(f"contest not indexed: {cid}")
        return bundle, contest

    def _make_delivery(
        self,
        bundle: Bundle,
        files: tuple[BundleFile, ...],
        *,
        buyer: str,
        kind: str,
        attacker: str | None,
    ) -> Delivery:
        token = secrets.token_urlsafe(32)
        delivery_dir = self.bundle_root / "deliveries"
        ensure_directory(delivery_dir)
        path = delivery_dir / f"{token}.zip"
        manifest_text = bundle.manifest_path.read_text(encoding="utf-8")
        try:
            with zipfile.ZipFile(
                path, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr(MANIFEST_NAME, manifest_text)
                for item in files:
                    data = (bundle.directory / item.path).read_bytes()
                    if hashlib.sha256(data).hexdigest() != item.sha256:
                        raise DataServiceError("bundle file hash mismatch")
                    archive.writestr(item.path, data)
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            raise
        delivery = Delivery(
            token=token,
            path=path,
            contest_id=bundle.contest_id,
            buyer=buyer,
            kind=kind,
            attacker=attacker,
            root=bundle.root,
            files=tuple(item.path for item in files),
            expires_at=self._clock() + self.delivery_ttl,
        )
        self._deliveries[token] = delivery
        return delivery


class ChainDataMarketWriter:
    """Operator-key publisher for ``DataMarket.publish`` with custody audit."""

    def __init__(
        self,
        w3: Web3,
        data_market: Any,
        custody: Any,
        operator_entry: str,
        chain_id: int,
        *,
        receipt_timeout: float = DEFAULT_RECEIPT_TIMEOUT,
    ) -> None:
        if not isinstance(operator_entry, str) or not operator_entry.strip():
            raise DataServiceError("operator_entry must be a non-empty entry name")
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise DataServiceError("chain_id must be a positive integer")
        if isinstance(receipt_timeout, bool) or not isinstance(receipt_timeout, (int, float)):
            raise DataServiceError("receipt_timeout must be a positive number")
        timeout = float(receipt_timeout)
        if not math.isfinite(timeout) or not 0 < timeout <= 600:
            raise DataServiceError("receipt_timeout must be positive and at most 600")
        self._w3 = w3
        self._market = data_market
        self._custody = custody
        self.operator_entry = operator_entry
        self.chain_id = chain_id
        self.receipt_timeout = timeout
        self._lock = threading.RLock()

    def dataset_root(self, contest_id: str) -> str:
        cid = _contest_id(contest_id)
        try:
            value = self._market.functions.datasetRoot(
                bytes.fromhex(cid[2:])
            ).call()
        except Exception as exc:
            raise DataServiceError("cannot read dataset root") from exc
        return _root(value)

    def publish(self, contest_id: str, root: str) -> str:
        cid = _contest_id(contest_id)
        root = _root(root)
        with self._lock:
            if self.dataset_root(cid) != ZERO_ROOT:
                raise DataServiceError("dataset is already published")
            context = {"purpose": "data_publish", "contest_id": cid}
            try:
                private_key = self._custody.load(self.operator_entry, context=context)
            except Exception:
                raise DataServiceError("operator key unavailable") from None
            try:
                account = Account.from_key(private_key)
            except Exception:
                raise DataServiceError("operator key is invalid") from None

            try:
                nonce = int(self._w3.eth.get_transaction_count(account.address))
                tx = self._market.functions.publish(
                    bytes.fromhex(cid[2:]), bytes.fromhex(root[2:])
                ).build_transaction(
                    {
                        "from": account.address,
                        "nonce": nonce,
                        "gas": PUBLISH_GAS,
                        "gasPrice": 0,
                        "chainId": self.chain_id,
                    }
                )
                signed = self._w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self._w3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=self.receipt_timeout
                )
            except Exception as exc:
                raise DataServiceError("publish transaction failed") from exc

            # web3 8 returns AttributeDict, which is a Mapping but not a dict.
            if not isinstance(receipt, Mapping) or receipt.get("status") != 1:
                raise DataServiceError("publish transaction reverted")
            return _tx_hex(tx_hash)
