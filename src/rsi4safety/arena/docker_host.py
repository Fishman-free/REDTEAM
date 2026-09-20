from __future__ import annotations

import io
import hashlib
import os
from pathlib import Path
import queue
import re
import tarfile
import threading
import time
import urllib.request
import uuid

from .config import ArenaConfig


class DockerUnavailable(RuntimeError):
    pass


def _real_root(directory: Path) -> Path:
    """Resolve symlinked roots (version-store projections) and macOS /var prefixes."""
    return Path(os.path.realpath(directory))


def tree_digest(directory: Path) -> str:
    """Hash paths, executable bits and bytes; timestamps and owners are irrelevant."""
    digest = hashlib.sha256()
    directory = _real_root(directory)
    for member in _source_files(directory):
        data = member.read_bytes()
        relative = member.relative_to(directory).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big") + relative)
        digest.update(bytes([bool(member.stat().st_mode & 0o111)]))
        digest.update(len(data).to_bytes(8, "big") + data)
    return digest.hexdigest()


def _source_files(directory: Path):
    # A symlinked ROOT is legitimate platform state: the version store projects
    # sut trees as symlinks. Interior symlinks remain forbidden.
    import os as _os
    directory = Path(_os.path.realpath(directory))
    if not directory.is_dir():
        raise ValueError("source must be a real directory")
    ignored = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    for member in sorted(directory.rglob("*")):
        if ignored.intersection(member.relative_to(directory).parts):
            continue
        if member.is_symlink():
            raise ValueError(f"source archives do not permit symbolic links: {member.relative_to(directory)}")
        if member.is_file():
            yield member
        elif not member.is_dir():
            raise ValueError(f"source archives require regular files: {member.relative_to(directory)}")


def _safe_extract(bundle: tarfile.TarFile, target_dir: Path) -> None:
    """Extract only bounded regular files/directories, never links or devices."""
    root = target_dir.resolve()
    members = bundle.getmembers()
    if len(members) > 50000 or sum(item.size for item in members) > 256 * 1024 * 1024:
        raise ValueError("archive exceeds extraction limits")
    for member in members:
        if not member.isfile() and not member.isdir():
            raise ValueError("archive contains a link or special file")
        path = root / member.name
        if Path(member.name).is_absolute() or ".." in Path(member.name).parts or not path.resolve().is_relative_to(root):
            raise ValueError("archive path escapes its destination")
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent.is_relative_to(root)):
            raise ValueError("archive destination contains a symbolic link")
    for member in members:
        path = root / member.name
        if member.isdir():
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError("archive file has no content")
            # Existing symlinks have been resolved above; refuse even an in-root
            # link to prevent overwriting another extracted artifact via alias.
            if path.is_symlink():
                raise ValueError("archive destination is a symbolic link")
            with path.open("wb") as target:
                import shutil
                shutil.copyfileobj(stream, target)


def _docker_client():
    try:
        import docker
    except ImportError as exc:
        raise DockerUnavailable("the docker package is not installed; run: pip install docker") from exc
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001 - surfaced as one actionable error
        raise DockerUnavailable(
            "Docker daemon is not reachable. Start Docker Desktop (open -a Docker) "
            "and retry once it reports healthy."
        ) from exc


