# Installation Details

[简体中文](install.md)

`install.sh` wires this repository's `AGENTS.md` into the local Codex config. It only handles Codex.

## Supported Platforms

- macOS / Linux: supported by default with Bash and `ln -s`.
- Windows: Codex symlink mode usually requires Developer Mode or administrator privileges. If symlinks are unavailable, provide a per-machine extra so the installer generates a concatenated file.

## Basic Usage

```bash
./install.sh        # defaults to Codex
./install.sh codex  # explicitly wires up Codex
```

Environment variables:

- `AGENT_RULES_LOCAL=/path/to/local-rules`: overrides the per-machine extras directory, which defaults to `~/.agent-rules-local`.

## Install Modes

| Mode | Used when | Sync behavior |
|------|-----------|---------------|
| Pure symlink | Codex without a local extra | Takes effect after `git pull` updates the repo |
| Concatenated file | Codex with a local extra | Re-run `./install.sh` after updating the repo or extra file |

Symlinks reference the current clone by absolute path. Keep the clone directory in place after installing; if you move it, re-clone and re-run the installer.

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

`codex-agents` does not manage models, providers, authentication, MCP, plugins, `job_max_runtime_seconds`, role subtables, or other global `config.toml` settings; dynamic model and effort selection belongs to the separate routing target below. Explicit `multi_agent = false` or an incompatible structure stops safely. A missing config is created with mode `0600`; an existing config is parsed completely with `tomllib`, receives only compatible missing keys, and is atomically replaced from transaction staging on the same Codex-root filesystem.

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

Managed roles use per-file symlinks, so repository updates synchronize their contents without another install. Start a new Codex task after changing role sources so the client reloads role descriptions.

## Dynamic Codex Subagent Routing

The routing Hook is another explicit target. It is not included in the default install, `codex`, or `codex-agents`:

```bash
./install.sh codex-agent-routing
```

This target also requires Python 3.11+ and installs no dependencies. It adds a specially marked inline Hook block to `config.toml` under the Codex root. The only matcher is `^Agent$` for the `PreToolUse` event. Codex tool-alias coverage makes that matcher capture canonical `spawn_agent` as well, and the router accepts both `tool_name` values. The command references `scripts/codex_agent_router.py` in this checkout by absolute path, and that script reads `codex/agent-routing.toml`. Updating model identifiers or routes in the same checkout therefore needs no reinstall. Re-run the installer after moving the checkout, changing the Python executable, or changing the managed block format.

The installer does not bypass Codex Hook trust. When a non-managed command Hook is loaded for the first time, Codex may ask the user to review and trust its absolute command path. Approve only after confirming that it points to this checkout.

The installer owns only its marked Hook block. It preserves other valid config and Hooks that do not match `Agent`. It stops before creating a transaction when:

- `[features] hooks = false` or the deprecated `codex_hooks = false` alias is set;
- a sibling `hooks.json` exists, avoiding mixed Hook sources and the associated warning;
- another `PreToolUse` Hook already matches `Agent` or canonical `spawn_agent`; or
- a managed marker is missing, duplicated, or encloses an invalid structure.

The Hook writes `model` and `reasoning_effort` into the dispatch input and preserves other fields. An explicit override requires `fork_turns = "none"` or a positive-integer bounded history. Omitting `fork_turns` or using `"all"` requires parent inheritance at runtime, so the Hook denies that dispatch. Unmanaged third-party agent types are left unchanged.

Changes use a separate transaction namespace and the same Codex-root lock as `codex-agents`. Either installer stops while the other has an in-progress transaction. Recover an interrupted transaction with:

```bash
./install.sh codex-agent-routing-recover 20260715T120000Z-a1b2c3d4e5f6
```

Undo a committed routing install with:

```bash
./install.sh codex-agent-routing-restore 20260715T120000Z-a1b2c3d4e5f6
```

Recovery and restore replace or remove only the marked block and preserve unrelated valid `config.toml` changes made later. If the managed block itself was edited externally, they refuse to overwrite it. See [how it works](how-it-works.en.md#codex-role-routing) for route classes, model tiers, and the Luna feature gate.

## Target Files and Existing Config

| Tool | Target file |
|------|-------------|
| Codex | `~/.codex/AGENTS.md` |

The script creates missing parent directories. Existing targets are handled by type:

- Real files: backed up next to the target as `*.bak.<timestamp>.<pid>`.
- Symlinks already pointing at this repository's `AGENTS.md`: treated as ready and skipped.
- Symlinks pointing elsewhere: pure symlink mode backs them up; concatenation mode removes the old symlink before writing a new file so the script never writes through a symlink onto its source.

The script refuses to use a path inside this repository as an install target, preventing accidental source overwrite.

## Migrating Existing Config

If a target already has content, decide where it belongs:

1. Already covered by repository rules: run `./install.sh` and keep the automatic backup.
2. Should be shared across machines: merge it into repository `AGENTS.md`, commit, then install.
3. Machine-specific: move it into a per-machine extra.

Useful comparison commands:

```bash
diff <(sort -u ~/.codex/AGENTS.md) <(sort -u ~/agent-rules/AGENTS.md)
grep '^#' ~/.codex/AGENTS.md
```

## Per-Machine Extras

Place the local extra at:

```text
~/.agent-rules-local/codex.md
```

Good candidates are wrapper-specific rules, machine paths, or personal external-tool conventions. Cross-project rules should be merged into repository `AGENTS.md`.

When a Codex local extra exists, the installer generates a concatenated file with the repository source plus that extra. Re-run the installer after updating either source.

## Manual Equivalents

Prefer `install.sh` for day-to-day use because it includes backup and overwrite-protection logic. Manual commands are mainly for troubleshooting:

```bash
REPO=~/agent-rules
mkdir -p ~/.codex
ln -s "$REPO/AGENTS.md" ~/.codex/AGENTS.md
```

Avoid `ln -sf` against unknown targets unless you have confirmed the old file is disposable.

## Uninstall and Restore

Remove installed files:

```bash
rm -f ~/.codex/AGENTS.md
```

Restore pre-install config from the newest backup if needed:

```bash
ls -t ~/.codex/AGENTS.md.bak.*
mv ~/.codex/AGENTS.md.bak.<timestamp>.<pid> ~/.codex/AGENTS.md
```

Removing symlinks or generated files does not modify this repository. After confirming the clone is no longer needed, you can delete it.
