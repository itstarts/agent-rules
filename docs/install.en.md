# Installation Details

[简体中文](install.md)

`install.sh` wires this repository's `AGENTS.md` into local AI coding tool config files. It only handles Codex, Claude Code, and Gemini CLI; configure other tools through their own documentation.

## Supported Platforms

- macOS / Linux: supported by default with Bash and `ln -s`.
- Windows: Claude can use import mode; Codex / Gemini symlink mode usually requires Developer Mode or administrator privileges. If symlinks are unavailable, configure the tool manually, or provide a Codex/Gemini per-machine extra so the installer generates a concatenated file.

## Basic Usage

```bash
./install.sh                      # defaults to codex claude
./install.sh codex claude gemini  # explicitly choose tools
CLAUDE_MODE=import ./install.sh claude
```

Environment variables:

- `CLAUDE_MODE=symlink|import`: Claude defaults to `symlink`; `import` writes an `@<AGENTS.md>` reference.
- `AGENT_RULES_LOCAL=/path/to/local-rules`: overrides the per-machine extras directory, which defaults to `~/.agent-rules-local`.

## Install Modes

| Mode | Used when | Sync behavior |
|------|-----------|---------------|
| Pure symlink | Codex/Gemini without local extras; Claude default mode | Takes effect after `git pull` updates the repo |
| Claude import | `CLAUDE_MODE=import` or a Claude local extra exists | Takes effect after `git pull` updates the repo |
| Concatenated file | Codex/Gemini with local extras | Re-run `./install.sh` after updating the repo or extra file |

Symlink and import modes reference the current clone by absolute path. Keep the clone directory in place after installing; if you move it, re-clone and re-run the installer.

## Global Codex Custom Agents

Agent installation is an explicit target. It is not part of the default install or the existing `codex` target:

```bash
./install.sh codex-agents
```

This target requires Python 3.11+ and the standard-library `tomllib`; it does not install dependencies. The Codex root defaults to `~/.codex`. When `CODEX_HOME` is set, that explicit directory is used and must already exist.

`codex/agents/managed-agents.txt` declares the exact set of 11 managed roles. The installer creates one absolute symlink per role under the Codex root's `agents/` directory. It does not replace the directory or modify unmanaged roles. Moving the repository breaks those absolute links; after a move, re-run `./install.sh codex-agents` and validate the installation.

The installer owns only these settings:

```toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
```

Models, providers, authentication, MCP, plugins, `job_max_runtime_seconds`, role subtables, and all other settings in global `config.toml` remain unmanaged. See [how it works](how-it-works.en.md#codex-role-routing) for the lightweight `model_reasoning_effort` policy inside role files. Explicit `multi_agent = false` or an incompatible structure stops safely. A missing config is created with mode `0600`; an existing config is parsed completely with `tomllib`, receives only compatible missing keys, and is atomically replaced from transaction staging on the same Codex-root filesystem.

Every installation that changes state prints a transaction ID containing a UTC timestamp and random suffix. Previous role files, broken-symlink metadata, and config backups live in a protected transaction directory under the Codex root. Directories are no broader than `0700`; regular backups and `journal.toml` are no broader than `0600`. Backups and the journal are durable before the first target changes.

Default and non-interactive conflicts create no backup and perform no installation. Only an interactive terminal where the user enters the exact backup-only confirmation creates one content-addressed, idempotent conflict snapshot and stops. That path never installs roles or modifies config.

An interrupted in-progress transaction blocks new installs. Use the transaction ID from the error:

```bash
./install.sh codex-agents-recover 20260715T120000Z-a1b2c3d4e5f6
```

To undo a committed install transaction:

```bash
./install.sh codex-agents-restore 20260715T120000Z-a1b2c3d4e5f6
```

`recover` repairs an interrupted transaction; `restore` reverses a committed one. Both use the same directory lock and journal state machine and can resume idempotently after another interruption. Recovery changes only the transaction's managed role targets and newly added config keys, preserving unrelated valid config changes made after installation.

Validate repository sources and installed targets after installation:

```bash
python3 -B scripts/validate_codex_agents.py
python3 -B scripts/validate_codex_agents.py --installed-root "${CODEX_HOME:-$HOME/.codex}"
codex --strict-config doctor --json
```

Managed roles use per-file symlinks, so repository updates synchronize their contents without another install. To ensure the client reloads role descriptions, routing, and reasoning effort, start a new Codex task after changing role sources.

## Target Files and Existing Config

| Tool | Target file |
|------|-------------|
| Codex | `~/.codex/AGENTS.md` |
| Claude Code | `~/.claude/CLAUDE.md` |
| Gemini CLI | `~/.gemini/GEMINI.md` |

The script creates missing parent directories. Existing targets are handled by type:

- Real files: backed up next to the target as `*.bak.<timestamp>.<pid>`.
- Symlinks already pointing at this repository's `AGENTS.md`: treated as ready and skipped.
- Symlinks pointing elsewhere: pure symlink mode backs them up; concatenation/import write modes remove the old symlink before writing a new file so the script never writes through a symlink onto its source.

The script refuses to use a path inside this repository as an install target, preventing accidental source overwrite.

## Migrating Existing Config

If a target already has content, decide where it belongs:

1. Already covered by repository rules: run `./install.sh` and keep the automatic backup.
2. Should be shared across machines: merge it into repository `AGENTS.md`, commit, then install.
3. Machine- or tool-specific: move it into a per-machine extra.

Useful comparison commands:

```bash
diff <(sort -u ~/.codex/AGENTS.md) <(sort -u ~/agent-rules/AGENTS.md)
grep '^#' ~/.codex/AGENTS.md
```

## Per-Machine Extras

Place local extras under `~/.agent-rules-local/<tool>.md`:

```text
~/.agent-rules-local/codex.md
~/.agent-rules-local/claude.md
~/.agent-rules-local/gemini.md
```

Good candidates are wrapper-specific rules, machine paths, or personal external-tool conventions. Cross-project rules should be merged into repository `AGENTS.md`.

Claude supports imports, so the installer writes:

```text
@/path/to/agent-rules/AGENTS.md
@/path/to/.agent-rules-local/claude.md
```

Codex / Gemini do not support imports in this setup, so the installer generates a concatenated file with the repository source plus the local extra. Re-run the installer after updating either source.

## Manual Equivalents

Prefer `install.sh` for day-to-day use because it includes backup and overwrite-protection logic. Manual commands are mainly for troubleshooting:

```bash
REPO=~/agent-rules
mkdir -p ~/.codex ~/.claude
ln -s "$REPO/AGENTS.md" ~/.codex/AGENTS.md
ln -s "$REPO/AGENTS.md" ~/.claude/CLAUDE.md
```

Avoid `ln -sf` against unknown targets unless you have confirmed the old file is disposable.

## Uninstall and Restore

Remove installed files:

```bash
rm -f ~/.codex/AGENTS.md ~/.claude/CLAUDE.md ~/.gemini/GEMINI.md
```

Restore pre-install config from the newest backup if needed:

```bash
ls -t ~/.codex/AGENTS.md.bak.*
mv ~/.codex/AGENTS.md.bak.<timestamp>.<pid> ~/.codex/AGENTS.md
```

Removing symlinks or generated files does not modify this repository. After confirming no tool depends on the clone, you can delete the clone directory.
