"""Initialize the platform custody vault from the Besu validator key.

The validator/deployer/operator/faucet-signer are intentionally the same
testnet account in this demo stack.  Secrets are read from the environment
and the shared volume; this script never prints a key.
"""

from __future__ import annotations

import os
from pathlib import Path

from redteam_platform.custody import Custody


def main() -> None:
    key = Path("/shared/keydir/key").read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit("validator key is empty")
    Path("/data").mkdir(parents=True, exist_ok=True)
    vault = Custody(Path("/data/vault.json"))
    for entry in ("operator", "treasury-owner", "faucet-signer"):
        vault.store(entry, key)
    vault.store(
        os.environ.get("PLATFORM_MODEL_KEY_ENTRY", "platform-model"),
        os.environ.get("PLATFORM_MODEL_KEY", "demo-key"),
    )
    print("vault initialized: operator / treasury-owner / faucet-signer / platform-model")


if __name__ == "__main__":
    main()
