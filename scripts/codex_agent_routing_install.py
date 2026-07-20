#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shlex
import stat
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True

from codex_agents import (  # noqa: E402
    TRANSACTION_ID_RE,
    InstallError,
    _check_platform_capabilities,
    _create_file_at,
    _created_root_still_matches,
    _digest,
    _ensure_no_in_progress_transaction,
    _identity_matches,
    _lstat_at,
    _open_directory_at,
    _open_root,
    _read_regular_at,
    _remove_created_root_if_safe,
    _remove_opened_tree_at,
    _replace_file_at,
    _resolve_codex_root,
    _transaction_id,
    _verify_root_identity,
)
from validate_codex_agents import ValidationError as RoleValidationError  # noqa: E402
from validate_codex_agents import validate_source  # noqa: E402


BEGIN_MARKER = "# agent-rules:codex-agent-routing:begin"
END_MARKER = "# agent-rules:codex-agent-routing:end"
NAMESPACE = "codex-agent-routing"
JOURNAL_SCHEMA_VERSION = 1
IN_PROGRESS_STATES = {"install-in-progress", "recover-in-progress", "restore-in-progress"}
ALL_STATES = IN_PROGRESS_STATES | {"committed", "recovered", "restored"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class MergeResult:
    text: str
    before_block: str | None
    changed: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _source_dir() -> Path:
    return _repo_root() / "codex" / "agents"


def _routing_policy() -> Path:
    return _repo_root() / "codex" / "agent-routing.toml"


def _router_path() -> Path:
    return _repo_root() / "scripts" / "codex_agent_router.py"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def managed_hook_block(*, python_executable: Path, router_path: Path) -> str:
    command = f"{shlex.quote(str(python_executable))} {shlex.quote(str(router_path))}"
    return "\n".join(
        (
            BEGIN_MARKER,
            "[[hooks.PreToolUse]]",
            'matcher = "^Agent$"',
            "",
            "[[hooks.PreToolUse.hooks]]",
            'type = "command"',
            f"command = {_toml_string(command)}",
            "timeout = 10",
            'statusMessage = "Selecting subagent model and effort"',
            END_MARKER,
            "",
        )
    )


def _managed_span(text: str) -> tuple[int, int, str] | None:
    lines = text.splitlines(keepends=True)
    begins: list[tuple[int, int]] = []
    ends: list[tuple[int, int]] = []
    offset = 0
    for index, line in enumerate(lines):
        marker = line.rstrip("\r\n")
        if marker in {BEGIN_MARKER, END_MARKER}:
            try:
                tomllib.loads(text[:offset])
            except tomllib.TOMLDecodeError:
                pass
            else:
                target = begins if marker == BEGIN_MARKER else ends
                target.append((index, offset))
        offset += len(line)
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or begins[0][0] >= ends[0][0]:
        raise ConfigError("config.toml: unsafe-managed-hook-markers")
    start = begins[0][1]
    end = ends[0][1] + len(lines[ends[0][0]])
    return start, end, text[start:end]


def _parse_config(text: str) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("config.toml: invalid-toml") from exc
    if not isinstance(parsed, dict):
        raise ConfigError("config.toml: invalid-root")
    return parsed


def _validate_managed_block(block: str) -> None:
    parsed = _parse_config(block)
    try:
        groups = parsed["hooks"]["PreToolUse"]
        group = groups[0]
        handlers = group["hooks"]
        handler = handlers[0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ConfigError("config.toml: unsafe-managed-hook-block") from exc
    if (
        len(groups) != 1
        or set(group) != {"matcher", "hooks"}
        or group["matcher"] != "^Agent$"
        or len(handlers) != 1
        or set(handler) != {"type", "command", "timeout", "statusMessage"}
        or handler["type"] != "command"
        or not isinstance(handler["command"], str)
        or not handler["command"].strip()
        or handler["timeout"] != 10
        or handler["statusMessage"] != "Selecting subagent model and effort"
    ):
        raise ConfigError("config.toml: unsafe-managed-hook-block")


def _matcher_matches_agent(matcher: object) -> bool:
    if not isinstance(matcher, str):
        raise ConfigError("config.toml: invalid-hook-matcher")
    try:
        pattern = re.compile(matcher)
    except re.error as exc:
        raise ConfigError("config.toml: invalid-hook-matcher") from exc
    return any(pattern.search(name) is not None for name in ("Agent", "spawn_agent"))


def _reject_conflicting_agent_hooks(text_without_managed_block: str) -> None:
    parsed = _parse_config(text_without_managed_block)
    hooks = parsed.get("hooks", {})
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise ConfigError("config.toml: invalid-hooks-table")
    groups = hooks.get("PreToolUse", [])
    if not isinstance(groups, list):
        raise ConfigError("config.toml: invalid-pre-tool-use-hooks")
    for group in groups:
        if not isinstance(group, dict):
            raise ConfigError("config.toml: invalid-pre-tool-use-hook")
        if _matcher_matches_agent(group.get("matcher", "")):
            raise ConfigError("config.toml: conflicting-agent-hook")


def merge_config_text(original: str | None, block: str) -> MergeResult:
    text = "" if original is None else original
    parsed = _parse_config(text)
    features = parsed.get("features", {})
    if isinstance(features, dict) and (
        features.get("hooks") is False or features.get("codex_hooks") is False
    ):
        raise ConfigError("config.toml: hooks-disabled")

    span = _managed_span(text)
    if span is None:
        remainder = text
        before_block = None
    else:
        start, end, before_block = span
        _validate_managed_block(before_block)
        remainder = text[:start] + text[end:]
    _reject_conflicting_agent_hooks(remainder)

    if before_block == block:
        return MergeResult(text=text, before_block=before_block, changed=False)
    if span is None:
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        candidate = prefix + block
    else:
        candidate = text[: span[0]] + block + text[span[1] :]
    _parse_config(candidate)
    return MergeResult(text=candidate, before_block=before_block, changed=True)


def restore_config_text(
    current: str,
    *,
    installed_block: str,
    before_block: str | None,
) -> str:
    _parse_config(current)
    span = _managed_span(current)
    if span is None:
        if before_block is None:
            return current
        raise ConfigError("config.toml: managed hook changed")
    start, end, current_block = span
    if current_block == before_block:
        return current
    if current_block != installed_block:
        raise ConfigError("config.toml: managed hook changed")
    candidate = current[:start] + (before_block or "") + current[end:]
    _parse_config(candidate)
    return candidate


def _encode_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _decode_optional(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InstallError(f"journal.toml {field} is invalid")
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise InstallError(f"journal.toml {field} is invalid") from exc


def _journal_bytes(journal: dict[str, Any]) -> bytes:
    payload = base64.b64encode(
        json.dumps(journal["payload"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    lines = (
        f"schema_version = {JOURNAL_SCHEMA_VERSION}",
        f'transaction_id = "{journal["transaction_id"]}"',
        f'state = "{journal["state"]}"',
        f'created_ns = {journal["created_ns"]}',
        f'root_path_b64 = "{base64.b64encode(journal["root_path"].encode()).decode("ascii")}"',
        f'root_identity = "{journal["root_identity"]}"',
        f'payload_b64 = "{payload}"',
        "",
    )
    return "\n".join(lines).encode("utf-8")


def _validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "before_kind",
        "before_mode",
        "before_digest",
        "before_dev",
        "before_ino",
        "before_block_b64",
        "installed_block_b64",
        "installed_digest",
    }:
        raise InstallError("journal.toml payload fields are invalid")
    if payload["before_kind"] not in {"missing", "regular"}:
        raise InstallError("journal.toml payload before kind is invalid")
    if not isinstance(payload["before_mode"], int) or not 0 <= payload["before_mode"] <= 0o777:
        raise InstallError("journal.toml payload mode is invalid")
    if payload["before_kind"] == "missing":
        if any(payload[key] is not None for key in ("before_digest", "before_dev", "before_ino")):
            raise InstallError("journal.toml payload missing prestate is invalid")
    elif (
        not isinstance(payload["before_digest"], str)
        or not isinstance(payload["before_dev"], int)
        or not isinstance(payload["before_ino"], int)
    ):
        raise InstallError("journal.toml payload regular prestate is invalid")
    if not isinstance(payload["installed_digest"], str):
        raise InstallError("journal.toml payload installed digest is invalid")
    before_block = _decode_optional(payload["before_block_b64"], field="before block")
    installed_block = _decode_optional(payload["installed_block_b64"], field="installed block")
    if installed_block is None:
        raise InstallError("journal.toml payload installed block is invalid")
    if before_block is not None:
        _validate_managed_block(before_block)
    _validate_managed_block(installed_block)
    return payload


def _validate_journal_files(transaction_fd: int, payload: dict[str, Any]) -> None:
    install_metadata = _lstat_at(transaction_fd, "install-config.toml")
    if (
        install_metadata is None
        or not stat.S_ISREG(install_metadata.st_mode)
        or install_metadata.st_uid != os.getuid()
        or install_metadata.st_mode & 0o077
        or _digest(_read_regular_at(transaction_fd, "install-config.toml"))
        != payload["installed_digest"]
    ):
        raise InstallError("journal.toml installed config digest is invalid")
    backup_metadata = _lstat_at(transaction_fd, "config.bin")
    if payload["before_kind"] == "missing":
        if backup_metadata is not None:
            raise InstallError("journal.toml unexpected config backup")
        return
    if (
        backup_metadata is None
        or not stat.S_ISREG(backup_metadata.st_mode)
        or backup_metadata.st_uid != os.getuid()
        or backup_metadata.st_mode & 0o077
        or _digest(_read_regular_at(transaction_fd, "config.bin")) != payload["before_digest"]
    ):
        raise InstallError("journal.toml backup digest is invalid")


def _load_journal(transaction_fd: int, transaction_id: str) -> dict[str, Any]:
    metadata = _lstat_at(transaction_fd, "journal.toml")
    if (
        metadata is None
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise InstallError("journal.toml must be a private current-user regular file")
    try:
        parsed = tomllib.loads(_read_regular_at(transaction_fd, "journal.toml").decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise InstallError("journal.toml is invalid") from exc
    if set(parsed) != {
        "schema_version",
        "transaction_id",
        "state",
        "created_ns",
        "root_path_b64",
        "root_identity",
        "payload_b64",
    }:
        raise InstallError("journal.toml fields are invalid")
    if parsed["schema_version"] != JOURNAL_SCHEMA_VERSION:
        raise InstallError("journal.toml schema mismatch")
    if parsed["transaction_id"] != transaction_id or parsed["state"] not in ALL_STATES:
        raise InstallError("journal.toml transaction or state is invalid")
    if not isinstance(parsed["created_ns"], int) or parsed["created_ns"] < 1:
        raise InstallError("journal.toml creation time is invalid")
    try:
        root_path = base64.b64decode(parsed["root_path_b64"], validate=True).decode("utf-8")
        payload = json.loads(base64.b64decode(parsed["payload_b64"], validate=True))
    except (ValueError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise InstallError("journal.toml encoded fields are invalid") from exc
    payload = _validate_payload(payload)
    _validate_journal_files(transaction_fd, payload)
    return {
        "transaction_id": transaction_id,
        "state": parsed["state"],
        "created_ns": parsed["created_ns"],
        "root_path": root_path,
        "root_identity": parsed["root_identity"],
        "payload": payload,
    }


def _save_journal(transaction_fd: int, journal: dict[str, Any]) -> None:
    _replace_file_at(transaction_fd, "journal.toml", _journal_bytes(journal), 0o600)


def _transaction_directories(root_fd: int, transaction_id: str) -> tuple[int, int, int, str]:
    backups_fd = _open_directory_at(root_fd, ".agent-rules-backups", create=True)
    try:
        namespace_fd = _open_directory_at(backups_fd, NAMESPACE, create=True)
    except BaseException:
        os.close(backups_fd)
        raise
    staging_name = f".staging-{transaction_id}"
    try:
        os.mkdir(staging_name, mode=0o700, dir_fd=namespace_fd)
        transaction_fd = _open_directory_at(namespace_fd, staging_name)
    except BaseException:
        os.close(namespace_fd)
        os.close(backups_fd)
        raise
    return backups_fd, namespace_fd, transaction_fd, staging_name


def _publish_transaction(
    namespace_fd: int,
    transaction_fd: int,
    staging_name: str,
    transaction_id: str,
) -> None:
    before = os.fstat(transaction_fd)
    os.rename(staging_name, transaction_id, src_dir_fd=namespace_fd, dst_dir_fd=namespace_fd)
    after = _lstat_at(namespace_fd, transaction_id)
    if after is None or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        raise InstallError("published routing transaction identity mismatch")
    os.fsync(namespace_fd)


def _open_transaction(root_fd: int, transaction_id: str) -> tuple[int, int, int]:
    backups_fd = _open_directory_at(root_fd, ".agent-rules-backups")
    try:
        namespace_fd = _open_directory_at(backups_fd, NAMESPACE)
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


def _newer_committed_transaction(
    namespace_fd: int,
    current: dict[str, Any],
) -> str | None:
    current_order = (current["created_ns"], current["transaction_id"])
    for name in sorted(os.listdir(namespace_fd)):
        if name == current["transaction_id"] or not TRANSACTION_ID_RE.fullmatch(name):
            continue
        transaction_fd = _open_directory_at(namespace_fd, name)
        try:
            candidate = _load_journal(transaction_fd, name)
        finally:
            os.close(transaction_fd)
        candidate_order = (candidate["created_ns"], candidate["transaction_id"])
        if candidate["state"] == "committed" and candidate_order > current_order:
            return name
    return None


def _clean_staging(namespace_fd: int, name: str) -> None:
    transaction_fd = _open_directory_at(namespace_fd, name)
    try:
        allowed = {"journal.toml", "config.bin", "install-config.toml"}
        entries = set(os.listdir(transaction_fd))
        if not entries.issubset(allowed):
            raise InstallError("abandoned routing staging transaction is unsafe")
        for entry in entries:
            metadata = _lstat_at(transaction_fd, entry)
            if (
                metadata is None
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077
            ):
                raise InstallError("abandoned routing staging transaction is unsafe")
        _remove_opened_tree_at(namespace_fd, name, transaction_fd)
    finally:
        os.close(transaction_fd)


def ensure_no_in_progress_routing_transaction(
    root_fd: int,
    *,
    clean_staging: bool = False,
) -> None:
    if _lstat_at(root_fd, ".agent-rules-backups") is None:
        return
    backups_fd = namespace_fd = None
    try:
        backups_fd = _open_directory_at(root_fd, ".agent-rules-backups")
        if _lstat_at(backups_fd, NAMESPACE) is None:
            return
        namespace_fd = _open_directory_at(backups_fd, NAMESPACE)
        for name in sorted(os.listdir(namespace_fd)):
            if name.startswith(".staging-") and TRANSACTION_ID_RE.fullmatch(name[9:]):
                if clean_staging:
                    _clean_staging(namespace_fd, name)
                    continue
                raise InstallError("codex-agent-routing staging transaction is incomplete")
            if not TRANSACTION_ID_RE.fullmatch(name):
                raise InstallError("invalid entry in codex-agent-routing transaction namespace")
            transaction_fd = _open_directory_at(namespace_fd, name)
            try:
                journal = _load_journal(transaction_fd, name)
            finally:
                os.close(transaction_fd)
            if journal["state"] in IN_PROGRESS_STATES:
                command = (
                    "codex-agent-routing-restore"
                    if journal["state"] == "restore-in-progress"
                    else "codex-agent-routing-recover"
                )
                raise InstallError(
                    f"routing transaction {name} is {journal['state']}; run {command} {name}"
                )
    finally:
        if namespace_fd is not None:
            os.close(namespace_fd)
        if backups_fd is not None:
            os.close(backups_fd)


def _read_config(root_fd: int) -> tuple[str | None, os.stat_result | None, int]:
    metadata = _lstat_at(root_fd, "config.toml")
    if metadata is None:
        return None, None, 0o600
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise InstallError("config.toml must be a current-user regular file")
    try:
        text = _read_regular_at(root_fd, "config.toml").decode("utf-8")
    except UnicodeError as exc:
        raise InstallError("config.toml must be UTF-8") from exc
    return text, metadata, stat.S_IMODE(metadata.st_mode)


def _payload(
    original: str | None,
    metadata: os.stat_result | None,
    mode: int,
    merge: MergeResult,
    installed_block: str,
) -> dict[str, Any]:
    original_bytes = None if original is None else original.encode("utf-8")
    return {
        "before_kind": "missing" if original is None else "regular",
        "before_mode": mode,
        "before_digest": None if original_bytes is None else _digest(original_bytes),
        "before_dev": None if metadata is None else metadata.st_dev,
        "before_ino": None if metadata is None else metadata.st_ino,
        "before_block_b64": _encode_optional(merge.before_block),
        "installed_block_b64": _encode_optional(installed_block),
        "installed_digest": _digest(merge.text.encode("utf-8")),
    }


def _verify_prestate(root_fd: int, payload: dict[str, Any]) -> None:
    metadata = _lstat_at(root_fd, "config.toml")
    if payload["before_kind"] == "missing":
        if metadata is not None:
            raise InstallError("config.toml changed after routing preflight")
        return
    if not _identity_matches(metadata, payload, "before") or not stat.S_ISREG(metadata.st_mode):
        raise InstallError("config.toml changed after routing preflight")
    if _digest(_read_regular_at(root_fd, "config.toml")) != payload["before_digest"]:
        raise InstallError("config.toml changed after routing preflight")


def _installed_block(payload: dict[str, Any]) -> str:
    value = _decode_optional(payload["installed_block_b64"], field="installed block")
    if value is None:
        raise InstallError("journal.toml installed block is missing")
    return value


def _before_block(payload: dict[str, Any]) -> str | None:
    return _decode_optional(payload["before_block_b64"], field="before block")


def _restore_payload(
    root_fd: int,
    payload: dict[str, Any],
    transaction_fd: int,
) -> None:
    current, metadata, mode = _read_config(root_fd)
    if current is None:
        if payload["before_kind"] == "missing":
            return
        raise InstallError("config.toml changed; refusing routing recovery")
    current_digest = _digest(current.encode("utf-8"))
    if current_digest == payload["installed_digest"]:
        current_metadata = _lstat_at(root_fd, "config.toml")
        if (
            metadata is None
            or current_metadata is None
            or (metadata.st_dev, metadata.st_ino)
            != (current_metadata.st_dev, current_metadata.st_ino)
            or _digest(_read_regular_at(root_fd, "config.toml")) != current_digest
        ):
            raise InstallError("config.toml changed during routing recovery")
        if payload["before_kind"] == "missing":
            os.unlink("config.toml", dir_fd=root_fd)
            os.fsync(root_fd)
        else:
            backup = _read_regular_at(transaction_fd, "config.bin")
            if _digest(backup) != payload["before_digest"]:
                raise InstallError("journal.toml backup digest changed during routing recovery")
            _replace_file_at(root_fd, "config.toml", backup, payload["before_mode"])
        return
    try:
        restored = restore_config_text(
            current,
            installed_block=_installed_block(payload),
            before_block=_before_block(payload),
        )
    except ConfigError as exc:
        raise InstallError(str(exc)) from exc
    if restored == current:
        return
    current_metadata = _lstat_at(root_fd, "config.toml")
    if (
        metadata is None
        or current_metadata is None
        or (metadata.st_dev, metadata.st_ino) != (current_metadata.st_dev, current_metadata.st_ino)
        or _digest(_read_regular_at(root_fd, "config.toml")) != _digest(current.encode("utf-8"))
    ):
        raise InstallError("config.toml changed during routing recovery")
    if payload["before_kind"] == "missing" and not restored.strip():
        os.unlink("config.toml", dir_fd=root_fd)
        os.fsync(root_fd)
    else:
        _replace_file_at(root_fd, "config.toml", restored.encode("utf-8"), mode)


def install(*, failpoint: Callable[[str], None] | None = None) -> str | None:
    _check_platform_capabilities()
    try:
        validate_source(_source_dir(), _routing_policy())
    except RoleValidationError as exc:
        raise InstallError(f"managed routing source invalid:{exc}") from exc
    router = _router_path().resolve(strict=True)
    python_executable = Path(sys.executable).resolve(strict=True)
    block = managed_hook_block(python_executable=python_executable, router_path=router)
    root, created_root, created_root_identity = _resolve_codex_root()
    try:
        root_fd = _open_root(root)
    except BaseException:
        if created_root:
            _remove_created_root_if_safe(root, created_root_identity)
        raise
    backups_fd = namespace_fd = transaction_fd = None
    staging_name: str | None = None
    published = False
    try:
        _verify_root_identity(root, root_fd)
        _ensure_no_in_progress_transaction(root_fd)
        ensure_no_in_progress_routing_transaction(root_fd, clean_staging=True)
        if _lstat_at(root_fd, "hooks.json") is not None:
            raise InstallError("hooks.json-present: consolidate hooks into config.toml first")
        original, metadata, mode = _read_config(root_fd)
        try:
            merge = merge_config_text(original, block)
        except ConfigError as exc:
            raise InstallError(str(exc)) from exc
        if not merge.changed:
            return None
        transaction_id = _transaction_id()
        backups_fd, namespace_fd, transaction_fd, staging_name = _transaction_directories(
            root_fd,
            transaction_id,
        )
        payload = _payload(original, metadata, mode, merge, block)
        if original is not None:
            _create_file_at(transaction_fd, "config.bin", original.encode("utf-8"), 0o600)
        _create_file_at(transaction_fd, "install-config.toml", merge.text.encode("utf-8"), 0o600)
        root_stat = os.fstat(root_fd)
        journal = {
            "transaction_id": transaction_id,
            "state": "install-in-progress",
            "created_ns": time.time_ns(),
            "root_path": str(root),
            "root_identity": f"{root_stat.st_dev}:{root_stat.st_ino}",
            "payload": payload,
        }
        _create_file_at(transaction_fd, "journal.toml", _journal_bytes(journal), 0o600)
        os.fsync(transaction_fd)
        os.fsync(namespace_fd)
        os.fsync(backups_fd)
        os.fsync(root_fd)
        _publish_transaction(namespace_fd, transaction_fd, staging_name, transaction_id)
        published = True
        if failpoint is not None:
            failpoint("journal-durable")
        _verify_prestate(root_fd, payload)
        candidate = _read_regular_at(transaction_fd, "install-config.toml")
        if _digest(candidate) != payload["installed_digest"]:
            raise InstallError("routing install object changed")
        _replace_file_at(root_fd, "config.toml", candidate, mode)
        if _digest(_read_regular_at(root_fd, "config.toml")) != payload["installed_digest"]:
            raise InstallError("installed routing config verification failed")
        if failpoint is not None:
            failpoint("config-applied")
        journal["state"] = "committed"
        _save_journal(transaction_fd, journal)
        if failpoint is not None:
            failpoint("committed")
        return transaction_id
    except BaseException as exc:
        if published and transaction_fd is not None and "journal" in locals():
            try:
                _restore_payload(root_fd, journal["payload"], transaction_fd)
                journal["state"] = "recovered"
                _save_journal(transaction_fd, journal)
            except BaseException as rollback_exc:
                raise InstallError(
                    "routing install failed and rollback could not complete; "
                    f"run codex-agent-routing-recover {journal['transaction_id']}"
                ) from rollback_exc
        elif staging_name is not None and namespace_fd is not None and transaction_fd is not None:
            try:
                _remove_opened_tree_at(namespace_fd, staging_name, transaction_fd)
            except (InstallError, OSError):
                pass
        if created_root:
            try:
                if not os.listdir(root_fd) and _created_root_still_matches(
                    root,
                    created_root_identity,
                ):
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


def recover_or_restore(command: str, transaction_id: str) -> None:
    if not TRANSACTION_ID_RE.fullmatch(transaction_id):
        raise InstallError("invalid transaction ID")
    root, _, _ = _resolve_codex_root(allow_create=False)
    root_fd = _open_root(root)
    backups_fd = namespace_fd = transaction_fd = None
    try:
        _verify_root_identity(root, root_fd)
        _ensure_no_in_progress_transaction(root_fd)
        backups_fd, namespace_fd, transaction_fd = _open_transaction(root_fd, transaction_id)
        journal = _load_journal(transaction_fd, transaction_id)
        root_stat = os.fstat(root_fd)
        if journal["root_path"] != str(root) or journal["root_identity"] != (
            f"{root_stat.st_dev}:{root_stat.st_ino}"
        ):
            raise InstallError("journal.toml Codex root mismatch")
        if command == "recover":
            allowed = {"install-in-progress", "recover-in-progress", "recovered"}
            progress = "recover-in-progress"
            complete = "recovered"
        else:
            allowed = {"committed", "restore-in-progress", "restored"}
            progress = "restore-in-progress"
            complete = "restored"
        if journal["state"] not in allowed:
            raise InstallError(f"routing transaction state cannot {command}:{journal['state']}")
        newer = _newer_committed_transaction(namespace_fd, journal)
        if newer is not None:
            if command == "recover" and journal["state"] == "recovered":
                return
            raise InstallError(f"newer committed routing transaction exists:{newer}")
        if journal["state"] == complete:
            _restore_payload(root_fd, journal["payload"], transaction_fd)
            return
        journal["state"] = progress
        _save_journal(transaction_fd, journal)
        _restore_payload(root_fd, journal["payload"], transaction_fd)
        journal["state"] = complete
        _save_journal(transaction_fd, journal)
    finally:
        for fd in (transaction_fd, namespace_fd, backups_fd, root_fd):
            if fd is not None:
                os.close(fd)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install and recover Codex agent routing hook")
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
            installed = install()
            if installed is None:
                print("codex-agent-routing already ready")
            else:
                print(f"transaction: {installed}")
            return 0
        recover_or_restore(args.command, args.transaction_id)
        print(f"routing transaction {args.transaction_id}: {args.command} complete")
        return 0
    except (ConfigError, InstallError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
