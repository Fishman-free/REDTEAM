from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tarfile
from typing import Any
import time

GENESIS_HASH = "0" * 64
ENTRY_KEYS = ("seq", "ts", "actor", "kind", "payload", "prev_hash", "entry_hash")
SNAPSHOT_EXCLUDED = {"__pycache__", ".git"}


def _entry_hash(seq: int, ts: float, actor: str, kind: str, payload: dict, prev_hash: str) -> str:
    material = (
        f"{seq}|{ts}|{actor}|{kind}|"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False)}|{prev_hash}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditVerifyResult:
    ok: bool
    checked: int
    first_bad_seq: int | None
    reason: str = ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if any(part in SNAPSHOT_EXCLUDED for part in Path(member.name).parts):
        return None
    return member


def snapshot_directory(source: Path, target: Path) -> str:
    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, "w:gz") as archive:
        archive.add(source, arcname=source.name, filter=_snapshot_filter)
    return file_sha256(target)


class HashChain:
    """Append-only tamper-evident log; single-process orchestrator usage."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.skipped = 0
        self._entries: list[dict] = []
        if self.path.exists():
            for index, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"audit chain line {index} is not valid JSON") from exc
                if not isinstance(entry, dict):
                    raise ValueError(f"audit chain line {index} is not an object")
                self._entries.append(entry)

    def append(self, actor: str, kind: str, **payload: Any) -> dict:
        seq = len(self._entries) + 1
        ts = time.time()
        prev_hash = self._entries[-1]["entry_hash"] if self._entries else GENESIS_HASH
        entry: dict[str, Any] = {
            "seq": seq,
            "ts": ts,
            "actor": actor,
            "kind": kind,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        entry["entry_hash"] = _entry_hash(seq, ts, actor, kind, payload, prev_hash)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
        self._entries.append(entry)
        return dict(entry)

    def ingest_file(self, path: Path, actor: str) -> int:
        path = Path(path)
        ingested = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                self.skipped += 1
                continue
            if not isinstance(raw, dict):
                self.skipped += 1
                continue
            self.append(actor, "mcp_tool_call", tool=raw.get("tool"), source_file=path.name, raw=raw)
            ingested += 1
        return ingested

    def head(self) -> str:
        return self._entries[-1]["entry_hash"] if self._entries else GENESIS_HASH

    def entries(self) -> list[dict]:
        return [dict(entry) for entry in self._entries]

    @staticmethod
    def verify(path: Path) -> AuditVerifyResult:
        path = Path(path)
        if not path.exists():
            return AuditVerifyResult(True, 0, None, "empty chain")
        prev_hash = GENESIS_HASH
        checked = 0
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return AuditVerifyResult(False, checked, index, f"line {index} is not valid JSON")
            if not isinstance(entry, dict):
                return AuditVerifyResult(False, checked, index, f"line {index} is not an object")
            seq = entry.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool):
                return AuditVerifyResult(False, checked, index, f"line {index} has a non-integer seq")
            if seq != index:
                return AuditVerifyResult(
                    False, checked, seq, f"expected seq {index} but found {seq}"
                )
            missing = [key for key in ENTRY_KEYS if key not in entry]
            if missing:
                return AuditVerifyResult(
                    False, checked, seq, f"entry {seq} is missing keys: {', '.join(missing)}"
                )
            if entry["prev_hash"] != prev_hash:
                return AuditVerifyResult(
                    False, checked, seq, f"entry {seq} breaks the prev_hash chain"
                )
            expected = _entry_hash(
                seq,
                entry["ts"],
                entry["actor"],
                entry["kind"],
                entry["payload"],
                entry["prev_hash"],
            )
            if entry["entry_hash"] != expected:
                return AuditVerifyResult(False, checked, seq, f"entry {seq} has a mismatched entry_hash")
            prev_hash = entry["entry_hash"]
            checked += 1
        return AuditVerifyResult(True, checked, None, "chain verified")
