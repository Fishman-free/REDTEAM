"""从一场已结算的挖矿赛继续：生成修复 -> 验证 -> 发布 -> 用新版本开题 -> 再打一次。

    python3 scripts/finish_loop_demo.py <parent_version> <settled_contest_id>
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:3000/api"
CONTAINER = "rtm-arena-api-1"


def admin_key() -> str:
    for line in open("deploy/.env.stack", encoding="utf-8"):
        if line.startswith("PLATFORM_ADMIN_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no admin key")


KEY = admin_key()


def call(path: str, payload: dict | None = None, timeout: int = 300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method="POST" if payload is not None else "GET",
        headers={"X-Admin-Key": KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def attack(cid: str) -> str:
    proc = subprocess.run(
        ["docker", "exec", "-e", f"CONTEST_ID={cid}", CONTAINER, "python", "/tmp/attack.py"],
        capture_output=True,
        text=True,
        timeout=400,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return "\n".join([line for line in out.strip().splitlines() if line.strip()][-6:])


def main() -> None:
    parent = sys.argv[1]
    cid = sys.argv[2]

    print(f"=== 用案例 {cid[:20]}… 生成修复（父版本 {parent}） ===")
    status, exported = call("/rsi/export", {"contest_id": cid})
    print(f"  export     {status}")
    status, proposal = call("/rsi/candidates", {"parent_version": parent, "case_ids": [cid]})
    if status != 201:
        raise SystemExit(f"propose 失败 {status}: {proposal}")
    cand = proposal["candidate_id"]
    changes = proposal.get("evidence", {}).get("changes", {})
    print(f"  candidate  {cand}")
    print(f"  新增条款   {len(changes.get('prompt_added', []))} 条 / 新增 memory {len(changes.get('memory_added', []))} 条")

    status, verification = call(f"/rsi/candidates/{cand}/verify", {})
    print(f"  verify     {status} passed={verification.get('passed')}")
    for check in verification.get("checks", []):
        print(f"    {check['name']:<20} {check['status']:<12} {check['detail'][:70]}")

    status, promoted = call(f"/rsi/candidates/{cand}/promote", {})
    if status != 200:
        raise SystemExit(f"promote 失败 {status}: {promoted}")
    print(f"  promoted   {promoted['name']}  digest={promoted['digest'][:16]}…")

    print("\n=== 用修复后的版本开新题 ===")
    status, contest = call("/mining/contests", {"version": promoted["name"]}, timeout=180)
    if status != 201:
        raise SystemExit(f"开题失败 {status}: {contest}")
    cid2 = contest["contest_id"]
    print(f"  contest    {cid2}")
    print(f"  defenseHash {contest['defense_hash'][:20]}…")
    print(f"  合法收款方  {contest['merchant']}")

    print("\n=== 再打一次（应当打不穿） ===")
    print(attack(cid2))
    _, body = call(f"/contests/{cid2}")
    final = body["contest"]
    print(f"  -> state={final['state']} winner={final['winner']} paid={final['paid_count']}")
    print("\n结论：", "打不穿，宿主拦截生效" if final["state"] != "settled" else "仍然被打穿")


if __name__ == "__main__":
    main()
