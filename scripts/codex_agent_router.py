#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "codex" / "agent-routing.toml"
DEFAULT_MANAGED_INDEX = (
    Path(__file__).resolve().parents[1] / "codex" / "agents" / "managed-agents.txt"
)
ROUTING_CLASSES = {"routine", "complex", "critical", "mechanical"}
EFFORT_RANK = {"none": 0, "minimal": 1, "low": 2, "medium": 3, "high": 4, "xhigh": 5, "max": 6}
TIER_RANK = {"luna": 1, "terra": 2, "sol": 3}
BUILTIN_ROUTED_AGENTS = {"default", "explorer", "worker"}
AGENT_NAME_RE = re.compile(r"^[a-z0-9_]+$")
CLASS_RE = re.compile(r"^ROUTING_CLASS=([^\s]+)\s*$")
REASON_RE = re.compile(r"^ROUTING_REASON=(.+?)\s*$")


def _load_policy(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _load_routed_agents(path: Path) -> set[str]:
    names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if (
        not names
        or names != sorted(names)
        or len(names) != len(set(names))
        or any(not AGENT_NAME_RE.fullmatch(name) for name in names)
    ):
        raise ValueError("managed agent index is invalid")
    return set(names) | BUILTIN_ROUTED_AGENTS


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _parse_routing(message: object) -> tuple[str, str | None, bool] | str:
    if not isinstance(message, str):
        return "routing-message-required"
    lines = message.splitlines()
    classes = [match.group(1) for line in lines if (match := CLASS_RE.fullmatch(line))]
    reasons = [match.group(1) for line in lines if (match := REASON_RE.fullmatch(line))]
    if sum("ROUTING_CLASS" in line for line in lines) != len(classes) or sum(
        "ROUTING_REASON" in line for line in lines
    ) != len(reasons):
        return "routing-marker-malformed"
    if not classes and not reasons:
        return "routine", None, True
    if len(classes) != 1:
        return "routing-class-required"
    routing_class = classes[0]
    if routing_class not in ROUTING_CLASSES:
        return f"invalid-routing-class:{routing_class}"
    if len(reasons) != 1 or not reasons[0].strip():
        return "routing-reason-required"
    return routing_class, reasons[0], False


def _valid_route(route: object) -> bool:
    return (
        isinstance(route, dict)
        and set(route) == {"tier", "effort"}
        and isinstance(route.get("tier"), str)
        and route["tier"] in TIER_RANK
        and isinstance(route.get("effort"), str)
        and route["effort"] in EFFORT_RANK
    )


def _valid_policy(policy: dict[str, Any], routed_agents: set[str]) -> bool:
    if set(policy) != {"version", "models", "runtime", "classes", "roles"}:
        return False
    if type(policy.get("version")) is not int or policy["version"] != 1:
        return False
    models = policy.get("models")
    runtime = policy.get("runtime")
    classes = policy.get("classes")
    roles = policy.get("roles")
    model_values = list(models.values()) if isinstance(models, dict) else []
    if (
        not isinstance(models, dict)
        or set(models) != set(TIER_RANK)
        or any(
            not isinstance(value, str)
            or not value
            or any(character.isspace() for character in value)
            for value in model_values
        )
        or len(model_values) != len(set(model_values))
        or not isinstance(runtime, dict)
        or set(runtime) != {"dynamic_tiers"}
        or not isinstance(classes, dict)
        or set(classes) != ROUTING_CLASSES - {"routine"}
        or not isinstance(roles, dict)
        or set(roles) != routed_agents
        or any(not _valid_route(route) for route in classes.values())
        or any(not _valid_route(route) for route in roles.values())
    ):
        return False
    dynamic_tiers = runtime["dynamic_tiers"]
    return (
        isinstance(dynamic_tiers, list)
        and bool(dynamic_tiers)
        and all(isinstance(tier, str) and tier in TIER_RANK for tier in dynamic_tiers)
        and len(dynamic_tiers) == len(set(dynamic_tiers))
    )


def _route(
    policy: dict[str, Any],
    agent_type: str,
    routing_class: str,
    routed_agents: set[str],
) -> tuple[str, str, str] | str | None:
    if not _valid_policy(policy, routed_agents):
        return "routing-policy-invalid"
    roles = policy.get("roles")
    models = policy.get("models")
    runtime = policy.get("runtime")
    classes = policy.get("classes")
    if not all(isinstance(item, dict) for item in (roles, models, runtime, classes)):
        return "routing-policy-invalid"
    role = roles.get(agent_type)
    if not isinstance(role, dict):
        return None
    tier = role.get("tier")
    effort = role.get("effort")
    if tier not in TIER_RANK or effort not in EFFORT_RANK:
        return "routing-policy-invalid"

    if routing_class != "routine":
        class_route = classes.get(routing_class)
        if not isinstance(class_route, dict):
            return "routing-policy-invalid"
        class_tier = class_route.get("tier")
        class_effort = class_route.get("effort")
        if class_tier not in TIER_RANK or class_effort not in EFFORT_RANK:
            return "routing-policy-invalid"
        if routing_class == "mechanical":
            tier, effort = class_tier, class_effort
        else:
            if TIER_RANK[class_tier] > TIER_RANK[tier]:
                tier = class_tier
            if EFFORT_RANK[class_effort] > EFFORT_RANK[effort]:
                effort = class_effort

    dynamic_tiers = runtime.get("dynamic_tiers")
    if not isinstance(dynamic_tiers, list) or any(item not in TIER_RANK for item in dynamic_tiers):
        return "routing-policy-invalid"
    if tier not in dynamic_tiers:
        return f"unsupported-dynamic-tier:{tier}"
    model = models.get(tier)
    if not isinstance(model, str) or not model:
        return "routing-policy-invalid"
    return model, effort, tier


def process_hook(
    payload: dict[str, Any],
    *,
    policy_path: Path = DEFAULT_POLICY,
    managed_index_path: Path = DEFAULT_MANAGED_INDEX,
) -> dict[str, Any] | None:
    if payload.get("hook_event_name") != "PreToolUse" or payload.get("tool_name") not in {
        "Agent",
        "spawn_agent",
    }:
        return None

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    agent_type = tool_input.get("agent_type", "default")
    if agent_type is None:
        agent_type = "default"
    if not isinstance(agent_type, str):
        return _deny("routing-agent-type-invalid")

    try:
        routed_agents = _load_routed_agents(managed_index_path)
    except (OSError, UnicodeError, ValueError):
        return _deny("routing-policy-invalid")
    if agent_type not in routed_agents:
        return None

    try:
        policy = _load_policy(policy_path)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return _deny("routing-policy-invalid")
    if not _valid_policy(policy, routed_agents):
        return _deny("routing-policy-invalid")

    parsed = _parse_routing(tool_input.get("message"))
    if isinstance(parsed, str):
        return _deny(parsed)
    routing_class, _reason, markers_missing = parsed
    route = _route(policy, agent_type, routing_class, routed_agents)
    if route is None:
        return None
    if isinstance(route, str):
        return _deny(route)
    model, effort, _tier = route

    fork_turns = tool_input.get("fork_turns")
    if fork_turns in (None, "all"):
        return _deny("full-history-fork-cannot-override-model")
    if fork_turns != "none" and (
        not isinstance(fork_turns, str) or not fork_turns.isdigit() or int(fork_turns) < 1
    ):
        return _deny("invalid-fork-turns-for-model-override")

    updated_input = dict(tool_input)
    updated_input["model"] = model
    updated_input["reasoning_effort"] = effort
    hook_output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated_input,
        }
    }
    if markers_missing:
        hook_output["hookSpecificOutput"]["additionalContext"] = (
            "missing-routing-markers: applied the managed role default"
        )
    return hook_output


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be an object")
        result = process_hook(payload)
    except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError):
        sys.stderr.write("codex-agent-router: invalid hook input or routing policy\n")
        return 2
    if result is not None:
        json.dump(result, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