class DockerHost:
    """Owns every container, network and workspace volume the campaign touches.

    Networks:
      <id>-egress  bridge, internet access - the three agents and the LLM gateway.
      <id>-battle  internal, no internet  - attacker probes PayGate here; the SUT
                   and the LLM gateway also attach so PayGate can call the model.
      <id>-sutops  internal, no internet  - only the SUT publishes its port here so
                   the host orchestrator can drive executions; agents never attach.
    """

    def __init__(self, config: ArenaConfig) -> None:
        self.config = config
        self._client = None
        self._containers: dict[str, object] = {}
        self.gateway_token: str | None = None  # shared with the SUT for llm mode

    def set_gateway_token(self, token: str | None) -> None:
        self.gateway_token = token

    @property
    def client(self):
        if self._client is None:
            self._client = _docker_client()
        return self._client

    def ping(self) -> bool:
        return bool(self.client.ping())

    @property
    def prefix(self) -> str:
        return f"arena-{self.config.campaign_id}"

    def net(self, suffix: str) -> str:
        return f"{self.prefix}-{suffix}"

    def _labels(self, role: str = "") -> dict[str, str]:
        return {"arena.campaign": self.config.campaign_id, "arena.role": role}

    def _owns(self, resource, kind: str) -> bool:
        labels = getattr(resource, "labels", None)
        if not isinstance(labels, dict):
            labels = getattr(resource, "attrs", {}).get("Labels") or {}
        if labels.get("arena.campaign") is not None:
            return labels["arena.campaign"] == self.config.campaign_id
        # Exact legacy names only: campaign 'case' must not remove 'case-extra'.
        name = resource.name
        if kind == "network":
            return name in {self.net(suffix) for suffix in ("egress", "battle", "sutops")}
        if kind == "volume":
            return name in {f"{self.prefix}-{role}-ws" for role in ("attacker", "defender", "judge")}
        return name in {f"{self.prefix}-{role}" for role in ("attacker", "defender", "judge", "llm-gateway")} or bool(
            re.fullmatch(re.escape(self.prefix) + r"-sut(?:-recon)?-[0-9a-f]{1,12}", name))

    # -- topology ---------------------------------------------------------
    def ensure_networks(self) -> None:
        existing = {item.name for item in self.client.networks.list()}
        for suffix, internal in (("egress", False), ("battle", True), ("sutops", True)):
            name = self.net(suffix)
            if name not in existing:
                self.client.networks.create(name, driver="bridge", internal=internal, labels=self._labels(suffix))
            else:
                network = self.client.networks.get(name)
                if bool(network.attrs.get("Internal")) != internal:
                    raise DockerUnavailable(f"network {name} has unsafe isolation settings; recreate campaign networks")

    def _connect(self, container, network_suffix: str, aliases: list[str]) -> None:
        network = self.client.networks.list(names=[self.net(network_suffix)])[0]
        network.connect(container.id, aliases=aliases)

    def _detach_default_bridge(self, container) -> None:
        """create() without networking_config lands containers on the default
        bridge, where the embedded DNS server does no name resolution and every
        campaign container could reach every other. Explicit joins above are
        the real topology; remove the accidental bridge membership."""
        try:
            self.client.api.disconnect_container_from_network(container.id, "bridge")
        except Exception:  # noqa: BLE001 - already detached or daemon variance
            pass

    # -- images ----------------------------------------------------------
    def build_image(self, tag: str, context_dir: Path, dockerfile: str = "Dockerfile") -> str:
        context_dir = _real_root(Path(context_dir))
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                image, _ = self.client.images.build(path=str(context_dir), tag=tag,
                                                    dockerfile=dockerfile, rm=True)
                return image.id
            except Exception as exc:  # noqa: BLE001 - BuildKit intermittently
                # reports "Cannot locate specified Dockerfile" under load; one
                # retry clears it. Anything else, or a second failure, raises.
                last_error = exc
                if "Cannot locate specified Dockerfile" not in str(exc) or attempt:
                    raise
        raise last_error  # pragma: no cover - unreachable

    def sut_image(self, sut_dir: Path | None = None) -> str:
        """One image per SUT tree digest: parent and candidate never share a tag."""
        from docker.errors import ImageNotFound
        directory = sut_dir if sut_dir is not None else self.config.sut_dir
        tag = f"{self.prefix}-sut:{tree_digest(directory)[:12]}"
        try:
            self.client.images.get(tag)
        except ImageNotFound:
            self.build_image(tag, directory)
        return tag

    # -- agent workspaces ---------------------------------------------------
    def _put_tree_into_volume(self, volume: str, source: Path, dest: str) -> None:
        """Copy a host tree into a path inside a named volume (creates the volume)."""
        archive_path = self.config.state_dir / f"seed-{volume}-{dest.strip('/').replace('/', '-')}.tar"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        source = _real_root(Path(source))
        with tarfile.open(archive_path, "w") as archive:
            for member in _source_files(source):
                info = archive.gettarinfo(str(member), arcname=f"{dest.strip('/')}/{member.relative_to(source)}")
                info.uid = info.gid = 1001
                info.uname = info.gname = "agent"
                info.mode = 0o755 if info.mode & 0o111 else 0o644
                with member.open("rb") as handle:
                    archive.addfile(info, handle)
        if not any(v.name == volume for v in self.client.volumes.list()):
            self.client.volumes.create(name=volume, labels=self._labels("workspace"))
        container = self.client.containers.create(
            f"{self.prefix}-agent:latest", command=["true"], volumes=[f"{volume}:/agent"],
            labels=self._labels("workspace-seed"),
        )
        try:
            with archive_path.open("rb") as handle:
                container.put_archive("/agent", handle)
        finally:
            container.remove(force=True)
        archive_path.unlink(missing_ok=True)

    def seed_workspace(self, role: str) -> bool:
        """Copy agents/<role> into the persistent workspace volume once; idempotent."""
        marker = self.config.state_dir / "workspace-seeded" / role
        volume = f"{self.prefix}-{role}-ws"
        volume_exists = any(v.name == volume for v in self.client.volumes.list())
        if marker.exists() and volume_exists:
            return False
        if role == "defender" and not volume_exists:
            # A host marker can outlive a removed Docker volume. Reseeding the
            # role creates that volume before seed_defender_source checks it.
            (marker.parent / "defender-source").unlink(missing_ok=True)
        self._put_tree_into_volume(f"{self.prefix}-{role}-ws",
                                   self.config.repo_root / "agents" / role, "workspace")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("seeded\n", encoding="utf-8")
        return True

    def seed_defender_source(self) -> bool:
        """Give the defender its own writable git-able copy of the current SUT tree."""
        marker = self.config.state_dir / "workspace-seeded" / "defender-source"
        volume = f"{self.prefix}-defender-ws"
        if marker.exists() and any(v.name == volume for v in self.client.volumes.list()):
            return False
        self._put_tree_into_volume(f"{self.prefix}-defender-ws",
                                   self.config.sut_dir, "source")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("seeded\n", encoding="utf-8")
        return True

    def sync_defender_source(self, source_dir: Path) -> None:
        """Reset only the defender's source checkout to the active platform tree.

The new independent git root prevents a rejected candidate becoming the next
round's starting point. Persistent /agent/workspace memory remains untouched.
        """
        container = self._containers.get("defender") or self.client.containers.get(f"{self.prefix}-defender")
        staging = f".source-sync-{uuid.uuid4().hex}"
        buffer = io.BytesIO()
        source_dir = _real_root(Path(source_dir))
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for member in _source_files(source_dir):
                info = archive.gettarinfo(str(member), arcname=f"{staging}/{member.relative_to(source_dir).as_posix()}")
                info.uid = info.gid = 1001
                info.uname = info.gname = "agent"
                info.mode = 0o755 if info.mode & 0o111 else 0o644
                with member.open("rb") as handle:
                    archive.addfile(info, handle)
        buffer.seek(0)
        if not container.put_archive("/agent", buffer.getvalue()):
            raise DockerUnavailable("could not copy active source into defender container")
        # Fixed in-container paths only. Python gives explicit symlink handling;
        # git -C + an initialized .git cannot discover a parent repository.
        script = """import os, pathlib, shutil, subprocess, sys
root = pathlib.Path('/agent')
staging = root / sys.argv[1]
active = root / 'source'
if not staging.is_dir() or staging.is_symlink():
    raise RuntimeError('source staging directory invalid')
if active.is_symlink():
    active.unlink()
elif active.exists():
    shutil.rmtree(active)
staging.rename(active)
for path in [active, *active.rglob('*')]:
    os.chown(path, 1001, 1001)
env = dict(os.environ)
for key in list(env):
    if key.startswith('GIT_'):
        del env[key]
env['GIT_CONFIG_NOSYSTEM'] = '1'
env['GIT_CONFIG_GLOBAL'] = '/dev/null'
for args in [('init', '--quiet'), ('config', 'user.name', 'arena-defender'),
             ('config', 'user.email', 'arena@localhost'), ('add', '-A'),
             ('commit', '--quiet', '--allow-empty', '-m', 'active platform version')]:
    subprocess.run(['git', '-c', 'safe.directory=/agent/source', '-c', 'core.hooksPath=/dev/null',
                    '-c', 'init.templateDir=', '-C', str(active), *args], check=True, env=env)
for path in [active, *active.rglob('*')]:
    os.chown(path, 1001, 1001)
"""
        result = container.exec_run(["python3", "-c", script, staging], user="0", workdir="/agent")
        if result.exit_code:
            raise DockerUnavailable("defender source reset failed: " + result.output.decode("utf-8", errors="replace")[-2000:])

    # -- long-lived containers ----------------------------------------------
    def up_agents(self, api_key: str | None, gateway_token: str | None = None) -> None:
        from docker.types import Mount
        self.ensure_networks()
        egress = self.net("egress")
        self.config.sut_dir.mkdir(parents=True, exist_ok=True)
        for role in ("attacker", "defender", "judge"):
            self.seed_workspace(role)
            if role == "defender":
                self.seed_defender_source()
            env = self.config.agent_container_env(role, api_key, gateway_token)
            mounts = [Mount(target="/agent", source=f"{self.prefix}-{role}-ws", type="volume")]
            if role == "judge":
                self.config.evidence_dir.mkdir(parents=True, exist_ok=True)
                mounts.append(Mount(target="/evidence",
                                    source=str(self.config.evidence_dir.resolve()),
                                    type="bind", read_only=True))
            exchange = self.config.exchange_dir / role
            for sub in ("inbox", "outbox", "audit"):
                (exchange / sub).mkdir(parents=True, exist_ok=True)
            mounts.append(Mount(target=f"/exchange/{role}",
                                source=str(exchange.resolve()), type="bind"))
            # Docker Desktop's gRPC-FUSE can briefly cache a stale "missing"
            # verdict for host paths recreated seconds ago; retry once when
            # the source demonstrably exists.
            for attempt in range(2):
                try:
                    container = self.client.containers.create(
                        f"{self.prefix}-agent:latest", command=["sleep", "infinity"],
                        name=f"{self.prefix}-{role}", environment=env, mounts=mounts,
                        labels=self._labels(role),
                        mem_limit=self.config.docker_memory,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    if (attempt == 0 and "does not exist" in str(exc)
                            and exchange.exists()):
                        time.sleep(5)
                        continue
                    raise
            container.start()
            # docker-py silently drops create-time networking_config (all
            # containers land on the default bridge): attach networks
            # explicitly, then remove the accidental bridge membership.
            self._connect(container, "egress", [role])
            if role == "attacker":
                self._connect(container, "battle", [role])
            self._detach_default_bridge(container)
            self._containers[role] = container

    def up_gateway(self, api_key: str | None, gateway_token: str | None = None) -> None:
        """LLM egress proxy: the only internet path for agents and the SUT.

        The raw GLM key lives only here; callers authenticate with the
        per-campaign gateway token and are rate limited / model allowlisted.
        """
        self.ensure_networks()
        env = {
            "GLM_API_KEY": api_key or "",
            "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
            "GLM_ANTHROPIC_BASE_URL": self.config.glm_base_url,
            "GLM_OPENAI_BASE_URL": self.config.glm_openai_base_url,
            "GATEWAY_TOKEN": gateway_token or "",
        }
        container = self.client.containers.create(
            f"{self.prefix}-gateway:latest",
            name=f"{self.prefix}-llm-gateway", environment=env,
            labels=self._labels("gateway"),
            mem_limit="512m",
        )
        container.start()
        self._connect(container, "egress", ["llm-gateway"])
        self._connect(container, "battle", ["llm-gateway"])
        self._detach_default_bridge(container)
        self._containers["gateway"] = container

    # -- agent session execution ---------------------------------------------
    def exec_agent(self, role: str, command: list[str], env: dict[str, str] | None = None,
                   workdir: str = "/agent/workspace", timeout_seconds: int = 2400) -> tuple[int, str]:
        if type(timeout_seconds) is not int or timeout_seconds < 1:
            raise ValueError("timeout_seconds must be a positive integer")
        if not command:
            raise ValueError("agent command must not be empty")
        container = self._containers.get(role) or self.client.containers.get(f"{self.prefix}-{role}")
        self._containers[role] = container
        completed: queue.Queue = queue.Queue(maxsize=1)
        def blocking_exec():
            try:
                # GNU timeout owns a process group and escalates to SIGKILL;
                # waiting on a Future alone does not terminate a Docker exec.
                result = container.exec_run(
                    ["timeout", "--signal=INT", "--kill-after=5s", f"{timeout_seconds}s", *command],
                    workdir=workdir, environment=env or {}, demux=True,
                )
                completed.put((result, None))
            except Exception as exc:
                completed.put((None, exc))
        threading.Thread(target=blocking_exec, daemon=True).start()
        try:
            result, error = completed.get(timeout=timeout_seconds + 10)
        except queue.Empty:
            # A stuck transport/exec cannot make ThreadPoolExecutor.__exit__
            # wait forever. Terminate every process, retaining workspace volumes.
            container.kill()
            container.start()
            return 124, "agent execution deadline exceeded; container processes terminated"
        if error is not None:
            raise error
        stdout = (result.output[0] or b"").decode("utf-8", errors="replace")
        stderr = (result.output[1] or b"").decode("utf-8", errors="replace")
        return result.exit_code, stdout + ("\n[stderr]\n" + stderr if stderr else "")

    def pull_agent_transcripts(self, role: str, target_dir: Path) -> None:
        container = self._containers.get(role) or self.client.containers.get(f"{self.prefix}-{role}")
        target_dir.mkdir(parents=True, exist_ok=True)
        stream, _ = container.get_archive("/agent/.claude-home/projects")
        buffer = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(buffer)) as bundle:
            _safe_extract(bundle, target_dir)

    def snapshot_agent_volume(self, role: str, target_dir: Path) -> None:
        container = self._containers.get(role) or self.client.containers.get(f"{self.prefix}-{role}")
        target_dir.mkdir(parents=True, exist_ok=True)
        stream, _ = container.get_archive("/agent/workspace")
        (target_dir / f"{role}-workspace.tar").write_bytes(b"".join(stream))

    # -- SUT -------------------------------------------------------------------
    def start_sut(self, db_path: Path, *, gateway: str = "research",
                  llm_mode: str | None = None, name_suffix: str = "",
                  sut_dir: Path | None = None) -> "SutContainer":
        # db_path is the host's eventual evidence destination, never a mount.
        # Candidate-local planner state lives in an ephemeral tmpfs instead.
        name = f"{self.prefix}-sut{name_suffix}-{uuid.uuid4().hex[:12]}"
        env = {
            "PAYGATE_DB": "/data/paygate.sqlite",
            "PAYGATE_GATEWAY": gateway,
            "PAYGATE_LLM_MODE": llm_mode or self.config.sut_llm_mode,
            "PAYGATE_LLM_URL": "http://llm-gateway:8080/v1/chat/completions",
            **({"PAYGATE_LLM_TOKEN": self.gateway_token} if self.gateway_token else {}),
            # The conversational assistant SUT reads its own mode/model envs.
            **({"PAYASSIST_MODE": llm_mode or self.config.sut_llm_mode,
                "PAYASSIST_MODEL": os.getenv("PAYASSIST_MODEL", "deepseek-chat")}
               if self.config.sut_app == "payassist" else {}),
        }
        # Ports publish reliably only while the default bridge membership (the
        # network the binding proxy targets) exists; the SUT therefore keeps
        # it, and isolation comes from agents/gateway being detached from the
        # bridge - the attacker reaches paygate via the battle alias below.
        container = self.client.containers.create(
            self.sut_image(sut_dir), name=name,
            environment=env, labels=self._labels("sut"),
            tmpfs={"/data": "rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001",
                   "/tmp": "rw,nosuid,nodev,noexec,size=64m"},
            read_only=True, cap_drop=["ALL"], security_opt=["no-new-privileges"],
            pids_limit=128, nano_cpus=2_000_000_000,
            ports={"8000/tcp": ("127.0.0.1", 0)},
            mem_limit="1g",
        )
        try:
            container.start()
            self._connect(container, "battle", ["paygate"])
            container.reload()
            port = container.attrs["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"]
            sut = SutContainer(container, db_path, f"http://127.0.0.1:{port}")
            sut.wait_healthy()
            return sut
        except Exception:
            container.remove(force=True)
            raise

    # -- teardown ----------------------------------------------------------------
    def down(self, *, remove_volumes: bool = False) -> list[str]:
        removed: list[str] = []
        for container in self.client.containers.list(all=True):
            if self._owns(container, "container"):
                try:
                    container.remove(force=True)
                    removed.append(container.name)
                except Exception:  # noqa: BLE001 - teardown is best effort
                    pass
        for network in self.client.networks.list():
            if self._owns(network, "network"):
                try:
                    network.remove()
                except Exception:  # noqa: BLE001
                    pass
        if remove_volumes:
            for volume in self.client.volumes.list():
                if self._owns(volume, "volume"):
                    try:
                        volume.remove(force=True)
                    except Exception:  # noqa: BLE001
                        pass
        return removed


class SutContainer:
    """One fresh PayGate planner. Its private SQLite is never platform evidence."""

    def __init__(self, container, db_path: Path, base_url: str) -> None:
        self.container = container
        self.db_path = db_path
        self.base_url = base_url

    def wait_healthy(self, timeout_seconds: int = 90) -> None:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{self.base_url}/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            time.sleep(0.5)
        raise DockerUnavailable(f"PayGate did not become healthy: {last_error}")

    def stop(self) -> None:
        try:
            self.container.remove(force=True)
        except Exception:  # noqa: BLE001
            pass
