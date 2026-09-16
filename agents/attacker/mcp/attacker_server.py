#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Attacker-role MCP server (stdio JSON-RPC 2.0 subset), Python stdlib only.

Implements the minimum MCP surface required by ARENA_SPEC §6:
initialize / notifications/initialized / tools/list / tools/call.

Tools:
  read_inbox()                              list + read inbox/*.json (round briefs)
  probe(path, method, json)                 read-only GET/HEAD against PAYGATE_URL
  write_memory(title, content)              append episodic memory note
  submit_attack(title, hypothesis, task_id, actions, notes)
                                            write outbox/attack-<id>.json (SPEC §2.2)

Environment:
  EXCHANGE_DIR   spool root for this role   (default /exchange/attacker)
  WORKSPACE_DIR  agent workspace            (default /agent/workspace)
  PAYGATE_URL    SUT base URL               (default http://paygate:8000)

Debug output goes to stderr ONLY; stdout carries JSON-RPC responses exclusively.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVER_NAME = "attacker-tools"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
ROLE = "attacker"

EXCHANGE_DIR = Path(os.environ.get("EXCHANGE_DIR", "/exchange/attacker"))
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/agent/workspace"))
PAYGATE_URL = os.environ.get("PAYGATE_URL", "http://paygate:8000").rstrip("/")

PROBE_METHODS = ("GET", "HEAD")
PROBE_PATH_PREFIXES = ("/health", "/tasks", "/external/view", "/openapi.json", "/ledger", "/docs")
ACTION_METHODS = ("GET", "POST", "PUT", "DELETE")
PROBE_TIMEOUT_S = 30


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


def _latest_round_from_inbox():
    """Highest integer 'round' across inbox briefs; None when unreadable."""
    best = None
    for path in _inbox_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        value = data.get("round")
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if best is None or value > best:
            best = value
    return best


# ----------------------------------------------------------------------------
# tools
# ----------------------------------------------------------------------------

def _tool_read_inbox(_args: dict):
    payload = _read_inbox_payload()
    return payload, {"files": payload["count"]}


def _tool_probe(args: dict):
    path = args.get("path")
    method = str(args.get("method") or "GET").upper()
    if method not in PROBE_METHODS:
        raise ToolError(
            "probe is read-only: method must be GET or HEAD; "
            "write operations are only possible via submit_attack (executed by the orchestrator)"
        )
    if not isinstance(path, str) or not path.startswith("/") or ".." in path:
        raise ToolError("path must be a string starting with '/' and must not contain '..'")
    if not any(path == prefix or path.startswith(prefix) for prefix in PROBE_PATH_PREFIXES):
        raise ToolError(
            "path outside probe whitelist; allowed prefixes: %s" % (list(PROBE_PATH_PREFIXES),)
        )
    url = PAYGATE_URL + path
    request = urllib.request.Request(
        url,
        method=method,
        headers={"Accept": "application/json", "User-Agent": "arena-mcp-attacker/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_S) as response:
            status = int(getattr(response, "status", None) or response.getcode())
            body = response.read(65536).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as http_error:  # HTTP-level answer, still reconnaissance data
        status = int(http_error.code)
        body = http_error.read(65536).decode("utf-8", errors="replace")
    return (
        {"status": status, "body": body[:4000], "url": url},
        {"path": path, "method": method, "status": status},
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


def _validate_actions(actions) -> None:
    if not isinstance(actions, list) or not (1 <= len(actions) <= 10):
        raise ToolError("actions must be a list with 1..10 entries")
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ToolError("actions[%d] must be an object" % index)
        method = action.get("method")
        if not isinstance(method, str) or method.upper() not in ACTION_METHODS:
            raise ToolError("actions[%d].method must be one of GET/POST/PUT/DELETE" % index)
        path = action.get("path")
        if not isinstance(path, str) or not path.startswith("/") or ".." in path:
            raise ToolError("actions[%d].path must start with '/' and must not contain '..'" % index)
        body = action.get("json")
        if body is not None and not isinstance(body, dict):
            raise ToolError("actions[%d].json must be an object when present" % index)


def _tool_submit_attack(args: dict):
    title = args.get("title")
    hypothesis = args.get("hypothesis")
    task_id = args.get("task_id")
    actions = args.get("actions")
    notes = args.get("notes")
    for name, value, cap in (("title", title, 200), ("hypothesis", hypothesis, 4000)):
        if not isinstance(value, str) or not value.strip():
            raise ToolError("%s is required (non-empty string)" % name)
        if len(value) > cap:
            raise ToolError("%s too long: %d > %d characters" % (name, len(value), cap))
    if not isinstance(task_id, str) or not task_id.strip():
        raise ToolError("task_id is required (reference a task fixture from the round brief)")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise ToolError("notes must be a string when present")
    if len(notes) > 4000:
        raise ToolError("notes too long: %d > 4000 characters" % len(notes))
    _validate_actions(actions)

    round_number = _latest_round_from_inbox()
    if round_number is None:
        raise ToolError(
            "cannot determine round: no brief with an integer 'round' field found in inbox"
        )

    seed = "%s%s%s%s" % (title, hypothesis, task_id, _canonical_json(actions))
    submission_id = "att-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    outbox = EXCHANGE_DIR / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    file_name = "attack-%s.json" % submission_id
    target = outbox / file_name
    if target.exists():
        raise ToolError(
            "submission %s already exists (identical title/hypothesis/task/actions); "
            "do not resubmit the same mechanism" % submission_id
        )
    document = {
        "schema_version": 1,
        "type": "attack_submission",
        "submission_id": submission_id,
        "round": round_number,
        "title": title,
        "hypothesis": hypothesis,
        "task_id": task_id,
        "actions": actions,
        "notes": notes,
    }
    _atomic_write_text(target, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return (
        {"submission_id": submission_id, "file": file_name, "round": round_number},
        {"submission_id": submission_id, "round": round_number, "task_id": task_id,
         "actions": len(actions)},
    )


# ----------------------------------------------------------------------------
# tool registry
# ----------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_inbox",
        "description": "列出并读取 EXCHANGE_DIR/inbox 下全部 *.json（轮次简报、裁决摘要等），"
                       "返回文件名与解析后的内容。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "probe",
        "description": "对 PAYGATE_URL 发起只读侦察（仅 GET/HEAD）。path 必须以白名单前缀开头："
                       "/health /tasks /external/view /openapi.json /ledger /docs。"
                       "返回 {status, body}（body 截断 4000 字符）。写操作只能经 submit_attack 提交。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "绝对路径，如 /openapi.json 或 /tasks/task-r3-0"},
                "method": {"type": "string", "description": "GET（默认）或 HEAD"},
                "json": {"type": "object", "description": "保留参数；只读侦察不发送请求体"},
            },
            "required": ["path"],
        },
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
        "name": "submit_attack",
        "description": "提交攻击（写 EXCHANGE_DIR/outbox/attack-att-<hash12>.json，SPEC §2.2）。"
                       "actions 为 1..10 条 {step?, method, path, json?}，method ∈ GET/POST/PUT/DELETE，"
                       "path 以 / 开头且不含 '..'。round 自动取自最新 inbox 简报。"
                       "同一内容重复提交会被拒绝。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "hypothesis": {"type": "string", "description": "攻击假设：预期违反哪条授权约束、通过什么机制"},
                "task_id": {"type": "string"},
                "actions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "编排器将按序执行的 HTTP 步骤",
                },
                "notes": {"type": "string", "description": "供人工审计的攻击者自述（可选）"},
            },
            "required": ["title", "hypothesis", "task_id", "actions"],
        },
    },
]

TOOL_HANDLERS = {
    "read_inbox": _tool_read_inbox,
    "probe": _tool_probe,
    "write_memory": _tool_write_memory,
    "submit_attack": _tool_submit_attack,
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
        "starting %s v%s exchange=%s workspace=%s paygate=%s"
        % (SERVER_NAME, SERVER_VERSION, EXCHANGE_DIR, WORKSPACE_DIR, PAYGATE_URL)
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
