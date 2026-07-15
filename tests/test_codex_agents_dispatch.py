from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.sh"


class InstallerDispatchTests(unittest.TestCase):
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

    def test_default_behavior_remains_codex_and_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = self.run_installer(home)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(REPO / "AGENTS.md", (home / ".codex" / "AGENTS.md").resolve())
            self.assertEqual(REPO / "AGENTS.md", (home / ".claude" / "CLAUDE.md").resolve())
            self.assertFalse((home / ".codex" / "agents").exists())
            self.assertFalse((home / ".codex" / "config.toml").exists())

    def test_codex_target_does_not_install_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = self.run_installer(home, "codex")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((home / ".codex" / "AGENTS.md").is_symlink())
            self.assertFalse((home / ".codex" / "agents").exists())
            self.assertFalse((home / ".codex" / "config.toml").exists())

    def test_invalid_target_is_rejected_before_any_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = self.run_installer(home, "codex", "bogus-tool")

            self.assertNotEqual(0, result.returncode)
            self.assertFalse((home / ".codex").exists())

    def test_recovery_command_requires_one_valid_transaction_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for args in (
                ("codex-agents-recover",),
                ("codex-agents-recover", "invalid"),
                ("codex-agents-restore", "20260715T120000Z-a1b2c3d4e5f6", "extra"),
            ):
                with self.subTest(args=args):
                    result = self.run_installer(home, *args)
                    self.assertNotEqual(0, result.returncode)
                    self.assertFalse((home / ".codex").exists())

    def test_recovery_command_cannot_mix_with_install_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = self.run_installer(
                home,
                "codex",
                "codex-agents-recover",
                "20260715T120000Z-a1b2c3d4e5f6",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertFalse((home / ".codex").exists())

    def test_missing_python_311_or_tomllib_only_blocks_codex_agents_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bin_dir = home / "bin"
            bin_dir.mkdir()
            fake_python = bin_dir / "python3"
            fake_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            fake_python.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            env["HOME"] = str(home)
            env["AGENT_RULES_LOCAL"] = str(home / "local-rules")

            agents = subprocess.run(
                [str(INSTALLER), "codex-agents"],
                cwd=REPO,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            codex = subprocess.run(
                [str(INSTALLER), "codex"],
                cwd=REPO,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(0, agents.returncode)
            self.assertIn("Python 3.11", agents.stderr)
            self.assertEqual(0, codex.returncode, codex.stderr)


if __name__ == "__main__":
    unittest.main()
