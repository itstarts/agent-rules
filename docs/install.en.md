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
