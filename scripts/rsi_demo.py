"""跑一遍 RSI 闭环：候选修复 -> 离线验证 -> 尝试发布。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:3000/api"


def admin_key() -> str:
    path = os.path.expanduser("~/REDTEAM/deploy/.env.stack")
    for line in open(path, encoding="utf-8"):
        if line.startswith("PLATFORM_ADMIN_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no admin key")


def call(path: str, payload: dict | None = None, timeout: int = 300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method="POST" if payload is not None else "GET",
        headers={"X-Admin-Key": admin_key(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


status, proposal = call("/rsi/candidates", {"parent_version": "v0_demo"})
print(f"[propose] {status}")
if status != 201:
    raise SystemExit(f"propose failed: {proposal}")
cid = proposal["candidate_id"]
print(f"  candidate      {cid}")
print(f"  parent_digest  {proposal['parent_digest'][:16]}…")
print(f"  digest         {proposal['digest'][:16]}…")
changes = proposal.get("evidence", {}).get("changes", {})
print(f"  prompt_added   {len(changes.get('prompt_added', []))} 条")
print(f"  memory_added   {len(changes.get('memory_added', []))} 条")
for item in changes.get("memory_added", []):
    print(f"    - {item['rule']}")

status, verification = call(f"/rsi/candidates/{cid}/verify", {})
print(f"\n[verify] {status} passed={verification.get('passed')}")
for check in verification.get("checks", []):
    print(f"  {check['name']:<20} {check['status']:<12} {check['detail'][:90]}")
for replay in verification.get("replays", []):
    print(f"  replay {replay['case_id'][:14]} breached={replay['breached']} {replay['detail'][:60]}")

status, promoted = call(f"/rsi/candidates/{cid}/promote", {})
print(f"\n[promote] {status} {json.dumps(promoted, ensure_ascii=False)[:200]}")
