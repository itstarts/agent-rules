from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import codex_agents  # noqa: E402


class ConfigMergeTests(unittest.TestCase):
    def test_missing_config_creates_only_managed_agents_table(self) -> None:
        result = codex_agents.merge_config_text(None)

        self.assertEqual(
            "[agents]\n"
            "max_threads = 4\n"
            "max_depth = 1\n"
            "interrupt_message = true\n",
            result.text,
        )
        self.assertEqual(("max_threads", "max_depth", "interrupt_message"), result.added_keys)
        self.assertTrue(result.table_created)
        self.assertTrue(result.changed)

    def test_existing_config_without_agents_is_preserved_and_appended(self) -> None:
        original = 'model = "example"\n\n[features]\nmulti_agent = true\n'

        result = codex_agents.merge_config_text(original)

        self.assertTrue(result.text.startswith(original))
        self.assertEqual(original + "\n[agents]\nmax_threads = 4\nmax_depth = 1\ninterrupt_message = true\n", result.text)
        self.assertEqual(("max_threads", "max_depth", "interrupt_message"), result.added_keys)
        self.assertTrue(result.table_created)

    def test_compatible_agents_table_is_byte_for_byte_unchanged(self) -> None:
        original = (
            "[agents]\n"
            "max_threads = 4\n"
            "max_depth = 1\n"
            "interrupt_message = true\n"
            "job_max_runtime_seconds = 900\n"
        )

        result = codex_agents.merge_config_text(original)

        self.assertEqual(original, result.text)
        self.assertEqual((), result.added_keys)
        self.assertFalse(result.table_created)
        self.assertFalse(result.changed)

    def test_missing_keys_are_inserted_in_parent_before_child_tables(self) -> None:
        original = (
            "[agents]\n"
            "job_max_runtime_seconds = 900\n"
            "max_depth = 1\n"
            "\n"
            "[agents.reviewer]\n"
            'description = "keep"\n'
        )

        result = codex_agents.merge_config_text(original)

        self.assertEqual(
            "[agents]\n"
            "max_threads = 4\n"
            "interrupt_message = true\n"
            "job_max_runtime_seconds = 900\n"
            "max_depth = 1\n"
            "\n"
            "[agents.reviewer]\n"
            'description = "keep"\n',
            result.text,
        )
        self.assertEqual(("max_threads", "interrupt_message"), result.added_keys)
        self.assertFalse(result.table_created)
        self.assertTrue(result.changed)

    def test_inline_agents_table_is_rejected_even_when_values_are_compatible(self) -> None:
        original = "agents = { max_threads = 4, max_depth = 1, interrupt_message = true }\n"

        with self.assertRaisesRegex(codex_agents.ConfigError, "unsafe-agents-structure"):
            codex_agents.merge_config_text(original)

    def test_ambiguous_agents_structures_and_conflicts_are_rejected(self) -> None:
        cases = {
            "quoted": '["agents"]\nmax_threads = 4\n',
            "dotted": "agents.max_threads = 4\n",
            "quoted-child-key": '[agents]\n"job_max_runtime_seconds" = 900\n',
            "dotted-child-key": "[agents]\nextra.value = 1\n",
            "quoted-child-table": '[agents]\n[agents."reviewer"]\ndescription = "x"\n',
            "conflict": "[agents]\nmax_depth = 3\n",
            "disabled": "[features]\nmulti_agent = false\n",
            "invalid": "[agents\n",
        }
        for name, original in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(codex_agents.ConfigError):
                    codex_agents.merge_config_text(original)

    def test_fake_headers_in_comments_and_multiline_strings_are_ignored(self) -> None:
        original = (
            '# [agents]\n'
            'note = """\n'
            "[agents]\n"
            "max_threads = 99\n"
            '"""\n'
        )

        result = codex_agents.merge_config_text(original)

        parsed = __import__("tomllib").loads(result.text)
        self.assertEqual("[agents]\nmax_threads = 99\n", parsed["note"])
        self.assertEqual(4, parsed["agents"]["max_threads"])
        self.assertEqual(1, len(codex_agents._agents_table_indexes(result.text)))

    def test_unrelated_table_names_containing_agents_are_preserved(self) -> None:
        original = "[myagents]\nvalue = 1\n\n[user_agents.settings]\nenabled = true\n\n[agents]\nmax_depth = 1\n"

        result = codex_agents.merge_config_text(original)

        parsed = __import__("tomllib").loads(result.text)
        self.assertEqual({"value": 1}, parsed["myagents"])
        self.assertEqual({"settings": {"enabled": True}}, parsed["user_agents"])
        self.assertEqual(4, parsed["agents"]["max_threads"])


if __name__ == "__main__":
    unittest.main()
