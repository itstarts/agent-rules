#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True

from validate_codex_agents import ValidationError as RoleValidationError
from validate_codex_agents import validate_source


TRANSACTION_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
MANAGED_AGENT_VALUES = {
    "max_threads": 4,
    "max_depth": 1,
    "interrupt_message": True,
}
IN_PROGRESS_STATES = {"install-in-progress", "recover-in-progress", "restore-in-progress"}
JOURNAL_SCHEMA_VERSION = 2
ALL_JOURNAL_STATES = {
    "install-in-progress",
    "committed",
    "recover-in-progress",
    "recovered",
    "restore-in-progress",
    "restored",
}
LEGACY_MANAGED_ROLE_NAMES = tuple(
    sorted(
        {
            "architect",
            "data-consistency-reviewer",
            "final-gate-reviewer",
            "product-analyst",
            "reviewer",
            "spec-plan-reviewer",
            "test-engineer",
            "ui-ux-designer",
            "visual-reviewer",
            "worker-backend",
            "worker-frontend",
        }
    )
)


@dataclass(frozen=True)
class MergeResult:
    text: str
    added_keys: tuple[str, ...]
    table_created: bool
    changed: bool


class ConfigError(ValueError):
    pass


class InstallError(RuntimeError):
    pass


class ConflictError(InstallError):
    def __init__(self, message: str, *, category: str, name: str, snapshot: bytes) -> None:
        super().__init__(message)
        self.category = category
        self.name = name
        self.snapshot = snapshot

    @property
    def fingerprint(self) -> str:
        material = self.category.encode() + b"\0" + self.name.encode() + b"\0" + self.snapshot
        return hashlib.sha256(material).hexdigest()


def _managed_table_text() -> str:
    return "[agents]\nmax_threads = 4\nmax_depth = 1\ninterrupt_message = true\n"


def _toml_value(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _structural_views(text: str) -> list[str]:
    """Hide TOML strings/comments while preserving structural characters and line indexes."""
    views: list[str] = []
    state = "normal"
    escaped = False
    for line in text.splitlines(keepends=True):
        output = list(line)
        index = 0
        while index < len(line):
            if state == "normal":
                if line.startswith('"""', index):
                    output[index : index + 3] = "   "
                    state = "multiline-basic"
                    index += 3
                elif line.startswith("'''", index):
                    output[index : index + 3] = "   "
                    state = "multiline-literal"
                    index += 3
                elif line[index] == '"':
                    output[index] = " "
                    state = "basic"
                    escaped = False
                    index += 1
                elif line[index] == "'":
                    output[index] = " "
                    state = "literal"
                    index += 1
                elif line[index] == "#":
                    for rest in range(index, len(line)):
                        if line[rest] not in "\r\n":
                            output[rest] = " "
                    break
                else:
                    index += 1
            elif state == "basic":
                character = line[index]
                if character not in "\r\n":
                    output[index] = " "
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    state = "normal"
                index += 1
            elif state == "literal":
                character = line[index]
                if character not in "\r\n":
                    output[index] = " "
                if character == "'":
                    state = "normal"
                index += 1
            elif state == "multiline-basic":
                if line.startswith('"""', index):
                    output[index : index + 3] = "   "
                    state = "normal"
                    index += 3
                else:
                    if line[index] not in "\r\n":
                        output[index] = " "
                    index += 1
            else:
                if line.startswith("'''", index):
                    output[index : index + 3] = "   "
                    state = "normal"
                    index += 3
                else:
                    if line[index] not in "\r\n":
                        output[index] = " "
                    index += 1
        views.append("".join(output))
    return views


def _agents_table_indexes(text: str) -> list[int]:
    header = re.compile(r"^\s*\[agents\]\s*$")
    return [index for index, view in enumerate(_structural_views(text)) if header.fullmatch(view.rstrip("\r\n"))]


def _validate_agents_structure(text: str) -> int:
    views = _structural_views(text)
    indexes = _agents_table_indexes(text)
    if len(indexes) != 1:
        raise ConfigError("config.toml: unsafe-agents-structure")
    allowed_agents_header = re.compile(r"^\s*\[agents(?:\.[A-Za-z0-9_-]+)*\]\s*$")
    for view in views:
        structural = view.rstrip("\r\n")
        if re.match(r"^\s*\[agents(?:\.|\])", structural):
            if not allowed_agents_header.fullmatch(structural):
                raise ConfigError("config.toml: unsafe-agents-structure")

    header_index = indexes[0]
    end = len(views)
    for index in range(header_index + 1, len(views)):
        stripped = views[index].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
    bare_assignment = re.compile(r"^\s*[A-Za-z0-9_-]+\s*=")
    for view in views[header_index + 1 : end]:
        if "=" in view and not bare_assignment.match(view):
            raise ConfigError("config.toml: unsafe-agents-structure")
    return header_index


def merge_config_text(original: str | None) -> MergeResult:
    if original is None:
        return MergeResult(
            text=_managed_table_text(),
            added_keys=tuple(MANAGED_AGENT_VALUES),
            table_created=True,
            changed=True,
        )
    try:
        parsed = tomllib.loads(original)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("config.toml: invalid-toml") from exc
    features = parsed.get("features")
    if isinstance(features, dict) and features.get("multi_agent") is False:
        raise ConfigError("config.toml: multi-agent-disabled")
    if "agents" in parsed:
        agents = parsed["agents"]
        if not isinstance(agents, dict):
            raise ConfigError("config.toml: agents-not-table")
        header_index = _validate_agents_structure(original)
        conflicting = [
            key for key, expected in MANAGED_AGENT_VALUES.items() if key in agents and agents[key] != expected
        ]
        if conflicting:
            raise ConfigError(f"config.toml: managed-key-conflict:{conflicting[0]}")
        missing = tuple(key for key in MANAGED_AGENT_VALUES if key not in agents)
        if not missing:
            return MergeResult(original, (), False, False)
        lines = original.splitlines(keepends=True)
        insertion = "".join(f"{key} = {_toml_value(MANAGED_AGENT_VALUES[key])}\n" for key in missing)
        lines.insert(header_index + 1, insertion)
        candidate = "".join(lines)
        try:
            candidate_tree = tomllib.loads(candidate)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError("config.toml: candidate-invalid") from exc
        expected_tree = copy.deepcopy(parsed)
        expected_tree["agents"].update({key: MANAGED_AGENT_VALUES[key] for key in missing})
        if candidate_tree != expected_tree or len(_agents_table_indexes(candidate)) != 1:
            raise ConfigError("config.toml: candidate-tree-mismatch")
        return MergeResult(candidate, missing, False, True)
    separator = "" if not original else ("\n" if original.endswith("\n") else "\n\n")
    return MergeResult(
        text=original + separator + _managed_table_text(),
        added_keys=tuple(MANAGED_AGENT_VALUES),
        table_created=True,
        changed=True,
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _source_dir() -> Path:
    return _repo_root() / "codex" / "agents"


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_codex_root(*, allow_create: bool = True) -> tuple[Path, bool, tuple[int, int] | None]:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        root = Path(configured).expanduser()
        try:
            metadata = root.lstat()
        except FileNotFoundError as exc:
            raise InstallError("CODEX_HOME must already exist") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise InstallError("CODEX_HOME must be a real directory")
        created = False
        created_identity = None
    else:
        home = os.environ.get("HOME")
        if not home:
            raise InstallError("HOME is required when CODEX_HOME is unset")
        root = Path(home).expanduser() / ".codex"
        created = False
        created_identity = None
        if root.exists() or root.is_symlink():
            metadata = root.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise InstallError("default Codex root must be a real directory")
        else:
            if not allow_create:
                raise InstallError("default Codex root does not exist")
            parent = root.parent.resolve(strict=True)
            if _inside(parent, _repo_root().resolve()):
                raise InstallError("Codex root must stay outside the repository")
            root.mkdir(mode=0o700)
            created = True
            created_metadata = root.lstat()
            created_identity = (created_metadata.st_dev, created_metadata.st_ino)
    resolved = root.resolve(strict=True)
    if _inside(resolved, _repo_root().resolve()):
        if created:
            root.rmdir()
        raise InstallError("Codex root must stay outside the repository")
    return resolved, created, created_identity


def _created_root_still_matches(root: Path, identity: tuple[int, int] | None) -> bool:
    if identity is None:
        return False
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode) and (
        metadata.st_dev,
        metadata.st_ino,
    ) == identity


def _remove_created_root_if_safe(root: Path, identity: tuple[int, int] | None) -> None:
    if not _created_root_still_matches(root, identity):
        return
    try:
        root.rmdir()
    except OSError:
        pass


def _check_platform_capabilities() -> None:
    missing: list[str] = []
    for attribute in ("O_NOFOLLOW", "O_DIRECTORY"):
        if not hasattr(os, attribute):
            missing.append(attribute)
    for function in (os.open, os.stat, os.mkdir, os.unlink, os.symlink, os.rename):
        if function not in os.supports_dir_fd:
            missing.append(f"dir_fd:{function.__name__}")
    if not hasattr(fcntl, "flock"):
        missing.append("flock")
    if missing:
        raise InstallError("required filesystem capabilities unavailable: " + ",".join(missing))


def _open_directory_at(parent_fd: int, name: str, *, create: bool = False, mode: int = 0o700) -> int:
    if not name or "/" in name or name in {".", ".."}:
        raise InstallError("invalid directory component")
    if create:
        try:
            os.mkdir(name, mode=mode, dir_fd=parent_fd)
        except FileExistsError:
            pass
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise InstallError(f"unsafe directory:{name}") from exc
    metadata = os.fstat(fd)
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
        os.close(fd)
        raise InstallError(f"unsafe directory ownership-or-permissions:{name}")
    return fd


def _open_root(root: Path, *, lock: bool = True) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, flags)
    if os.fstat(fd).st_uid != os.getuid():
        os.close(fd)
        raise InstallError("Codex root must belong to the current user")
    if lock:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise InstallError("another codex-agents transaction holds the root lock") from exc
    return fd


def _verify_root_identity(root: Path, root_fd: int) -> None:
    try:
        path_stat = root.lstat()
    except FileNotFoundError as exc:
        raise InstallError("Codex root path disappeared during transaction") from exc
    fd_stat = os.fstat(root_fd)
    if stat.S_ISLNK(path_stat.st_mode) or (path_stat.st_dev, path_stat.st_ino) != (fd_stat.st_dev, fd_stat.st_ino):
        raise InstallError("Codex root path changed during transaction")


def _lstat_at(parent_fd: int, name: str) -> os.stat_result | None:
    if not name or "/" in name or name in {".", ".."}:
        raise InstallError("invalid filesystem component")
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _identity(metadata: os.stat_result) -> dict[str, int]:
    return {"dev": metadata.st_dev, "ino": metadata.st_ino}


def _identity_matches(metadata: os.stat_result | None, record: dict[str, Any], prefix: str) -> bool:
    return (
        metadata is not None
        and metadata.st_dev == record.get(f"{prefix}_dev")
        and metadata.st_ino == record.get(f"{prefix}_ino")
    )


