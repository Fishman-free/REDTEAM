#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Defender-role MCP server (stdio JSON-RPC 2.0 subset), Python stdlib only.

Implements the minimum MCP surface required by ARENA_SPEC §6:
initialize / notifications/initialized / tools/list / tools/call.

Tools:
  read_inbox()                       list + read inbox/*.json (round briefs, verdict digests)
  run_tests()                        run pytest in SOURCE_DIR (with graceful fallbacks)
  write_memory(title, content)       append episodic memory note
  submit_patch(summary, tests_added) git archive HEAD -> outbox tar + manifest (SPEC §2.5)
  apply_promotion(tar_name)       verify promotion notice hash, extract over SOURCE_DIR, commit

Environment:
  EXCHANGE_DIR   spool root for this role   (default /exchange/defender)
  WORKSPACE_DIR  agent workspace            (default /agent/workspace)
  SOURCE_DIR     SUT source checkout        (default /agent/source)

pytest is NOT stdlib but is preinstalled in the defender image; the code below
degrades to plain pytest / unittest discover when the rich invocation is absent.

Debug output goes to stderr ONLY; stdout carries JSON-RPC responses exclusively.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

SERVER_NAME = "defender-tools"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
ROLE = "defender"

EXCHANGE_DIR = Path(os.environ.get("EXCHANGE_DIR", "/exchange/defender"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/agent/workspace"))
SOURCE_DIR = Path(os.environ.get("SOURCE_DIR", "/agent/source"))

# Path traversal guard: SOURCE_DIR must be an absolute path without ".." and
# without shell-metacharacter noise. (The previous POSIX-only regex was fed a
# Path object and crashed on import on every platform.)
_SOURCE_DIR_TEXT = str(os.environ.get("SOURCE_DIR", "/agent/source"))
# NUL LF CR ESC " $ & ' * < > ? ` | ;  -- as codepoints so this file stays
# byte-safe under every editor/encoding combination.
_UNSAFE_SOURCE_DIR_CHARS = frozenset(map(chr, (0, 10, 13, 27, 34, 36, 38, 39,
                                               42, 60, 62, 63, 96, 124, 59)))
if (not Path(_SOURCE_DIR_TEXT).is_absolute()
        or ".." in Path(_SOURCE_DIR_TEXT).parts
        or any(ch in _UNSAFE_SOURCE_DIR_CHARS for ch in _SOURCE_DIR_TEXT)):
    raise RuntimeError(f"blocked: SOURCE_DIR is not a safe absolute path: {_SOURCE_DIR_TEXT}")
SOURCE_DIR = Path(_SOURCE_DIR_TEXT)

RUN_TESTS_OUTER_TIMEOUT_S = 300  # outer kill switch; inner per-test cap is --timeout=120
GIT_TIMEOUT_S = 60
GIT_ARCHIVE_TIMEOUT_S = 300


class ToolError(Exception):
    """Recoverable tool failure -> tools/call result with isError: true."""


# ----------------------------------------------------------------------------
# plumbing (stdout is reserved for JSON-RPC; debug goes to stderr)
# ----------------------------------------------------------------------------

def _stderr_log(message: str) -> None:
    try:
        sys.stderr.write("[mcp:%s] %s\n" % (ROLE, message))
        sys.stderr.flush()
    except Exception:
        pass


def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit(tool: str, arguments, detail: dict) -> None:
    """Append one line to EXCHANGE_DIR/audit/mcp.jsonl; never raise into the loop."""
    try:
        audit_dir = EXCHANGE_DIR / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        try:
            canonical = _canonical_json(arguments if isinstance(arguments, dict) else {})
        except Exception:
            canonical = "<unserializable>"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        entry = {"ts": time.time(), "tool": tool, "args_digest": digest, "detail": detail}
        with open(audit_dir / "mcp.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            handle.flush()
    except Exception as exc:  # audit must never kill the server
        _stderr_log("audit write failed: %r" % (exc,))


# ----------------------------------------------------------------------------
# inbox helpers
# ----------------------------------------------------------------------------

def _inbox_files() -> list:
    inbox = EXCHANGE_DIR / "inbox"
    if not inbox.is_dir():
        return []
    return sorted(path for path in inbox.glob("*.json") if path.is_file())


def _read_inbox_payload() -> dict:
    files = []
    for path in _inbox_files():
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            content = {"_error": "unparseable: %s" % exc}
        files.append({"file": path.name, "content": content})
    return {"files": files, "count": len(files)}


def _inbox_documents_by_recency():
    entries = []
    for path in _inbox_files():
        try:
            entries.append((path.stat().st_mtime, path, json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    entries.sort(key=lambda item: item[0], reverse=True)
    return entries


def _latest_int_field(field: str):
    for _mtime, _path, data in _inbox_documents_by_recency():
        if isinstance(data, dict):
            value = data.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _latest_string_field(*fields: str) -> str | None:
    for _mtime, _path, data in _inbox_documents_by_recency():
        if not isinstance(data, dict):
            continue
        for field in fields:
            value = data.get(field)
            if isinstance(value, str) and value:
                return value
    return None


# ----------------------------------------------------------------------------
# tools
# ----------------------------------------------------------------------------

def _tool_read_inbox(_args: dict):
    payload = _read_inbox_payload()
    return payload, {"files": payload["count"]}


def _run_command(cmd, cwd: Path, timeout: int):
    """subprocess.run wrapper; kills and reports on timeout (never raises)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode, " ".join(cmd), output
    except subprocess.TimeoutExpired:
        return None, " ".join(cmd), "TIMEOUT: process killed after %ss" % timeout
    except FileNotFoundError:
        return None, " ".join(cmd), "command not found: %s" % cmd[0]
    except Exception as exc:
        return None, " ".join(cmd), "subprocess error: %s: %s" % (type(exc).__name__, exc)


def _tool_run_tests(_args: dict):
    if not SOURCE_DIR.is_dir():
        raise ToolError("SOURCE_DIR %s does not exist" % SOURCE_DIR)

    # 1) preferred: pytest with a per-test timeout (pytest-timeout preinstalled in image)
    code, command, output = _run_command(
        ["python3", "-m", "pytest", "tests/", "-q", "--timeout=120"],
        SOURCE_DIR,
        RUN_TESTS_OUTER_TIMEOUT_S,
    )
    detail = {"mode": "pytest+timeout", "exit_code": code}

    if "No module named pytest" in output:
        # 2) no pytest at all -> degrade to stdlib unittest discovery
        code, command, output = _run_command(
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
            SOURCE_DIR,
            RUN_TESTS_OUTER_TIMEOUT_S,
        )
        detail = {"mode": "unittest-discover", "exit_code": code}
    elif code == 4 or "unrecognized arguments" in output or "unrecognized option" in output:
        # 3) pytest exists but --timeout flag unsupported -> plain pytest
        code, command, output = _run_command(
            ["python3", "-m", "pytest", "tests/", "-q"],
            SOURCE_DIR,
            RUN_TESTS_OUTER_TIMEOUT_S,
        )
        detail = {"mode": "pytest-plain", "exit_code": code}

    detail["command"] = command
    _stderr_log("run_tests: %s -> exit=%s" % (command, code))
    return (
        {"exit_code": code, "command": command, "output_tail": output[-4000:]},
        detail,
    )


def _tool_write_memory(args: dict):
    title = args.get("title")
    content = args.get("content")
    if not isinstance(title, str) or not title.strip():
        raise ToolError("title is required (non-empty string)")
    if len(title) > 120:
        raise ToolError("title too long: %d > 120 characters" % len(title))
    if not isinstance(content, str):
        raise ToolError("content must be a string")
    if len(content) > 8000:
        raise ToolError("content too long: %d > 8000 characters" % len(content))
    memory_dir = WORKSPACE_DIR / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now()
    file_name = "episodic-%s.md" % stamp.strftime("%Y%m%d")
    entry = "## %s %s\n%s\n" % (stamp.strftime("%Y-%m-%d %H:%M:%S"), title.strip(), content)
    with open(memory_dir / file_name, "a", encoding="utf-8") as handle:
        handle.write(entry)
        handle.flush()
    return (
        {"file": file_name, "bytes_appended": len(entry.encode("utf-8"))},
        {"file": file_name, "title_chars": len(title)},
    )


def _tool_submit_patch(args: dict):
    summary = args.get("summary")
    tests_added = args.get("tests_added")
    if tests_added is None:
        tests_added = []
    if not isinstance(summary, str) or not summary.strip():
        raise ToolError("summary is required (non-empty string)")
    if len(summary) > 4000:
        raise ToolError("summary too long: %d > 4000 characters" % len(summary))
    if not isinstance(tests_added, list) or not all(isinstance(item, str) for item in tests_added):
        raise ToolError("tests_added must be a list of test file path strings")
    if not SOURCE_DIR.is_dir():
        raise ToolError("SOURCE_DIR %s does not exist" % SOURCE_DIR)

    rev = subprocess.run(
        ["git", "-C", str(SOURCE_DIR), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
    )
    if rev.returncode != 0:
        raise ToolError("not a git repo (git -C %s rev-parse HEAD failed): %s"
                        % (SOURCE_DIR, (rev.stderr or "").strip()[:200]))
    sha = rev.stdout.strip()
    if len(sha) < 12:
        raise ToolError("unexpected HEAD sha from git: %r" % sha)
    submission_id = "pat-" + sha[:12]

    outbox = EXCHANGE_DIR / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    tar_name = "patch-%s.tar" % submission_id
    manifest_name = "patch-%s.json" % submission_id
    tar_target = outbox / tar_name
    if (outbox / manifest_name).exists() or tar_target.exists():
        raise ToolError(
            "submission %s already exists for this commit; make a new commit before resubmitting"
            % submission_id
        )

    # git archive HEAD -> temp file -> copy into outbox (atomic final placement)
    fd, temp_path = tempfile.mkstemp(prefix="arena-patch-", suffix=".tar")
    os.close(fd)
    try:
        with open(temp_path, "wb") as tar_file:
            archive = subprocess.run(
                ["git", "-C", str(SOURCE_DIR), "archive", "--format=tar", "HEAD"],
                stdout=tar_file,
                stderr=subprocess.PIPE,
                timeout=GIT_ARCHIVE_TIMEOUT_S,
            )
        if archive.returncode != 0:
            raise ToolError("git archive failed: %s"
                            % (archive.stderr or b"").decode("utf-8", errors="replace").strip()[:200])
        if os.path.getsize(temp_path) == 0:
            raise ToolError("git archive produced an empty tar")
        shutil.copyfile(temp_path, tar_target)
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    # hash the finished outbox artifact BEFORE writing the manifest
    tar_sha256 = _sha256_file(tar_target)

    round_number = _latest_int_field("round")
    if round_number is None:
        round_number = 0
    base_sut_version = _latest_string_field("base_sut_version", "sut_version") or "unknown"

    manifest = {
        "schema_version": 1,
        "type": "patch_submission",
        "submission_id": submission_id,
        "round": round_number,
        "base_sut_version": base_sut_version,
        "patch_ref": "git:%s" % sha,
        "summary": summary,
        "tests_added": tests_added,
        "files": {"patch.tar": "sha256:%s" % tar_sha256},
    }
    _atomic_write_text(outbox / manifest_name, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    _stderr_log("submitted patch %s (tar %d bytes)" % (submission_id, os.path.getsize(tar_target)))
    return (
        {
            "submission_id": submission_id,
            "manifest": manifest_name,
            "archive": tar_name,
            "tar_sha256": tar_sha256,
            "round": round_number,
            "base_sut_version": base_sut_version,
        },
        {"submission_id": submission_id, "round": round_number, "commit": sha,
         "tar_bytes": os.path.getsize(tar_target), "tests_added": len(tests_added)},
    )


# ----------------------------------------------------------------------------
# promotion integrity
# ----------------------------------------------------------------------------

def _extract_promotion_tar(tar_path: Path, dest: Path) -> int:
    """Extract bounded regular files only; refuse links, devices and escapes."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with tarfile.open(tar_path) as bundle:
        members = bundle.getmembers()
        if len(members) > 50000 or sum(member.size for member in members) > 256 * 1024 * 1024:
            raise ToolError("promotion archive exceeds extraction limits")
        for member in members:
            name = Path(member.name)
            resolved = (root / name).resolve()
            # Path traversal guard: reject absolute paths, parent traversal,
            # and any member that resolves outside the extraction root.
            if (name.is_absolute()
                    or ".." in name.parts
                    or str(name).startswith("/")
                    or not str(resolved).startswith(str(root) + os.sep)
                    and str(resolved) != str(root)):
                raise ToolError("promotion archive member escapes destination: %s" % member.name)
        bundle.extractall(dest, filter="data")
    return sum(1 for member in members if member.isfile())


def _tool_apply_promotion(args: dict):
    tar_name = args.get("tar_name")
    if not isinstance(tar_name, str) or not tar_name.strip():
        raise ToolError("tar_name is required (non-empty string)")
    if tar_name != Path(tar_name).name or tar_name in {".", ".."}:
        raise ToolError("tar_name must be a bare inbox file name, got %r" % tar_name)
    inbox = EXCHANGE_DIR / "inbox"
    notices = []
    if inbox.is_dir():
        for path in sorted(inbox.glob("promotion-notice-*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and data.get("tar") == tar_name:
                notices.append((path, data))
    if not notices:
        raise ToolError("no promotion notice in the inbox matches tar_name %r" % tar_name)
    notice_path, notice = notices[-1]
    expected = notice.get("tar_sha256")
    if (not isinstance(expected, str) or not expected.startswith("sha256:")
            or len(expected) != len("sha256:") + 64):
        raise ToolError("promotion notice %s lacks a sha256:<hex> tar_sha256" % notice_path.name)
    tar_path = inbox / tar_name
    if not tar_path.is_file():
        raise ToolError("promotion tar %s not found in the inbox" % tar_name)
    actual = _sha256_file(tar_path)
    if actual != expected[len("sha256:"):]:
        # Never extract: a tampered tar must not reach SOURCE_DIR.
        raise ToolError("integrity mismatch: inbox tar sha256 %s != notice %s for %s"
                        % (actual, expected, tar_name))
    if not SOURCE_DIR.is_dir():
        raise ToolError("SOURCE_DIR %s does not exist" % SOURCE_DIR)
    rev = subprocess.run(
        ["git", "-C", str(SOURCE_DIR), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
    )
    if rev.returncode != 0:
        raise ToolError("not a git repo (git -C %s rev-parse HEAD failed): %s"
                        % (SOURCE_DIR, (rev.stderr or "").strip()[:200]))
    files_extracted = _extract_promotion_tar(tar_path, SOURCE_DIR)
    promotion_id = notice.get("submission_id") or notice.get("version_id") or "unknown"
    for git_args in (("add", "-A"), ("commit", "-m", "sync promoted %s" % promotion_id)):
        step = subprocess.run(
            ["git", "-C", str(SOURCE_DIR), *git_args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
        if step.returncode != 0:
            raise ToolError("git %s failed: %s"
                            % (" ".join(git_args), (step.stderr or "").strip()[:200]))
    sha = subprocess.run(
        ["git", "-C", str(SOURCE_DIR), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
    )
    _stderr_log("applied promotion %s (%d files)" % (promotion_id, files_extracted))
    return (
        {"promotion": promotion_id, "tar": tar_name, "notice": notice_path.name,
         "files_extracted": files_extracted, "commit": sha.stdout.strip(),
         "tar_sha256": actual},
        {"promotion": promotion_id, "notice": notice_path.name,
         "files_extracted": files_extracted, "verified_sha256": True},
    )


# ----------------------------------------------------------------------------
# tool registry
# ----------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_inbox",
        "description": "列出并读取 EXCHANGE_DIR/inbox 下全部 *.json（轮次简报、需修复的裁决摘要等），"
                       "返回文件名与解析后的内容。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_tests",
        "description": "在 SOURCE_DIR 执行测试套件（优先 python3 -m pytest tests/ -q --timeout=120，"
                       "不识别 --timeout 时退化 plain pytest，无 pytest 时退化 unittest discover；"
                       "超时杀掉）。返回 exit_code 与输出末尾 4000 字符。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "write_memory",
        "description": "向 WORKSPACE_DIR/memory/episodic-<YYYYMMDD>.md 追加一条记忆"
                       "（## <时间戳> <title> 后跟 content）。title ≤120 字符，content ≤8000 字符。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "submit_patch",
        "description": "提交补丁：git -C SOURCE_DIR archive --format=tar HEAD 输出复制到 "
                       "EXCHANGE_DIR/outbox/patch-pat-<sha12>.tar，随后写 manifest "
                       "patch-pat-<sha12>.json（SPEC §2.5，files 含 tar 的 sha256）。"
                       "提交前请先 commit；同一 commit 只能提交一次。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "补丁说明：根因、改动点、验证方式"},
                "tests_added": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "新增回归测试文件路径列表（可选）",
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "apply_promotion",
        "description": "应用晋级通知：在 inbox 的 promotion-notice-*.json 中定位 tar_name 匹配的条目，"
                       "校验该 tar 文件的 sha256 与通知内 tar_sha256 完全一致（不一致一律拒绝、绝不解包），"
                       "通过后将 tar 安全解包覆盖 SOURCE_DIR，并执行 git add -A 与 "
                       "git commit -m \"sync promoted <id>\"。禁止手动 tar xf 解包 inbox 的 tar。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tar_name": {
                    "type": "string",
                    "description": "晋级通知附带的 tar 文件名（inbox 内的裸文件名，如 promoted-pat-xxxx.tar）",
                },
            },
            "required": ["tar_name"],
        },
    },
]

TOOL_HANDLERS = {
    "read_inbox": _tool_read_inbox,
    "run_tests": _tool_run_tests,
    "write_memory": _tool_write_memory,
    "submit_patch": _tool_submit_patch,
    "apply_promotion": _tool_apply_promotion,
}


# ----------------------------------------------------------------------------
# JSON-RPC dispatch
# ----------------------------------------------------------------------------

def _dispatch_tool(params: dict):
    """Returns (mcp_result_payload, audit_detail, tool_name). Never raises."""
    name = params.get("name")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    tool_name = name if isinstance(name, str) and name else "<missing>"
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        payload = {
            "content": [{"type": "text", "text": "unknown tool: %r" % (name,)}],
            "isError": True,
        }
        return payload, {"ok": False, "error": "unknown tool: %r" % (name,)}, tool_name
    try:
        result, detail = handler(arguments)
        detail = dict(detail)
        detail.setdefault("ok", True)
        payload = {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": False,
        }
        return payload, detail, tool_name
    except ToolError as exc:
        _stderr_log("tool %s rejected: %s" % (tool_name, exc))
        detail = {"ok": False, "tool": tool_name, "error": str(exc)}
        payload = {"content": [{"type": "text", "text": "error: %s" % exc}], "isError": True}
        return payload, detail, tool_name
    except Exception as exc:  # defensive: a tool bug must not kill the loop
        _stderr_log("tool %s crashed: %r" % (tool_name, exc))
        detail = {"ok": False, "tool": tool_name,
                  "error": "%s: %s" % (type(exc).__name__, exc)}
        payload = {
            "content": [{"type": "text", "text": "internal error: %s: %s" % (type(exc).__name__, exc)}],
            "isError": True,
        }
        return payload, detail, tool_name


def _rpc_result(msg_id, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": msg_id, "result": result})


def _rpc_error(msg_id, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def _process_message(msg) -> None:
    if not isinstance(msg, dict):
        return
    method = msg.get("method")
    params = msg.get("params")
    if not isinstance(params, dict):
        params = {}
    msg_id = msg.get("id")
    has_id = ("id" in msg) and (msg_id is not None)

    if method == "initialize":
        if has_id:
            requested = params.get("protocolVersion")
            protocol = requested if isinstance(requested, str) and requested else DEFAULT_PROTOCOL_VERSION
            _rpc_result(msg_id, {
                "protocolVersion": protocol,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        return
    if method == "notifications/initialized":
        return  # notification: no id, no response
    if method == "tools/list":
        if has_id:
            _rpc_result(msg_id, {"tools": TOOLS})
        return
    if method == "tools/call":
        payload, detail, tool_name = _dispatch_tool(params)
        _audit(tool_name, params.get("arguments"), detail)
        if has_id:
            _rpc_result(msg_id, payload)
        return
    if method == "ping":
        if has_id:
            _rpc_result(msg_id, {})
        return
    if has_id:
        _rpc_error(msg_id, -32601, "method not found: %r" % (method,))
    return


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    _stderr_log(
        "starting %s v%s exchange=%s workspace=%s source=%s"
        % (SERVER_NAME, SERVER_VERSION, EXCHANGE_DIR, WORKSPACE_DIR, SOURCE_DIR)
    )
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except Exception:
            _stderr_log("skipping non-JSON line: %.120r" % line)
            continue
        try:
            _process_message(message)
        except Exception as exc:
            _stderr_log("message handler error: %r" % (exc,))
    _stderr_log("stdin closed, exiting")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
