from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from .authorization import build_user_channel_plan
from .config import ArenaConfig
from .constitution import evaluate_authorization_dict, verify_ledger_schema
from .trusted_execution import TrustedPaymentExecutor


@dataclass
class SutExecution:
    """Everything one repetition against a fresh SUT instance produced."""

    fixture: dict
    actions: list
    db_path: Path | None = None
    http_trace: list[dict] = field(default_factory=list)
    ledger_rows: list[dict] = field(default_factory=list)
    ledger_ok: bool = False  # empty rows can be a legitimate no-payment outcome
    ledger_captured: bool = False  # host rows may survive a later artifact export failure
    log: str = ""
    error: str | None = None
    task_run_count: int = 0
    evidence_authority: str = "arena-host-payment-executor-v1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_PROCESS_TREE_TIMEOUT_SECONDS = 5
_PROCESS_WAIT_TIMEOUT_SECONDS = 5
_DB_CLEANUP_TIMEOUT_SECONDS = 5


def _terminate_process_tree(process: subprocess.Popen, *, force: bool) -> None:
    """Terminate the owned process group, including Windows venv children."""
    if os.name == "nt":
        # Always target the full tree: the Python launcher may have spawned a
        # venv child that still owns SQLite handles after the launcher exits.
        command = ["taskkill", "/PID", str(process.pid), "/T", "/F"]
        try:
            result = subprocess.run(command, capture_output=True,
                                    timeout=_PROCESS_TREE_TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Windows SUT process-tree termination timed out after "
                f"{_PROCESS_TREE_TIMEOUT_SECONDS}s (force={force})"
            ) from exc
        if result.returncode and process.poll() is None:
            detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                "Windows SUT process-tree termination failed"
                + (f": {detail[-300:]}" if detail else "")
            )
    else:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)



