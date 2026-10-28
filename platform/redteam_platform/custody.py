"""Encrypted custody for platform-managed wallets and defender BYOK keys.

Vault layout (JSON)::

    {"version": 1, "entries": {entry_id: {"salt": hex, "nonce": hex, "ct": hex}}}

Encryption is AES-256-GCM with an scrypt-derived key.  The entry id is used as
the AAD, so ciphertexts cannot be moved between entries.  The master key comes
from ``PLATFORM_MASTER_KEY`` (32-byte hex) and is never written to disk.

Security notes:

* vault directories are created mode 0700 (best effort) and files replaced
  atomically (temp file + fsync + ``os.replace``) with mode 0600 (best effort);
* all read-modify-write cycles run under a process-wide re-entrant lock;
* secrets are never logged and never appear in error messages.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VAULT_VERSION = 1
MASTER_KEY_ENV = "PLATFORM_MASTER_KEY"

SALT_BYTES = 16
NONCE_BYTES = 12
KEY_BYTES = 32

DEFAULT_SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1


class CustodyError(RuntimeError):
    """Raised when the vault or master key is missing, corrupt or invalid."""


def _validate_master_key(raw: str | None) -> bytes:
    if not isinstance(raw, str) or not raw.strip():
        raise CustodyError(f"{MASTER_KEY_ENV} is required (32-byte hex)")
    try:
        key = bytes.fromhex(raw.strip())
    except ValueError as exc:
        raise CustodyError(f"{MASTER_KEY_ENV} must be 32-byte hex") from exc
    if len(key) != KEY_BYTES:
        raise CustodyError(f"{MASTER_KEY_ENV} must be 32-byte hex")
    return key


def _require_entry_id(entry_id: str) -> str:
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise CustodyError("entry_id must be a non-empty string")
    return entry_id


def _require_secret(secret: str) -> str:
    if not isinstance(secret, str) or secret == "":
        raise CustodyError("secret must be a non-empty string")
    return secret


def _best_effort_chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        # Windows and some filesystems cannot represent POSIX modes.
        pass


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync (not supported on Windows)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class Custody:
    """Small AES-GCM vault stored in a single JSON file.

    ``master_key_hex`` defaults to the ``PLATFORM_MASTER_KEY`` environment
    variable when omitted.  ``scrypt_n`` is exposed only so tests can use a
    cheaper cost factor; production must keep the 2**15 default.
    """

    _lock = threading.RLock()

    def __init__(
        self,
        vault_path: str | Path,
        master_key_hex: str | None = None,
        *,
        scrypt_n: int = DEFAULT_SCRYPT_N,
    ) -> None:
        self.vault_path = Path(vault_path).expanduser()
        if master_key_hex is None:
            master_key_hex = os.environ.get(MASTER_KEY_ENV)
        self._master_key = _validate_master_key(master_key_hex)
        if (
            isinstance(scrypt_n, bool)
            or not isinstance(scrypt_n, int)
            or scrypt_n < 2
            or scrypt_n & (scrypt_n - 1)
        ):
            raise CustodyError("scrypt_n must be a power of two >= 2")
        self._scrypt_n = scrypt_n

    # -- key derivation -------------------------------------------------

    def _derive_key(self, salt: bytes) -> bytes:
        try:
            return Scrypt(
                salt=salt,
                length=KEY_BYTES,
                n=self._scrypt_n,
                r=SCRYPT_R,
                p=SCRYPT_P,
            ).derive(self._master_key)
        except (ValueError, TypeError) as exc:
            raise CustodyError("vault entry is corrupt") from exc

    # -- vault I/O ------------------------------------------------------

    def _read_vault(self) -> dict[str, Any]:
        if not self.vault_path.exists():
            raise CustodyError(f"vault not found: {self.vault_path}")
        try:
            with self.vault_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise CustodyError(f"cannot read vault {self.vault_path}: {exc}") from exc
        if (
            not isinstance(data, dict)
            or data.get("version") != VAULT_VERSION
            or not isinstance(data.get("entries"), dict)
        ):
            raise CustodyError("vault has an unsupported or corrupt format")
        return data

    def _read_vault_for_write(self) -> dict[str, Any]:
        if not self.vault_path.exists():
            return {"version": VAULT_VERSION, "entries": {}}
        return self._read_vault()

    def _atomic_write(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
        parent = self.vault_path.parent

        created_parent = not parent.exists()
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CustodyError(f"cannot create vault directory {parent}: {exc}") from exc
        if not parent.is_dir():
            raise CustodyError(f"vault parent path is not a directory: {parent}")
        if created_parent:
            _best_effort_chmod(parent, 0o700)

        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self.vault_path.name}.",
                suffix=".tmp",
                dir=str(parent),
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            _best_effort_chmod(Path(tmp_name), 0o600)
            os.replace(tmp_name, self.vault_path)
            tmp_name = None
            _fsync_directory(parent)
        except CustodyError:
            raise
        except OSError as exc:
            raise CustodyError(f"cannot write vault {self.vault_path}: {exc}") from exc
        finally:
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass

    # -- public API -----------------------------------------------------

    def store(self, entry_id: str, secret: str) -> None:
        """Encrypt ``secret`` under ``entry_id`` (creating or replacing it)."""
        entry_id = _require_entry_id(entry_id)
        secret = _require_secret(secret)
        with self._lock:
            data = self._read_vault_for_write()
            salt = os.urandom(SALT_BYTES)
            nonce = os.urandom(NONCE_BYTES)
            key = self._derive_key(salt)
            ciphertext = AESGCM(key).encrypt(
                nonce, secret.encode("utf-8"), entry_id.encode("utf-8")
            )
            data["entries"][entry_id] = {
                "salt": salt.hex(),
                "nonce": nonce.hex(),
                "ct": ciphertext.hex(),
            }
            self._atomic_write(data)

    def load(self, entry_id: str) -> str:
        """Decrypt and return the secret stored under ``entry_id``."""
        entry_id = _require_entry_id(entry_id)
        with self._lock:
            data = self._read_vault()
            entry = data["entries"].get(entry_id)
            if not isinstance(entry, dict):
                raise CustodyError(f"vault entry not found: {entry_id!r}")
            try:
                salt = bytes.fromhex(entry["salt"])
                nonce = bytes.fromhex(entry["nonce"])
                ciphertext = bytes.fromhex(entry["ct"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CustodyError("vault entry is corrupt") from exc
            key = self._derive_key(salt)
            try:
                plaintext = AESGCM(key).decrypt(
                    nonce, ciphertext, entry_id.encode("utf-8")
                )
            except (InvalidTag, ValueError) as exc:
                raise CustodyError("vault entry failed authentication") from exc
            try:
                return plaintext.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CustodyError("vault entry is corrupt") from exc

    def delete(self, entry_id: str) -> None:
        """Remove ``entry_id`` from the vault."""
        entry_id = _require_entry_id(entry_id)
        with self._lock:
            data = self._read_vault()
            if entry_id not in data["entries"]:
                raise CustodyError(f"vault entry not found: {entry_id!r}")
            del data["entries"][entry_id]
            self._atomic_write(data)
