# agent-rules

[简体中文](README.md) | **English**

Shared engineering rules across AI coding tools: keep `AGENTS.md` as the single source, maintain it in one place, and have Codex, Claude Code, Cursor, Copilot, and others stay in sync automatically.

## Files

| File | Purpose |
|------|---------|
| `AGENTS.md` | **Single source of truth**: global, tech-stack-agnostic engineering discipline, suitable for any project |
| `CLAUDE.md` | Symlink → `AGENTS.md`, read by Claude Code |
| `project-template.md` | Project-level template carrying stack/business constraints (SQL/DB, MQ, money/permissions/data-masking, etc.) |
| `install.sh` | Installer: creates global symlinks / concatenations; idempotent, auto-backup, supports per-machine extras |

## Quick start (global)

> Supported platforms: macOS / Linux (depends on Bash and `ln -s`). On Windows, Claude can use import mode; Codex / Gemini rely on symlink or concatenation and need Developer Mode / administrator rights to restore symlinks, or follow "Manual equivalents" to set them up by hand.
> This is a rule set **meant to be used directly, and also encouraged to fork and adapt for your own team** — `AGENTS.md` carries explicit opinionated choices (e.g. communicating in Chinese by default, a specific task-tiering scheme), so confirm they match your habits before adopting as-is.

```bash
git clone https://github.com/itstarts/agent-rules.git ~/agent-rules
cd ~/agent-rules
./install.sh                      # defaults to Codex + Claude Code
./install.sh codex claude gemini  # also wire up Gemini CLI
```

> **In symlink / Claude import mode, keep the clone directory in place — do not move or delete it**: both modes point at this directory by absolute path, so once it moves, the corresponding tool's global config breaks immediately; to relocate, re-clone and re-run `./install.sh`. (Concatenation mode bakes the content into the target file and does not depend on the clone directory, but you still need to re-run `./install.sh` to re-concatenate after the source updates.)

After installing, here is how each tool stays in sync with repo updates:

