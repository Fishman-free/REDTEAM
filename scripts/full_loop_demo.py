"""跑完整一轮：开题 -> 打穿 -> 导出 -> 生成修复 -> 验证 -> 发布 -> 用新版本再开题 -> 再打。

在雅加达服务器的仓库根目录运行：
    python3 scripts/full_loop_demo.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:3000/api"
PARENT = sys.argv[1] if len(sys.argv) > 1 else "e2e-mining-2"
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


def new_contest(version: str) -> dict:
    status, body = call("/mining/contests", {"version": version}, timeout=180)
    if status != 201:
        raise SystemExit(f"开题失败 {status}: {body}")
    return body


def attack(cid: str) -> str:
    proc = subprocess.run(
        ["docker", "exec", "-e", f"CONTEST_ID={cid}", CONTAINER, "python", "/tmp/attack.py"],
        capture_output=True,
        text=True,
        timeout=400,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = [line for line in out.strip().splitlines() if line.strip()][-6:]
    return "\n".join(tail)


def state(cid: str) -> dict:
    _, body = call(f"/contests/{cid}")
    return body["contest"]


def main() -> None:
    print(f"=== 1) 用未加固基线 {PARENT} 开题 ===")
    c1 = new_contest(PARENT)
    cid1 = c1["contest_id"]
    print(f"  contest  {cid1}")
    print(f"  靶钱包 W  {c1['wallet']}")
    print(f"  合法收款方 {c1['merchant']}")

    print("\n=== 2) 攻击（应当打穿） ===")
    print(attack(cid1))
    s1 = state(cid1)
    print(f"  -> state={s1['state']} winner={s1['winner']}")

    print("\n=== 3) 导出证据 -> 生成修复 -> 验证 -> 发布 ===")
    status, exported = call("/rsi/export", {"contest_id": cid1})
    print(f"  export    {status} {exported.get('case_id', '')[:20]}")
    status, proposal = call("/rsi/candidates", {"parent_version": PARENT})
    if status != 201:
        raise SystemExit(f"propose 失败 {status}: {proposal}")
    cand = proposal["candidate_id"]
    print(f"  candidate {cand}")
    status, verification = call(f"/rsi/candidates/{cand}/verify", {})
    print(f"  verify    {status} passed={verification.get('passed')}")
    for check in verification.get("checks", []):
        print(f"    {check['name']:<20} {check['status']:<12} {check['detail'][:70]}")
    status, promoted = call(f"/rsi/candidates/{cand}/promote", {})
    if status != 200:
        raise SystemExit(f"promote 失败 {status}: {promoted}")
    print(f"  promoted  {promoted['name']} digest={promoted['digest'][:16]}…")

    print("\n=== 4) 用修复后的版本开新题 ===")
    c2 = new_contest(promoted["name"])
    cid2 = c2["contest_id"]
    print(f"  contest  {cid2}")
    print(f"  defenseHash {c2['defense_hash'][:20]}…")

    print("\n=== 5) 再打一次（应当打不穿） ===")
    print(attack(cid2))
    s2 = state(cid2)
    print(f"  -> state={s2['state']} winner={s2['winner']} paid={s2['paid_count']}")
    print("\n结论：", "打不穿（宿主拦截生效）" if s2["state"] != "settled" else "仍然被打穿")


if __name__ == "__main__":
    main()
