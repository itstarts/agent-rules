from __future__ import annotations

import os
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.sh"
sys.path.insert(0, str(REPO / "scripts"))

import codex_agents  # noqa: E402
MANAGED = tuple(
    line.strip()
    for line in (REPO / "codex" / "agents" / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
    if line.strip()
)


class CodexAgentsInstallTests(unittest.TestCase):
    def run_install(self, home: Path, *, codex_home: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["AGENT_RULES_LOCAL"] = str(home / "local-rules")
        if codex_home is None:
            env.pop("CODEX_HOME", None)
        else:
            env["CODEX_HOME"] = str(codex_home)
        return subprocess.run(
            [str(INSTALLER), "codex-agents"],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_first_install_creates_managed_links_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = self.run_install(home)
            codex_root = home / ".codex"

            self.assertEqual(0, result.returncode, result.stderr)
            for name in MANAGED:
                target = codex_root / "agents" / f"{name}.toml"
                self.assertTrue(target.is_symlink(), name)
                self.assertEqual((REPO / "codex" / "agents" / f"{name}.toml").resolve(), target.resolve())
            config = tomllib.loads((codex_root / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(4, config["agents"]["max_threads"])
            self.assertEqual(1, config["agents"]["max_depth"])
            self.assertIs(True, config["agents"]["interrupt_message"])
            self.assertRegex(result.stdout, r"transaction: [0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")

    def test_repeat_install_is_idempotent_and_preserves_unmanaged_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex"
            agents = codex_root / "agents"
            agents.mkdir(parents=True)
            unmanaged = agents / "personal-helper.toml"
            unmanaged.write_text('name = "personal-helper"\n', encoding="utf-8")
            config = codex_root / "config.toml"
            original_prefix = 'model = "example"\n\n[features]\nmulti_agent = true\n'
            config.write_text(original_prefix, encoding="utf-8")

            first = self.run_install(home)
            self.assertEqual(0, first.returncode, first.stderr)
            first_config = config.read_bytes()
            transactions = list((codex_root / ".agent-rules-backups" / "codex-agents").iterdir())

            second = self.run_install(home)

            self.assertEqual(0, second.returncode, second.stderr)
            self.assertIn("already ready", second.stdout)
            self.assertEqual(first_config, config.read_bytes())
            self.assertEqual('name = "personal-helper"\n', unmanaged.read_text(encoding="utf-8"))
            self.assertEqual(transactions, list((codex_root / ".agent-rules-backups" / "codex-agents").iterdir()))
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual("example", parsed["model"])
            self.assertIs(True, parsed["features"]["multi_agent"])

    def test_explicit_missing_codex_home_is_rejected_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_home = home / "missing-codex-home"

            result = self.run_install(home, codex_home=codex_home)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("must already exist", result.stderr)
            self.assertFalse(codex_home.exists())

    def test_explicit_existing_codex_home_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            codex_home = Path(tmp) / "isolated-codex"
            codex_home.mkdir()

            result = self.run_install(home, codex_home=codex_home)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((codex_home / "agents" / "architect.toml").is_symlink())
            self.assertTrue((codex_home / "config.toml").is_file())
            self.assertFalse((home / ".codex").exists())

    def test_compatible_legacy_role_is_backed_up_and_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            legacy = home / ".codex" / "agents" / "architect.toml"
            legacy.parent.mkdir(parents=True)
            legacy_content = 'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n'
            legacy.write_text(legacy_content, encoding="utf-8")

            result = self.run_install(home)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(legacy.is_symlink())
            transaction = next((home / ".codex" / ".agent-rules-backups" / "codex-agents").iterdir())
            self.assertEqual(legacy_content.encode(), (transaction / "role-architect.bin").read_bytes())
            self.assertEqual(0o600, (transaction / "role-architect.bin").stat().st_mode & 0o777)

    def test_broken_managed_symlink_is_backed_up_as_metadata_and_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            architect = home / ".codex" / "agents" / "architect.toml"
            architect.parent.mkdir(parents=True)
            broken_target = home / "moved-repository" / "architect.toml"
            architect.symlink_to(broken_target)

            result = self.run_install(home)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual((REPO / "codex" / "agents" / "architect.toml").resolve(), architect.resolve())
            transaction = next((home / ".codex" / ".agent-rules-backups" / "codex-agents").iterdir())
            metadata = transaction / "role-architect.symlink"
            self.assertEqual(str(broken_target), metadata.read_text(encoding="utf-8"))
            self.assertFalse(metadata.is_symlink())

    def test_self_referential_relative_symlink_is_not_misreported_as_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            architect = home / ".codex" / "agents" / "architect.toml"
            architect.parent.mkdir(parents=True)
            architect.symlink_to("architect.toml")

            result = self.run_install(home)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("already ready", result.stdout)
            self.assertEqual(str(REPO / "codex" / "agents" / "architect.toml"), os.readlink(architect))

    def test_foreign_live_symlink_conflict_is_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = home / "foreign.toml"
            target.write_text('name = "architect"\n', encoding="utf-8")
            architect = home / ".codex" / "agents" / "architect.toml"
            architect.parent.mkdir(parents=True)
            architect.symlink_to(target)

            result = self.run_install(home)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(target.resolve(), architect.resolve())
            self.assertFalse((home / ".codex" / ".agent-rules-backups").exists())
            self.assertFalse((home / ".codex" / "config.toml").exists())

    def test_managed_config_conflict_is_zero_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex"
            codex_root.mkdir()
            config = codex_root / "config.toml"
            original = "[agents]\nmax_threads = 99\n"
            config.write_text(original, encoding="utf-8")

            result = self.run_install(home)

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(original, config.read_text(encoding="utf-8"))
            self.assertFalse((codex_root / "agents").exists())
            self.assertFalse((codex_root / ".agent-rules-backups").exists())

    def test_in_progress_journal_blocks_a_new_install_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first = self.run_install(home)
            self.assertEqual(0, first.returncode, first.stderr)
            transaction_id = first.stdout.split("transaction: ", 1)[1].split()[0]
            namespace = home / ".codex" / ".agent-rules-backups" / "codex-agents"
            journal = namespace / transaction_id / "journal.toml"
            journal.write_text(
                journal.read_text(encoding="utf-8").replace('state = "committed"', 'state = "install-in-progress"'),
                encoding="utf-8",
            )
            before = sorted(path.name for path in namespace.iterdir())

            second = self.run_install(home)

            self.assertNotEqual(0, second.returncode)
            self.assertIn(transaction_id, second.stderr)
            self.assertIn("codex-agents-recover", second.stderr)
            self.assertEqual(before, sorted(path.name for path in namespace.iterdir()))

    def test_interactive_confirmation_creates_one_idempotent_backup_only_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex"
            codex_root.mkdir()
            config = codex_root / "config.toml"
            original = b"[agents]\nmax_threads = 99\n"
            config.write_bytes(original)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                first = codex_agents.install(interaction=lambda _: True)
                second = codex_agents.install(interaction=lambda _: True)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertEqual(first, second)
            self.assertTrue(first.startswith("snapshot:"))
            self.assertEqual(original, config.read_bytes())
            self.assertFalse((codex_root / "agents").exists())
            snapshots = list((codex_root / ".agent-rules-backups" / "codex-agent-conflicts").iterdir())
            self.assertEqual(1, len(snapshots))
            self.assertEqual(0o600, snapshots[0].stat().st_mode & 0o777)

    def test_transaction_and_config_permissions_are_not_broader_than_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = self.run_install(home)
            self.assertEqual(0, result.returncode, result.stderr)
            codex_root = home / ".codex"
            transaction = next((codex_root / ".agent-rules-backups" / "codex-agents").iterdir())

            self.assertEqual(0o600, (codex_root / "config.toml").stat().st_mode & 0o777)
            self.assertEqual(0o700, transaction.stat().st_mode & 0o777)
            self.assertEqual(0o600, (transaction / "journal.toml").stat().st_mode & 0o777)

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_pre_journal_crash_leaves_only_cleanable_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                child = os.fork()
                if child == 0:
                    codex_agents.install(
                        failpoint=lambda point: os._exit(77) if point == "staging-created" else None
                    )
                    os._exit(0)
                _, status = os.waitpid(child, 0)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertEqual(77, os.waitstatus_to_exitcode(status))
            second = self.run_install(home)
            self.assertEqual(0, second.returncode, second.stderr)
            namespace = home / ".codex" / ".agent-rules-backups" / "codex-agents"
            self.assertFalse(any(path.name.startswith(".staging-") for path in namespace.iterdir()))
            self.assertEqual(1, len([path for path in namespace.iterdir() if not path.name.startswith(".")]))

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_journal_temporary_file_crash_is_cleanly_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            original_replace = codex_agents._replace_file_at
            try:
                child = os.fork()
                if child == 0:
                    def crash_before_journal_rename(parent_fd: int, name: str, content: bytes, mode: int = 0o600) -> None:
                        if name == "journal.toml":
                            codex_agents._create_file_at(
                                parent_fd,
                                ".journal.toml.tmp-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                                content[: max(1, len(content) // 2)],
                                mode,
                            )
                            os._exit(76)
                        original_replace(parent_fd, name, content, mode)

                    codex_agents._replace_file_at = crash_before_journal_rename
                    codex_agents.install()
                    os._exit(0)
                _, status = os.waitpid(child, 0)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertEqual(76, os.waitstatus_to_exitcode(status))
            retried = self.run_install(home)
            self.assertEqual(0, retried.returncode, retried.stderr)

    def test_unknown_journal_state_blocks_install_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first = self.run_install(home)
            transaction_id = first.stdout.split("transaction: ", 1)[1].split()[0]
            journal = (
                home
                / ".codex"
                / ".agent-rules-backups"
                / "codex-agents"
                / transaction_id
                / "journal.toml"
            )
            journal.write_text(
                journal.read_text(encoding="utf-8").replace('state = "committed"', 'state = "unknown"'),
                encoding="utf-8",
            )

            second = self.run_install(home)

            self.assertNotEqual(0, second.returncode)
            self.assertIn("state is invalid", second.stderr)
            self.assertNotIn("Traceback", second.stderr)

    def test_legacy_completed_transaction_history_does_not_block_new_install(self) -> None:
        for terminal_state in ("restored", "recovered"):
            with self.subTest(terminal_state=terminal_state), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                first = self.run_install(home)
                self.assertEqual(0, first.returncode, first.stderr)
                transaction_id = first.stdout.split("transaction: ", 1)[1].split()[0]
                restored = subprocess.run(
                    [str(INSTALLER), "codex-agents-restore", transaction_id],
                    cwd=REPO,
                    env={**os.environ, "HOME": str(home), "AGENT_RULES_LOCAL": str(home / "local-rules")},
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, restored.returncode, restored.stderr)
                journal = (
                    home
                    / ".codex"
                    / ".agent-rules-backups"
                    / "codex-agents"
                    / transaction_id
                    / "journal.toml"
                )
                journal_text = journal.read_text(encoding="utf-8").replace(
                    "schema_version = 2", "schema_version = 1"
                )
                if terminal_state == "recovered":
                    journal_text = journal_text.replace('state = "restored"', 'state = "recovered"')
                journal.write_text(journal_text, encoding="utf-8")

                second = self.run_install(home)

                self.assertEqual(0, second.returncode, second.stderr)
                self.assertTrue((home / ".codex" / "agents" / "architect.toml").is_symlink())

    def test_pre_journal_failpoints_leave_targets_unchanged_and_no_official_transaction(self) -> None:
        points = (
            "role-object-prepared:architect",
            "config-object-prepared",
            "backup-written:architect",
            "backup-written:config",
            "backups-fsynced",
            "before-journal-write",
            "journal-written-in-staging",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                root = home / ".codex"
                agents = root / "agents"
                agents.mkdir(parents=True)
                architect = agents / "architect.toml"
                legacy = b'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n'
                architect.write_bytes(legacy)
                config = root / "config.toml"
                original_config = b'model = "example"\n'
                config.write_bytes(original_config)
                previous_home = os.environ.get("HOME")
                previous_codex_home = os.environ.pop("CODEX_HOME", None)
                os.environ["HOME"] = str(home)

                def fail(current: str) -> None:
                    if current == point:
                        raise RuntimeError("injected failure")

                try:
                    with self.assertRaisesRegex(RuntimeError, "injected failure"):
                        codex_agents.install(failpoint=fail)
                finally:
                    if previous_home is None:
                        os.environ.pop("HOME", None)
                    else:
                        os.environ["HOME"] = previous_home
                    if previous_codex_home is not None:
                        os.environ["CODEX_HOME"] = previous_codex_home

                self.assertFalse(architect.is_symlink())
                self.assertEqual(legacy, architect.read_bytes())
                self.assertEqual(original_config, config.read_bytes())
                namespace = root / ".agent-rules-backups" / "codex-agents"
                self.assertEqual([], list(namespace.iterdir()))

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_pre_journal_forced_exit_matrix_is_cleanly_retryable(self) -> None:
        points = (
            "staging-created",
            "role-object-prepared:architect",
            "config-object-prepared",
            "install-objects-fsynced",
            "backup-written:architect",
            "backup-written:config",
            "backups-fsynced",
            "before-journal-write",
            "journal-written-in-staging",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                root = home / ".codex"
                agents = root / "agents"
                agents.mkdir(parents=True)
                architect = agents / "architect.toml"
                legacy = b'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n'
                architect.write_bytes(legacy)
                config = root / "config.toml"
                original_config = b'model = "before"\n'
                config.write_bytes(original_config)
                previous_home = os.environ.get("HOME")
                previous_codex_home = os.environ.pop("CODEX_HOME", None)
                os.environ["HOME"] = str(home)
                try:
                    child = os.fork()
                    if child == 0:
                        codex_agents.install(
                            failpoint=lambda current: os._exit(72) if current == point else None
                        )
                        os._exit(0)
                    _, status = os.waitpid(child, 0)
                finally:
                    if previous_home is None:
                        os.environ.pop("HOME", None)
                    else:
                        os.environ["HOME"] = previous_home
                    if previous_codex_home is not None:
                        os.environ["CODEX_HOME"] = previous_codex_home

                self.assertEqual(72, os.waitstatus_to_exitcode(status))
                self.assertEqual(legacy, architect.read_bytes())
                self.assertEqual(original_config, config.read_bytes())
                retried = self.run_install(home)
                self.assertEqual(0, retried.returncode, retried.stderr)
                namespace = root / ".agent-rules-backups" / "codex-agents"
                self.assertFalse(any(path.name.startswith(".staging-") for path in namespace.iterdir()))

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_published_install_forced_exit_matrix_is_recoverable(self) -> None:
        points = (
            "journal-durable",
            *(f"role-applied:{name}" for name in MANAGED),
            "config-prepared",
            "config-applied",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                root = home / ".codex"
                agents = root / "agents"
                agents.mkdir(parents=True)
                architect = agents / "architect.toml"
                legacy = b'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n'
                architect.write_bytes(legacy)
                config = root / "config.toml"
                original_config = b'model = "before"\n'
                config.write_bytes(original_config)
                previous_home = os.environ.get("HOME")
                previous_codex_home = os.environ.pop("CODEX_HOME", None)
                os.environ["HOME"] = str(home)
                try:
                    child = os.fork()
                    if child == 0:
                        codex_agents.install(
                            failpoint=lambda current: os._exit(71) if current == point else None
                        )
                        os._exit(0)
                    _, status = os.waitpid(child, 0)
                finally:
                    if previous_home is None:
                        os.environ.pop("HOME", None)
                    else:
                        os.environ["HOME"] = previous_home
                    if previous_codex_home is not None:
                        os.environ["CODEX_HOME"] = previous_codex_home

                self.assertEqual(71, os.waitstatus_to_exitcode(status))
                namespace = root / ".agent-rules-backups" / "codex-agents"
                transaction_id = next(path.name for path in namespace.iterdir() if not path.name.startswith("."))
                recovered = subprocess.run(
                    [str(INSTALLER), "codex-agents-recover", transaction_id],
                    cwd=REPO,
                    env={**os.environ, "HOME": str(home), "AGENT_RULES_LOCAL": str(home / "local-rules")},
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, recovered.returncode, recovered.stderr)
                self.assertEqual(legacy, architect.read_bytes())
                self.assertEqual(original_config, config.read_bytes())
                for name in MANAGED:
                    if name != "architect":
                        self.assertFalse((agents / f"{name}.toml").exists())

    def test_default_root_is_removed_when_open_or_lock_phase_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                with self.assertRaisesRegex(RuntimeError, "injected root failure"):
                    codex_agents.install(
                        failpoint=lambda point: (_ for _ in ()).throw(RuntimeError("injected root failure"))
                        if point == "default-root-created"
                        else None
                    )
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertFalse((home / ".codex").exists())

    def test_rebound_default_root_is_never_written_or_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            moved = home / ".codex-created-by-installer"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def rebind(point: str) -> None:
                if point == "default-root-created":
                    root.rename(moved)
                    root.mkdir()

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "root.*changed"):
                    codex_agents.install(failpoint=rebind)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertTrue(root.is_dir())
            self.assertEqual([], list(root.iterdir()))
            self.assertTrue(moved.is_dir())
            self.assertEqual([], list(moved.iterdir()))


if __name__ == "__main__":
    unittest.main()
