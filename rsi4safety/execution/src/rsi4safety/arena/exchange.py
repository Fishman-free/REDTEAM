from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from ..domain import ViolationCode, stable_hash

SCHEMA_VERSION = 1

SEVERITIES = ("high", "medium", "low", "none")
HTTP_METHODS = ("GET", "POST", "PUT", "DELETE")
VIOLATION_CODE_VALUES = frozenset(code.value for code in ViolationCode)

ATTACK_ID_PATTERN = re.compile(r"^att-[0-9a-f]{12}$")
PATCH_ID_PATTERN = re.compile(r"^pat-[0-9a-f]{12}$")
FILE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class AttackSubmission:
    submission_id: str
    round: int
    title: str
    hypothesis: str
    task_id: str
    actions: tuple[dict, ...]
    notes: str = ""


@dataclass(frozen=True)
class Verdict:
    evidence_id: str
    round: int
    valid_finding: bool
    severity: str
    category: str
    rationale: str
    confirmed_violation_codes: tuple[str, ...]
    affects_authorized_utility: bool
    recommendation_scope: str = ""


@dataclass(frozen=True)
class PatchSubmission:
    submission_id: str
    round: int
    base_sut_version: str
    patch_ref: str
    summary: str
    tests_added: tuple[str, ...]
    files: dict


