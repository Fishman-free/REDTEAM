#!/usr/bin/env python3
"""Manage only this project's loopback SSH forward to the Studio model server."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "Qwen/Qwen3-4B-Instruct-2507"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "stop"))
    parser.add_argument("--host", default="studio", help="Existing SSH host alias")
    parser.add_argument("--local-port", type=int, default=18081)
    parser.add_argument("--remote-port", type=int, default=18080)
    args = parser.parse_args()
    if args.host.startswith("-") or any(c.isspace() for c in args.host):
        parser.error("host must be an SSH alias, not options")
    if not all(1 <= x <= 65535 for x in (args.local_port, args.remote_port)):
        parser.error("ports must be between 1 and 65535")
    state = ROOT / ".rsi4safety" / "studio"
    state.mkdir(parents=True, exist_ok=True)
    socket = state / f"ssh-{args.local_port}.sock"
    connection = ["ssh", "-S", str(socket), "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
    def control(action):
        return subprocess.run([*connection, "-O", action, args.host], capture_output=True,
                              text=True, timeout=10)
    running = control("check").returncode == 0
    if args.action == "stop":
        if running:
            result = control("exit")
            if result.returncode:
                raise SystemExit(result.stderr.strip())
        print(json.dumps({"status": "stopped", "local_port": args.local_port}))
        return
    if args.action == "start" and not running:
        result = subprocess.run([
            *connection, "-M", "-fNT", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
            "-L", f"127.0.0.1:{args.local_port}:127.0.0.1:{args.remote_port}", args.host,
        ], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise SystemExit(result.stderr.strip())
        running = True
    if not running:
        raise SystemExit("Project SSH tunnel is not running; use start.")
    base = f"http://127.0.0.1:{args.local_port}/v1"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base + "/models", timeout=10) as response:
        models = [m["id"] for m in json.load(response).get("data", [])]
    print(json.dumps({"status": "ready", "ssh_host": args.host, "base_url": base,
                      "models": models, "payment_model_available": DEFAULT_MODEL in models},
                     ensure_ascii=False, indent=2))
    if DEFAULT_MODEL not in models:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
