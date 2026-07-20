from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.sh"
sys.path.insert(0, str(REPO / "scripts"))

import codex_agent_routing_install  # noqa: E402


class RoutingConfigMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.block = codex_agent_routing_install.managed_hook_block(
            python_executable=Path("/usr/bin/python3"),
            router_path=REPO / "scripts" / "codex_agent_router.py",
        )

    def test_merge_preserves_unrelated_config_and_hooks(self) -> None:
        original = (
            'model = "example-model"\n\n'
            "[[hooks.PreToolUse]]\n"
            'matcher = "^Bash$"\n\n'
            "[[hooks.PreToolUse.hooks]]\n"
            'type = "command"\n'
            'command = "/usr/local/bin/check-bash"\n'
        )

        merged = codex_agent_routing_install.merge_config_text(original, self.block)

        self.assertTrue(merged.changed)
        self.assertIn(original.rstrip(), merged.text)
        self.assertEqual(1, merged.text.count("agent-rules:codex-agent-routing:begin"))
        parsed = tomllib.loads(merged.text)
        self.assertEqual("example-model", parsed["model"])
        self.assertEqual(2, len(parsed["hooks"]["PreToolUse"]))

    def test_merge_is_idempotent_for_the_exact_managed_block(self) -> None:
        first = codex_agent_routing_install.merge_config_text(None, self.block)
        second = codex_agent_routing_install.merge_config_text(first.text, self.block)

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(first.text, second.text)

    def test_merge_replaces_only_a_previous_managed_block(self) -> None:
        previous = self.block.replace("/usr/bin/python3", "/old/python3")
        original = "answer = 42\n\n" + previous

        merged = codex_agent_routing_install.merge_config_text(original, self.block)

        self.assertTrue(merged.changed)
        self.assertEqual(previous, merged.before_block)
        self.assertIn("answer = 42", merged.text)
        self.assertNotIn("/old/python3", merged.text)

    def test_merge_rejects_disabled_hooks_and_malformed_markers(self) -> None:
        cases = (
            "[features]\nhooks = false\n",
            "# agent-rules:codex-agent-routing:begin\n",
            "# agent-rules:codex-agent-routing:end\n",
        )
        for original in cases:
            with self.subTest(original=original):
                with self.assertRaises(codex_agent_routing_install.ConfigError):
                    codex_agent_routing_install.merge_config_text(original, self.block)

    def test_marker_examples_inside_multiline_strings_are_not_managed_blocks(self) -> None:
        example = self.block.rstrip()
        original = f'note = """\n{example}\n"""\n'

        merged = codex_agent_routing_install.merge_config_text(original, self.block)

        self.assertTrue(merged.changed)
        parsed = tomllib.loads(merged.text)
        self.assertIn("agent-rules:codex-agent-routing:begin", parsed["note"])
        self.assertEqual(1, len(parsed["hooks"]["PreToolUse"]))

    def test_restore_reinstates_previous_managed_block_and_keeps_later_changes(self) -> None:
        previous = self.block.replace("/usr/bin/python3", "/old/python3")
        installed = codex_agent_routing_install.merge_config_text(
            "answer = 42\n\n" + previous,
            self.block,
        ).text
        current = installed + "\n[local]\nkept = true\n"

        restored = codex_agent_routing_install.restore_config_text(
            current,
            installed_block=self.block,
            before_block=previous,
        )

        self.assertIn("/old/python3", restored)
        self.assertNotIn("/usr/bin/python3", restored)
        self.assertIn("[local]\nkept = true", restored)
        tomllib.loads(restored)