def write_json_atomic(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def new_submission_id(prefix: str, seed: dict) -> str:
    return f"{prefix}-{stable_hash(seed)[:12]}"


def _check_common(data: dict, expected_type: str, id_pattern: re.Pattern[str], id_field: str) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if data.get("type") != expected_type:
        errors.append(f"type must be {expected_type}")
    submission_id = data.get(id_field)
    if not isinstance(submission_id, str) or not id_pattern.fullmatch(submission_id):
        errors.append(f"{id_field} must match {id_pattern.pattern}")
    round_number = data.get("round")
    if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
        errors.append("round must be an integer >= 1")
    return errors


def _check_text(data: dict, field: str, errors: list[str], *, limit: int, allow_empty: bool = False) -> None:
    value = data.get(field)
    if not isinstance(value, str) or (not value and not allow_empty) or len(value) > limit:
        errors.append(f"{field} must be a {'non-empty ' if not allow_empty else ''}string of at most {limit} characters")


def validate_attack_submission(data: dict) -> tuple[AttackSubmission | None, list[str]]:
    if not isinstance(data, dict):
        return None, ["submission must be a JSON object"]
    errors = _check_common(data, "attack_submission", ATTACK_ID_PATTERN, "submission_id")
    for field in ("title", "hypothesis", "task_id"):
        _check_text(data, field, errors, limit=500)
    actions = data.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 10:
        errors.append("actions must be a list of 1 to 10 items")
        actions = []
    for index, action in enumerate(actions):
        label = f"actions[{index}]"
        if not isinstance(action, dict):
            errors.append(f"{label} must be an object")
            continue
        step = action.get("step")
        if not isinstance(step, int) or isinstance(step, bool):
            errors.append(f"{label}.step must be an integer")
        if action.get("method") not in HTTP_METHODS:
            errors.append(f"{label}.method must be one of GET/POST/PUT/DELETE")
        path = action.get("path")
        if not isinstance(path, str) or not path.startswith("/") or ".." in path:
            errors.append(f"{label}.path must start with / and contain no ..")
        body = action.get("json")
        if body is not None and not isinstance(body, dict):
            errors.append(f"{label}.json must be an object")
    notes = data.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 4000:
        errors.append("notes must be a string of at most 4000 characters")
    if errors:
        return None, errors
    return (
        AttackSubmission(
            submission_id=data["submission_id"],
            round=data["round"],
            title=data["title"],
            hypothesis=data["hypothesis"],
            task_id=data["task_id"],
            actions=tuple(dict(action) for action in data["actions"]),
            notes=data.get("notes", ""),
        ),
        [],
    )


def validate_verdict(data: dict) -> tuple[Verdict | None, list[str]]:
    if not isinstance(data, dict):
        return None, ["verdict must be a JSON object"]
    # Verdicts carry no submission id; they reference orchestrator-issued evidence ids.
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if data.get("type") != "verdict":
        errors.append("type must be verdict")
    round_number = data.get("round")
    if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
        errors.append("round must be an integer >= 1")
    _check_text(data, "evidence_id", errors, limit=200)
    _check_text(data, "category", errors, limit=200)
    _check_text(data, "rationale", errors, limit=8000)
    valid_finding = data.get("valid_finding")
    if not isinstance(valid_finding, bool):
        errors.append("valid_finding must be a boolean")
    severity = data.get("severity")
    if severity not in SEVERITIES:
        errors.append("severity must be one of high/medium/low/none")
    elif valid_finding is False and severity != "none":
        errors.append("severity must be none when valid_finding is false")
    affects_utility = data.get("affects_authorized_utility")
    if not isinstance(affects_utility, bool):
        errors.append("affects_authorized_utility must be a boolean")
    codes = data.get("confirmed_violation_codes")
    if not isinstance(codes, list) or any(not isinstance(code, str) for code in codes):
        errors.append("confirmed_violation_codes must be a list of strings")
        codes = None
    elif not set(codes).issubset(VIOLATION_CODE_VALUES):
        errors.append(
            "confirmed_violation_codes must be a subset of: " + ",".join(sorted(VIOLATION_CODE_VALUES))
        )
    scope = data.get("recommendation_scope", "")
    if not isinstance(scope, str) or len(scope) > 200:
        errors.append("recommendation_scope must be a string of at most 200 characters")
    if errors:
        return None, errors
    return (
        Verdict(
            evidence_id=data["evidence_id"],
            round=data["round"],
            valid_finding=valid_finding,
            severity=severity,
            category=data["category"],
            rationale=data["rationale"],
            confirmed_violation_codes=tuple(dict.fromkeys(codes)),
            affects_authorized_utility=affects_utility,
            recommendation_scope=scope,
        ),
        [],
    )


def validate_patch_submission(data: dict) -> tuple[PatchSubmission | None, list[str]]:
    if not isinstance(data, dict):
        return None, ["submission must be a JSON object"]
    errors = _check_common(data, "patch_submission", PATCH_ID_PATTERN, "submission_id")
    _check_text(data, "base_sut_version", errors, limit=200)
    _check_text(data, "summary", errors, limit=4000)
    patch_ref = data.get("patch_ref")
    if not isinstance(patch_ref, str) or not patch_ref.startswith("git:"):
        errors.append("patch_ref must start with git:")
    tests_added = data.get("tests_added")
    if not isinstance(tests_added, list) or any(not isinstance(item, str) for item in tests_added):
        errors.append("tests_added must be a list of strings")
        tests_added = []
    files = data.get("files")
    if not isinstance(files, dict) or set(files) != {"patch.tar"}:
        errors.append('files must contain exactly the key "patch.tar"')
    elif not isinstance(files["patch.tar"], str) or not FILE_DIGEST_PATTERN.fullmatch(files["patch.tar"]):
        errors.append("files['patch.tar'] must be a sha256:<64 hex> digest")
    if errors:
        return None, errors
    return (
        PatchSubmission(
            submission_id=data["submission_id"],
            round=data["round"],
            base_sut_version=data["base_sut_version"],
            patch_ref=data["patch_ref"],
            summary=data["summary"],
            tests_added=tuple(tests_added),
            files=dict(files),
        ),
        [],
    )


def _load_consumed(consumed_marker: Path) -> set[str]:
    if not consumed_marker.exists():
        return set()
    payload = json.loads(consumed_marker.read_text(encoding="utf-8"))
    names = payload.get("consumed", []) if isinstance(payload, dict) else payload
    return {name for name in names if isinstance(name, str)}


def read_new_submissions(outbox: Path, consumed_marker: Path) -> list[tuple[Path, dict]]:
    outbox = Path(outbox)
    consumed = _load_consumed(Path(consumed_marker))
    submissions: list[tuple[Path, dict]] = []
    if not outbox.is_dir():
        return submissions
    for path in sorted(outbox.glob("*.json")):
        if path.name in consumed:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            submissions.append((path, payload))
    return submissions


def mark_consumed(consumed_marker: Path, name: str) -> None:
    consumed_marker = Path(consumed_marker)
    consumed = _load_consumed(consumed_marker)
    consumed.add(name)
    write_json_atomic(consumed_marker, {"consumed": sorted(consumed)})
