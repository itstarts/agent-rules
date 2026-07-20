from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "scripts" / "validate_codex_agents.py"
ROUTING_CASES = REPO / "tests" / "fixtures" / "codex_agent_routing_cases.json"
ROUTING_POLICY = REPO / "codex" / "agent-routing.toml"
EXPECTED_ROUTES = {
    "architect": ("sol", "xhigh"),
    "data_consistency_reviewer": ("sol", "xhigh"),
    "default": ("sol", "high"),
    "explorer": ("terra", "medium"),
    "final_gate_reviewer": ("sol", "max"),
    "product_analyst": ("terra", "medium"),
    "reviewer": ("sol", "high"),
    "spec_plan_reviewer": ("sol", "high"),
    "test_engineer": ("terra", "high"),
    "ui_ux_designer": ("sol", "medium"),
    "visual_reviewer": ("terra", "medium"),
    "worker": ("sol", "high"),
    "worker_backend": ("sol", "high"),
    "worker_frontend": ("sol", "high"),
}


class RepositoryRoleValidationTests(unittest.TestCase):
    def run_validator(self, source_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), "--source-dir", str(source_dir), *extra],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_repository_roles_pass_validation(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("11 managed Codex agents validated\n", result.stdout)

    def test_repository_role_names_are_spawn_agent_compatible(self) -> None:
        source = REPO / "codex" / "agents"
        names = (source / "managed-agents.txt").read_text(encoding="utf-8").splitlines()

        for name in names:
            with self.subTest(name=name):
                self.assertRegex(name, re.compile(r"^[a-z0-9_]+$"))
                self.assertEqual(name, (source / f"{name}.toml").stem)

    def test_repository_descriptions_are_concise_and_routing_specific(self) -> None:
        source = REPO / "codex" / "agents"
        names = (source / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
        descriptions: list[str] = []

        for name in names:
            role = tomllib.loads((source / f"{name}.toml").read_text(encoding="utf-8"))
            description = role["description"]
            descriptions.append(description)
            with self.subTest(name=name):
                self.assertLessEqual(len(description), 120)
                self.assertIn("用于", description)
                self.assertIn("不用于", description)
                self.assertIn(role["sandbox_mode"], description)
                self.assertIn("production code", description)
                for repeated_boundary in ("安装依赖", "长期服务", "commit", "push", "merge", "tag", "release", "外部系统"):
                    self.assertNotIn(repeated_boundary, description)

        self.assertLessEqual(sum(map(len, descriptions)), 1100)

    def test_managed_roles_delegate_model_and_effort_to_routing_policy(self) -> None:
        source = REPO / "codex" / "agents"
        names = (source / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
        policy = tomllib.loads(ROUTING_POLICY.read_text(encoding="utf-8"))

        for name in names:
            role = tomllib.loads((source / f"{name}.toml").read_text(encoding="utf-8"))
            with self.subTest(name=name):
                self.assertNotIn("model", role)
                self.assertNotIn("model_reasoning_effort", role)

        self.assertEqual(set(EXPECTED_ROUTES), set(policy["roles"]))
        for name, (tier, effort) in EXPECTED_ROUTES.items():
            with self.subTest(route=name):
                self.assertEqual(tier, policy["roles"][name]["tier"])
                self.assertEqual(effort, policy["roles"][name]["effort"])

    def test_final_gate_requires_only_applicable_evidence(self) -> None:
        role = tomllib.loads(
            (REPO / "codex" / "agents" / "final_gate_reviewer.toml").read_text(encoding="utf-8")
        )
        self.assertIn("重量", role["description"])
        self.assertIn("适用", role["description"])
        self.assertIn("已触发且适用", role["developer_instructions"])
        self.assertIn("任务涉及", role["developer_instructions"])
        self.assertIn("影响适用门禁的环境阻塞", role["developer_instructions"])
        self.assertIn("缺失已触发且适用的评审", role["developer_instructions"])

    def test_routing_evaluation_cases_cover_managed_and_builtin_boundaries(self) -> None:
        payload = json.loads(ROUTING_CASES.read_text(encoding="utf-8"))
        cases = payload["cases"]
        managed = set(
            (REPO / "codex" / "agents" / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
        )
        allowed_roles = managed | {"explorer", "worker"}

        self.assertGreaterEqual(len(cases), 15)
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        covered_roles: set[str] = set()
        cases_by_id: dict[str, dict[str, object]] = {}
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    {
                        "id",
                        "prompt",
                        "should_delegate",
                        "expected_roles",
                        "expected_routes",
                        "max_children",
                        "reason",
                        "routing_class",
                    },
                    set(case),
                )
                self.assertIsInstance(case["prompt"], str)
                self.assertTrue(case["prompt"].strip())
                self.assertIsInstance(case["reason"], str)
                self.assertTrue(case["reason"].strip())
                self.assertIs(type(case["should_delegate"]), bool)
                self.assertIs(type(case["max_children"]), int)
                self.assertIsInstance(case["expected_roles"], list)
                self.assertIsInstance(case["expected_routes"], dict)
                self.assertLessEqual(case["max_children"], 4)
                self.assertGreaterEqual(case["max_children"], 0)
                self.assertTrue(set(case["expected_roles"]).issubset(allowed_roles))
                self.assertEqual(len(case["expected_roles"]), len(set(case["expected_roles"])))
                self.assertLessEqual(len(case["expected_roles"]), case["max_children"])
                if case["should_delegate"]:
                    self.assertTrue(case["expected_roles"])
                    self.assertGreater(case["max_children"], 0)
                    self.assertIn(case["routing_class"], {"routine", "complex", "critical", "mechanical"})
                    self.assertEqual(set(case["expected_roles"]), set(case["expected_routes"]))
                    for route in case["expected_routes"].values():
                        self.assertEqual({"model", "reasoning_effort"}, set(route))
                        self.assertIsInstance(route["model"], str)
                        self.assertIsInstance(route["reasoning_effort"], str)
                else:
                    self.assertEqual([], case["expected_roles"])
                    self.assertEqual(0, case["max_children"])
                    self.assertIsNone(case["routing_class"])
                    self.assertEqual({}, case["expected_routes"])
                covered_roles.update(case["expected_roles"])
                cases_by_id[case["id"]] = case

        self.assertTrue(managed.issubset(covered_roles))
        self.assertTrue({"explorer", "worker"}.issubset(covered_roles))
        self.assertTrue(any(not case["should_delegate"] for case in cases))
        self.assertEqual([], cases_by_id["single-symbol-lookup"]["expected_roles"])
        self.assertEqual(
            ["data_consistency_reviewer"],
            cases_by_id["migration-consistency-review"]["expected_roles"],
        )
        self.assertEqual(["visual_reviewer"], cases_by_id["visual-verification"]["expected_roles"])
        self.assertEqual(
            ["worker_backend", "worker_frontend"],
            cases_by_id["parallel-fullstack-slices"]["expected_roles"],
        )
        self.assertEqual(2, cases_by_id["parallel-fullstack-slices"]["max_children"])

    def test_invalid_role_sources_are_rejected_without_echoing_instructions(self) -> None:
        source = REPO / "codex" / "agents"
        cases = {
            "unknown-field": lambda text: text + '\nmodel = "forbidden"\n',
            "empty-required": lambda text: text.replace('name = "architect"', 'name = ""'),
            "sandbox-mismatch": lambda text: text.replace('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"'),
            "invalid-effort": lambda text: text + '\nmodel_reasoning_effort = "turbo"\n',
            "duplicate-nickname": lambda text: text.replace('["Keystone", "Lattice"]', '["Keystone", "Keystone"]'),
            "description-boundary": lambda text: text.replace("不用于实施", "排除实施"),
            "instruction-boundary": lambda text: text.replace("不安装依赖", "保持环境不变", 1),
            "personal-path": lambda text: text + "\n# " + "/" + "Users" + "/example/private\n",
        }
        for expected, mutate in cases.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                copied = Path(tmp) / "agents"
                shutil.copytree(source, copied)
                target = copied / "architect.toml"
                target.write_text(mutate(target.read_text(encoding="utf-8")), encoding="utf-8")

                result = self.run_validator(copied)

                self.assertNotEqual(0, result.returncode)
                self.assertIn("architect.toml", result.stderr)
                self.assertNotIn("只产出架构方案", result.stderr)

    def test_validator_rejects_index_declared_role_without_routing_entry(self) -> None:
        source = REPO / "codex" / "agents"
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "agents"
            shutil.copytree(source, copied)
            probe = (copied / "architect.toml").read_text(encoding="utf-8")
            probe = probe.replace('name = "architect"', 'name = "architecture_probe"')
            probe = probe.replace('["Keystone", "Lattice"]', '["Arch Probe"]')
            (copied / "architecture_probe.toml").write_text(probe, encoding="utf-8")
            names = (copied / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
            names.append("architecture_probe")
            (copied / "managed-agents.txt").write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")

            result = self.run_validator(copied)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("routing-policy: role-set-mismatch", result.stderr)

    def test_validator_accepts_index_declared_role_with_routing_entry(self) -> None:
        source = REPO / "codex" / "agents"
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "agents"
            shutil.copytree(source, copied)
            probe = (copied / "architect.toml").read_text(encoding="utf-8")
            probe = probe.replace('name = "architect"', 'name = "architecture_probe"')
            probe = probe.replace('["Keystone", "Lattice"]', '["Arch Probe"]')
            (copied / "architecture_probe.toml").write_text(probe, encoding="utf-8")
            names = (copied / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
            names.append("architecture_probe")
            (copied / "managed-agents.txt").write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")
            policy = Path(tmp) / "agent-routing.toml"
            policy.write_text(
                ROUTING_POLICY.read_text(encoding="utf-8")
                + '\n[roles.architecture_probe]\ntier = "sol"\neffort = "xhigh"\n',
                encoding="utf-8",
            )

            result = self.run_validator(copied, "--routing-policy", str(policy))

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("12 managed Codex agents validated\n", result.stdout)

    def test_invalid_routing_policies_are_rejected(self) -> None:
        source = REPO / "codex" / "agents"
        original = ROUTING_POLICY.read_text(encoding="utf-8")
        cases = {
            "unknown-role": original + '\n[roles.stale_role]\ntier = "terra"\neffort = "medium"\n',
            "unknown-top-level": original.replace(
                "version = 1\n",
                "version = 1\nunknown = true\n",
            ),
            "boolean-version": original.replace("version = 1", "version = true"),
            "unknown-runtime-key": original.replace(
                'dynamic_tiers = ["sol", "terra"]',
                'dynamic_tiers = ["sol", "terra"]\nunknown = true',
            ),
            "non-string-dynamic-tier": original.replace(
                'dynamic_tiers = ["sol", "terra"]',
                "dynamic_tiers = [{}]",
            ),
            "invalid-tier": original.replace('tier = "terra"', 'tier = "sun"', 1),
            "invalid-effort": original.replace('effort = "medium"', 'effort = "turbo"', 1),
            "empty-model": original.replace('sol = "gpt-5.6-sol"', 'sol = ""'),
        }
        for expected, content in cases.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                policy = Path(tmp) / "agent-routing.toml"
                policy.write_text(content, encoding="utf-8")

                result = self.run_validator(source, "--routing-policy", str(policy))

                self.assertNotEqual(0, result.returncode)
                self.assertIn("routing-policy:", result.stderr)

    def test_validator_rejects_total_description_budget_overflow(self) -> None:
        source = REPO / "codex" / "agents"
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "agents"
            shutil.copytree(source, copied)
            names = (copied / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
            template = (copied / "architect.toml").read_text(encoding="utf-8")
            for index in range(5):
                name = f"architecture_probe_{index}"
                probe = template.replace('name = "architect"', f'name = "{name}"')
                probe = probe.replace('["Keystone", "Lattice"]', f'["Arch Probe {index}"]')
                (copied / f"{name}.toml").write_text(probe, encoding="utf-8")
                names.append(name)
            (copied / "managed-agents.txt").write_text("\n".join(sorted(names)) + "\n", encoding="utf-8")

            result = self.run_validator(copied)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("description-total-too-long", result.stderr)

    def test_installed_validation_accepts_only_exact_managed_symlinks(self) -> None:
        source = REPO / "codex" / "agents"
        with tempfile.TemporaryDirectory() as tmp:
            installed_root = Path(tmp) / "codex-home"
            installed_agents = installed_root / "agents"
            installed_agents.mkdir(parents=True)
            names = (source / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
            for name in names:
                (installed_agents / f"{name}.toml").symlink_to((source / f"{name}.toml").resolve())

            valid = self.run_validator(source, "--installed-root", str(installed_root))
            self.assertEqual(0, valid.returncode, valid.stderr)

            (installed_agents / "architect.toml").unlink()
            (installed_agents / "architect.toml").write_text('name = "architect"\n', encoding="utf-8")
            invalid = self.run_validator(source, "--installed-root", str(installed_root))
            self.assertNotEqual(0, invalid.returncode)
            self.assertIn("installed-target-not-symlink", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
