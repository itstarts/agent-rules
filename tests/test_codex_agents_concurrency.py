from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.sh"
sys.path.insert(0, str(REPO / "scripts"))

import codex_agents  # noqa: E402


class CodexAgentsConcurrencyTests(unittest.TestCase):
    def test_competing_root_lock_fails_without_persistent_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex"
            codex_root.mkdir()
            holder = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import fcntl, os, sys; "
                        "fd=os.open(sys.argv[1], os.O_RDONLY|os.O_DIRECTORY); "
                        "fcntl.flock(fd, fcntl.LOCK_EX); "
                        "print('ready', flush=True); "
                        "sys.stdin.read(1)"
                    ),
                    str(codex_root),
                ],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self.assertEqual("ready\n", holder.stdout.readline())
                env = os.environ.copy()
                env["HOME"] = str(home)
                env.pop("CODEX_HOME", None)
                result = subprocess.run(
                    [str(INSTALLER), "codex-agents"],
                    cwd=REPO,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            finally:
                holder.stdin.write("x")
                holder.stdin.flush()
                holder.wait(timeout=5)
                holder.stdin.close()
                holder.stdout.close()
                holder.stderr.close()

            self.assertNotEqual(0, result.returncode)
            self.assertIn("root lock", result.stderr)
            self.assertEqual([], list(codex_root.iterdir()))

    def test_root_rebinding_never_writes_the_replacement_directory(self) -> None:
        for interrupt_at in ("journal-durable", "role-applied:architect", "config-prepared"):
            with self.subTest(interrupt_at=interrupt_at), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                root = home / ".codex"
                moved = home / ".codex-moved"
                previous_home = os.environ.get("HOME")
                previous_codex_home = os.environ.pop("CODEX_HOME", None)
                os.environ["HOME"] = str(home)

                def replace_root(point: str) -> None:
                    if point == interrupt_at and not moved.exists():
                        root.rename(moved)
                        root.mkdir()

                try:
                    with self.assertRaisesRegex(codex_agents.InstallError, "root path changed"):
                        codex_agents.install(failpoint=replace_root)
                finally:
                    if previous_home is None:
                        os.environ.pop("HOME", None)
                    else:
                        os.environ["HOME"] = previous_home
                    if previous_codex_home is not None:
                        os.environ["CODEX_HOME"] = previous_codex_home

                self.assertEqual([], list(root.iterdir()))
                self.assertFalse((moved / "agents").exists())
                self.assertFalse((moved / "config.toml").exists())

    def test_same_content_inode_replacement_after_locked_preflight_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            agents = root / "agents"
            agents.mkdir(parents=True)
            architect = agents / "architect.toml"
            content = b'name = "architect"\ndescription = "legacy"\ndeveloper_instructions = "legacy"\n'
            architect.write_bytes(content)
            config = root / "config.toml"
            config.write_text('model = "example"\n', encoding="utf-8")
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_same_bytes(point: str) -> None:
                if point == "locked-preflight-complete":
                    replacement = agents / "replacement.toml"
                    replacement.write_bytes(content)
                    replacement.replace(architect)

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "changed after preflight"):
                    codex_agents.install(failpoint=replace_same_bytes)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertFalse(architect.is_symlink())
            self.assertEqual(content, architect.read_bytes())
            self.assertEqual('model = "example"\n', config.read_text(encoding="utf-8"))
            self.assertFalse((root / ".agent-rules-backups").exists())

    def test_agents_directory_rebinding_after_locked_preflight_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            agents = root / "agents"
            agents.mkdir(parents=True)
            legacy = agents / "architect.toml"
            legacy.write_text('name = "architect"\n', encoding="utf-8")
            moved = root / "agents-moved"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_agents(point: str) -> None:
                if point == "locked-preflight-complete":
                    agents.rename(moved)
                    agents.mkdir()

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "agents directory changed"):
                    codex_agents.install(failpoint=replace_agents)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertEqual([], list(agents.iterdir()))
            self.assertTrue((moved / "architect.toml").is_file())
            self.assertFalse((root / ".agent-rules-backups").exists())

    def test_same_config_bytes_new_inode_after_locked_preflight_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            root.mkdir()
            config = root / "config.toml"
            original = b'model = "example"\n'
            config.write_bytes(original)
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_config(point: str) -> None:
                if point == "locked-preflight-complete":
                    replacement = root / "replacement.toml"
                    replacement.write_bytes(original)
                    replacement.replace(config)

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "config.toml changed"):
                    codex_agents.install(failpoint=replace_config)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertEqual(original, config.read_bytes())
            self.assertFalse((root / ".agent-rules-backups").exists())

    def test_ready_symlink_recreated_after_locked_preflight_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first = subprocess.run(
                [str(INSTALLER), "codex-agents"],
                cwd=REPO,
                env={**os.environ, "HOME": str(home), "AGENT_RULES_LOCAL": str(home / "local-rules")},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, first.returncode, first.stderr)
            architect = home / ".codex" / "agents" / "architect.toml"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def recreate(point: str) -> None:
                if point == "locked-preflight-complete":
                    target = os.readlink(architect)
                    replacement = architect.with_name("replacement-architect.toml")
                    replacement.symlink_to(target)
                    replacement.replace(architect)

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "changed after preflight"):
                    codex_agents.install(failpoint=recreate)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertTrue(architect.is_symlink())

    def test_install_role_object_replacement_after_journal_publish_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_object(point: str) -> None:
                if point == "journal-durable":
                    namespace = root / ".agent-rules-backups" / "codex-agents"
                    transaction = next(path for path in namespace.iterdir() if not path.name.startswith("."))
                    target = transaction / "install-architect.toml"
                    link_text = os.readlink(target)
                    replacement = transaction / "replacement-install-architect.toml"
                    replacement.symlink_to(link_text)
                    replacement.replace(target)

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "role install object changed"):
                    codex_agents.install(failpoint=replace_object)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertFalse((root / "agents").exists())
            self.assertFalse((root / "config.toml").exists())

    def test_config_install_object_replacement_before_rename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_object(point: str) -> None:
                if point == "config-prepared":
                    namespace = root / ".agent-rules-backups" / "codex-agents"
                    transaction = next(path for path in namespace.iterdir() if not path.name.startswith("."))
                    target = transaction / "install-config.toml"
                    replacement = transaction / "replacement-config.toml"
                    replacement.write_bytes(target.read_bytes())
                    replacement.replace(target)

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "config install object changed"):
                    codex_agents.install(failpoint=replace_object)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertFalse((root / "agents").exists())
            self.assertFalse((root / "config.toml").exists())

    def test_staging_directory_replacement_before_publish_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            moved = home / "original-staging"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_staging(point: str) -> None:
                if point == "journal-written-in-staging":
                    namespace = root / ".agent-rules-backups" / "codex-agents"
                    staging = next(path for path in namespace.iterdir() if path.name.startswith(".staging-"))
                    staging.rename(moved)
                    staging.mkdir()
                    (staging / "sentinel.txt").write_text("keep\n", encoding="utf-8")

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "staging transaction changed"):
                    codex_agents.install(failpoint=replace_staging)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertFalse((root / "agents").exists())
            self.assertFalse((root / "config.toml").exists())
            self.assertTrue(moved.is_dir())
            replacement = next(
                path
                for path in (root / ".agent-rules-backups" / "codex-agents").iterdir()
                if path.name.startswith(".staging-")
            )
            self.assertEqual("keep\n", (replacement / "sentinel.txt").read_text(encoding="utf-8"))

            retried = subprocess.run(
                [str(INSTALLER), "codex-agents"],
                cwd=REPO,
                env={**os.environ, "HOME": str(home), "AGENT_RULES_LOCAL": str(home / "local-rules")},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(0, retried.returncode)
            self.assertIn("abandoned staging transaction is unsafe", retried.stderr)
            self.assertEqual("keep\n", (replacement / "sentinel.txt").read_text(encoding="utf-8"))

    def test_staging_replacement_after_cleanup_identity_check_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            moved = home / "opened-staging"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)
            original_lstat_at = codex_agents._lstat_at
            replaced = False

            def replace_after_identity_read(parent_fd: int, name: str):
                nonlocal replaced
                metadata = original_lstat_at(parent_fd, name)
                if not replaced and name.startswith(".staging-"):
                    namespace = root / ".agent-rules-backups" / "codex-agents"
                    staging = namespace / name
                    staging.rename(moved)
                    staging.mkdir()
                    (staging / "sentinel.txt").write_text("keep\n", encoding="utf-8")
                    replaced = True
                return metadata

            try:
                with mock.patch.object(codex_agents, "_lstat_at", side_effect=replace_after_identity_read):
                    with self.assertRaisesRegex(RuntimeError, "injected failure"):
                        codex_agents.install(
                            failpoint=lambda point: (_ for _ in ()).throw(RuntimeError("injected failure"))
                            if point == "before-journal-write"
                            else None
                        )
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            replacement = next(
                path
                for path in (root / ".agent-rules-backups" / "codex-agents").iterdir()
                if path.name.startswith(".staging-")
            )
            self.assertTrue(moved.is_dir())
            self.assertEqual("keep\n", (replacement / "sentinel.txt").read_text(encoding="utf-8"))

    def test_replaced_agents_install_object_is_not_recursively_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            replacement: Path | None = None
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def replace_object(point: str) -> None:
                nonlocal replacement
                if point == "journal-durable":
                    namespace = root / ".agent-rules-backups" / "codex-agents"
                    transaction = next(path for path in namespace.iterdir() if not path.name.startswith("."))
                    target = transaction / "agents-object"
                    candidate = transaction / "replacement-agents-object"
                    candidate.mkdir()
                    target.rmdir()
                    candidate.rename(target)
                    replacement = target

            try:
                with self.assertRaisesRegex(codex_agents.InstallError, "automatic rollback could not complete"):
                    codex_agents.install(failpoint=replace_object)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertIsNotNone(replacement)
            self.assertTrue(replacement.is_dir())

    def test_agents_directory_rebinding_mid_install_stops_before_next_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / ".codex"
            moved = root / "agents-installed"
            previous_home = os.environ.get("HOME")
            previous_codex_home = os.environ.pop("CODEX_HOME", None)
            os.environ["HOME"] = str(home)

            def rebind(point: str) -> None:
                if point == "role-applied:architect":
                    agents = root / "agents"
                    agents.rename(moved)
                    agents.mkdir()

            try:
                with self.assertRaises(codex_agents.InstallError):
                    codex_agents.install(failpoint=rebind)
            finally:
                if previous_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = previous_home
                if previous_codex_home is not None:
                    os.environ["CODEX_HOME"] = previous_codex_home

            self.assertEqual(["architect.toml"], sorted(path.name for path in moved.iterdir()))
            self.assertEqual([], list((root / "agents").iterdir()))


if __name__ == "__main__":
    unittest.main()
