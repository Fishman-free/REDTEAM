from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .config import ArenaConfig


@dataclass
class SutExecution:
    """Everything one repetition against a fresh SUT instance produced."""

    fixture: dict
    actions: list
    db_path: Path | None = None
    http_trace: list[dict] = field(default_factory=list)
    ledger_rows: list[dict] = field(default_factory=list)
    ledger_ok: bool = False  # empty rows can be a legitimate no-payment outcome
    log: str = ""
    error: str | None = None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Http:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.trace: list[dict] = []

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        started = time.time()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw[:2000]
        self.trace.append({
            "method": method, "path": path, "body": body, "status": status,
            "response": parsed if not isinstance(parsed, str) else parsed,
            "duration_ms": round((time.time() - started) * 1000, 1),
        })
        return status, parsed

    def wait_healthy(self, timeout_seconds: float = 60) -> None:
        deadline = time.time() + timeout_seconds
        last: Exception | None = None
        while time.time() < deadline:
            try:
                status, _ = self.call("GET", "/health")
                if status == 200:
                    return
            except Exception as exc:  # noqa: BLE001
                last = exc
            time.sleep(0.3)
        raise RuntimeError(f"SUT not healthy: {last}")


def ledger_rows_from_file(db_path: Path) -> list[dict]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT request_id, order_id, recipient, amount_minor, currency, purpose, "
            "status, reason, created_at, seq FROM payments ORDER BY seq"
        )]
    finally:
        connection.close()


class BaseSutDriver:
    """Shared execution flow; subclasses provide start/stop and an HTTP endpoint."""

    def __init__(self, config: ArenaConfig) -> None:
        self.config = config
        self.execution = SutExecution(fixture={}, actions=[])
        self.http: _Http | None = None

    def start(self) -> None: ...
    def stop(self) -> str: ...

    def _reset(self, fixture: dict, actions: list) -> None:
        self.execution = SutExecution(fixture=dict(fixture), actions=json.loads(json.dumps(actions)),
                                      db_path=getattr(self, "db_path", None))

    def run(self, fixture: dict, actions: list) -> SutExecution:
        """Fresh instance: post the task, replay actions, then read the ledger file."""
        self._reset(fixture, actions)
        self.execution.db_path = self.db_path
        self.start()
        try:
            self.http = _Http(self.base_url)
            self.http.wait_healthy()
            status, created = self.http.call("POST", "/tasks", {
                "user_request": fixture["user_request"],
                "authorization": fixture["authorization"],
            })
            if status >= 400:
                self.execution.error = f"task creation failed: {status} {created}"
                return self.execution
            self.execution.http_trace.extend(self.http.trace)
            self.http.trace.clear()
            new_task_id = created["task_id"]
            actions = _materialize_placeholders(self.execution.actions, fixture)
            actions = _retarget_task_ids(actions, "{task_id}", new_task_id)
            if fixture.get("task_id") and fixture["task_id"] != new_task_id:
                actions = _retarget_task_ids(actions, fixture["task_id"], new_task_id)
            for action in actions:
                status, _ = self.http.call(action["method"], action["path"], action.get("json"))
                if status >= 500:
                    self.execution.error = f"server error at step {action.get('step')}: {status}"
                    break
            self.execution.http_trace.extend(self.http.trace)
        finally:
            log = self.stop()
            self.execution.log = log[-20000:]
        try:
            self.execution.ledger_rows = ledger_rows_from_file(self.db_path)
            self.execution.ledger_ok = True
        except sqlite3.Error as exc:
            self.execution.error = self.execution.error or f"ledger unreadable: {exc}"
        return self.execution

    def run_clean(self, fixture: dict) -> SutExecution:
        return self.run(fixture, [{"step": 1, "method": "POST",
                                   "path": "/tasks/{task_id}/run", "json": {}}])


def _materialize_placeholders(actions: list, fixture: dict) -> list:
    authorization = fixture.get("authorization", {})
    text = json.dumps(actions, ensure_ascii=False)
    for key, value in {
        "{order_id}": str(authorization.get("order_id", "")),
        "{amount}": str(authorization.get("exact_amount_minor", "")),
        "{recipient}": str(authorization.get("recipient", "")),
    }.items():
        text = text.replace(key, value)
    return json.loads(text)


def _retarget_task_ids(actions: list, old_id: str, new_id: str) -> list:
    retargeted = json.dumps(actions, ensure_ascii=False).replace(old_id, new_id)
    return json.loads(retargeted)


class InProcessSutDriver(BaseSutDriver):
    """Runs PayGate as a local uvicorn subprocess; used by dry-run and unit tests."""

    def __init__(self, config: ArenaConfig, *, gateway: str = "research") -> None:
        super().__init__(config)
        self.gateway = gateway
        self.port = _free_port()
        # Absolute: the SUT subprocess runs with a different cwd than the orchestrator.
        self.db_path = (config.state_dir / "tmp" / f"sut-{self.port}.sqlite").resolve()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._process: subprocess.Popen | None = None

    def start(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.unlink(missing_ok=True)
        env = dict(os.environ)
        env.update({
            "PAYGATE_DB": str(self.db_path),
            "PAYGATE_GATEWAY": self.gateway,
            "PAYGATE_LLM_MODE": self.config.sut_llm_mode,
        })
        self._process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=self.config.sut_dir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

    def stop(self) -> str:
        process = self._process
        self._process = None
        if process is None:
            return ""
        process.terminate()
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _ = process.communicate(timeout=10)
        return output.decode("utf-8", errors="replace")


class DockerSutDriver(BaseSutDriver):
    """Each repetition gets a brand-new PayGate container with a fresh ledger."""

    def __init__(self, config: ArenaConfig, docker_host, *, gateway: str = "research") -> None:
        super().__init__(config)
        self.docker_host = docker_host
        self.gateway = gateway
        self.db_path = config.state_dir / "tmp" / f"sut-{time.time_ns()}.sqlite"
        self.base_url = ""
        self._sut = None

    def start(self) -> None:
        self.db_path.unlink(missing_ok=True)
        self._sut = self.docker_host.start_sut(self.db_path, gateway=self.gateway,
                                               sut_dir=self.config.sut_dir)
        self.base_url = self._sut.base_url

    def stop(self) -> str:
        if self._sut is None:
            return ""
        try:
            logs = self._sut.container.logs(tail=400).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            logs = ""
        self._sut.stop()
        self._sut = None
        return logs
