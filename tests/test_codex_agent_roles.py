from __future__ import annotations

import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "scripts" / "validate_codex_agents.py"


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

    def test_invalid_role_sources_are_rejected_without_echoing_instructions(self) -> None:
        source = REPO / "codex" / "agents"
        cases = {
            "unknown-field": lambda text: text + '\nmodel = "forbidden"\n',
            "empty-required": lambda text: text.replace('name = "architect"', 'name = ""'),
            "sandbox-mismatch": lambda text: text.replace('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"'),
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
