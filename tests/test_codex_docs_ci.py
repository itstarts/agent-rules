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

    def test_readmes_expose_only_the_short_install_entry(self) -> None:
        for relative in ("README.md", "README.en.md"):
            with self.subTest(relative=relative):
                content = self.read(relative)
                self.assertIn("./install.sh codex-agents", content)
                self.assertIn("docs/install", content)
                self.assertNotIn("install-in-progress", content)

    def test_install_guides_cover_commands_and_safety_contract(self) -> None:
        required = (
            "Python 3.11+",
            "CODEX_HOME",
            "./install.sh codex-agents",
            "codex-agents-recover",
            "codex-agents-restore",
            "managed-agents.txt",
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


if __name__ == "__main__":
    unittest.main()
