from __future__ import annotations

import os
import re
import base64
import json
import hashlib
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.sh"
sys.path.insert(0, str(REPO / "scripts"))

import codex_agents  # noqa: E402


class CodexAgentsRecoveryTests(unittest.TestCase):
    def run_command(self, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
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

    def journal_path(self, home: Path, transaction_id: str) -> Path:
        return home / ".codex" / ".agent-rules-backups" / "codex-agents" / transaction_id / "journal.toml"

    def mutate_payload(self, journal: Path, mutate: object) -> None:
        text = journal.read_text(encoding="utf-8")
        parsed = tomllib.loads(text)
        payload = json.loads(base64.b64decode(parsed["payload_b64"]).decode("utf-8"))
        mutate(payload)
        replacement = base64.b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        journal.write_text(text.replace(parsed["payload_b64"], replacement), encoding="utf-8")

    def test_restore_first_install_returns_to_exact_managed_prestate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertEqual(0, restored.returncode, restored.stderr)
            codex_root = home / ".codex"
            self.assertFalse((codex_root / "config.toml").exists())
            self.assertFalse((codex_root / "agents").exists())
            journal = tomllib.loads(
                (
                    codex_root
                    / ".agent-rules-backups"
                    / "codex-agents"
                    / transaction_id
                    / "journal.toml"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual("restored", journal["state"])

    def test_restore_preserves_unrelated_config_changes_after_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex"
            codex_root.mkdir()
            config = codex_root / "config.toml"
            config.write_text('model = "before"\n', encoding="utf-8")
            installed = self.run_command(home, "codex-agents")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            with config.open("a", encoding="utf-8") as handle:
                handle.write('\n[notice]\nlevel = "all"\n')

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertEqual(0, restored.returncode, restored.stderr)
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual("before", parsed["model"])
            self.assertEqual({"level": "all"}, parsed["notice"])
            self.assertNotIn("agents", parsed)

    def test_restore_preserves_quoted_unrelated_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            config = home / ".codex" / "config.toml"
            with config.open("a", encoding="utf-8") as handle:
                handle.write('\n["notice"]\nlevel = "all"\n\n[notice."settings"]\nenabled = true\n')

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertEqual(0, restored.returncode, restored.stderr)
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual({"level": "all", "settings": {"enabled": True}}, parsed["notice"])
            self.assertNotIn("agents", parsed)

    def test_restore_recovers_legacy_role_and_only_removes_added_config_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex"
            agents = codex_root / "agents"
            agents.mkdir(parents=True)
            architect = agents / "architect.toml"
            legacy = b'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n'
            architect.write_bytes(legacy)
            config = codex_root / "config.toml"
            config.write_text(
                "[agents]\n"
                "max_depth = 1\n"
                "job_max_runtime_seconds = 900\n"
                "\n"
                "[agents.reviewer]\n"
                'description = "keep"\n',
                encoding="utf-8",
            )
            installed = self.run_command(home, "codex-agents")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertEqual(0, restored.returncode, restored.stderr)
            self.assertFalse(architect.is_symlink())
            self.assertEqual(legacy, architect.read_bytes())
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(1, parsed["agents"]["max_depth"])
            self.assertEqual(900, parsed["agents"]["job_max_runtime_seconds"])
            self.assertEqual({"description": "keep"}, parsed["agents"]["reviewer"])
            self.assertNotIn("max_threads", parsed["agents"])
            self.assertNotIn("interrupt_message", parsed["agents"])

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_recover_continues_after_forced_exit_between_target_and_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                child = os.fork()
                if child == 0:
                    codex_agents.install(
                        failpoint=lambda point: os._exit(79) if point.startswith("role-applied:") else None
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

            self.assertEqual(79, os.waitstatus_to_exitcode(status))
            namespace = home / ".codex" / ".agent-rules-backups" / "codex-agents"
            transaction_id = next(namespace.iterdir()).name
            blocked = self.run_command(home, "codex-agents")
            self.assertNotEqual(0, blocked.returncode)

            recovered = self.run_command(home, "codex-agents-recover", transaction_id)

            self.assertEqual(0, recovered.returncode, recovered.stderr)
            self.assertFalse((home / ".codex" / "agents").exists())
            self.assertFalse((home / ".codex" / "config.toml").exists())

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_restore_idempotently_continues_after_forced_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                child = os.fork()
                if child == 0:
                    codex_agents.recover_or_restore(
                        "restore",
                        transaction_id,
                        failpoint=lambda point: os._exit(78)
                        if point.startswith("recovery-role-persisted:")
                        else None,
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

            self.assertEqual(78, os.waitstatus_to_exitcode(status))
            resumed = self.run_command(home, "codex-agents-restore", transaction_id)
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            self.assertFalse((home / ".codex" / "agents").exists())
            self.assertFalse((home / ".codex" / "config.toml").exists())

    def test_tampered_journal_target_is_rejected_before_any_restore_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            journal = (
                home
                / ".codex"
                / ".agent-rules-backups"
                / "codex-agents"
                / transaction_id
                / "journal.toml"
            )
            parsed = tomllib.loads(journal.read_text(encoding="utf-8"))
            payload = json.loads(base64.b64decode(parsed["payload_b64"]).decode("utf-8"))
            payload["roles"][0]["filename"] = "../config.toml"
            replacement = base64.b64encode(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).decode("ascii")
            journal.write_text(
                journal.read_text(encoding="utf-8").replace(parsed["payload_b64"], replacement),
                encoding="utf-8",
            )

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertNotEqual(0, restored.returncode)
            self.assertIn("payload", restored.stderr)
            self.assertTrue((home / ".codex" / "config.toml").exists())
            self.assertTrue((home / ".codex" / "agents" / "architect.toml").is_symlink())

    def test_unknown_journal_fields_and_duplicate_roles_are_rejected(self) -> None:
        mutations = (
            lambda payload: payload.update({"unexpected": True}),
            lambda payload: payload["roles"][0].update({"unexpected": True}),
            lambda payload: payload["roles"].append(dict(payload["roles"][0])),
            lambda payload: payload["config"].update({"install_temp": "../unmanaged.toml"}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                installed = self.run_command(home, "codex-agents")
                transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
                architect = home / ".codex" / "agents" / "architect.toml"
                self.mutate_payload(self.journal_path(home, transaction_id), mutate)

                restored = self.run_command(home, "codex-agents-restore", transaction_id)

                self.assertNotEqual(0, restored.returncode)
                self.assertIn("journal.toml payload", restored.stderr)
                self.assertTrue(architect.is_symlink())

    def test_committed_journal_cannot_claim_an_incomplete_restore_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            root = home / ".codex"
            config_before = (root / "config.toml").read_bytes()
            self.mutate_payload(
                self.journal_path(home, transaction_id),
                lambda payload: payload.update({"restore_plan_ready": True}),
            )

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertNotEqual(0, restored.returncode)
            self.assertEqual(config_before, (root / "config.toml").read_bytes())
            for name in (REPO / "codex" / "agents" / "managed-agents.txt").read_text().splitlines():
                self.assertTrue((root / "agents" / f"{name}.toml").is_symlink())

    def test_terminal_journal_state_requires_completed_targets(self) -> None:
        for terminal_state, command in (("restored", "restore"), ("recovered", "recover")):
            with self.subTest(terminal_state=terminal_state), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                installed = self.run_command(home, "codex-agents")
                transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
                journal = self.journal_path(home, transaction_id)
                self.mutate_payload(journal, lambda payload: payload.update({"restore_plan_ready": True}))
                journal.write_text(
                    journal.read_text(encoding="utf-8").replace('state = "committed"', f'state = "{terminal_state}"'),
                    encoding="utf-8",
                )

                completed = self.run_command(home, f"codex-agents-{command}", transaction_id)

                self.assertNotEqual(0, completed.returncode)
                self.assertTrue((home / ".codex" / "agents" / "architect.toml").is_symlink())

    def test_legacy_terminal_journal_cannot_bypass_target_validation(self) -> None:
        for terminal_state, command in (("restored", "restore"), ("recovered", "recover")):
            with self.subTest(terminal_state=terminal_state), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                installed = self.run_command(home, "codex-agents")
                transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
                journal = self.journal_path(home, transaction_id)
                journal.write_text(
                    journal.read_text(encoding="utf-8")
                    .replace("schema_version = 2", "schema_version = 1")
                    .replace('state = "committed"', f'state = "{terminal_state}"'),
                    encoding="utf-8",
                )

                completed = self.run_command(home, f"codex-agents-{command}", transaction_id)

                self.assertNotEqual(0, completed.returncode)
                self.assertIn("schema mismatch", completed.stderr)
                self.assertTrue((home / ".codex" / "agents" / "architect.toml").is_symlink())

    def test_terminal_journal_requires_completed_progress_even_when_targets_are_restored(self) -> None:
        mutations = (
            lambda payload: payload["roles"][0].pop("restored"),
            lambda payload: payload["roles"][0].update({"restored": False}),
            lambda payload: payload["config"].pop("restored"),
            lambda payload: payload["config"].update({"restored": False}),
        )
        for terminal_state, command in (("restored", "restore"), ("recovered", "recover")):
            for mutate in mutations:
                with (
                    self.subTest(terminal_state=terminal_state, mutate=mutate),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    home = Path(tmp)
                    installed = self.run_command(home, "codex-agents")
                    transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
                    restored = self.run_command(home, "codex-agents-restore", transaction_id)
                    self.assertEqual(0, restored.returncode, restored.stderr)
                    journal = self.journal_path(home, transaction_id)
                    self.mutate_payload(journal, mutate)
                    if terminal_state == "recovered":
                        journal.write_text(
                            journal.read_text(encoding="utf-8").replace(
                                'state = "restored"', 'state = "recovered"'
                            ),
                            encoding="utf-8",
                        )

                    completed = self.run_command(home, f"codex-agents-{command}", transaction_id)

                    self.assertNotEqual(0, completed.returncode)
                    self.assertIn("completed restore progress", completed.stderr)
                    self.assertFalse((home / ".codex" / "agents").exists())
                    self.assertFalse((home / ".codex" / "config.toml").exists())

    def test_committed_journal_rejects_isolated_restore_fields(self) -> None:
        mutations = (
            lambda payload: payload["roles"][0].update({"restore_dev": 1}),
            lambda payload: payload["roles"][0].update({"restore_ino": 1}),
            lambda payload: payload["roles"][0].update({"restored": True}),
            lambda payload: payload["config"].update({"restored": True}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                installed = self.run_command(home, "codex-agents")
                transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
                self.mutate_payload(self.journal_path(home, transaction_id), mutate)

                restored = self.run_command(home, "codex-agents-restore", transaction_id)

                self.assertNotEqual(0, restored.returncode)
                self.assertTrue((home / ".codex" / "agents" / "architect.toml").is_symlink())

    def test_ready_role_cannot_inject_an_install_object_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            agents = root / "agents"
            agents.mkdir(parents=True)
            architect = agents / "architect.toml"
            architect.symlink_to((REPO / "codex" / "agents" / "architect.toml").resolve())
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            victim = home / "victim.txt"
            victim.write_text("keep\n", encoding="utf-8")
            victim_metadata = victim.stat()

            def mutate(payload: dict[str, object]) -> None:
                ready = next(role for role in payload["roles"] if role["name"] == "architect")
                ready["install_object"] = "../../../victim.txt"
                ready["installed_dev"] = victim_metadata.st_dev
                ready["installed_ino"] = victim_metadata.st_ino

            self.mutate_payload(self.journal_path(home, transaction_id), mutate)

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertNotEqual(0, restored.returncode)
            self.assertEqual("keep\n", victim.read_text(encoding="utf-8"))
            self.assertTrue(architect.is_symlink())

    def test_tampered_restore_output_path_cannot_consume_unmanaged_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            config = root / "config.toml"
            config.write_text('model = "before"\n', encoding="utf-8")
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                with self.assertRaisesRegex(RuntimeError, "stop after plan"):
                    codex_agents.recover_or_restore(
                        "restore",
                        transaction_id,
                        failpoint=lambda point: (_ for _ in ()).throw(RuntimeError("stop after plan"))
                        if point == "recovery-state-persisted"
                        else None,
                    )
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home
            unmanaged = root / "unmanaged.toml"
            unmanaged.write_text('keep = true\n', encoding="utf-8")
            self.mutate_payload(
                self.journal_path(home, transaction_id),
                lambda payload: payload["config"]["restore_plan"].update({"output_temp": "unmanaged.toml"}),
            )

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertNotEqual(0, restored.returncode)
            self.assertEqual('keep = true\n', unmanaged.read_text(encoding="utf-8"))
            self.assertTrue((root / "agents" / "architect.toml").is_symlink())

    def test_missing_or_broad_backup_and_journal_permissions_are_rejected(self) -> None:
        for mutation in ("missing-backup", "broad-journal", "broad-role-backup", "broad-config-backup"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                architect = home / ".codex" / "agents" / "architect.toml"
                architect.parent.mkdir(parents=True)
                architect.write_text(
                    'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n',
                    encoding="utf-8",
                )
                config = home / ".codex" / "config.toml"
                config.write_text('model = "before"\n', encoding="utf-8")
                installed = self.run_command(home, "codex-agents")
                transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
                transaction = self.journal_path(home, transaction_id).parent
                if mutation == "missing-backup":
                    (transaction / "role-architect.bin").unlink()
                elif mutation == "broad-journal":
                    (transaction / "journal.toml").chmod(0o644)
                elif mutation == "broad-role-backup":
                    (transaction / "role-architect.bin").chmod(0o644)
                else:
                    (transaction / "config.bin").chmod(0o644)

                restored = self.run_command(home, "codex-agents-restore", transaction_id)

                self.assertNotEqual(0, restored.returncode)
                self.assertTrue(architect.is_symlink())

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_restore_role_progress_for_every_managed_role_is_resumable(self) -> None:
        managed = tuple(
            line.strip()
            for line in (REPO / "codex" / "agents" / "managed-agents.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        phases = ("recovery-role-replaced", "recovery-role-persisted")
        for interrupted_name in managed:
            for phase in phases:
                with self.subTest(interrupted_name=interrupted_name, phase=phase), tempfile.TemporaryDirectory() as tmp:
                    self._assert_restore_role_phase_is_resumable(Path(tmp), managed, interrupted_name, phase)

    def _assert_restore_role_phase_is_resumable(
        self, home: Path, managed: tuple[str, ...], interrupted_name: str, phase: str
    ) -> None:
        agents = home / ".codex" / "agents"
        agents.mkdir(parents=True)
        for name in managed:
            (agents / f"{name}.toml").write_text(
                f'name = "{name}"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n',
                encoding="utf-8",
            )
        installed = self.run_command(home, "codex-agents")
        transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
        previous_home = os.environ.get("HOME")
        previous_codex_home = os.environ.pop("CODEX_HOME", None)
        os.environ["HOME"] = str(home)
        try:
            child = os.fork()
            if child == 0:
                codex_agents.recover_or_restore(
                    "restore",
                    transaction_id,
                    failpoint=lambda point: os._exit(70)
                    if point == f"{phase}:{interrupted_name}"
                    else None,
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

        self.assertEqual(70, os.waitstatus_to_exitcode(status))
        resumed = self.run_command(home, "codex-agents-restore", transaction_id)
        self.assertEqual(0, resumed.returncode, resumed.stderr)
        for name in managed:
            target = agents / f"{name}.toml"
            self.assertTrue(target.is_file())
            self.assertFalse(target.is_symlink())

    def test_tampered_restore_output_is_rejected_before_target_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            config = root / "config.toml"
            config.write_text('model = "before"\n', encoding="utf-8")
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                with self.assertRaisesRegex(RuntimeError, "stop after plan"):
                    codex_agents.recover_or_restore(
                        "restore",
                        transaction_id,
                        failpoint=lambda point: (_ for _ in ()).throw(RuntimeError("stop after plan"))
                        if point == "recovery-state-persisted"
                        else None,
                    )
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home
            malicious = b'malicious = true\n'
            temporary = root / f".config.toml.restore-{transaction_id}"
            temporary.write_bytes(malicious)

            def mutate(payload: dict[str, object]) -> None:
                plan = payload["config"]["restore_plan"]
                plan["output_b64"] = base64.b64encode(malicious).decode("ascii")
                plan["output_digest"] = hashlib.sha256(malicious).hexdigest()

            self.mutate_payload(self.journal_path(home, transaction_id), mutate)
            installed_config = config.read_bytes()

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertNotEqual(0, restored.returncode)
            self.assertEqual(installed_config, config.read_bytes())

    def test_restore_rejects_managed_config_changes_before_touching_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            self.assertEqual(0, installed.returncode, installed.stderr)
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            config = home / ".codex" / "config.toml"
            changed = config.read_text(encoding="utf-8").replace("max_threads = 4", "max_threads = 5")
            config.write_text(changed, encoding="utf-8")

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertNotEqual(0, restored.returncode)
            self.assertEqual(changed, config.read_text(encoding="utf-8"))
            self.assertTrue((home / ".codex" / "agents" / "architect.toml").is_symlink())

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_restore_resumes_after_config_replace_before_progress_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            config = home / ".codex" / "config.toml"
            with config.open("a", encoding="utf-8") as handle:
                handle.write('\n[notice]\nlevel = "all"\n')
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                child = os.fork()
                if child == 0:
                    codex_agents.recover_or_restore(
                        "restore",
                        transaction_id,
                        failpoint=lambda point: os._exit(76) if point == "recovery-config-replaced" else None,
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

            self.assertEqual(76, os.waitstatus_to_exitcode(status))
            resumed = self.run_command(home, "codex-agents-restore", transaction_id)
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            parsed = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual({"level": "all"}, parsed["notice"])
            self.assertNotIn("agents", parsed)

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_restore_resumes_after_created_agents_directory_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                child = os.fork()
                if child == 0:
                    codex_agents.recover_or_restore(
                        "restore",
                        transaction_id,
                        failpoint=lambda point: os._exit(75) if point == "agents-dir-removed" else None,
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

            self.assertEqual(75, os.waitstatus_to_exitcode(status))
            resumed = self.run_command(home, "codex-agents-restore", transaction_id)
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            self.assertFalse((home / ".codex" / "agents").exists())

    def test_same_target_symlink_recreated_after_install_is_third_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            architect = home / ".codex" / "agents" / "architect.toml"
            target = os.readlink(architect)
            architect.unlink()
            architect.symlink_to(target)

            restored = self.run_command(home, "codex-agents-restore", transaction_id)

            self.assertNotEqual(0, restored.returncode)
            self.assertIn("targets changed", restored.stderr)
            self.assertTrue(architect.is_symlink())

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_restore_plan_role_object_creation_is_crash_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            architect = home / ".codex" / "agents" / "architect.toml"
            architect.parent.mkdir(parents=True)
            legacy = b'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n'
            architect.write_bytes(legacy)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                child = os.fork()
                if child == 0:
                    codex_agents.recover_or_restore(
                        "restore",
                        transaction_id,
                        failpoint=lambda point: os._exit(74)
                        if point == "restore-object-prepared:architect"
                        else None,
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

            self.assertEqual(74, os.waitstatus_to_exitcode(status))
            resumed = self.run_command(home, "codex-agents-restore", transaction_id)
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            self.assertEqual(legacy, architect.read_bytes())

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_restore_plan_config_object_creation_is_crash_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            config = root / "config.toml"
            original = b'model = "before"\n'
            config.write_bytes(original)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            try:
                child = os.fork()
                if child == 0:
                    codex_agents.recover_or_restore(
                        "restore",
                        transaction_id,
                        failpoint=lambda point: os._exit(73)
                        if point == "restore-config-object-prepared"
                        else None,
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

            self.assertEqual(73, os.waitstatus_to_exitcode(status))
            resumed = self.run_command(home, "codex-agents-restore", transaction_id)
            self.assertEqual(0, resumed.returncode, resumed.stderr)
            self.assertEqual(original, config.read_bytes())

    def test_replaced_restore_role_object_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            architect = home / ".codex" / "agents" / "architect.toml"
            architect.parent.mkdir(parents=True)
            legacy = b'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n'
            architect.write_bytes(legacy)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            transaction = home / ".codex" / ".agent-rules-backups" / "codex-agents" / transaction_id
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_object(point: str) -> None:
                if point == "recovery-state-persisted":
                    target = transaction / "restore-architect.toml"
                    replacement = transaction / "replacement.toml"
                    replacement.write_bytes(target.read_bytes())
                    replacement.replace(target)

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "restore object changed"):
                    codex_agents.recover_or_restore("restore", transaction_id, failpoint=replace_object)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertTrue(architect.is_symlink())

    def test_replaced_restore_config_object_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            config = root / "config.toml"
            original = b'model = "before"\n'
            config.write_bytes(original)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_object(point: str) -> None:
                if point == "recovery-state-persisted":
                    target = root / f".config.toml.restore-{transaction_id}"
                    replacement = root / ".replacement-config.toml"
                    replacement.write_bytes(target.read_bytes())
                    replacement.replace(target)

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "restore config object changed"):
                    codex_agents.recover_or_restore("restore", transaction_id, failpoint=replace_object)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertNotEqual(original, config.read_bytes())
            journal = tomllib.loads(self.journal_path(home, transaction_id).read_text(encoding="utf-8"))
            self.assertEqual("restore-in-progress", journal["state"])

    def test_rebound_created_agents_directory_is_not_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            installed = self.run_command(home, "codex-agents")
            transaction_id = re.search(r"transaction: ([^\s]+)", installed.stdout).group(1)
            root = home / ".codex"
            agents = root / "agents"
            moved = root / "agents-installed"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def rebind_agents(point: str) -> None:
                if point == "recovery-config-persisted":
                    agents.rename(moved)
                    agents.mkdir()

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "agents directory changed"):
                    codex_agents.recover_or_restore("restore", transaction_id, failpoint=rebind_agents)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertTrue(agents.is_dir())
            self.assertEqual([], list(agents.iterdir()))
            self.assertTrue(moved.is_dir())


if __name__ == "__main__":
    unittest.main()