- **Pure symlink** (Codex/Gemini without per-machine extras, and Claude in symlink mode): linked directly to the repo's `AGENTS.md`, takes effect after `git pull`.
- **Claude import file** (with extras or `CLAUDE_MODE=import`): import reads the referenced file dynamically, so it **takes effect automatically** after `git pull` updates the source — no re-run needed.
- **Concatenated file** (Codex/Gemini with extras — these tools don't support import, so content can only be baked in): after `git pull` you must **re-run `./install.sh`** to re-concatenate.

`install.sh` is safe to re-run: a pure symlink already pointing at the repo is skipped; import / concatenation targets are regenerated on every run (an existing real file is first backed up to `*.bak.<timestamp>.<pid>`, an existing symlink is removed before writing — it never writes through a symlink onto the source).

## Machines that already have AGENTS / CLAUDE config

If `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, or `~/.gemini/GEMINI.md` are already real files, `install.sh` backs them up before wiring in. Decide what to do with the old content first:

1. **Old content is already covered by the repo** → run `./install.sh` directly; the old file stays as `.bak`.
2. **Old content has rules the repo lacks and you want them shared across machines** → merge them into the repo's `AGENTS.md` and commit first, then `./install.sh`.
3. **Old content is machine/tool-specific** (a particular wrapper, external service, machine environment details) → put it in a per-machine extra (see below), not in the repo.

Compare old content against the repo source:

```bash
diff <(sort -u ~/.codex/AGENTS.md) <(sort -u ~/agent-rules/AGENTS.md)
grep '^#' ~/.codex/AGENTS.md   # see which sections the old file has
```

## Per-machine extras

Rules that should not enter the repo and only apply on one machine go in `~/.agent-rules-local/<tool>.md` (e.g. `codex.md` / `claude.md` / `gemini.md`; the directory can be overridden via the `AGENT_RULES_LOCAL` env var). `install.sh` detects them and layers them on automatically:

- **Tools that support import (Claude)**: writes an import file pulling in the repo source + the extra, auto-synced after `git pull`. It looks like:
  ```
  @/Users/<you>/agent-rules/AGENTS.md
  @/Users/<you>/.agent-rules-local/claude.md
  ```
  (After `@` is an absolute path; Claude's import supports relative / absolute / `~` paths, recursing up to 4 levels.)
- **Tools without import (Codex / Gemini)**: generates a "repo source + extra" concatenated file; **re-run `./install.sh`** to re-concatenate after the source updates.

To add a Claude-specific extra, prefer `~/.agent-rules-local/claude.md` (the script pulls it in via `@import`, surviving re-runs). Do not manually append sections to the generated `~/.claude/CLAUDE.md` — every `install.sh` re-run rewrites that file and your manual edits are lost. `CLAUDE_MODE=import ./install.sh claude` is only for forcing import mode even when there are no extras.

Good candidates for here: call conventions that depend on a specific wrapper / external review service, or path and environment conventions unique to one machine — these shouldn't pollute the cross-tool shared source.

## Project-level (single project)

Copy the template into the project root and tailor it to that project's tech stack:

```bash
cd /path/to/your-project
cp ~/agent-rules/project-template.md ./AGENTS.md  # read by Codex etc., tailor per project
ln -s AGENTS.md ./CLAUDE.md                        # read by Claude Code
```

Project-level rules layer on top of global ones. Priority (see the top of `AGENTS.md`): user instructions > project-level > global > system defaults.

## How it works

Different tools read different filenames, and most aren't interchangeable:

- **`AGENTS.md`** is an open standard led by the Agentic AI Foundation (under the Linux Foundation), **natively read** by 20+ tools including Codex, Cursor, Copilot, Aider, Windsurf, Zed, Jules, and Devin. These tools read `AGENTS.md` directly from the project root or their own conventional location, with no bridging from this repo needed; `install.sh` only wires the global source into the three locations `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, and `~/.gemini/GEMINI.md` (i.e. the `codex` / `claude` / `gemini` tool names) — other tools' global setup follows their own docs.
- **Claude Code** reads only `CLAUDE.md` (not `AGENTS.md`), but supports `@import` (relative / absolute / `~` paths, recursing up to 4 levels).
- **Gemini CLI** reads `GEMINI.md`.

So `AGENTS.md` is the single source, and the other "only-my-own-filename" tools are bridged via symlink or import: symlink where possible (auto-synced with `git pull`), concatenation / import where per-machine extras must be layered.

### Manual equivalents

`install.sh` normally suffices. Below is what the script does under the hood, for troubleshooting. Note: these raw commands **lack the script's backup and overwrite-protection logic** — `ln -sf` overwrites any existing real file or symlink at the target, so confirm the target is disposable before running; for day-to-day installs prefer `install.sh`.

```bash
REPO=~/agent-rules
mkdir -p ~/.codex ~/.claude                    # install.sh creates these; manual setup must do it yourself
ln -sf "$REPO/AGENTS.md" ~/.codex/AGENTS.md    # Codex (when no extras)
ln -sf "$REPO/AGENTS.md" ~/.claude/CLAUDE.md   # Claude (symlink mode)
# Or Claude import mode: write ~/.claude/CLAUDE.md as `@<absolute REPO path>/AGENTS.md` then append your extras
```

## Uninstall and restore

`install.sh` does not modify the source repo; it only creates symlinks / writes files at the three locations `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, and `~/.gemini/GEMINI.md` (creating missing parent directories with `mkdir -p` as needed), and backs up any pre-existing real file to `*.bak.<timestamp>.<pid>` in the same directory. To restore:

```bash
# 1. Remove the symlinks / generated files this installer created (pick the tools you wired in)
rm -f ~/.codex/AGENTS.md ~/.claude/CLAUDE.md ~/.gemini/GEMINI.md

# 2. If you had your own config before installing, restore it from backup (filename uses the actual timestamp)
ls -t ~/.codex/AGENTS.md.bak.*        # find the most recent backup
mv ~/.codex/AGENTS.md.bak.<timestamp>.<pid> ~/.codex/AGENTS.md
```

Removing the symlinks does not affect the source repo; deleting the clone directory afterward removes everything.

## Maintenance and notes

- Edit global rules only in `AGENTS.md` (the single source). How changes take effect:
  - **Symlink / import mode** (Claude by default, and Codex/Gemini without per-machine extras): follows automatically, no extra action; just `git push` / `git pull` across machines.
  - **Concatenation mode** (Codex/Gemini with per-machine extras): after editing the source or `~/.agent-rules-local/<tool>.md`, **re-run `./install.sh <tool>`** to re-concatenate.
- Symlinks are tracked by git (stored as the link itself) and preserved after clone.
- **Windows**: restoring symlinks on clone needs administrator rights or Developer Mode, otherwise symlinks become plain text files — use import mode in that case.

## Contributing

Feel free to fork and make it your own. Issues and PRs for the **general engineering discipline** (the tech-stack-agnostic parts) are welcome too; rules involving personal / team preferences (communication language, task-tiering conventions, etc.) should be adjusted in your own fork and are not expected to be merged upstream.

## License

[MIT](LICENSE) © itstarts