class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Http:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.trace: list[dict] = []

    def call(self, method: str, path: str, body: dict | None = None, *, timeout_seconds: float = 30) -> tuple[int, object]:
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("HTTP path must be relative to this SUT")
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        started = time.time()
        try:
            # Never follow SUT-controlled redirects or inherit a host HTTP proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=timeout_seconds) as response:
                status = response.status
                raw = response.read(2_000_001).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(2_000_001).decode("utf-8", errors="replace")
        except Exception as exc:
            self.trace.append({"method": method, "path": path, "body": body,
                               "status": None, "error": str(exc),
                               "duration_ms": round((time.time() - started) * 1000, 1)})
            raise
        if len(raw.encode("utf-8")) > 2_000_000:
            raise ValueError("SUT response exceeds the 2 MB protocol limit")
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
        deadline = time.monotonic() + timeout_seconds
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                status, _ = self.call("GET", "/health", timeout_seconds=min(2, max(0.001, deadline - time.monotonic())))
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
        self._deadline: float | None = None

    def _remaining_seconds(self, phase: str) -> float:
        if self._deadline is None:
            return 30.0
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"SUT execution deadline exceeded during {phase} "
                f"(limit={self.config.sut_execution_timeout_seconds}s)"
            )
        return remaining

    def start(self) -> None: ...
    def stop(self) -> str: ...

    def _reset(self, fixture: dict, actions: list) -> None:
        self.execution = SutExecution(fixture=dict(fixture), actions=json.loads(json.dumps(actions)),
                                      db_path=getattr(self, "db_path", None))

    def run(self, fixture: dict, actions: list) -> SutExecution:
        """Replay scoped interference and execute payment proposals on the host.

The task always runs, even when a submitted attack only injects content or
probes health. An explicit run is preserved (including repeated runs) without
silently adding another. Target HTTP/database execution claims are untrusted.
        """
        self._reset(fixture, actions)
        self.execution.db_path = self.db_path
        executor: TrustedPaymentExecutor | None = None
        self.http = None
        self._deadline = time.monotonic() + self.config.sut_execution_timeout_seconds
        try:
            authorization = evaluate_authorization_dict(fixture["authorization"])
            # 图 1b：任务与确认变更经平台核验的用户通道形成可执行授权记录；
            # 外部攻击动作只走 /external/*，永远触碰不到 /user/confirm。
            channel_plan = build_user_channel_plan(fixture)
            executor = TrustedPaymentExecutor(
                authorization,
                guarded=getattr(self, "gateway", "research") == "guarded",
                auth_record=channel_plan.record if channel_plan is not None else None,
            )
            self.start()
            self.http = _Http(self.base_url)
            self.http.wait_healthy(timeout_seconds=min(60, self._remaining_seconds("health check")))
            status, created = self.http.call("POST", "/tasks", {
                "user_request": fixture["user_request"],
                "authorization": fixture["authorization"],
            })
            if status not in {200, 201}:
                raise ValueError(f"task creation failed: HTTP {status}")
            if not isinstance(created, dict) or not isinstance(created.get("task_id"), str):
                raise ValueError("task creation response must contain task_id")
            new_task_id = created["task_id"]
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", new_task_id):
                raise ValueError("SUT returned an invalid task_id")
            if channel_plan is not None:
                for message in channel_plan.messages[1:]:
                    status, _ = self.http.call(
                        "POST", "/user/confirm",
                        {"task_id": new_task_id, "subject": channel_plan.subject,
                         "content": message.content, "message_id": message.message_id},
                        timeout_seconds=min(30, self._remaining_seconds("user confirmation")),
                    )
                    self.http.trace[-1]["platform_triggered"] = True
                    if status not in {200, 201}:
                        raise ValueError(
                            f"user confirmation delivery failed: HTTP {status} "
                            "(the SUT must expose the verified user-dialogue entry)"
                        )
            actions = _materialize_placeholders(self.execution.actions, fixture)
            actions = _retarget_task_ids(actions, "{task_id}", new_task_id)
            if fixture.get("task_id") and fixture["task_id"] != new_task_id:
                actions = _retarget_task_ids(actions, fixture["task_id"], new_task_id)
            _validate_actions(actions, new_task_id)
            run_path = f"/tasks/{new_task_id}/run"
            if not any(action["path"] == run_path for action in actions):
                actions = [*actions, {"step": len(actions) + 1, "method": "POST",
                                     "path": run_path, "json": {}, "platform_triggered": True}]
            for action in actions:
                status, response = self.http.call(
                    action["method"], action["path"], action.get("json"),
                    timeout_seconds=min(30, self._remaining_seconds(f"action {action.get('step')}")))
                if not 200 <= status < 300:
                    raise ValueError(f"HTTP error at step {action.get('step')}: {status}")
                if action["path"] == run_path:
                    events = executor.accept_run_response(response)
                    self.http.trace[-1]["platform_triggered"] = action.get("platform_triggered", False)
                    self.http.trace[-1]["platform_events"] = events
            self.execution.task_run_count = executor.run_count
        except Exception as exc:
            self.execution.error = f"{type(exc).__name__}: {exc}"
        finally:
            if self.http is not None:
                self.execution.http_trace = list(self.http.trace)
            try:
                self.execution.log = self.stop()[-20000:]
            except Exception as exc:
                cleanup_error = f"SUT cleanup failed: {exc}"
                self.execution.error = (f"{self.execution.error}; {cleanup_error}"
                                       if self.execution.error else cleanup_error)
            self._deadline = None
            if executor is not None:
                try:
                    self.execution.task_run_count = executor.run_count
                    self.execution.ledger_rows = executor.rows()
                    self.execution.ledger_captured = True
                    executor.export(self.db_path)
                    self.execution.ledger_ok, reason = verify_ledger_schema(self.db_path)
                    if not self.execution.ledger_ok:
                        self.execution.error = self.execution.error or f"platform ledger schema: {reason}"
                except Exception as exc:
                    self.execution.error = self.execution.error or f"platform ledger export failed: {exc}"
                finally:
                    executor.close()
        return self.execution

    def run_clean(self, fixture: dict) -> SutExecution:
        return self.run(fixture, [{"step": 1, "method": "POST",
                                   "path": "/tasks/{task_id}/run", "json": {}}])


def _materialize_placeholders(actions: list, fixture: dict) -> list:
    authorization = fixture.get("authorization", {})
    replacements = {
        "{order_id}": str(authorization.get("order_id", "")),
        "{amount}": str(authorization.get("exact_amount_minor", "")),
        "{recipient}": str(authorization.get("recipient", "")),
    }
    def substitute(value):
        if isinstance(value, str):
            for token, replacement in replacements.items():
                value = value.replace(token, replacement)
            return value
        if isinstance(value, list):
            return [substitute(item) for item in value]
        if isinstance(value, dict):
            return {key: substitute(item) for key, item in value.items()}
        return value
    return substitute(actions)


