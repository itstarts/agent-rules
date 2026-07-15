#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


EXPECTED_SANDBOX = {
    "architect": "read-only",
    "data-consistency-reviewer": "read-only",
    "final-gate-reviewer": "read-only",
    "product-analyst": "read-only",
    "reviewer": "read-only",
    "spec-plan-reviewer": "read-only",
    "test-engineer": "workspace-write",
    "ui-ux-designer": "read-only",
    "visual-reviewer": "read-only",
    "worker-backend": "workspace-write",
    "worker-frontend": "workspace-write",
}
ALLOWED_FIELDS = {
    "name",
    "description",
    "developer_instructions",
    "nickname_candidates",
    "sandbox_mode",
}
REQUIRED_FIELDS = {"name", "description", "developer_instructions"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NICKNAME_RE = re.compile(r"^[A-Za-z0-9 _-]+$")
DESCRIPTION_MARKERS = (
    "用于",
    "不用于",
    "production code",
    "依赖",
    "长期服务",
    "commit",
    "push",
    "merge",
    "tag",
    "release",
    "外部系统",
)
READ_ONLY_MARKERS = ("不修改", "不创建", "不删除", "不安装依赖", "不启动本地长期服务")
WRITE_MARKERS = ("明确分配", "不覆盖", "不扩大", "不安装依赖", "掩盖")


class ValidationError(Exception):
    pass


def _default_source_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "codex" / "agents"


def _read_index(source_dir: Path) -> list[str]:
    index = source_dir / "managed-agents.txt"
    try:
        names = [line.strip() for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        raise ValidationError("managed-agents.txt: missing-or-unreadable") from exc
    if names != sorted(names):
        raise ValidationError("managed-agents.txt: not-sorted")
    if len(names) != len(set(names)):
        raise ValidationError("managed-agents.txt: duplicate-name")
    return names


def _sensitive_category(text: str) -> str | None:
    patterns = {
        "personal-absolute-path": re.compile(re.escape("/" + "Users" + "/") + r"[^/\s]+/"),
        "credential-shape": re.compile(
            r"(?i)(?:"
            + "api"
            + r"[_-]?"
            + "key"
            + r"|"
            + "access"
            + r"[_-]?"
            + "token"
            + r"|"
            + "bear"
            + r"er\s+[A-Za-z0-9._-]+)"
        ),
        "provider-url": re.compile(r"https?://[^\s]+", re.IGNORECASE),
        "session-shape": re.compile(r"019f[0-9a-f-]{20,}", re.IGNORECASE),
    }
    for category, pattern in patterns.items():
        if pattern.search(text):
            return category
    return None


def _load_role(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValidationError(f"{path.name}: invalid-toml") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{path.name}: invalid-root")
    return data


def validate_source(source_dir: Path) -> int:
    names = _read_index(source_dir)
    expected = sorted(EXPECTED_SANDBOX)
    if names != expected:
        raise ValidationError("managed-agents.txt: managed-set-mismatch")

    toml_names = sorted(path.stem for path in source_dir.glob("*.toml"))
    if toml_names != expected:
        raise ValidationError("codex/agents: toml-set-mismatch")

    all_nicknames: set[str] = set()
    for name in names:
        path = source_dir / f"{name}.toml"
        data = _load_role(path)
        unknown = sorted(set(data) - ALLOWED_FIELDS)
        if unknown:
            raise ValidationError(f"{path.name}: unknown-field:{unknown[0]}")
        for field in REQUIRED_FIELDS:
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{path.name}: missing-or-empty:{field}")
        if data["name"] != name or not NAME_RE.fullmatch(data["name"]):
            raise ValidationError(f"{path.name}: name-mismatch-or-invalid")
        if data.get("sandbox_mode") != EXPECTED_SANDBOX[name]:
            raise ValidationError(f"{path.name}: sandbox-mismatch")

        nicknames = data.get("nickname_candidates")
        if not isinstance(nicknames, list) or not nicknames:
            raise ValidationError(f"{path.name}: invalid-nickname-list")
        if any(not isinstance(item, str) or not NICKNAME_RE.fullmatch(item) for item in nicknames):
            raise ValidationError(f"{path.name}: invalid-nickname")
        if len(nicknames) != len(set(nicknames)):
            raise ValidationError(f"{path.name}: duplicate-nickname")
        duplicate = next((item for item in nicknames if item in all_nicknames), None)
        if duplicate is not None:
            raise ValidationError(f"{path.name}: global-duplicate-nickname")
        all_nicknames.update(nicknames)

        description = data["description"]
        for marker in DESCRIPTION_MARKERS + (EXPECTED_SANDBOX[name],):
            if marker not in description:
                raise ValidationError(f"{path.name}: description-boundary-missing")

        instructions = data["developer_instructions"]
        markers = READ_ONLY_MARKERS if EXPECTED_SANDBOX[name] == "read-only" else WRITE_MARKERS
        for marker in markers:
            if marker not in instructions:
                raise ValidationError(f"{path.name}: instruction-boundary-missing")
        category = _sensitive_category(path.read_text(encoding="utf-8"))
        if category:
            raise ValidationError(f"{path.name}: {category}")
    return len(names)


def validate_installed(source_dir: Path, installed_root: Path) -> None:
    agents_dir = installed_root / "agents"
    for name in sorted(EXPECTED_SANDBOX):
        source = (source_dir / f"{name}.toml").resolve(strict=True)
        target = agents_dir / f"{name}.toml"
        if not target.is_symlink():
            raise ValidationError(f"{target.name}: installed-target-not-symlink")
        try:
            resolved = target.resolve(strict=True)
        except OSError as exc:
            raise ValidationError(f"{target.name}: installed-target-broken") from exc
        if resolved != source:
            raise ValidationError(f"{target.name}: installed-target-mismatch")
        data = _load_role(target)
        if data.get("name") != name or data.get("sandbox_mode") != EXPECTED_SANDBOX[name]:
            raise ValidationError(f"{target.name}: installed-content-mismatch")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate managed Codex custom agents")
    parser.add_argument("--source-dir", type=Path, default=_default_source_dir())
    parser.add_argument("--installed-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        count = validate_source(args.source_dir)
        if args.installed_root is not None:
            validate_installed(args.source_dir, args.installed_root)
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    suffix = " and installed targets" if args.installed_root is not None else ""
    print(f"{count} managed Codex agents{suffix} validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
