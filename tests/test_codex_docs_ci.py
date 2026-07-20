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

    def test_release_audit_baseline_and_notes_format_are_governed(self) -> None:
        rules = self.read("AGENTS.md")
        for marker in (
            "历史安全基线",
            "该 tag 之后新增的可达历史",
            "基线不可验证",
            "不得移动、覆盖、删除或复用",
            "## 本版内容",
            "Keep a Changelog",
            "### Verification",
            "compare 链接",
        ):
            self.assertIn(marker, rules)

        contributing = self.read("CONTRIBUTING.md")
        chinese_process = contributing.split("## 发版流程", 1)[1].split(
            "## Release notes 模板", 1
        )[0]
        english_process = contributing.split("### Release Process", 1)[1].split(
            "### Release Notes Template", 1
        )[0]

        for section in (chinese_process, english_process):
            for marker in (
                "git rev-list --all",
                "BASELINE_TAG..HEAD",
                "GitHub Release",
                "annotated tag",
            ):
                self.assertIn(marker, section)

        for section, markers in (
            (
                chinese_process,
                (
                    "历史被改写",
                    "基线不可验证",
                    "增量扫描异常",
                    "回退到全量扫描",
                    "peeled commit 与 `main` 一致",
                    "以只读方式核对",
                ),
            ),
            (
                english_process,
                (
                    "rewritten history",
                    "an unverifiable baseline",
                    "incremental-scan anomaly",
                    "Fall back to a full audit",
                    "peeled commit matches `main`",
                    "read back and verify",
                ),
            ),
        ):
            for marker in markers:
                self.assertIn(marker, section)

        chinese_order = (
            "合入 `main`",
            "等待合入提交的 CI 成功",
            "精确且干净的最终 `main` 提交上执行",
            "定稿 Release notes",
            "在本地创建 annotated tag",
            "推送 tag 后再次核对远端 tag 身份",
            "创建 GitHub Release",
        )
        english_order = (
            "Merge into `main`",
            "wait for CI on the merge commit to pass",
            "exact, clean final `main` commit",
            "Finalize the release notes",
            "Create the annotated tag locally",
            "Push the tag, then verify the remote tag identity",
            "Create the GitHub Release",
        )
        for section, markers in (
            (chinese_process, chinese_order),
            (english_process, english_order),
        ):
            positions = [section.index(marker) for marker in markers]
            self.assertEqual(positions, sorted(positions))

        chinese_template = contributing.split("## Release notes 模板", 1)[1].split(
            "## English", 1
        )[0]
        english_template = contributing.split("### Release Notes Template", 1)[1]
        for section in (chinese_template, english_template):
            for marker in (
                "## 本版内容",
                "### Verification",
                "/compare/vPREVIOUS...vCURRENT",
                "/tree/vCURRENT",
            ):
                self.assertIn(marker, section)
        self.assertIn("空分类省略", chinese_template)
        self.assertIn("Keep only applicable", english_template)

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