def _validate_actions(actions: list, task_id: str) -> None:
    """Attackers may control external content, never trusted task creation."""
    if not isinstance(actions, list) or len(actions) > 128:
        raise ValueError("actions must be a list with at most 128 steps")
    allowed = {
        ("GET", "/health"),
        ("POST", "/external/merchant_message"),
        ("POST", "/external/invoice"),
        ("POST", "/external/webhook"),
        ("PUT", "/external/product_page"),
        ("POST", f"/tasks/{task_id}/run"),
        ("GET", f"/tasks/{task_id}"),  # read-only observation point for evidence
        *(("GET", f"/external/view/{surface}") for surface in
          ("merchant_message", "invoice", "webhook", "product_page")),
    }
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(f"action {index} must be an object")
        method, path = action.get("method"), action.get("path")
        if not isinstance(method, str) or not isinstance(path, str) or (method, path) not in allowed:
            raise ValueError(f"action {index} is outside the attack surface allowlist")
        body = action.get("json")
        if body is not None and not isinstance(body, dict):
            raise ValueError(f"action {index} json must be an object")
        if len(json.dumps(body, ensure_ascii=False).encode()) > 1_000_000:
            raise ValueError(f"action {index} exceeds the 1 MB protocol limit")
        if path == f"/tasks/{task_id}/run" and body not in (None, {}):
            raise ValueError("task run cannot override authorization or task inputs")


def _retarget_task_ids(actions: list, old_id: str, new_id: str) -> list:
    # A task identifier may be a substring of the authorized order/recipient.
    # Only endpoint identity is remapped, never payload text or trusted facts.
    retargeted = []
    prefix = f"/tasks/{old_id}"
    for action in actions:
        item = dict(action) if isinstance(action, dict) else action
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            path = item["path"]
            if path == prefix or path.startswith(prefix + "/"):
                item["path"] = f"/tasks/{new_id}" + path[len(prefix):]
        retargeted.append(item)
    return retargeted


class InProcessSutDriver(BaseSutDriver):
    """Local development runner for trusted fixtures; not a hostile-code sandbox.

Use DockerSutDriver for externally authored or adversarial candidate code.
    """

    def __init__(self, config: ArenaConfig, *, gateway: str = "research") -> None:
        super().__init__(config)
        self.gateway = gateway
        self.port = _free_port()
        # Absolute: the SUT subprocess runs with a different cwd than the orchestrator.
        self.db_path = (config.state_dir / "tmp" / f"sut-{self.port}.sqlite").resolve()
        self._private_db_path = self.db_path.with_suffix(".private.sqlite")
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._process: subprocess.Popen | None = None
        self._log_file = None

    def start(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._private_db_path.unlink(missing_ok=True)
        # Dry runs never need model credentials or the host's full environment.
        env = {key: value for key, value in os.environ.items()
               if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
        env.update({
            "PAYGATE_DB": str(self._private_db_path),
            "PAYGATE_GATEWAY": self.gateway,
            "PAYGATE_LLM_MODE": self.config.sut_llm_mode,
            # PayAssist reads its own mode env; deterministic enables offline bench.
            **({"PAYASSIST_MODE": "deterministic"} if self.config.sut_app == "payassist" else {}),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self._log_file = tempfile.TemporaryFile()
        self._process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=self.config.sut_dir, env=env,
            stdout=self._log_file, stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def stop(self) -> str:
        process = self._process
        self._process = None
        cleanup_errors: list[str] = []
        if process is not None:
            try:
                _terminate_process_tree(process, force=False)
            except ProcessLookupError:
                pass
            except Exception as exc:  # noqa: BLE001 - continue cleanup for diagnostics
                cleanup_errors.append(f"initial tree termination: {exc}")
            try:
                process.wait(timeout=_PROCESS_WAIT_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    _terminate_process_tree(process, force=True)
                except ProcessLookupError:
                    pass
                except Exception as exc:  # noqa: BLE001 - retain cleanup diagnostics
                    cleanup_errors.append(f"forced tree termination: {exc}")
                try:
                    process.wait(timeout=_PROCESS_WAIT_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as exc:
                    cleanup_errors.append(
                        f"process did not exit after {_PROCESS_WAIT_TIMEOUT_SECONDS}s: {exc}"
                    )
        if os.name == "nt" and process is not None:
            # taskkill may return before the descendant releases SQLite handles.
            deadline = time.monotonic() + _DB_CLEANUP_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                try:
                    self._private_db_path.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.1)
            else:
                cleanup_errors.append(
                    f"private database remained locked for {_DB_CLEANUP_TIMEOUT_SECONDS}s"
                )
        output = b""
        if self._log_file is not None:
            try:
                self._log_file.seek(0, os.SEEK_END)
                size = self._log_file.tell()
                self._log_file.seek(max(0, size - 20000))
                output = self._log_file.read()
            finally:
                self._log_file.close()
                self._log_file = None
        self._private_db_path.unlink(missing_ok=True)
        if cleanup_errors:
            raise RuntimeError("SUT cleanup failed: " + "; ".join(cleanup_errors))
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
