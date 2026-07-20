from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import codex_agent_router  # noqa: E402


POLICY = REPO / "codex" / "agent-routing.toml"
MANAGED_INDEX = REPO / "codex" / "agents" / "managed-agents.txt"
ROUTER = REPO / "scripts" / "codex_agent_router.py"


class CodexAgentRouterTests(unittest.TestCase):
    def payload(
        self,
        agent_type: str,
        *,
        routing_class: str | None = "routine",
        reason: str | None = "边界清晰的任务",
        fork_turns: str = "3",
    ) -> dict[str, object]:
        lines: list[str] = []
        if routing_class is not None:
            lines.append(f"ROUTING_CLASS={routing_class}")
        if reason is not None:
            lines.append(f"ROUTING_REASON={reason}")
        lines.append("执行明确分配的子任务。")
        return {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {
                "agent_type": agent_type,
                "fork_turns": fork_turns,
                "message": "\n".join(lines),
                "task_name": "bounded_task",
            },
        }

    def test_routine_role_uses_policy_default_model_and_effort(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {
                "agent_type": "product_analyst",
                "fork_turns": "3",
                "message": (
                    "ROUTING_CLASS=routine\n"
                    "ROUTING_REASON=边界清晰的需求澄清\n"
                    "澄清用户场景和验收标准。"
                ),
                "task_name": "requirements_clarification",
            },
        }

        result = codex_agent_router.process_hook(payload, policy_path=POLICY)

        hook_output = result["hookSpecificOutput"]
        self.assertEqual("PreToolUse", hook_output["hookEventName"])
        self.assertEqual("allow", hook_output["permissionDecision"])
        self.assertEqual(
            "gpt-5.6-terra",
            hook_output["updatedInput"]["model"],
        )
        self.assertEqual(
            "medium",
            hook_output["updatedInput"]["reasoning_effort"],
        )
        self.assertNotIn("model_reasoning_effort", hook_output["updatedInput"])

    def test_omitted_agent_type_uses_the_default_route(self) -> None:
        payload = self.payload("reviewer")
        del payload["tool_input"]["agent_type"]

        result = codex_agent_router.process_hook(payload, policy_path=POLICY)

        updated = result["hookSpecificOutput"]["updatedInput"]
        self.assertEqual("gpt-5.6-sol", updated["model"])
        self.assertEqual("high", updated["reasoning_effort"])

    def test_complex_route_raises_weak_default_to_sol_high(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("product_analyst", routing_class="complex", reason="涉及公共契约取舍"),
            policy_path=POLICY,
        )

        updated = result["hookSpecificOutput"]["updatedInput"]
        self.assertEqual("gpt-5.6-sol", updated["model"])
        self.assertEqual("high", updated["reasoning_effort"])

    def test_critical_route_uses_sol_xhigh(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("reviewer", routing_class="critical", reason="评审权限契约变更"),
            policy_path=POLICY,
        )

        updated = result["hookSpecificOutput"]["updatedInput"]
        self.assertEqual("gpt-5.6-sol", updated["model"])
        self.assertEqual("xhigh", updated["reasoning_effort"])

    def test_final_gate_keeps_max_for_critical_route(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("final_gate_reviewer", routing_class="critical", reason="高风险迁移最终门禁"),
            policy_path=POLICY,
        )

        updated = result["hookSpecificOutput"]["updatedInput"]
        self.assertEqual("gpt-5.6-sol", updated["model"])
        self.assertEqual("max", updated["reasoning_effort"])

    def test_mechanical_route_is_denied_when_luna_override_is_disabled(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("explorer", routing_class="mechanical", reason="批量结构化提取"),
            policy_path=POLICY,
        )

        hook_output = result["hookSpecificOutput"]
        self.assertEqual("deny", hook_output["permissionDecision"])
        self.assertIn("unsupported-dynamic-tier:luna", hook_output["permissionDecisionReason"])

    def test_full_history_fork_is_denied_before_model_override(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("reviewer", fork_turns="all"),
            policy_path=POLICY,
        )

        hook_output = result["hookSpecificOutput"]
        self.assertEqual("deny", hook_output["permissionDecision"])
        self.assertIn("full-history-fork", hook_output["permissionDecisionReason"])

    def test_missing_routing_markers_use_default_and_add_context(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("product_analyst", routing_class=None, reason=None),
            policy_path=POLICY,
        )

        hook_output = result["hookSpecificOutput"]
        self.assertEqual("allow", hook_output["permissionDecision"])
        self.assertIn("missing-routing-markers", hook_output["additionalContext"])
        self.assertEqual("gpt-5.6-terra", hook_output["updatedInput"]["model"])

    def test_declared_class_without_reason_is_denied(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("reviewer", routing_class="critical", reason=None),
            policy_path=POLICY,
        )

        hook_output = result["hookSpecificOutput"]
        self.assertEqual("deny", hook_output["permissionDecision"])
        self.assertIn("routing-reason-required", hook_output["permissionDecisionReason"])

    def test_invalid_routing_class_is_denied(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("reviewer", routing_class="urgent"),
            policy_path=POLICY,
        )

        hook_output = result["hookSpecificOutput"]
        self.assertEqual("deny", hook_output["permissionDecision"])
        self.assertIn("invalid-routing-class:urgent", hook_output["permissionDecisionReason"])

    def test_unmanaged_agent_is_not_rewritten(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("third_party_agent"),
            policy_path=POLICY,
        )

        self.assertIsNone(result)

    def test_unmanaged_agent_ignores_managed_routing_markers(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("third_party_agent", routing_class="urgent"),
            policy_path=POLICY,
        )

        self.assertIsNone(result)

    def test_unmanaged_agent_is_ignored_when_the_policy_is_invalid(self) -> None:
        result = codex_agent_router.process_hook(
            self.payload("third_party_agent"),
            policy_path=Path("/dev/null"),
        )

        self.assertIsNone(result)

    def test_new_indexed_role_can_be_routed_without_a_router_code_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / "managed-agents.txt"
            names = MANAGED_INDEX.read_text(encoding="utf-8").splitlines()
            names.append("architecture_probe")
            index.write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")
            policy = root / "agent-routing.toml"
            policy.write_text(
                POLICY.read_text(encoding="utf-8")
                + '\n[roles.architecture_probe]\ntier = "sol"\neffort = "xhigh"\n',
                encoding="utf-8",
            )

            result = codex_agent_router.process_hook(
                self.payload("architecture_probe"),
                policy_path=policy,
                managed_index_path=index,
            )

        updated = result["hookSpecificOutput"]["updatedInput"]
        self.assertEqual("gpt-5.6-sol", updated["model"])
        self.assertEqual("xhigh", updated["reasoning_effort"])

    def test_non_agent_tool_is_ignored(self) -> None:
        payload = self.payload("reviewer")
        payload["tool_name"] = "Bash"

        self.assertIsNone(codex_agent_router.process_hook(payload, policy_path=POLICY))

    def test_canonical_spawn_agent_tool_name_is_routed(self) -> None:
        payload = self.payload("reviewer")
        payload["tool_name"] = "spawn_agent"

        result = codex_agent_router.process_hook(payload, policy_path=POLICY)

        self.assertEqual("allow", result["hookSpecificOutput"]["permissionDecision"])
        self.assertEqual(
            "gpt-5.6-sol",
            result["hookSpecificOutput"]["updatedInput"]["model"],
        )

    def test_rewrite_preserves_unmanaged_fields_and_replaces_stale_overrides(self) -> None:
        payload = self.payload("reviewer", routing_class="complex")
        payload["tool_input"].update(
            {
                "model": "stale-model",
                "reasoning_effort": "low",
                "custom_field": {"kept": True},
            }
        )

        result = codex_agent_router.process_hook(payload, policy_path=POLICY)

        updated = result["hookSpecificOutput"]["updatedInput"]
        self.assertEqual("gpt-5.6-sol", updated["model"])
        self.assertEqual("high", updated["reasoning_effort"])
        self.assertEqual({"kept": True}, updated["custom_field"])

    def test_duplicate_routing_markers_are_denied(self) -> None:
        payload = self.payload("reviewer")
        payload["tool_input"]["message"] += "\nROUTING_CLASS=critical"

        result = codex_agent_router.process_hook(payload, policy_path=POLICY)

        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
        self.assertIn(
            "routing-class-required",
            result["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_malformed_routing_markers_are_not_treated_as_missing(self) -> None:
        payload = self.payload("reviewer")
        payload["tool_input"]["message"] = payload["tool_input"]["message"].replace(
            "ROUTING_CLASS=",
            "ROUTING_CLASS =",
        )

        result = codex_agent_router.process_hook(payload, policy_path=POLICY)

        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
        self.assertIn(
            "routing-marker-malformed",
            result["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_cli_rejects_non_object_input_without_a_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(ROUTER)],
            cwd=REPO,
            input=json.dumps([]),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("invalid hook input", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_runtime_rejects_an_unsupported_policy_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "agent-routing.toml"
            policy.write_text(
                POLICY.read_text(encoding="utf-8").replace("version = 1", "version = 2"),
                encoding="utf-8",
            )

            result = codex_agent_router.process_hook(
                self.payload("reviewer"),
                policy_path=policy,
            )

        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
        self.assertIn(
            "routing-policy-invalid",
            result["hookSpecificOutput"]["permissionDecisionReason"],
        )


if __name__ == "__main__":
    unittest.main()
