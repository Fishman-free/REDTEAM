"""Locate the source checkout independently of the caller's working directory."""

from pathlib import Path


def project_root() -> Path:
    """Return the project containing the package and its executable assets.

    Arena runs from a source checkout (normally installed with ``pip install -e
    .``), because SUTs, role workspaces and Docker contexts are editable inputs.
    Looking up from this module avoids selecting an unrelated caller directory.
    """
    for candidate in Path(__file__).resolve().parents:
        if ((candidate / "pyproject.toml").is_file()
                and (candidate / "execution" / "src" / "rsi4safety").is_dir()
                and (candidate / "payment_agents").is_dir()
                and all((candidate / "execution" / name).is_dir() for name in ("agents", "docker"))):
            return candidate
    raise RuntimeError(
        "RSI4Safety source checkout not found; install the rsi4safety project "
        "with pip install -e . (ArenaConfig callers may supply repo_root explicitly)."
    )
