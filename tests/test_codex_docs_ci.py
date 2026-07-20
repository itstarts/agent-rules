from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


class CodexDocsAndCiContractTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (REPO / relative).read_text(encoding="utf-8")

    def test_ci_runs_role_validation_and_all_python_tests(self) -> None:
        workflow = self.read(".github/workflows/ci.yml")
        self.assertIn("python3 -B scripts/validate_codex_agents.py", workflow)
        self.assertIn("python3 -B -m unittest discover -s tests -p 'test_*.py'", workflow)

    def test_global_rules_cover_dynamic_route_fork_constraints(self) -> None:
        rules = self.read("AGENTS.md")
        for marker in ('fork_turns = "none"', "正整数", '"all"', "继承父 Agent"):
            self.assertIn(marker, rules)

    def test_readmes_expose_only_the_short_install_entries(self) -> None:
        for relative in ("README.md", "README.en.md"):
            with self.subTest(relative=relative):
                content = self.read(relative)
                self.assertIn("./install.sh codex-agents", content)
                self.assertIn("./install.sh codex-agent-routing", content)
                self.assertIn("docs/install", content)
                self.assertNotIn("install-in-progress", content)

    def test_install_guides_cover_commands_and_safety_contract(self) -> None:
        required = (
            "Python 3.11+",
            "CODEX_HOME",
            "./install.sh codex-agents",
            "codex-agents-recover",
            "codex-agents-restore",
            "./install.sh codex-agent-routing",
            "codex-agent-routing-recover",
            "codex-agent-routing-restore",
            "managed-agents.txt",
            "PreToolUse",
            "^Agent$",
            "max_threads = 4",
            "max_depth = 1",
            "interrupt_message = true",
            "transaction ID",
        )
        for relative in ("docs/install.md", "docs/install.en.md"):
            with self.subTest(relative=relative):
                content = self.read(relative)
                for marker in required:
                    self.assertIn(marker, content)

    def test_how_it_works_guides_cover_source_locking_and_recovery(self) -> None:
        required = (
            "codex/agents",
            "managed-agents.txt",
            "root_fd",
            "journal.toml",
            "read-only",
            "workspace-write",
        )
        for relative in ("docs/how-it-works.md", "docs/how-it-works.en.md"):
            with self.subTest(relative=relative):
                content = self.read(relative)
                for marker in required:
                    self.assertIn(marker, content)

    def test_how_it_works_guides_cover_role_routing_and_effort_policy(self) -> None:
        shared = (
            "product_analyst",
            "architect",
            "spec_plan_reviewer",
            "reviewer",
            "data_consistency_reviewer",
            "final_gate_reviewer",
            "ui_ux_designer",
            "visual_reviewer",
            "worker_backend",
            "worker_frontend",
            "test_engineer",
            "agent-routing.toml",
            "codex_agent_router.py",
            "ROUTING_CLASS",
            "ROUTING_REASON",
            "routine",
            "complex",
            "critical",
            "mechanical",
            "reasoning_effort",
            "fork_turns",
            "ESCALATION_REQUIRED",
            "Sol",
            "Terra",
            "Luna",
        )
        for relative, heading in (
            ("docs/how-it-works.md", "角色路由"),
            ("docs/how-it-works.en.md", "Role Routing"),
        ):
            with self.subTest(relative=relative):
                content = self.read(relative)
                self.assertIn(heading, content)
                for marker in shared:
                    self.assertIn(marker, content)

    def test_legacy_agent_design_docs_record_the_dynamic_routing_amendment(self) -> None:
        spec = self.read(
            "docs/superpowers/specs/2026-07-15-versioned-codex-custom-agents-design.md"
        )
        plan = self.read("docs/superpowers/plans/2026-07-15-versioned-codex-custom-agents.md")

        for content in (spec, plan):
            self.assertIn("2026-07-20", content)
            self.assertIn("agent-routing.toml", content)
            self.assertIn("codex-agent-routing", content)
        self.assertNotIn("只有以下边界明确的轻量只读角色固定", spec)
        self.assertNotIn(
            'product_analyst`、`ui_ux_designer`、`visual_reviewer` 使用 '
            '`model_reasoning_effort = "medium"`',
            plan,
        )


if __name__ == "__main__":
    unittest.main()
