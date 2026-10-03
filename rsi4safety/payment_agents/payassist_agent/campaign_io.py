"""Atomic writes shared by campaign components."""
import json
import os
import threading
from pathlib import Path

def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # A per-thread temp name keeps concurrent writers from racing on one file.
    temp = path.with_suffix(f"{path.suffix}.tmp-{os.getpid()}-{threading.get_ident()}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
