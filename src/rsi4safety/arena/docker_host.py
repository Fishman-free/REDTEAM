from __future__ import annotations

import io
from pathlib import Path
import tarfile
import time
import urllib.request

from .config import ArenaConfig


class DockerUnavailable(RuntimeError):
    pass


def tree_digest(directory: Path) -> str:
    """Content digest of a SUT tree; .git and caches never affect the key."""
    import hashlib
    import io
    import tarfile
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as bundle:
        for member in sorted(directory.rglob("*")):
            if member.is_file() and "__pycache__" not in member.parts and ".git" not in member.parts:
                bundle.add(member, arcname=str(member.relative_to(directory)))
    return hashlib.sha256(buffer.getvalue()).hexdigest()


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
      <id>-sutops  bridge                 - only the SUT publishes its port here so
                   the host orchestrator can drive executions; agents never attach.
    """

    def __init__(self, config: ArenaConfig) -> None:
        self.config = config
        self._client = None
        self._containers: dict[str, object] = {}

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

    # -- topology ---------------------------------------------------------
    def ensure_networks(self) -> None:
        existing = {item.name for item in self.client.networks.list()}
        for suffix, internal in (("egress", False), ("battle", True), ("sutops", False)):
            name = self.net(suffix)
            if name not in existing:
                self.client.networks.create(name, driver="bridge", internal=internal)

    def _connect(self, container, network_suffix: str, aliases: list[str]) -> None:
        network = self.client.networks.list(names=[self.net(network_suffix)])[0]
        network.connect(container.id, aliases=aliases)

    # -- images ----------------------------------------------------------
    def build_image(self, tag: str, context_dir: Path, dockerfile: str = "Dockerfile") -> str:
        image, _ = self.client.images.build(path=str(context_dir), tag=tag,
                                            dockerfile=dockerfile, rm=True)
        return image.id

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
        with tarfile.open(archive_path, "w") as archive:
            for member in sorted(source.rglob("*")):
                if member.is_file() and "__pycache__" not in member.parts:
                    archive.add(member, arcname=f"{dest.strip('/')}/{member.relative_to(source)}")
        if not any(v.name == volume for v in self.client.volumes.list()):
            self.client.volumes.create(name=volume)
        container = self.client.containers.create(
            f"{self.prefix}-agent:latest", command=["true"], volumes=[f"{volume}:/agent"]
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
        if marker.exists():
            return False
        self._put_tree_into_volume(f"{self.prefix}-{role}-ws",
                                   self.config.repo_root / "agents" / role, "workspace")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("seeded\n", encoding="utf-8")
        return True

    def seed_defender_source(self) -> bool:
        """Give the defender its own writable git-able copy of the current SUT tree."""
        marker = self.config.state_dir / "workspace-seeded" / "defender-source"
        if marker.exists():
            return False
        self._put_tree_into_volume(f"{self.prefix}-defender-ws",
                                   self.config.sut_dir, "source")
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("seeded\n", encoding="utf-8")
        return True

    # -- long-lived containers ----------------------------------------------
    def up_agents(self, api_key: str | None) -> None:
        from docker.types import Mount
        self.ensure_networks()
        egress = self.net("egress")
        self.config.sut_dir.mkdir(parents=True, exist_ok=True)
        for role in ("attacker", "defender", "judge"):
            self.seed_workspace(role)
            if role == "defender":
                self.seed_defender_source()
            env = self.config.agent_container_env(role, api_key)
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
            container = self.client.containers.create(
                f"{self.prefix}-agent:latest", command=["sleep", "infinity"],
                name=f"{self.prefix}-{role}", environment=env, mounts=mounts,
                networking_config=self.client.api.create_networking_config(
                    {egress: self.client.api.create_endpoint_config(aliases=[role])}
                ),
                mem_limit=self.config.docker_memory,
            )
            container.start()
            if role == "attacker":
                self._connect(container, "battle", [role])
            self._containers[role] = container

    def up_gateway(self, api_key: str | None) -> None:
        """LLM egress proxy: the only internet path PayGate is allowed to use."""
        self.ensure_networks()
        env = {"GLM_API_KEY": api_key or "", "GLM_OPENAI_BASE_URL": self.config.glm_openai_base_url}
        container = self.client.containers.create(
            f"{self.prefix}-gateway:latest",
            name=f"{self.prefix}-llm-gateway", environment=env,
            networking_config=self.client.api.create_networking_config(
                {self.net("egress"): self.client.api.create_endpoint_config(aliases=["llm-gateway"])}
            ),
            mem_limit="512m",
        )
        container.start()
        self._connect(container, "battle", ["llm-gateway"])
        self._containers["gateway"] = container

    # -- agent session execution ---------------------------------------------
    def exec_agent(self, role: str, command: list[str], env: dict[str, str] | None = None,
                   workdir: str = "/agent/workspace", timeout_seconds: int = 2400) -> tuple[int, str]:
        import concurrent.futures
        container = self._containers.get(role) or self.client.containers.get(f"{self.prefix}-{role}")
        self._containers[role] = container

        def blocking_exec():
            return container.exec_run(command, workdir=workdir,
                                      environment=env or {}, demux=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(blocking_exec)
            try:
                result = future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                # SIGINT lets Claude Code finish the current turn and flush its transcript.
                try:
                    container.exec_run(["pkill", "-INT", "-f", "claude"])
                except Exception:  # noqa: BLE001 - the kill is best effort
                    pass
                result = future.result(timeout=120)
        stdout = (result.output[0] or b"").decode("utf-8", errors="replace")
        stderr = (result.output[1] or b"").decode("utf-8", errors="replace")
        return result.exit_code, stdout + ("\n[stderr]\n" + stderr if stderr else "")

    def pull_agent_transcripts(self, role: str, target_dir: Path) -> None:
        container = self._containers.get(role) or self.client.containers.get(f"{self.prefix}-{role}")
        target_dir.mkdir(parents=True, exist_ok=True)
        stream, _ = container.get_archive("/agent/.claude-home/projects")
        buffer = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(buffer)) as bundle:
            bundle.extractall(target_dir)

    def snapshot_agent_volume(self, role: str, target_dir: Path) -> None:
        container = self._containers.get(role) or self.client.containers.get(f"{self.prefix}-{role}")
        target_dir.mkdir(parents=True, exist_ok=True)
        stream, _ = container.get_archive("/agent/workspace")
        (target_dir / f"{role}-workspace.tar").write_bytes(b"".join(stream))

    # -- SUT -------------------------------------------------------------------
    def start_sut(self, db_path: Path, *, gateway: str = "research",
                  llm_mode: str | None = None, name_suffix: str = "",
                  sut_dir: Path | None = None) -> "SutContainer":
        from docker.types import Mount
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.touch(exist_ok=True)
        name = f"{self.prefix}-sut{name_suffix}-{int(time.time() * 1000) % 10**9}"
        env = {
            "PAYGATE_DB": "/data/paygate.sqlite",
            "PAYGATE_GATEWAY": gateway,
            "PAYGATE_LLM_MODE": llm_mode or self.config.sut_llm_mode,
            "PAYGATE_LLM_URL": "http://llm-gateway:8080/v1/chat/completions",
        }
        container = self.client.containers.create(
            self.sut_image(sut_dir), name=name,
            environment=env,
            mounts=[Mount(target="/data/paygate.sqlite",
                          source=str(db_path.resolve()), type="bind")],
            networking_config=self.client.api.create_networking_config(
                {self.net("battle"): self.client.api.create_endpoint_config(aliases=["paygate"]),
                 self.net("sutops"): self.client.api.create_endpoint_config(aliases=[name])}
            ),
            ports={"8000/tcp": ("127.0.0.1", 0)},
            mem_limit="1g",
        )
        container.start()
        container.reload()
        port = container.attrs["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"]
        sut = SutContainer(container, db_path, f"http://127.0.0.1:{port}")
        sut.wait_healthy()
        return sut

    # -- teardown ----------------------------------------------------------------
    def down(self, *, remove_volumes: bool = False) -> list[str]:
        removed: list[str] = []
        for container in self.client.containers.list(all=True):
            if container.name.startswith(self.prefix):
                try:
                    container.remove(force=True)
                    removed.append(container.name)
                except Exception:  # noqa: BLE001 - teardown is best effort
                    pass
        for network in self.client.networks.list():
            if network.name.startswith(self.prefix + "-") and network.name != self.prefix:
                try:
                    network.remove()
                except Exception:  # noqa: BLE001
                    pass
        if remove_volumes:
            for volume in self.client.volumes.list():
                if volume.name.startswith(self.prefix + "-"):
                    try:
                        volume.remove(force=True)
                    except Exception:  # noqa: BLE001
                        pass
        return removed


class SutContainer:
    """One fresh PayGate instance bound to a host-side ledger file."""

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