def _read_regular_at(parent_fd: int, name: str) -> bytes:
    before = _lstat_at(parent_fd, name)
    if before is None or not stat.S_ISREG(before.st_mode):
        raise InstallError(f"expected regular file:{name}")
    if before.st_uid != os.getuid():
        raise InstallError(f"regular file must belong to current user:{name}")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise InstallError(f"file changed while opening:{name}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _create_file_at(parent_fd: int, name: str, content: bytes, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(name, flags, mode, dir_fd=parent_fd)
    try:
        os.fchmod(fd, mode)
        _write_all(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_file_at(parent_fd: int, name: str, content: bytes, mode: int = 0o600) -> None:
    temporary = f".{name}.tmp-{uuid.uuid4().hex}"
    _create_file_at(parent_fd, temporary, content, mode)
    try:
        temporary_metadata = _lstat_at(parent_fd, temporary)
        if temporary_metadata is None or not stat.S_ISREG(temporary_metadata.st_mode):
            raise InstallError("replacement temporary file changed")
        os.rename(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        if not _identity_matches(
            _lstat_at(parent_fd, name),
            {"temporary_dev": temporary_metadata.st_dev, "temporary_ino": temporary_metadata.st_ino},
            "temporary",
        ):
            raise InstallError("replacement file identity mismatch")
        os.fsync(parent_fd)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _transaction_id() -> str:
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(6)}"


def _journal_bytes(journal: dict[str, Any]) -> bytes:
    payload = base64.b64encode(
        json.dumps(journal["payload"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    lines = [
        f"schema_version = {JOURNAL_SCHEMA_VERSION}",
        f'transaction_id = "{journal["transaction_id"]}"',
        f'state = "{journal["state"]}"',
        f'root_path_b64 = "{base64.b64encode(journal["root_path"].encode()).decode("ascii")}"',
        f'root_identity = "{journal["root_identity"]}"',
        f'payload_b64 = "{payload}"',
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _load_journal(transaction_fd: int, transaction_id: str) -> dict[str, Any]:
    metadata = _lstat_at(transaction_fd, "journal.toml")
    if metadata is None or not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise InstallError("journal.toml must be a current-user regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise InstallError("journal.toml permissions are too broad")
    try:
        parsed = tomllib.loads(_read_regular_at(transaction_fd, "journal.toml").decode("utf-8"))
        payload = json.loads(base64.b64decode(parsed["payload_b64"], validate=True).decode("utf-8"))
        root_path = base64.b64decode(parsed["root_path_b64"], validate=True).decode("utf-8")
    except (KeyError, TypeError, UnicodeError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        raise InstallError("journal.toml is invalid") from exc
    if parsed.get("schema_version") != JOURNAL_SCHEMA_VERSION:
        raise InstallError("journal.toml schema mismatch")
    if set(parsed) != {
        "schema_version",
        "transaction_id",
        "state",
        "root_path_b64",
        "root_identity",
        "payload_b64",
    }:
        raise InstallError("journal.toml fields are invalid")
    if parsed.get("transaction_id") != transaction_id:
        raise InstallError("journal.toml transaction mismatch")
    if parsed.get("state") not in ALL_JOURNAL_STATES:
        raise InstallError("journal.toml state is invalid")
    if not isinstance(root_path, str) or not root_path:
        raise InstallError("journal.toml root path is invalid")
    if not isinstance(parsed.get("root_identity"), str) or not re.fullmatch(r"[0-9]+:[0-9]+", parsed["root_identity"]):
        raise InstallError("journal.toml root identity is invalid")
    if not isinstance(payload, dict) or not isinstance(payload.get("roles"), list):
        raise InstallError("journal.toml payload is invalid")
    _validate_journal_payload(payload, transaction_id, parsed["state"])
    _validate_journal_backups(transaction_fd, payload)
    return {
        "transaction_id": transaction_id,
        "state": parsed.get("state"),
        "root_path": root_path,
        "root_identity": parsed.get("root_identity"),
        "payload": payload,
    }


def _legacy_completed_state(transaction_fd: int, transaction_id: str) -> str | None:
    metadata = _lstat_at(transaction_fd, "journal.toml")
    if (
        metadata is None
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        return None
    try:
        parsed = tomllib.loads(_read_regular_at(transaction_fd, "journal.toml").decode("utf-8"))
        payload = json.loads(base64.b64decode(parsed["payload_b64"], validate=True).decode("utf-8"))
        root_path = base64.b64decode(parsed["root_path_b64"], validate=True).decode("utf-8")
    except (
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        tomllib.TOMLDecodeError,
        json.JSONDecodeError,
        InstallError,
    ):
        return None
    state = parsed.get("state")
    schema = parsed.get("schema_version")
    if (
        schema == 1
        and parsed.get("transaction_id") == transaction_id
        and state in {"recovered", "restored"}
    ):
        return state
    names = (
        [role.get("name") for role in payload.get("roles", []) if isinstance(role, dict)]
        if isinstance(payload, dict)
        else []
    )
    supported_history = (
        schema == JOURNAL_SCHEMA_VERSION
        and state in {"committed", "recovered", "restored"}
        and names == list(LEGACY_MANAGED_ROLE_NAMES)
    )
    if not supported_history:
        return None
    if (
        set(parsed)
        != {
            "schema_version",
            "transaction_id",
            "state",
            "root_path_b64",
            "root_identity",
            "payload_b64",
        }
        or parsed.get("transaction_id") != transaction_id
        or not isinstance(root_path, str)
        or not root_path
        or not isinstance(parsed.get("root_identity"), str)
        or not re.fullmatch(r"[0-9]+:[0-9]+", parsed["root_identity"])
    ):
        return None
    try:
        _validate_journal_payload(
            payload,
            transaction_id,
            state,
            expected_names=names,
            source_paths_must_exist=False,
        )
        _validate_journal_backups(transaction_fd, payload)
    except InstallError:
        return None
    return state


def _validate_journal_payload(
    payload: dict[str, Any],
    transaction_id: str,
    state: str,
    *,
    expected_names: list[str] | None = None,
    source_paths_must_exist: bool = True,
) -> None:
    if not set(payload) <= {"agents", "roles", "config", "restore_plan_ready"}:
        raise InstallError("journal.toml payload fields are invalid")
    plan_ready = payload.get("restore_plan_ready")
    if plan_ready is not None and not isinstance(plan_ready, bool):
        raise InstallError("journal.toml payload restore plan state is invalid")
    if state in {"install-in-progress", "committed"} and "restore_plan_ready" in payload:
        raise InstallError("journal.toml payload restore plan is invalid for state")
    if state in {"recover-in-progress", "restore-in-progress"} and not isinstance(plan_ready, bool):
        raise InstallError("journal.toml payload restore plan state is missing")
    if state in {"recovered", "restored"} and plan_ready is not True:
        raise InstallError("journal.toml payload completed restore plan is invalid")
    agents_state = payload.get("agents")
    if not isinstance(agents_state, dict) or agents_state.get("before_kind") not in {"missing", "directory"}:
        raise InstallError("journal.toml payload agents state is invalid")
    if not set(agents_state) <= {
        "before_kind",
        "before_dev",
        "before_ino",
        "install_object",
        "installed_dev",
        "installed_ino",
        "applied",
    }:
        raise InstallError("journal.toml payload agents fields are invalid")
    if agents_state["before_kind"] == "directory":
        if not all(isinstance(agents_state.get(key), int) for key in ("before_dev", "before_ino")):
            raise InstallError("journal.toml payload agents identity is invalid")
    else:
        if not all(isinstance(agents_state.get(key), int) for key in ("installed_dev", "installed_ino")):
            raise InstallError("journal.toml payload created agents identity is invalid")
        if agents_state.get("install_object") != "agents-object":
            raise InstallError("journal.toml payload agents object is invalid")
    if "applied" in agents_state and not isinstance(agents_state["applied"], bool):
        raise InstallError("journal.toml payload agents progress is invalid")
    expected_names = sorted(validate_source_names()) if expected_names is None else expected_names
    roles = payload.get("roles")
    if not isinstance(roles, list):
        raise InstallError("journal.toml payload is invalid")
    names = [role.get("name") for role in roles if isinstance(role, dict)]
    if names != expected_names or len(names) != len(roles):
        raise InstallError("journal.toml payload role set is invalid")
    for role in roles:
        name = role["name"]
        before_kind = role.get("before_kind")
        if not set(role) <= {
            "name",
            "filename",
            "before_kind",
            "source",
            "link_text",
            "digest",
            "mode",
            "before_dev",
            "before_ino",
            "backup",
            "install_object",
            "installed_dev",
            "installed_ino",
            "applied",
            "restore_object",
            "restore_dev",
            "restore_ino",
            "restored",
        }:
            raise InstallError("journal.toml payload role fields are invalid")
        if role.get("filename") != f"{name}.toml":
            raise InstallError("journal.toml payload role path is invalid")
        expected_source = str(
            (_source_dir() / f"{name}.toml").resolve(strict=source_paths_must_exist)
        )
        if role.get("source") != expected_source:
            raise InstallError("journal.toml payload role source is invalid")
        if before_kind not in {"missing", "ready", "regular", "symlink"}:
            raise InstallError("journal.toml payload role state is invalid")
        identity_prefix = "before" if before_kind != "missing" else None
        if identity_prefix and not all(isinstance(role.get(f"{identity_prefix}_{part}"), int) for part in ("dev", "ino")):
            raise InstallError("journal.toml payload role identity is invalid")
        if before_kind != "ready" and not all(isinstance(role.get(f"installed_{part}"), int) for part in ("dev", "ino")):
            raise InstallError("journal.toml payload installed role identity is invalid")
        if before_kind != "ready" and role.get("install_object") != f"install-{name}.toml":
            raise InstallError("journal.toml payload install role object is invalid")
        if before_kind == "ready" and any(
            key in role for key in ("install_object", "installed_dev", "installed_ino")
        ):
            raise InstallError("journal.toml payload ready role install fields are invalid")
        if before_kind == "missing" and any(
            key in role for key in ("before_dev", "before_ino", "backup", "digest", "mode", "link_text")
        ):
            raise InstallError("journal.toml payload missing role fields are invalid")
        if before_kind == "regular":
            if (
                role.get("backup") != f"role-{name}.bin"
                or not isinstance(role.get("digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", role["digest"])
                or not isinstance(role.get("mode"), int)
                or not 0 <= role["mode"] <= 0o777
            ):
                raise InstallError("journal.toml payload role backup is invalid")
        elif before_kind == "symlink":
            if role.get("backup") != f"role-{name}.symlink" or not isinstance(role.get("link_text"), str):
                raise InstallError("journal.toml payload symlink backup is invalid")
        for progress_key in ("applied", "restored"):
            if progress_key in role and not isinstance(role[progress_key], bool):
                raise InstallError("journal.toml payload role progress is invalid")
        if state in {"install-in-progress", "committed"} and any(
            key in role for key in ("restore_object", "restore_dev", "restore_ino", "restored")
        ):
            raise InstallError("journal.toml payload restore role fields are invalid for state")
        if "restore_object" not in role and any(key in role for key in ("restore_dev", "restore_ino")):
            raise InstallError("journal.toml payload restore role identity has no object")
        if "restore_object" in role:
            if plan_ready is None or before_kind not in {"regular", "symlink"}:
                raise InstallError("journal.toml payload restore role object is invalid for state")
            if role["restore_object"] != f"restore-{name}.toml":
                raise InstallError("journal.toml payload restore role object is invalid")
            restore_identity_complete = all(
                isinstance(role.get(f"restore_{part}"), int) for part in ("dev", "ino")
            )
            if plan_ready is True and not restore_identity_complete:
                raise InstallError("journal.toml payload restore role identity is invalid")
            if any(key in role for key in ("restore_dev", "restore_ino")) and not restore_identity_complete:
                raise InstallError("journal.toml payload restore role identity is incomplete")

    config = payload.get("config")
    if not isinstance(config, dict) or config.get("before_kind") not in {"missing", "regular"}:
        raise InstallError("journal.toml payload config state is invalid")
    if not set(config) <= {
        "before_kind",
        "before_digest",
        "before_mode",
        "before_dev",
        "before_ino",
        "candidate_b64",
        "installed_digest",
        "added_keys",
        "table_created",
        "changed",
        "backup",
        "install_temp",
        "installed_dev",
        "installed_ino",
        "applied",
        "restore_plan",
        "restored",
    }:
        raise InstallError("journal.toml payload config fields are invalid")
    for key in ("changed", "table_created"):
        if not isinstance(config.get(key), bool):
            raise InstallError(f"journal.toml payload config {key} is invalid")
    if not isinstance(config.get("before_mode"), int) or not 0 <= config["before_mode"] <= 0o777:
        raise InstallError("journal.toml payload config mode is invalid")
    if config["before_kind"] == "regular":
        if not all(isinstance(config.get(f"before_{part}"), int) for part in ("dev", "ino")):
            raise InstallError("journal.toml payload config identity is invalid")
        if not isinstance(config.get("before_digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", config["before_digest"]):
            raise InstallError("journal.toml payload config digest is invalid")
    if "install_temp" in config and not all(
        isinstance(config.get(f"installed_{part}"), int) for part in ("dev", "ino")
    ):
        raise InstallError("journal.toml payload installed config identity is invalid")
    if "install_temp" in config and config["install_temp"] not in {
        "install-config.toml",
        f".config.toml.agent-rules-{transaction_id}",
    }:
        raise InstallError("journal.toml payload install config object is invalid")
    added_keys = config.get("added_keys")
    if (
        not isinstance(added_keys, list)
        or len(added_keys) != len(set(added_keys))
        or any(key not in MANAGED_AGENT_VALUES for key in added_keys)
    ):
        raise InstallError("journal.toml payload config keys are invalid")
    if config["before_kind"] == "regular" and config.get("changed") and config.get("backup") != "config.bin":
        raise InstallError("journal.toml payload config backup is invalid")
    for progress_key in ("applied", "restored"):
        if progress_key in config and not isinstance(config[progress_key], bool):
            raise InstallError("journal.toml payload config progress is invalid")
    if state in {"install-in-progress", "committed"} and any(
        key in config for key in ("restore_plan", "restored")
    ):
        raise InstallError("journal.toml payload restore config fields are invalid for state")
    try:
        candidate = base64.b64decode(config["candidate_b64"], validate=True)
        candidate_tree = tomllib.loads(candidate.decode("utf-8"))
    except (KeyError, UnicodeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise InstallError("journal.toml payload config candidate is invalid") from exc
    if _digest(candidate) != config.get("installed_digest"):
        raise InstallError("journal.toml payload config digest is invalid")
    if any(candidate_tree.get("agents", {}).get(key) != value for key, value in MANAGED_AGENT_VALUES.items()):
        raise InstallError("journal.toml payload config values are invalid")
    plan = config.get("restore_plan")
    if plan is not None:
        if plan_ready is None:
            raise InstallError("journal.toml payload restore config plan is invalid for state")
        if not isinstance(plan, dict) or plan.get("input_state") not in {"installed", "installed-modified"}:
            raise InstallError("journal.toml payload restore config plan is invalid")
        if not set(plan) <= {
            "input_state",
            "input_dev",
            "input_ino",
            "input_digest",
            "input_b64",
            "output_missing",
            "output_temp",
            "output_dev",
            "output_ino",
            "output_digest",
            "output_b64",
        }:
            raise InstallError("journal.toml payload restore config fields are invalid")
        if not all(isinstance(plan.get(f"input_{part}"), int) for part in ("dev", "ino")):
            raise InstallError("journal.toml payload restore config input identity is invalid")
        if not isinstance(plan.get("input_digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", plan["input_digest"]):
            raise InstallError("journal.toml payload restore config input digest is invalid")
        if "input_b64" in plan:
            try:
                input_bytes = base64.b64decode(plan["input_b64"], validate=True)
            except (TypeError, ValueError) as exc:
                raise InstallError("journal.toml payload restore config input is invalid") from exc
            if _digest(input_bytes) != plan["input_digest"]:
                raise InstallError("journal.toml payload restore config input is inconsistent")
        elif state in {"recover-in-progress", "restore-in-progress"}:
            raise InstallError("journal.toml payload restore config input is missing")
        if not isinstance(plan.get("output_missing"), bool):
            raise InstallError("journal.toml payload restore config output is invalid")
        if not plan["output_missing"]:
            if plan.get("output_temp") != f".config.toml.restore-{transaction_id}":
                raise InstallError("journal.toml payload restore config path is invalid")
            output_identity_complete = all(isinstance(plan.get(f"output_{part}"), int) for part in ("dev", "ino"))
            if plan_ready is True and not output_identity_complete:
                raise InstallError("journal.toml payload restore config output identity is invalid")
            if any(key in plan for key in ("output_dev", "output_ino")) and not output_identity_complete:
                raise InstallError("journal.toml payload restore config output identity is incomplete")
            if not isinstance(plan.get("output_digest"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", plan["output_digest"]
            ):
                raise InstallError("journal.toml payload restore config output digest is invalid")
            try:
                output = base64.b64decode(plan["output_b64"], validate=True)
            except (KeyError, TypeError, ValueError) as exc:
                raise InstallError("journal.toml payload restore config output is invalid") from exc
            if _digest(output) != plan["output_digest"]:
                raise InstallError("journal.toml payload restore config output is inconsistent")
        elif any(
            key in plan
            for key in ("output_temp", "output_dev", "output_ino", "output_digest", "output_b64")
        ):
            raise InstallError("journal.toml payload missing restore output has extra fields")

    if plan_ready is None:
        if plan is not None or any("restore_object" in role for role in roles):
            raise InstallError("journal.toml payload restore plan fields are invalid for state")
    if state in {"recovered", "restored"} and (
        any(role.get("restored") is not True for role in roles) or config.get("restored") is not True
    ):
        raise InstallError("journal.toml payload completed restore progress is invalid")


def _validate_journal_backups(transaction_fd: int, payload: dict[str, Any]) -> None:
    def read_backup(name: str) -> bytes:
        metadata = _lstat_at(transaction_fd, name)
        if metadata is None or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise InstallError("journal.toml payload backup permissions are too broad")
        return _read_regular_at(transaction_fd, name)

    for role in payload["roles"]:
        if role["before_kind"] == "regular":
            if _digest(read_backup(role["backup"])) != role["digest"]:
                raise InstallError("journal.toml payload role backup digest is invalid")
        elif role["before_kind"] == "symlink":
            try:
                link_text = read_backup(role["backup"]).decode("utf-8")
            except UnicodeError as exc:
                raise InstallError("journal.toml payload symlink backup encoding is invalid") from exc
            if link_text != role["link_text"]:
                raise InstallError("journal.toml payload symlink backup is inconsistent")

    config = payload["config"]
    if config["before_kind"] == "missing":
        expected_merge = merge_config_text(None)
    elif config.get("changed"):
        backup = read_backup(config["backup"])
        if _digest(backup) != config.get("before_digest"):
            raise InstallError("journal.toml payload config backup digest is invalid")
        try:
            expected_merge = merge_config_text(backup.decode("utf-8"))
        except (UnicodeError, ConfigError) as exc:
            raise InstallError("journal.toml payload config backup is invalid") from exc
    else:
        return
    candidate = base64.b64decode(config["candidate_b64"], validate=True)
    if (
        candidate != expected_merge.text.encode("utf-8")
        or config["added_keys"] != list(expected_merge.added_keys)
        or config["table_created"] != expected_merge.table_created
        or config["changed"] != expected_merge.changed
    ):
        raise InstallError("journal.toml payload config transition is invalid")


def _save_journal(transaction_fd: int, journal: dict[str, Any]) -> None:
    _replace_file_at(transaction_fd, "journal.toml", _journal_bytes(journal), 0o600)


def _transaction_directories(root_fd: int, transaction_id: str) -> tuple[int, int, int, str]:
    backups_fd = _open_directory_at(root_fd, ".agent-rules-backups", create=True)
    namespace_fd = _open_directory_at(backups_fd, "codex-agents", create=True)
    staging_name = f".staging-{transaction_id}"
    try:
        os.mkdir(staging_name, mode=0o700, dir_fd=namespace_fd)
    except FileExistsError as exc:
        os.close(namespace_fd)
        os.close(backups_fd)
        raise InstallError("transaction directory already exists") from exc
    transaction_fd = _open_directory_at(namespace_fd, staging_name)
    os.fsync(namespace_fd)
    os.fsync(backups_fd)
    os.fsync(root_fd)
    return backups_fd, namespace_fd, transaction_fd, staging_name


def _publish_transaction(
    namespace_fd: int, transaction_fd: int, staging_name: str, transaction_id: str
) -> None:
    path_metadata = _lstat_at(namespace_fd, staging_name)
    opened_metadata = os.fstat(transaction_fd)
    if (
        path_metadata is None
        or not stat.S_ISDIR(path_metadata.st_mode)
        or stat.S_ISLNK(path_metadata.st_mode)
        or path_metadata.st_uid != os.getuid()
        or (path_metadata.st_dev, path_metadata.st_ino)
        != (opened_metadata.st_dev, opened_metadata.st_ino)
    ):
        raise InstallError("staging transaction changed before publish")
    os.rename(staging_name, transaction_id, src_dir_fd=namespace_fd, dst_dir_fd=namespace_fd)
    published = _lstat_at(namespace_fd, transaction_id)
    if not _identity_matches(published, {"published_dev": opened_metadata.st_dev, "published_ino": opened_metadata.st_ino}, "published"):
        raise InstallError("published transaction identity mismatch")
    os.fsync(namespace_fd)


def _remove_tree_at(parent_fd: int, name: str) -> None:
    directory_fd = _open_directory_at(parent_fd, name)
    try:
        for child in os.listdir(directory_fd):
            metadata = _lstat_at(directory_fd, child)
            if metadata is None:
                continue
            if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                _remove_tree_at(directory_fd, child)
            else:
                os.unlink(child, dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    os.rmdir(name, dir_fd=parent_fd)
    os.fsync(parent_fd)


def _remove_opened_tree_at(parent_fd: int, name: str, directory_fd: int) -> None:
    opened_metadata = os.fstat(directory_fd)
    for child in os.listdir(directory_fd):
        metadata = _lstat_at(directory_fd, child)
        if metadata is None:
            continue
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            _remove_tree_at(directory_fd, child)
        else:
            os.unlink(child, dir_fd=directory_fd)
    os.fsync(directory_fd)
    path_metadata = _lstat_at(parent_fd, name)
    if (
        path_metadata is None
        or not stat.S_ISDIR(path_metadata.st_mode)
        or stat.S_ISLNK(path_metadata.st_mode)
        or (path_metadata.st_dev, path_metadata.st_ino)
        != (opened_metadata.st_dev, opened_metadata.st_ino)
    ):
        raise InstallError("staging transaction changed before cleanup")
    os.rmdir(name, dir_fd=parent_fd)
    os.fsync(parent_fd)


def _validate_abandoned_staging(root_fd: int, transaction_fd: int, transaction_id: str) -> None:
    managed = set(validate_source_names())
    allowed_regular = {"install-config.toml", "config.bin"}
    allowed_regular.update(f"role-{name}.bin" for name in managed)
    allowed_regular.update(f"role-{name}.symlink" for name in managed)
    allowed_symlinks = {f"install-{name}.toml": str((_source_dir() / f"{name}.toml").resolve()) for name in managed}
    entries = set(os.listdir(transaction_fd))
    journal_temporaries = {
        name for name in entries if re.fullmatch(r"\.journal\.toml\.tmp-[0-9a-f]{32}", name)
    }
    if len(journal_temporaries) > 1 or (journal_temporaries and "journal.toml" in entries):
        raise InstallError("abandoned staging transaction is unsafe")
    allowed = allowed_regular | set(allowed_symlinks) | {"agents-object", "journal.toml"} | journal_temporaries
    if not entries <= allowed:
        raise InstallError("abandoned staging transaction is unsafe")
    for name in entries:
        metadata = _lstat_at(transaction_fd, name)
        if metadata is None or metadata.st_uid != os.getuid():
            raise InstallError("abandoned staging transaction is unsafe")
        if name == "agents-object":
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise InstallError("abandoned staging transaction is unsafe")
            agents_object_fd = _open_directory_at(transaction_fd, name)
            try:
                if os.listdir(agents_object_fd):
                    raise InstallError("abandoned staging transaction is unsafe")
            finally:
                os.close(agents_object_fd)
        elif name in allowed_symlinks:
            if not stat.S_ISLNK(metadata.st_mode) or os.readlink(name, dir_fd=transaction_fd) != allowed_symlinks[name]:
                raise InstallError("abandoned staging transaction is unsafe")
        elif not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise InstallError("abandoned staging transaction is unsafe")
    if "journal.toml" in entries:
        journal = _load_journal(transaction_fd, transaction_id)
        if journal["state"] != "install-in-progress":
            raise InstallError("abandoned staging transaction is unsafe")
        _verify_payload_prestate(root_fd, journal["payload"])


def _clean_abandoned_staging(root_fd: int, namespace_fd: int, staging_name: str) -> None:
    transaction_id = staging_name[9:]
    transaction_fd = _open_directory_at(namespace_fd, staging_name)
    try:
        path_metadata = _lstat_at(namespace_fd, staging_name)
        opened_metadata = os.fstat(transaction_fd)
        if (
            path_metadata is None
            or not stat.S_ISDIR(path_metadata.st_mode)
            or stat.S_ISLNK(path_metadata.st_mode)
            or (path_metadata.st_dev, path_metadata.st_ino)
            != (opened_metadata.st_dev, opened_metadata.st_ino)
        ):
            raise InstallError("abandoned staging transaction is unsafe")
        _validate_abandoned_staging(root_fd, transaction_fd, transaction_id)
        _remove_opened_tree_at(namespace_fd, staging_name, transaction_fd)
    finally:
        os.close(transaction_fd)


def _existing_transaction_directories(root_fd: int, transaction_id: str) -> tuple[int, int, int]:
    backups_fd = _open_directory_at(root_fd, ".agent-rules-backups")
    try:
        namespace_fd = _open_directory_at(backups_fd, "codex-agents")
    except BaseException:
        os.close(backups_fd)
        raise
    try:
        transaction_fd = _open_directory_at(namespace_fd, transaction_id)
    except BaseException:
        os.close(namespace_fd)
        os.close(backups_fd)
        raise
    return backups_fd, namespace_fd, transaction_fd


def _ensure_no_in_progress_transaction(root_fd: int, *, clean_staging: bool = False) -> None:
    if _lstat_at(root_fd, ".agent-rules-backups") is None:
        return
    backups_fd = namespace_fd = None
    try:
        backups_fd = _open_directory_at(root_fd, ".agent-rules-backups")
        if _lstat_at(backups_fd, "codex-agents") is None:
            return
        namespace_fd = _open_directory_at(backups_fd, "codex-agents")
        for transaction_id in sorted(os.listdir(namespace_fd)):
            if transaction_id.startswith(".staging-") and TRANSACTION_ID_RE.fullmatch(transaction_id[9:]):
                if clean_staging:
                    _clean_abandoned_staging(root_fd, namespace_fd, transaction_id)
                continue
            if not TRANSACTION_ID_RE.fullmatch(transaction_id):
                raise InstallError("invalid entry in codex-agents transaction namespace")
            transaction_fd = _open_directory_at(namespace_fd, transaction_id)
            try:
                try:
                    journal = _load_journal(transaction_fd, transaction_id)
                except InstallError:
                    if _legacy_completed_state(transaction_fd, transaction_id) is not None:
                        continue
                    raise
            finally:
                os.close(transaction_fd)
            if journal["state"] in IN_PROGRESS_STATES:
                command = "codex-agents-recover" if journal["state"] in {"install-in-progress", "recover-in-progress"} else "codex-agents-restore"
                raise InstallError(f"transaction {transaction_id} is {journal['state']}; run {command} {transaction_id}")
    finally:
        if namespace_fd is not None:
            os.close(namespace_fd)
        if backups_fd is not None:
            os.close(backups_fd)


def _role_preflight(agents_fd: int | None, name: str, source: Path) -> dict[str, Any]:
    filename = f"{name}.toml"
    if agents_fd is None:
        return {"name": name, "filename": filename, "before_kind": "missing", "source": str(source)}
    metadata = _lstat_at(agents_fd, filename)
    if metadata is None:
        return {"name": name, "filename": filename, "before_kind": "missing", "source": str(source)}
    before_identity = {"before_dev": metadata.st_dev, "before_ino": metadata.st_ino}
    if metadata.st_uid != os.getuid():
        raise InstallError(f"managed role must belong to current user:{filename}")
    if stat.S_ISLNK(metadata.st_mode):
        link_text = os.readlink(filename, dir_fd=agents_fd)
        if link_text == str(source):
            return {
                "name": name,
                "filename": filename,
                "before_kind": "ready",
                "source": str(source),
                "link_text": link_text,
                **before_identity,
            }
        try:
            os.stat(filename, dir_fd=agents_fd, follow_symlinks=True)
            target_exists = True
        except OSError as exc:
            if exc.errno not in {errno.ENOENT, errno.ELOOP}:
                raise
            target_exists = False
        if target_exists:
            raise ConflictError(
                f"managed role conflict:{filename}:foreign-symlink",
                category="role-symlink",
                name=filename,
                snapshot=link_text.encode("utf-8"),
            )
        return {
            "name": name,
            "filename": filename,
            "before_kind": "symlink",
            "source": str(source),
            "link_text": link_text,
            **before_identity,
        }
    if stat.S_ISREG(metadata.st_mode):
        content = _read_regular_at(agents_fd, filename)
        try:
            parsed = tomllib.loads(content.decode("utf-8"))
        except (UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ConflictError(
                f"managed role conflict:{filename}:invalid-toml",
                category="role-file",
                name=filename,
                snapshot=content,
            ) from exc
        if parsed.get("name") != name:
            raise ConflictError(
                f"managed role conflict:{filename}:name-mismatch",
                category="role-file",
                name=filename,
                snapshot=content,
            )
        return {
            "name": name,
            "filename": filename,
            "before_kind": "regular",
            "source": str(source),
            "digest": _digest(content),
            "mode": stat.S_IMODE(metadata.st_mode),
            **before_identity,
        }
    raise ConflictError(
        f"managed role conflict:{filename}:unsupported-type",
        category="role-special",
        name=filename,
        snapshot=f"mode:{stat.S_IFMT(metadata.st_mode):o}".encode("ascii"),
    )


def _preflight(root_fd: int) -> dict[str, Any]:
    agents_metadata = _lstat_at(root_fd, "agents")
    agents_fd: int | None = None
    agents_state: dict[str, Any]
    if agents_metadata is not None:
        if not stat.S_ISDIR(agents_metadata.st_mode) or stat.S_ISLNK(agents_metadata.st_mode):
            raise InstallError("agents target must be a real directory")
        agents_fd = _open_directory_at(root_fd, "agents")
        opened_agents = os.fstat(agents_fd)
        if (opened_agents.st_dev, opened_agents.st_ino) != (agents_metadata.st_dev, agents_metadata.st_ino):
            os.close(agents_fd)
            raise InstallError("agents directory changed during preflight")
        agents_state = {
            "before_kind": "directory",
            "before_dev": agents_metadata.st_dev,
            "before_ino": agents_metadata.st_ino,
        }
    else:
        agents_state = {"before_kind": "missing"}
    try:
        roles = [
            _role_preflight(agents_fd, name, (_source_dir() / f"{name}.toml").resolve(strict=True))
            for name in sorted(validate_source_names())
        ]
    finally:
        if agents_fd is not None:
            os.close(agents_fd)

    config_metadata = _lstat_at(root_fd, "config.toml")
    if config_metadata is None:
        original_bytes = None
        original_text = None
        original_mode = 0o600
    else:
        if not stat.S_ISREG(config_metadata.st_mode) or stat.S_ISLNK(config_metadata.st_mode):
            raise InstallError("config.toml must be a regular file")
        if config_metadata.st_uid != os.getuid():
            raise InstallError("config.toml must belong to current user")
        original_bytes = _read_regular_at(root_fd, "config.toml")
        try:
            original_text = original_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise InstallError("config.toml must be UTF-8") from exc
        original_mode = min(stat.S_IMODE(config_metadata.st_mode), 0o600)
    try:
        merge = merge_config_text(original_text)
    except ConfigError as exc:
        raise ConflictError(
            str(exc),
            category="config",
            name="config.toml",
            snapshot=original_bytes or b"",
        ) from exc
    config_state = {
        "before_kind": "missing" if original_bytes is None else "regular",
        "before_digest": None if original_bytes is None else _digest(original_bytes),
        "before_mode": original_mode,
        "candidate_b64": base64.b64encode(merge.text.encode("utf-8")).decode("ascii"),
        "installed_digest": _digest(merge.text.encode("utf-8")),
        "added_keys": list(merge.added_keys),
        "table_created": merge.table_created,
        "changed": merge.changed,
    }
    if config_metadata is not None:
        config_state.update({"before_dev": config_metadata.st_dev, "before_ino": config_metadata.st_ino})
    return {
        "agents": agents_state,
        "roles": roles,
        "config": config_state,
    }


def validate_source_names() -> list[str]:
    try:
        validate_source(_source_dir())
    except RoleValidationError as exc:
        raise InstallError(f"managed role source invalid:{exc}") from exc
    return [
        line.strip()
        for line in (_source_dir() / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _prepare_install_objects(
    transaction_fd: int,
    payload: dict[str, Any],
    failpoint: Callable[[str], None] | None,
) -> None:
    agents = payload["agents"]
    if agents["before_kind"] == "missing":
        object_name = "agents-object"
        os.mkdir(object_name, mode=0o700, dir_fd=transaction_fd)
        metadata = _lstat_at(transaction_fd, object_name)
        agents.update(
            {
                "install_object": object_name,
                "installed_dev": metadata.st_dev,
                "installed_ino": metadata.st_ino,
            }
        )
        if failpoint is not None:
            failpoint("agents-object-prepared")
    for role in payload["roles"]:
        if role["before_kind"] == "ready":
            continue
        object_name = f'install-{role["name"]}.toml'
        os.symlink(role["source"], object_name, dir_fd=transaction_fd)
        metadata = _lstat_at(transaction_fd, object_name)
        role.update(
            {
                "install_object": object_name,
                "installed_dev": metadata.st_dev,
                "installed_ino": metadata.st_ino,
            }
        )
        if failpoint is not None:
            failpoint(f'role-object-prepared:{role["name"]}')
    config = payload["config"]
    if config["changed"]:
        object_name = "install-config.toml"
        candidate = base64.b64decode(config["candidate_b64"], validate=True)
        _create_file_at(transaction_fd, object_name, candidate, config["before_mode"])
        metadata = _lstat_at(transaction_fd, object_name)
        config.update(
            {
                "install_temp": object_name,
                "installed_dev": metadata.st_dev,
                "installed_ino": metadata.st_ino,
            }
        )
        if failpoint is not None:
            failpoint("config-object-prepared")
    os.fsync(transaction_fd)
    if failpoint is not None:
        failpoint("install-objects-fsynced")


def _verify_payload_prestate(root_fd: int, payload: dict[str, Any]) -> None:
    agents_state = payload["agents"]
    agents_metadata = _lstat_at(root_fd, "agents")
    if agents_state["before_kind"] == "missing":
        if agents_metadata is not None:
            raise InstallError("agents directory changed after preflight")
    else:
        if not _identity_matches(agents_metadata, agents_state, "before"):
            raise InstallError("agents directory changed after preflight")
        agents_fd = _open_directory_at(root_fd, "agents")
        try:
            if not _identity_matches(os.fstat(agents_fd), agents_state, "before"):
                raise InstallError("agents directory changed after preflight")
            for role in payload["roles"]:
                metadata = _lstat_at(agents_fd, role["filename"])
                if role["before_kind"] == "missing":
                    if metadata is not None:
                        raise InstallError(f'role changed after preflight:{role["filename"]}')
                elif not _identity_matches(metadata, role, "before"):
                    raise InstallError(f'role changed after preflight:{role["filename"]}')
                elif role["before_kind"] == "regular" and _digest(
                    _read_regular_at(agents_fd, role["filename"])
                ) != role["digest"]:
                    raise InstallError(f'role content changed after preflight:{role["filename"]}')
                elif role["before_kind"] in {"ready", "symlink"} and os.readlink(
                    role["filename"], dir_fd=agents_fd
                ) != role["link_text"]:
                    raise InstallError(f'role link changed after preflight:{role["filename"]}')
        finally:
            os.close(agents_fd)
    config = payload["config"]
    config_metadata = _lstat_at(root_fd, "config.toml")
    if config["before_kind"] == "missing":
        if config_metadata is not None:
            raise InstallError("config.toml changed after preflight")
    else:
        if not _identity_matches(config_metadata, config, "before"):
            raise InstallError("config.toml changed after preflight")
        if _digest(_read_regular_at(root_fd, "config.toml")) != config["before_digest"]:
            raise InstallError("config.toml content changed after preflight")


def _backup_prestate(
    root_fd: int,
    payload: dict[str, Any],
    transaction_fd: int,
    failpoint: Callable[[str], None] | None,
) -> None:
    agents_fd: int | None = None
    if any(role["before_kind"] in {"regular", "symlink"} for role in payload["roles"]):
        agents_fd = _open_directory_at(root_fd, "agents")
        agents_metadata = os.fstat(agents_fd)
        if not _identity_matches(agents_metadata, payload["agents"], "before"):
            os.close(agents_fd)
            raise InstallError("agents directory changed before backup")
    try:
        for role in payload["roles"]:
            if role["before_kind"] == "regular":
                if not _identity_matches(_lstat_at(agents_fd, role["filename"]), role, "before"):
                    raise InstallError(f'role changed before backup:{role["filename"]}')
                content = _read_regular_at(agents_fd, role["filename"])
                if _digest(content) != role["digest"]:
                    raise InstallError(f'role content changed before backup:{role["filename"]}')
                backup_name = f'role-{role["name"]}.bin'
                _create_file_at(transaction_fd, backup_name, content, min(role["mode"], 0o600))
                role["backup"] = backup_name
                if failpoint is not None:
                    failpoint(f'backup-written:{role["name"]}')
            elif role["before_kind"] == "symlink":
                if not _identity_matches(_lstat_at(agents_fd, role["filename"]), role, "before"):
                    raise InstallError(f'role changed before backup:{role["filename"]}')
                if os.readlink(role["filename"], dir_fd=agents_fd) != role["link_text"]:
                    raise InstallError(f'role link changed before backup:{role["filename"]}')
                backup_name = f'role-{role["name"]}.symlink'
                _create_file_at(transaction_fd, backup_name, role["link_text"].encode("utf-8"), 0o600)
                role["backup"] = backup_name
                if failpoint is not None:
                    failpoint(f'backup-written:{role["name"]}')
        config = payload["config"]
        if config["before_kind"] == "regular" and config["changed"]:
            if not _identity_matches(_lstat_at(root_fd, "config.toml"), config, "before"):
                raise InstallError("config.toml changed before backup")
            content = _read_regular_at(root_fd, "config.toml")
            if _digest(content) != config["before_digest"]:
                raise InstallError("config.toml content changed before backup")
            _create_file_at(transaction_fd, "config.bin", content, min(config["before_mode"], 0o600))
            config["backup"] = "config.bin"
            if failpoint is not None:
                failpoint("backup-written:config")
        os.fsync(transaction_fd)
        if failpoint is not None:
            failpoint("backups-fsynced")
    finally:
        if agents_fd is not None:
            os.close(agents_fd)


def _install_roles(
    root: Path,
    root_fd: int,
    payload: dict[str, Any],
    transaction_fd: int,
    journal: dict[str, Any],
    failpoint: Callable[[str], None] | None,
) -> None:
    agents_state = payload["agents"]
    if agents_state["before_kind"] == "missing":
        if _lstat_at(root_fd, "agents") is not None:
            raise InstallError("agents directory changed before install")
        install_metadata = _lstat_at(transaction_fd, agents_state["install_object"])
        if not _identity_matches(install_metadata, agents_state, "installed") or not stat.S_ISDIR(
            install_metadata.st_mode
        ):
            raise InstallError("agents install object changed")
        os.rename(
            agents_state["install_object"],
            "agents",
            src_dir_fd=transaction_fd,
            dst_dir_fd=root_fd,
        )
        os.fsync(root_fd)
        agents_state["applied"] = True
        _save_journal(transaction_fd, journal)
    agents_fd = _open_directory_at(root_fd, "agents")
    try:
        expected_prefix = "installed" if agents_state["before_kind"] == "missing" else "before"
        _verify_agents_binding(root_fd, agents_fd, agents_state, expected_prefix)
        for role in payload["roles"]:
            if role["before_kind"] == "ready":
                role["applied"] = False
                continue
            _verify_root_identity(root, root_fd)
            _verify_agents_binding(root_fd, agents_fd, agents_state, expected_prefix)
            current = _lstat_at(agents_fd, role["filename"])
            if role["before_kind"] == "missing":
                if current is not None:
                    raise InstallError(f'target changed before install:{role["filename"]}')
            elif role["before_kind"] == "regular":
                if not _identity_matches(current, role, "before") or not stat.S_ISREG(current.st_mode):
                    raise InstallError(f'target changed before install:{role["filename"]}')
                if _digest(_read_regular_at(agents_fd, role["filename"])) != role["digest"]:
                    raise InstallError(f'target changed before install:{role["filename"]}')
            elif role["before_kind"] == "symlink":
                if not _identity_matches(current, role, "before") or not stat.S_ISLNK(current.st_mode):
                    raise InstallError(f'target changed before install:{role["filename"]}')
                if os.readlink(role["filename"], dir_fd=agents_fd) != role["link_text"]:
                    raise InstallError(f'target changed before install:{role["filename"]}')
            install_metadata = _lstat_at(transaction_fd, role["install_object"])
            if (
                not _identity_matches(install_metadata, role, "installed")
                or not stat.S_ISLNK(install_metadata.st_mode)
                or os.readlink(role["install_object"], dir_fd=transaction_fd) != role["source"]
            ):
                raise InstallError(f'role install object changed:{role["filename"]}')
            os.rename(
                role["install_object"],
                role["filename"],
                src_dir_fd=transaction_fd,
                dst_dir_fd=agents_fd,
            )
            os.fsync(agents_fd)
            if not _identity_matches(_lstat_at(agents_fd, role["filename"]), role, "installed"):
                raise InstallError(f'installed role identity mismatch:{role["filename"]}')
            role["applied"] = True
            if failpoint is not None:
                failpoint(f'role-applied:{role["name"]}')
            _save_journal(transaction_fd, journal)
    finally:
        os.close(agents_fd)


def _install_config(
    root: Path,
    root_fd: int,
    payload: dict[str, Any],
    transaction_fd: int,
    journal: dict[str, Any],
    failpoint: Callable[[str], None] | None,
) -> None:
    config = payload["config"]
    if not config["changed"]:
        config["applied"] = False
        return
    _verify_root_identity(root, root_fd)
    current = _lstat_at(root_fd, "config.toml")
    if config["before_kind"] == "missing":
        if current is not None:
            raise InstallError("config.toml changed before install")
    else:
        if not _identity_matches(current, config, "before") or not stat.S_ISREG(current.st_mode):
            raise InstallError("config.toml changed before install")
        if _digest(_read_regular_at(root_fd, "config.toml")) != config["before_digest"]:
            raise InstallError("config.toml changed before install")
    candidate = base64.b64decode(config["candidate_b64"], validate=True)
    try:
        parsed = tomllib.loads(candidate.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise InstallError("candidate config is invalid") from exc
    if parsed.get("agents", {}).get("max_threads") != 4 or len(_agents_table_indexes(candidate.decode("utf-8"))) != 1:
        raise InstallError("candidate config verification failed")
    temporary = config["install_temp"]
    if failpoint is not None:
        failpoint("config-prepared")
    temporary_metadata = _lstat_at(transaction_fd, temporary)
    if (
        not _identity_matches(temporary_metadata, config, "installed")
        or not stat.S_ISREG(temporary_metadata.st_mode)
        or _digest(_read_regular_at(transaction_fd, temporary)) != config["installed_digest"]
    ):
        raise InstallError("config install object changed")
    os.rename(temporary, "config.toml", src_dir_fd=transaction_fd, dst_dir_fd=root_fd)
    os.fsync(root_fd)
    final = _read_regular_at(root_fd, "config.toml")
    if _digest(final) != config["installed_digest"]:
        raise InstallError("final config verification failed")
    if not _identity_matches(_lstat_at(root_fd, "config.toml"), config, "installed"):
        raise InstallError("final config identity verification failed")
    tomllib.loads(final.decode("utf-8"))
    config["applied"] = True
    if failpoint is not None:
        failpoint("config-applied")
    _save_journal(transaction_fd, journal)


def _validate_installed(root_fd: int, payload: dict[str, Any]) -> None:
    agents_fd = _open_directory_at(root_fd, "agents")
    try:
        agents_prefix = "installed" if payload["agents"]["before_kind"] == "missing" else "before"
        if not _identity_matches(os.fstat(agents_fd), payload["agents"], agents_prefix):
            raise InstallError("installed agents directory identity mismatch")
        for role in payload["roles"]:
            metadata = _lstat_at(agents_fd, role["filename"])
            if metadata is None or not stat.S_ISLNK(metadata.st_mode):
                raise InstallError(f'installed role verification failed:{role["filename"]}')
            if os.readlink(role["filename"], dir_fd=agents_fd) != role["source"]:
                raise InstallError(f'installed role target mismatch:{role["filename"]}')
            identity_prefix = "before" if role["before_kind"] == "ready" else "installed"
            if not _identity_matches(metadata, role, identity_prefix):
                raise InstallError(f'installed role identity mismatch:{role["filename"]}')
    finally:
        os.close(agents_fd)
    config = tomllib.loads(_read_regular_at(root_fd, "config.toml").decode("utf-8"))
    if any(config["agents"].get(key) != value for key, value in MANAGED_AGENT_VALUES.items()):
        raise InstallError("installed config verification failed")
    if payload["config"]["changed"] and not _identity_matches(
        _lstat_at(root_fd, "config.toml"), payload["config"], "installed"
    ):
        raise InstallError("installed config identity mismatch")


def _verify_agents_binding(
    root_fd: int, agents_fd: int, agents_state: dict[str, Any], expected_prefix: str
) -> None:
    path_metadata = _lstat_at(root_fd, "agents")
    opened_metadata = os.fstat(agents_fd)
    if (
        not _identity_matches(path_metadata, agents_state, expected_prefix)
        or not _identity_matches(opened_metadata, agents_state, expected_prefix)
        or not stat.S_ISDIR(path_metadata.st_mode)
    ):
        raise InstallError("agents directory binding changed")


def _snapshot_conflict(root_fd: int, conflict: ConflictError) -> str:
    backups_fd = snapshots_fd = None
    try:
        backups_fd = _open_directory_at(root_fd, ".agent-rules-backups", create=True)
        snapshots_fd = _open_directory_at(backups_fd, "codex-agent-conflicts", create=True)
        name = f"{conflict.fingerprint}.snapshot"
        payload = json.dumps(
            {
                "category": conflict.category,
                "name": conflict.name,
                "content_b64": base64.b64encode(conflict.snapshot).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            _create_file_at(snapshots_fd, name, payload, 0o600)
            os.fsync(snapshots_fd)
            os.fsync(backups_fd)
            os.fsync(root_fd)
        except FileExistsError:
            if _read_regular_at(snapshots_fd, name) != payload:
                raise InstallError("conflict snapshot name collision")
        return conflict.fingerprint
    finally:
        if snapshots_fd is not None:
            os.close(snapshots_fd)
        if backups_fd is not None:
            os.close(backups_fd)


def _terminal_confirms_snapshot(message: str) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    print(f"{message}\n输入“只备份”创建幂等冲突快照并停止安装：", end="", flush=True)
    return input().strip() == "只备份"


def _role_state(agents_fd: int, role: dict[str, Any], transaction_fd: int) -> str:
    metadata = _lstat_at(agents_fd, role["filename"])
    if metadata is not None and stat.S_ISLNK(metadata.st_mode):
        link_text = os.readlink(role["filename"], dir_fd=agents_fd)
        if link_text == role["source"] and _identity_matches(metadata, role, "installed"):
            return "installed"
        if link_text == role["source"] and role["before_kind"] == "ready":
            if _identity_matches(metadata, role, "before"):
                return "before"
        if role["before_kind"] == "symlink" and link_text == role["link_text"]:
            if _identity_matches(metadata, role, "before") or _identity_matches(metadata, role, "restore"):
                return "before"
    if role["before_kind"] == "missing" and metadata is None:
        return "before"
    if role["before_kind"] == "regular" and metadata is not None and stat.S_ISREG(metadata.st_mode):
        if (
            _identity_matches(metadata, role, "before") or _identity_matches(metadata, role, "restore")
        ) and _digest(_read_regular_at(agents_fd, role["filename"])) == role["digest"]:
            backup = _read_regular_at(transaction_fd, role["backup"])
            if _digest(backup) == role["digest"]:
                return "before"
    return "other"


def _config_state(root_fd: int, config: dict[str, Any]) -> str:
    metadata = _lstat_at(root_fd, "config.toml")
    plan = config.get("restore_plan")
    if isinstance(plan, dict):
        if metadata is None:
            return "before" if plan.get("output_missing") is True else "other"
        if not stat.S_ISREG(metadata.st_mode):
            return "other"
        digest = _digest(_read_regular_at(root_fd, "config.toml"))
        if _identity_matches(metadata, plan, "output") and digest == plan.get("output_digest"):
            return "before"
        if _identity_matches(metadata, plan, "input") and digest == plan.get("input_digest"):
            return plan.get("input_state", "installed")
        return "other"
    if metadata is None:
        return "before" if config["before_kind"] == "missing" else "other"
    if not stat.S_ISREG(metadata.st_mode):
        return "other"
    digest = _digest(_read_regular_at(root_fd, "config.toml"))
    if _identity_matches(metadata, config, "installed") and digest == config["installed_digest"]:
        return "installed"
    if (
        config["before_kind"] == "regular"
        and _identity_matches(metadata, config, "before")
        and digest == config["before_digest"]
    ):
        return "before"
    if not config["changed"] and _identity_matches(metadata, config, "before") and digest == config["before_digest"]:
        return "before"
    try:
        _restore_config_candidate(_read_regular_at(root_fd, "config.toml").decode("utf-8"), config)
    except (UnicodeError, ConfigError):
        return "other"
    return "installed-modified"


def _restore_config_candidate(current: str, config: dict[str, Any]) -> bytes | None:
    try:
        current_tree = tomllib.loads(current)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("restore-config-invalid") from exc
    agents = current_tree.get("agents")
    if not isinstance(agents, dict):
        raise ConfigError("restore-agents-structure-changed")
    try:
        header_index = _validate_agents_structure(current)
    except ConfigError as exc:
        raise ConfigError("restore-agents-structure-changed") from exc
    for key in MANAGED_AGENT_VALUES:
        if agents.get(key) != MANAGED_AGENT_VALUES[key]:
            raise ConfigError(f"restore-managed-key-changed:{key}")

    lines = current.splitlines(keepends=True)
    views = _structural_views(current)
    end = len(lines)
    for index in range(header_index + 1, len(views)):
        structural = views[index].strip()
        if structural.startswith("[") and structural.endswith("]"):
            end = index
            break
    remove_indexes: set[int] = set()
    for key in config["added_keys"]:
        matcher = re.compile(rf"^\s*{re.escape(key)}\s*=")
        matches = [index for index in range(header_index + 1, end) if matcher.match(views[index])]
        if len(matches) != 1:
            raise ConfigError(f"restore-managed-key-location-changed:{key}")
        remove_indexes.add(matches[0])

    has_agents_child = any(
        re.fullmatch(r"\s*\[agents\.[A-Za-z0-9_.-]+\]\s*", view.rstrip("\r\n"))
        for view in views[header_index + 1 :]
    )
    parent_has_other_content = any(
        index not in remove_indexes and bool(views[index].strip())
        for index in range(header_index + 1, end)
    )
    if config["table_created"] and not parent_has_other_content and not has_agents_child:
        remove_indexes.add(header_index)
    candidate_text = "".join(line for index, line in enumerate(lines) if index not in remove_indexes)
    if not candidate_text.strip() and config["before_kind"] == "missing":
        return None
    try:
        candidate_tree = tomllib.loads(candidate_text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("restore-candidate-invalid") from exc
    expected_tree = copy.deepcopy(current_tree)
    expected_agents = expected_tree["agents"]
    for key in config["added_keys"]:
        del expected_agents[key]
    if config["table_created"] and not expected_agents:
        del expected_tree["agents"]
    if candidate_tree != expected_tree:
        raise ConfigError("restore-candidate-tree-mismatch")
    return candidate_text.encode("utf-8")


def _prepare_restore_plan(
    root_fd: int,
    agents_fd: int | None,
    transaction_fd: int,
    payload: dict[str, Any],
    journal: dict[str, Any],
    progress_state: str,
    failpoint: Callable[[str], None] | None = None,
) -> None:
    if "restore_plan_ready" not in payload:
        if agents_fd is not None:
            for role in payload["roles"]:
                if _role_state(agents_fd, role, transaction_fd) != "installed":
                    continue
                if role["before_kind"] in {"regular", "symlink"}:
                    role["restore_object"] = f'restore-{role["name"]}.toml'

        config = payload["config"]
        config_state = _config_state(root_fd, config)
        if config.get("changed") and config_state in {"installed", "installed-modified"}:
            current_metadata = _lstat_at(root_fd, "config.toml")
            current = _read_regular_at(root_fd, "config.toml")
            if config_state == "installed-modified":
                output = _restore_config_candidate(current.decode("utf-8"), config)
            elif config["before_kind"] == "missing":
                output = None
            else:
                output = _read_regular_at(transaction_fd, config["backup"])
            plan: dict[str, Any] = {
                "input_state": config_state,
                "input_dev": current_metadata.st_dev,
                "input_ino": current_metadata.st_ino,
                "input_digest": _digest(current),
                "input_b64": base64.b64encode(current).decode("ascii"),
                "output_missing": output is None,
            }
            if output is not None:
                plan.update(
                    {
                        "output_temp": f'.config.toml.restore-{journal["transaction_id"]}',
                        "output_digest": _digest(output),
                        "output_b64": base64.b64encode(output).decode("ascii"),
                    }
                )
            config["restore_plan"] = plan
        payload["restore_plan_ready"] = False
        journal["state"] = progress_state
        _save_journal(transaction_fd, journal)
        if failpoint is not None:
            failpoint("recovery-plan-persisted")

    for role in payload["roles"]:
        object_name = role.get("restore_object")
        if not isinstance(object_name, str):
            continue
        metadata = _lstat_at(transaction_fd, object_name)
        if "restore_dev" not in role:
            if metadata is None:
                if role["before_kind"] == "regular":
                    _create_file_at(
                        transaction_fd,
                        object_name,
                        _read_regular_at(transaction_fd, role["backup"]),
                        min(role["mode"], 0o600),
                    )
                else:
                    os.symlink(role["link_text"], object_name, dir_fd=transaction_fd)
                metadata = _lstat_at(transaction_fd, object_name)
            if role["before_kind"] == "regular":
                if (
                    metadata is None
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or _digest(_read_regular_at(transaction_fd, object_name)) != role["digest"]
                ):
                    raise InstallError(f'restore object invalid:{role["filename"]}')
            elif (
                metadata is None
                or not stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or os.readlink(object_name, dir_fd=transaction_fd) != role["link_text"]
            ):
                raise InstallError(f'restore object invalid:{role["filename"]}')
            if failpoint is not None:
                failpoint(f'restore-object-prepared:{role["name"]}')
            role.update({"restore_dev": metadata.st_dev, "restore_ino": metadata.st_ino})
            _save_journal(transaction_fd, journal)

    config = payload["config"]
    plan = config.get("restore_plan")
    if isinstance(plan, dict) and not plan["output_missing"] and "output_dev" not in plan:
        temporary = plan["output_temp"]
        output = base64.b64decode(plan["output_b64"], validate=True)
        metadata = _lstat_at(root_fd, temporary)
        if metadata is None:
            _create_file_at(root_fd, temporary, output, min(config["before_mode"], 0o600))
            metadata = _lstat_at(root_fd, temporary)
        if (
            metadata is None
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or _digest(_read_regular_at(root_fd, temporary)) != plan["output_digest"]
        ):
            raise InstallError("restore config object invalid")
        if failpoint is not None:
            failpoint("restore-config-object-prepared")
        plan.update({"output_dev": metadata.st_dev, "output_ino": metadata.st_ino})
        _save_journal(transaction_fd, journal)

    payload["restore_plan_ready"] = True
    _save_journal(transaction_fd, journal)


def _restore_role(agents_fd: int, role: dict[str, Any], transaction_fd: int) -> None:
    state = _role_state(agents_fd, role, transaction_fd)
    if state == "before":
        role["restored"] = True
        return
    if state != "installed":
        raise InstallError(f'restore target changed:{role["filename"]}')
    if role["before_kind"] == "missing":
        os.unlink(role["filename"], dir_fd=agents_fd)
    elif role["before_kind"] in {"regular", "symlink"}:
        restore_metadata = _lstat_at(transaction_fd, role["restore_object"])
        if not _identity_matches(restore_metadata, role, "restore"):
            raise InstallError(f'restore object changed:{role["filename"]}')
        if role["before_kind"] == "regular":
            if not stat.S_ISREG(restore_metadata.st_mode) or _digest(
                _read_regular_at(transaction_fd, role["restore_object"])
            ) != role["digest"]:
                raise InstallError(f'restore object changed:{role["filename"]}')
        elif not stat.S_ISLNK(restore_metadata.st_mode) or os.readlink(
            role["restore_object"], dir_fd=transaction_fd
        ) != role["link_text"]:
            raise InstallError(f'restore object changed:{role["filename"]}')
        os.rename(
            role["restore_object"],
            role["filename"],
            src_dir_fd=transaction_fd,
            dst_dir_fd=agents_fd,
        )
    role["restored"] = True
    os.fsync(agents_fd)


def _restore_config(root_fd: int, config: dict[str, Any], transaction_fd: int) -> None:
    state = _config_state(root_fd, config)
    if state == "before":
        config["restored"] = True
        return
    if state not in {"installed", "installed-modified"}:
        raise InstallError("restore config changed in managed structure")
    plan = config.get("restore_plan")
    if not isinstance(plan, dict):
        raise InstallError("restore config plan is missing")
    if plan["output_missing"]:
        os.unlink("config.toml", dir_fd=root_fd)
        os.fsync(root_fd)
    else:
        output_metadata = _lstat_at(root_fd, plan["output_temp"])
        if (
            not _identity_matches(output_metadata, plan, "output")
            or not stat.S_ISREG(output_metadata.st_mode)
            or _digest(_read_regular_at(root_fd, plan["output_temp"])) != plan["output_digest"]
        ):
            raise InstallError("restore config object changed")
        os.rename(plan["output_temp"], "config.toml", src_dir_fd=root_fd, dst_dir_fd=root_fd)
        os.fsync(root_fd)
        metadata = _lstat_at(root_fd, "config.toml")
        if not _identity_matches(metadata, plan, "output"):
            raise InstallError("restore config output identity mismatch")
        if _digest(_read_regular_at(root_fd, "config.toml")) != plan["output_digest"]:
            raise InstallError("restore config output digest mismatch")
    config["restored"] = True


def _validate_restore_plan_transition(config: dict[str, Any], transaction_fd: int) -> None:
    plan = config.get("restore_plan")
    if not isinstance(plan, dict):
        return
    try:
        input_bytes = base64.b64decode(plan["input_b64"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise InstallError("restore config plan input is invalid") from exc
    if _digest(input_bytes) != plan["input_digest"]:
        raise InstallError("restore config plan input digest mismatch")
    if plan["input_state"] == "installed-modified":
        try:
            expected_output = _restore_config_candidate(input_bytes.decode("utf-8"), config)
        except (UnicodeError, ConfigError) as exc:
            raise InstallError("restore config plan transition is invalid") from exc
    elif config["before_kind"] == "missing":
        expected_output = None
    else:
        expected_output = _read_regular_at(transaction_fd, config["backup"])
    if expected_output is None:
        if plan["output_missing"] is not True:
            raise InstallError("restore config plan output mismatch")
        return
    try:
        planned_output = base64.b64decode(plan["output_b64"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise InstallError("restore config plan output is invalid") from exc
    if plan["output_missing"] or planned_output != expected_output:
        raise InstallError("restore config plan transition mismatch")


def recover_or_restore(
    command: str,
    transaction_id: str,
    *,
    failpoint: Callable[[str], None] | None = None,
) -> None:
    if not TRANSACTION_ID_RE.fullmatch(transaction_id):
        raise InstallError("invalid transaction ID")
    root, _, _ = _resolve_codex_root(allow_create=False)
    outer_root_fd = _open_root(root, lock=False)
    outer_backups_fd = outer_namespace_fd = outer_transaction_fd = None
    try:
        _verify_root_identity(root, outer_root_fd)
        outer_backups_fd, outer_namespace_fd, outer_transaction_fd = _existing_transaction_directories(
            outer_root_fd, transaction_id
        )
        _load_journal(outer_transaction_fd, transaction_id)
    finally:
        for fd in (outer_transaction_fd, outer_namespace_fd, outer_backups_fd, outer_root_fd):
            if fd is not None:
                os.close(fd)
    root_fd = _open_root(root)
    backups_fd = namespace_fd = transaction_fd = None
    try:
        _verify_root_identity(root, root_fd)
        backups_fd, namespace_fd, transaction_fd = _existing_transaction_directories(root_fd, transaction_id)
        journal = _load_journal(transaction_fd, transaction_id)
        root_stat = os.fstat(root_fd)
        if journal["root_path"] != str(root):
            raise InstallError("journal.toml Codex root path mismatch")
        if journal["root_identity"] != f"{root_stat.st_dev}:{root_stat.st_ino}":
            raise InstallError("journal.toml Codex root identity mismatch")
        if command == "restore":
            allowed = {"committed", "restore-in-progress", "restored"}
            progress_state = "restore-in-progress"
            complete_state = "restored"
        else:
            allowed = {"install-in-progress", "recover-in-progress", "recovered"}
            progress_state = "recover-in-progress"
            complete_state = "recovered"
        if journal["state"] not in allowed:
            raise InstallError(f"transaction state cannot {command}:{journal['state']}")
        terminal_state = journal["state"] == complete_state
        payload = journal["payload"]
        agents_fd: int | None = None
        if _lstat_at(root_fd, "agents") is None:
            if payload["agents"]["before_kind"] != "missing":
                raise InstallError("agents directory changed; refusing recovery")
            role_states = ["before" if role["before_kind"] == "missing" else "other" for role in payload["roles"]]
        else:
            agents_fd = _open_directory_at(root_fd, "agents")
            agents_metadata = os.fstat(agents_fd)
            if not (
                _identity_matches(agents_metadata, payload["agents"], "before")
                or _identity_matches(agents_metadata, payload["agents"], "installed")
            ):
                os.close(agents_fd)
                raise InstallError("agents directory identity changed; refusing recovery")
            role_states = [_role_state(agents_fd, role, transaction_fd) for role in payload["roles"]]
        config_state = _config_state(root_fd, payload["config"])
        if any(value == "other" for value in role_states) or config_state == "other":
            if agents_fd is not None:
                os.close(agents_fd)
            raise InstallError("transaction targets changed; refusing recovery")
        if terminal_state:
            agents_restored = (
                _lstat_at(root_fd, "agents") is None
                if payload["agents"]["before_kind"] == "missing"
                else agents_fd is not None
                and _identity_matches(os.fstat(agents_fd), payload["agents"], "before")
            )
            if not agents_restored or any(value != "before" for value in role_states) or config_state != "before":
                if agents_fd is not None:
                    os.close(agents_fd)
                raise InstallError("completed transaction targets do not match restored state")
            if agents_fd is not None:
                os.close(agents_fd)
            return
        if payload.get("restore_plan_ready") is True:
            for role, role_state in zip(payload["roles"], role_states, strict=True):
                if role_state == "installed" and role["before_kind"] in {"regular", "symlink"}:
                    if not all(key in role for key in ("restore_object", "restore_dev", "restore_ino")):
                        if agents_fd is not None:
                            os.close(agents_fd)
                        raise InstallError("restore role plan is incomplete")
            if (
                payload["config"]["changed"]
                and config_state in {"installed", "installed-modified"}
                and not isinstance(payload["config"].get("restore_plan"), dict)
            ):
                if agents_fd is not None:
                    os.close(agents_fd)
                raise InstallError("restore config plan is incomplete")
        _validate_restore_plan_transition(payload["config"], transaction_fd)
        if journal["state"] not in {"recover-in-progress", "restore-in-progress"} or not payload.get(
            "restore_plan_ready", False
        ):
            _prepare_restore_plan(
                root_fd,
                agents_fd,
                transaction_fd,
                payload,
                journal,
                progress_state,
                failpoint,
            )
        if failpoint is not None:
            failpoint("recovery-state-persisted")
        if agents_fd is not None:
            try:
                agents_prefix = "installed" if payload["agents"]["before_kind"] == "missing" else "before"
                for role in reversed(payload["roles"]):
                    _verify_root_identity(root, root_fd)
                    _verify_agents_binding(root_fd, agents_fd, payload["agents"], agents_prefix)
                    _restore_role(agents_fd, role, transaction_fd)
                    if failpoint is not None:
                        failpoint(f'recovery-role-replaced:{role["name"]}')
                    _save_journal(transaction_fd, journal)
                    if failpoint is not None:
                        failpoint(f'recovery-role-persisted:{role["name"]}')
            finally:
                os.close(agents_fd)
        _verify_root_identity(root, root_fd)
        _restore_config(root_fd, payload["config"], transaction_fd)
        if failpoint is not None:
            failpoint("recovery-config-replaced")
        _save_journal(transaction_fd, journal)
        if failpoint is not None:
            failpoint("recovery-config-persisted")
        if payload["agents"]["before_kind"] == "missing" and _remove_created_agents_directory(
            root_fd, payload["agents"]
        ):
            if failpoint is not None:
                failpoint("agents-dir-removed")
        _cleanup_transaction_temps(root_fd, transaction_fd, payload)
        journal["state"] = complete_state
        _save_journal(transaction_fd, journal)
        if failpoint is not None:
            failpoint("recovery-complete")
    finally:
        for fd in (transaction_fd, namespace_fd, backups_fd, root_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _cleanup_transaction_temps(root_fd: int, transaction_fd: int, payload: dict[str, Any]) -> None:
    for role in payload["roles"]:
        for key, prefix in (("install_object", "installed"), ("restore_object", "restore")):
            name = role.get(key)
            if isinstance(name, str):
                metadata = _lstat_at(transaction_fd, name)
                if metadata is not None and _identity_matches(metadata, role, prefix):
                    os.unlink(name, dir_fd=transaction_fd)
    agents_object = payload["agents"].get("install_object")
    if isinstance(agents_object, str):
        metadata = _lstat_at(transaction_fd, agents_object)
        if metadata is not None:
            if (
                not _identity_matches(metadata, payload["agents"], "installed")
                or not stat.S_ISDIR(metadata.st_mode)
            ):
                raise InstallError("agents install object changed before cleanup")
            agents_object_fd = _open_directory_at(transaction_fd, agents_object)
            try:
                if not _identity_matches(os.fstat(agents_object_fd), payload["agents"], "installed"):
                    raise InstallError("agents install object changed before cleanup")
                if os.listdir(agents_object_fd):
                    raise InstallError("agents install object is not empty during cleanup")
            finally:
                os.close(agents_object_fd)
            if not _identity_matches(
                _lstat_at(transaction_fd, agents_object), payload["agents"], "installed"
            ):
                raise InstallError("agents install object changed before cleanup")
            os.rmdir(agents_object, dir_fd=transaction_fd)
    config = payload["config"]
    for container, key, prefix in (
        (config, "install_temp", "installed"),
        (config.get("restore_plan", {}), "output_temp", "output"),
    ):
        name = container.get(key) if isinstance(container, dict) else None
        if isinstance(name, str):
            owner_fd = transaction_fd if key == "install_temp" and name == "install-config.toml" else root_fd
            metadata = _lstat_at(owner_fd, name)
            if metadata is not None and _identity_matches(metadata, container, prefix):
                os.unlink(name, dir_fd=owner_fd)
    os.fsync(transaction_fd)
    os.fsync(root_fd)


def _remove_created_agents_directory(root_fd: int, agents_state: dict[str, Any]) -> bool:
    metadata = _lstat_at(root_fd, "agents")
    if metadata is None:
        return False
    if not _identity_matches(metadata, agents_state, "installed") or not stat.S_ISDIR(metadata.st_mode):
        raise InstallError("agents directory changed before removal")
    agents_fd = _open_directory_at(root_fd, "agents")
    try:
        if not _identity_matches(os.fstat(agents_fd), agents_state, "installed"):
            raise InstallError("agents directory changed before removal")
        if os.listdir(agents_fd):
            return False
    finally:
        os.close(agents_fd)
    if not _identity_matches(_lstat_at(root_fd, "agents"), agents_state, "installed"):
        raise InstallError("agents directory changed before removal")
    os.rmdir("agents", dir_fd=root_fd)
    os.fsync(root_fd)
    return True


def _rollback_payload(root_fd: int, payload: dict[str, Any], transaction_fd: int, journal: dict[str, Any]) -> None:
    agents_fd = _open_directory_at(root_fd, "agents") if _lstat_at(root_fd, "agents") is not None else None
    _prepare_restore_plan(root_fd, agents_fd, transaction_fd, payload, journal, "recover-in-progress")
    if agents_fd is not None:
        try:
            for role in reversed(payload["roles"]):
                _restore_role(agents_fd, role, transaction_fd)
        finally:
            os.close(agents_fd)
    _restore_config(root_fd, payload["config"], transaction_fd)
    if payload["agents"]["before_kind"] == "missing":
        _remove_created_agents_directory(root_fd, payload["agents"])
    _cleanup_transaction_temps(root_fd, transaction_fd, payload)
    journal["state"] = "recovered"
    _save_journal(transaction_fd, journal)


def install(
    *,
    failpoint: Callable[[str], None] | None = None,
    interaction: Callable[[str], bool] | None = None,
) -> str | None:
    _check_platform_capabilities()
    try:
        validate_source(_source_dir())
    except RoleValidationError as exc:
        raise InstallError(f"managed role source invalid:{exc}") from exc
    root, created_root, created_root_identity = _resolve_codex_root()
    if not created_root:
        outer_fd = _open_root(root, lock=False)
        try:
            _verify_root_identity(root, outer_fd)
            _ensure_no_in_progress_transaction(outer_fd)
            try:
                _preflight(outer_fd)
            except ConflictError:
                pass
        finally:
            os.close(outer_fd)
        if failpoint is not None:
            failpoint("outer-preflight-complete")
    try:
        if created_root and failpoint is not None:
            failpoint("default-root-created")
        root_fd = _open_root(root)
        if created_root and (os.fstat(root_fd).st_dev, os.fstat(root_fd).st_ino) != created_root_identity:
            os.close(root_fd)
            raise InstallError("default Codex root identity changed")
    except BaseException:
        if created_root:
            _remove_created_root_if_safe(root, created_root_identity)
        raise
    backups_fd = namespace_fd = transaction_fd = None
    staging_name: str | None = None
    transaction_published = False
    try:
        _verify_root_identity(root, root_fd)
        _ensure_no_in_progress_transaction(root_fd, clean_staging=True)
        try:
            payload = _preflight(root_fd)
        except ConflictError as initial_conflict:
            confirmer = interaction or _terminal_confirms_snapshot
            if not confirmer(str(initial_conflict)):
                raise
            _verify_root_identity(root, root_fd)
            try:
                _preflight(root_fd)
            except ConflictError as confirmed_conflict:
                if confirmed_conflict.fingerprint != initial_conflict.fingerprint:
                    raise InstallError("conflict changed before snapshot") from confirmed_conflict
                snapshot_id = _snapshot_conflict(root_fd, confirmed_conflict)
                return f"snapshot:{snapshot_id}"
            raise InstallError("conflict disappeared before snapshot")
        if failpoint is not None:
            failpoint("locked-preflight-complete")
        _verify_payload_prestate(root_fd, payload)
        changes = any(role["before_kind"] != "ready" for role in payload["roles"]) or payload["config"]["changed"]
        if not changes:
            return None
        transaction_id = _transaction_id()
        backups_fd, namespace_fd, transaction_fd, staging_name = _transaction_directories(root_fd, transaction_id)
        if failpoint is not None:
            failpoint("staging-created")
        root_stat = os.fstat(root_fd)
        journal = {
            "transaction_id": transaction_id,
            "state": "install-in-progress",
            "root_path": str(root),
            "root_identity": f"{root_stat.st_dev}:{root_stat.st_ino}",
            "payload": payload,
        }
        _prepare_install_objects(transaction_fd, payload, failpoint)
        _backup_prestate(root_fd, payload, transaction_fd, failpoint)
        if failpoint is not None:
            failpoint("before-journal-write")
        _save_journal(transaction_fd, journal)
        if failpoint is not None:
            failpoint("journal-written-in-staging")
        os.fsync(transaction_fd)
        os.fsync(namespace_fd)
        os.fsync(backups_fd)
        os.fsync(root_fd)
        _publish_transaction(namespace_fd, transaction_fd, staging_name, transaction_id)
        transaction_published = True
        if failpoint is not None:
            failpoint("journal-durable")
        _install_roles(root, root_fd, payload, transaction_fd, journal, failpoint)
        _install_config(root, root_fd, payload, transaction_fd, journal, failpoint)
        _verify_root_identity(root, root_fd)
        _validate_installed(root_fd, payload)
        journal["state"] = "committed"
        _save_journal(transaction_fd, journal)
        if failpoint is not None:
            failpoint("committed")
        return transaction_id
    except BaseException as exc:
        if transaction_published and transaction_fd is not None and 'journal' in locals() and 'payload' in locals():
            try:
                _rollback_payload(root_fd, payload, transaction_fd, journal)
            except BaseException as rollback_exc:
                raise InstallError(
                    f"install failed and automatic rollback could not complete; run codex-agents-recover {journal['transaction_id']}"
                ) from rollback_exc
        elif staging_name is not None and namespace_fd is not None:
            try:
                staging_metadata = _lstat_at(namespace_fd, staging_name)
                opened_metadata = os.fstat(transaction_fd) if transaction_fd is not None else None
                if (
                    staging_metadata is not None
                    and opened_metadata is not None
                    and (staging_metadata.st_dev, staging_metadata.st_ino)
                    == (opened_metadata.st_dev, opened_metadata.st_ino)
                ):
                    _remove_opened_tree_at(namespace_fd, staging_name, transaction_fd)
            except (InstallError, OSError):
                pass
        if created_root:
            try:
                if not os.listdir(root_fd) and _created_root_still_matches(root, created_root_identity):
                    os.close(root_fd)
                    root_fd = -1
                    _remove_created_root_if_safe(root, created_root_identity)
            except OSError:
                pass
        raise exc
    finally:
        for fd in (transaction_fd, namespace_fd, backups_fd, root_fd):
            if fd is not None and fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install and recover managed Codex custom agents")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("install")
    for command in ("recover", "restore"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("transaction_id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    transaction_id = getattr(args, "transaction_id", None)
    if transaction_id is not None and not TRANSACTION_ID_RE.fullmatch(transaction_id):
        print("invalid transaction ID", file=sys.stderr)
        return 2
    try:
        if args.command == "install":
            installed_transaction = install()
            if installed_transaction is None:
                print("codex-agents already ready")
            elif installed_transaction.startswith("snapshot:"):
                print(f"conflict {installed_transaction}; backup-only complete, no installation performed")
            else:
                print(f"transaction: {installed_transaction}")
            return 0
        recover_or_restore(args.command, args.transaction_id)
        print(f"transaction {args.transaction_id}: {args.command} complete")
        return 0
    except (InstallError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