class RoutingInstallerIntegrationTests(unittest.TestCase):
    def run_installer(self, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("CODEX_HOME", None)
        env["HOME"] = str(home)
        env["AGENT_RULES_LOCAL"] = str(home / "local-rules")
        return subprocess.run(
            [str(INSTALLER), *args],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def transaction_id(self, result: subprocess.CompletedProcess[str]) -> str:
        match = re.search(r"transaction: ([0-9]{8}T[0-9]{6}Z-[0-9a-f]{12})", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        return match.group(1)

    def leave_in_progress_transaction(
        self,
        home: Path,
        *,
        module: str,
        stage: str,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("CODEX_HOME", None)
        env["HOME"] = str(home)
        env["PYTHONPATH"] = str(REPO / "scripts")
        program = (
            f"from {module} import install; import os; "
            f"install(failpoint=lambda point: os._exit(73) if point == {stage!r} else None)"
        )
        return subprocess.run(
            [sys.executable, "-B", "-c", program],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_install_is_idempotent_and_restore_preserves_later_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            config = root / "config.toml"
            config.write_text('model = "kept"\n', encoding="utf-8")

            installed = self.run_installer(home, "codex-agent-routing")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = self.transaction_id(installed)
            installed_text = config.read_text(encoding="utf-8")
            self.assertIn("agent-rules:codex-agent-routing:begin", installed_text)

            repeated = self.run_installer(home, "codex-agent-routing")
            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertIn("already ready", repeated.stdout)
            namespace = root / ".agent-rules-backups" / "codex-agent-routing"
            self.assertEqual(1, len(list(namespace.iterdir())))

            config.write_text(installed_text + "\n[local]\nkept = true\n", encoding="utf-8")
            restored = self.run_installer(
                home,
                "codex-agent-routing-restore",
                transaction_id,
            )

            self.assertEqual(0, restored.returncode, restored.stderr)
            final = config.read_text(encoding="utf-8")
            self.assertNotIn("agent-rules:codex-agent-routing:begin", final)
            self.assertIn('model = "kept"', final)
            self.assertIn("[local]\nkept = true", final)
            tomllib.loads(final)

    def test_restore_without_later_changes_restores_exact_config_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            config = root / "config.toml"
            original = 'model = "kept"'
            config.write_text(original, encoding="utf-8")
            installed = self.run_installer(home, "codex-agent-routing")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = self.transaction_id(installed)

            restored = self.run_installer(
                home,
                "codex-agent-routing-restore",
                transaction_id,
            )

            self.assertEqual(0, restored.returncode, restored.stderr)
            self.assertEqual(original, config.read_text(encoding="utf-8"))

    def test_disabled_hooks_fail_without_a_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            config = root / "config.toml"
            original = "[features]\nhooks = false\n"
            config.write_text(original, encoding="utf-8")

            result = self.run_installer(home, "codex-agent-routing")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("hooks-disabled", result.stderr)
            self.assertEqual(original, config.read_text(encoding="utf-8"))
            self.assertFalse((root / ".agent-rules-backups").exists())

    def test_existing_hooks_json_is_rejected_to_avoid_mixed_hook_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            hooks_json = root / "hooks.json"
            hooks_json.write_text('{"hooks": {}}\n', encoding="utf-8")

            result = self.run_installer(home, "codex-agent-routing")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("hooks.json-present", result.stderr)
            self.assertFalse((root / "config.toml").exists())
            self.assertFalse((root / ".agent-rules-backups").exists())

    def test_existing_agent_hook_is_rejected_without_a_transaction(self) -> None:
        for matcher in ("Agent", "^spawn_agent$"):
            with self.subTest(matcher=matcher), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                root = home / ".codex"
                root.mkdir()
                config = root / "config.toml"
                original = (
                    "[[hooks.PreToolUse]]\n"
                    f'matcher = "{matcher}"\n\n'
                    "[[hooks.PreToolUse.hooks]]\n"
                    'type = "command"\n'
                    'command = "/usr/local/bin/custom-agent-hook"\n'
                )
                config.write_text(original, encoding="utf-8")

                result = self.run_installer(home, "codex-agent-routing")

                self.assertNotEqual(0, result.returncode)
                self.assertIn("conflicting-agent-hook", result.stderr)
                self.assertEqual(original, config.read_text(encoding="utf-8"))
                self.assertFalse((root / ".agent-rules-backups").exists())

    def test_restore_refuses_an_edited_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_installer(home, "codex-agent-routing")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = self.transaction_id(installed)
            config = home / ".codex" / "config.toml"
            changed = config.read_text(encoding="utf-8").replace("timeout = 10", "timeout = 11")
            config.write_text(changed, encoding="utf-8")

            restored = self.run_installer(
                home,
                "codex-agent-routing-restore",
                transaction_id,
            )

            self.assertNotEqual(0, restored.returncode)
            self.assertIn("managed hook changed", restored.stderr)
            self.assertEqual(changed, config.read_text(encoding="utf-8"))

    def test_codex_agents_install_blocks_an_in_progress_routing_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            crashed = self.leave_in_progress_transaction(
                home,
                module="codex_agent_routing_install",
                stage="journal-durable",
            )
            self.assertEqual(73, crashed.returncode, crashed.stderr)

            result = self.run_installer(home, "codex-agents")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("codex-agent-routing-recover", result.stderr)

    def test_routing_install_blocks_an_in_progress_codex_agents_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            crashed = self.leave_in_progress_transaction(
                home,
                module="codex_agents",
                stage="journal-durable",
            )
            self.assertEqual(73, crashed.returncode, crashed.stderr)

            result = self.run_installer(home, "codex-agent-routing")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("codex-agents-recover", result.stderr)

    def test_hard_exit_after_config_apply_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            crashed = self.leave_in_progress_transaction(
                home,
                module="codex_agent_routing_install",
                stage="config-applied",
            )
            self.assertEqual(73, crashed.returncode, crashed.stderr)
            root = home / ".codex"
            config = root / "config.toml"
            self.assertIn(
                "agent-rules:codex-agent-routing:begin",
                config.read_text(encoding="utf-8"),
            )
            namespace = root / ".agent-rules-backups" / "codex-agent-routing"
            transaction_id = next(
                path.name for path in namespace.iterdir() if not path.name.startswith(".")
            )

            recovered = self.run_installer(
                home,
                "codex-agent-routing-recover",
                transaction_id,
            )
            repeated = self.run_installer(
                home,
                "codex-agent-routing-recover",
                transaction_id,
            )

            self.assertEqual(0, recovered.returncode, recovered.stderr)
            self.assertEqual(0, repeated.returncode, repeated.stderr)
            self.assertFalse(config.exists())

    def test_older_restored_transaction_cannot_remove_a_later_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first = self.run_installer(home, "codex-agent-routing")
            self.assertEqual(0, first.returncode, first.stderr)
            first_id = self.transaction_id(first)
            restored = self.run_installer(home, "codex-agent-routing-restore", first_id)
            self.assertEqual(0, restored.returncode, restored.stderr)

            second = self.run_installer(home, "codex-agent-routing")
            self.assertEqual(0, second.returncode, second.stderr)
            second_id = self.transaction_id(second)
            self.assertNotEqual(first_id, second_id)

            stale_restore = self.run_installer(
                home,
                "codex-agent-routing-restore",
                first_id,
            )

            self.assertNotEqual(0, stale_restore.returncode)
            self.assertIn("newer committed routing transaction", stale_restore.stderr)
            config = home / ".codex" / "config.toml"
            self.assertIn(
                "agent-rules:codex-agent-routing:begin",
                config.read_text(encoding="utf-8"),
            )

    def test_older_recovered_transaction_cannot_remove_a_later_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            crashed = self.leave_in_progress_transaction(
                home,
                module="codex_agent_routing_install",
                stage="config-applied",
            )
            self.assertEqual(73, crashed.returncode, crashed.stderr)
            root = home / ".codex"
            namespace = root / ".agent-rules-backups" / "codex-agent-routing"
            first_id = next(
                path.name for path in namespace.iterdir() if not path.name.startswith(".")
            )
            recovered = self.run_installer(
                home,
                "codex-agent-routing-recover",
                first_id,
            )
            self.assertEqual(0, recovered.returncode, recovered.stderr)
            second = self.run_installer(home, "codex-agent-routing")
            self.assertEqual(0, second.returncode, second.stderr)

            stale_recover = self.run_installer(
                home,
                "codex-agent-routing-recover",
                first_id,
            )

            self.assertEqual(0, stale_recover.returncode, stale_recover.stderr)
            self.assertIn(
                "agent-rules:codex-agent-routing:begin",
                (root / "config.toml").read_text(encoding="utf-8"),
            )

    def test_tampered_routing_backup_blocks_later_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            (root / "config.toml").write_text('model = "kept"\n', encoding="utf-8")
            installed = self.run_installer(home, "codex-agent-routing")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = self.transaction_id(installed)
            backup = (
                root
                / ".agent-rules-backups"
                / "codex-agent-routing"
                / transaction_id
                / "config.bin"
            )
            backup.write_text("tampered\n", encoding="utf-8")

            repeated = self.run_installer(home, "codex-agent-routing")

            self.assertNotEqual(0, repeated.returncode)
            self.assertIn("backup digest", repeated.stderr)


if __name__ == "__main__":
    unittest.main()
