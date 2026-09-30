import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from rsi4safety.arena.audit import GENESIS_HASH, HashChain, file_sha256, snapshot_directory


class HashChainTests(unittest.TestCase):
    def test_append_builds_a_verifiable_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chain_path = Path(directory) / "audit" / "chain.jsonl"
            chain = HashChain(chain_path)
            self.assertEqual(chain.head(), GENESIS_HASH)
            first = chain.append("orchestrator", "campaign_start", campaign_id="c-1")
            chain.append("attacker", "attack_submitted", title="forged receipt")
            third = chain.append("judge", "verdict", severity="high")
            self.assertEqual(first["seq"], 1)
            self.assertEqual(first["prev_hash"], GENESIS_HASH)
            self.assertEqual(third["seq"], 3)
            self.assertEqual(chain.head(), third["entry_hash"])
            entries = chain.entries()
            self.assertEqual([entry["seq"] for entry in entries], [1, 2, 3])
            self.assertEqual(entries[2]["prev_hash"], entries[1]["entry_hash"])
            result = HashChain.verify(chain_path)
            self.assertTrue(result.ok)
            self.assertEqual(result.checked, 3)
            self.assertIsNone(result.first_bad_seq)

    def test_reloaded_chain_continues_the_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chain_path = Path(directory) / "chain.jsonl"
            HashChain(chain_path).append("orchestrator", "campaign_start")
            reloaded = HashChain(chain_path)
            entry = reloaded.append("orchestrator", "round_start", round=1)
            self.assertEqual(entry["seq"], 2)
            self.assertEqual(entry["prev_hash"], reloaded.entries()[0]["entry_hash"])
            self.assertTrue(HashChain.verify(chain_path).ok)

    def test_tampered_payload_fails_verification_at_the_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chain_path = Path(directory) / "chain.jsonl"
            chain = HashChain(chain_path)
            for index in range(3):
                chain.append("attacker", "probe_log", attempt=index)
            lines = chain_path.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(lines[1])
            tampered["payload"]["attempt"] = "rewritten"
            lines[1] = json.dumps(tampered, ensure_ascii=False)
            chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = HashChain.verify(chain_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.first_bad_seq, 2)
            self.assertEqual(result.checked, 1)

    def test_reordered_lines_break_sequence_numbering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chain_path = Path(directory) / "chain.jsonl"
            chain = HashChain(chain_path)
            for index in range(3):
                chain.append("defender", "patch_submitted", attempt=index)
            lines = chain_path.read_text(encoding="utf-8").splitlines()
            chain_path.write_text(
                "\n".join([lines[0], lines[2], lines[1]]) + "\n", encoding="utf-8"
            )
            result = HashChain.verify(chain_path)
            self.assertFalse(result.ok)
            self.assertEqual(result.first_bad_seq, 3)

    def test_ingest_file_appends_each_well_formed_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chain = HashChain(root / "chain.jsonl")
            audit_file = root / "mcp.jsonl"
            audit_file.write_text(
                "\n".join(
                    [
                        json.dumps({"ts": 1.0, "tool": "probe", "args_digest": "a", "detail": {}}),
                        "",
                        "not json at all",
                        json.dumps({"ts": 2.0, "tool": "submit_attack", "args_digest": "b"}),
                        json.dumps(["not", "an", "object"]),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            ingested = chain.ingest_file(audit_file, "mcp:attacker")
            self.assertEqual(ingested, 2)
            self.assertEqual(chain.skipped, 2)
            entries = chain.entries()
            self.assertEqual([entry["kind"] for entry in entries], ["mcp_tool_call", "mcp_tool_call"])
            self.assertEqual(entries[0]["actor"], "mcp:attacker")
            self.assertEqual(entries[0]["payload"]["tool"], "probe")
            self.assertEqual(entries[0]["payload"]["source_file"], "mcp.jsonl")
            self.assertEqual(entries[0]["payload"]["raw"]["tool"], "probe")
            result = HashChain.verify(root / "chain.jsonl")
            self.assertTrue(result.ok)
            self.assertEqual(result.checked, 2)

    def test_verify_accepts_a_missing_chain_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = HashChain.verify(Path(directory) / "absent.jsonl")
            self.assertTrue(result.ok)
            self.assertEqual(result.checked, 0)


class SnapshotTests(unittest.TestCase):
    def test_snapshot_directory_roundtrips_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            source = root / "workspace"
            (source / "sut" / "app").mkdir(parents=True)
            (source / "sut" / "app" / "main.py").write_text("print('paygate')\n", encoding="utf-8")
            (source / "sut" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            (source / "memory.md").write_text("记忆快照\n", encoding="utf-8")
            (source / "__pycache__").mkdir()
            (source / "__pycache__" / "main.cpython-313.pyc").write_bytes(b"junk")
            target = root / "snapshots" / "workspace.tar.gz"
            digest = snapshot_directory(source, target)
            self.assertTrue(target.exists())
            self.assertEqual(digest, file_sha256(target))
            extracted = root / "extracted"
            extracted.mkdir()
            with tarfile.open(target, "r:gz") as archive:
                archive.extractall(extracted, filter="data")
            restored = extracted / source.name
            self.assertEqual(
                (restored / "sut" / "app" / "main.py").read_text(encoding="utf-8"),
                "print('paygate')\n",
            )
            self.assertEqual(
                (restored / "sut" / "requirements.txt").read_text(encoding="utf-8"),
                "fastapi\n",
            )
            self.assertEqual((restored / "memory.md").read_text(encoding="utf-8"), "记忆快照\n")
            self.assertFalse((restored / "__pycache__").exists())
            with tarfile.open(target, "r:gz") as archive:
                names = archive.getnames()
            self.assertFalse(any("__pycache__" in name for name in names))

    def test_file_sha256_matches_hashlib(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.bin"
            path.write_bytes(b"arena" * 1000)
            expected = hashlib.sha256(b"arena" * 1000).hexdigest()
            self.assertEqual(file_sha256(path), expected)


if __name__ == "__main__":
    unittest.main()
