# How It Works

[简体中文](how-it-works.md)

This repository treats `AGENTS.md` as the single rule source, then wires it into different tools through symlinks, Claude imports, or concatenated files.

## File Responsibilities

| File | Responsibility |
|------|----------------|
| `AGENTS.md` | Global engineering rule source |
| `CLAUDE.md` | Repository symlink pointing at `AGENTS.md` |
| `project-template.md` | Project-level rule template |
| `install.sh` | Local installer |
| `codex/agents/` | Versioned Codex custom-agent sources |
| `codex/agents/managed-agents.txt` | The installer's only ownership index |

## Tool Filename Differences

Different tools read different filenames:

- Tools that support `AGENTS.md`, including Codex, can read it directly.
- Claude Code uses `CLAUDE.md` and supports `@` imports.
- Gemini CLI uses `GEMINI.md`.

This repository's installer only wires the global rule source into common global locations for Codex, Claude Code, and Gemini CLI. Other tools that support project-root `AGENTS.md` usually do not need extra bridging from this repository; if they need global config, follow that tool's documentation.

## Sync Model

`AGENTS.md` is the single source. Sync behavior depends on install mode:

- Symlink: the target file points at repository `AGENTS.md`.
- Claude import: the target file contains `@/path/to/AGENTS.md`.
- Concatenated file: the target file contains the repository source plus a per-machine extra.

Symlink and import modes take effect after repository updates. Concatenated files require re-running `./install.sh`.

## Global Rules and Project-Level Rules

Global rules are for cross-project engineering discipline that is tech-stack agnostic by default. Domain rules may also be global when they are broadly reusable and have explicit task, stack, and tool activation conditions. Project-level rules carry concrete business, stack, and high-risk-path constraints.

Recommended project-level setup:

```bash
cp ~/agent-rules/project-template.md ./AGENTS.md
ln -s AGENTS.md ./CLAUDE.md
```

Priority:

1. Current user instruction
2. Project-level rules
3. Global rules
4. Default behavior

Project-level rules may refine workflows and constraints, but should not loosen safety, permission, or verification-evidence requirements.

## Codex Roles and Transaction Boundaries

`AGENTS.md` is the engineering-rule source; `codex/agents/` is the separate source for Codex custom agents. The source directory intentionally avoids project-level `.codex/agents` auto-loading. Personal Codex loads the roles through per-file absolute symlinks only after the explicit `./install.sh codex-agents` command. `managed-agents.txt` prevents the installer from silently adopting unknown files in the directory.

Role files contain only `name`, `description`, `developer_instructions`, `nickname_candidates`, and `sandbox_mode`. Analysis and review roles default to `read-only`; explicitly scoped implementation roles default to `workspace-write`. A parent session's live permission policy is reapplied, so role files express auditable defaults and responsibility boundaries rather than an unbypassable security boundary.

The installation transaction takes a non-blocking exclusive lock on the Codex root directory descriptor itself, named `root_fd`, without creating a persistent lock file. All in-root access starts from `root_fd` and uses no-follow and `dir_fd` operations. The installer rechecks the root device and inode before critical writes, so replacing the root path cannot redirect an old transaction into the replacement directory.

After backups are complete and `fsync` has made them durable, the transaction publishes a schema-versioned `journal.toml`, installs roles one by one, atomically replaces config, and persists progress. Recovery first journals deterministic object names plus input/output digests, then creates recovery objects and rechecks their identities before every rename. State moves from `install-in-progress` to `committed`; interrupted work moves through `recover-in-progress` to `recovered`, while reversal of a committed transaction moves through `restore-in-progress` to `restored`. Resume accepts only the transaction-created state or exact pre-transaction state; any third state stops to avoid overwriting concurrent changes.

## Design Tradeoffs

- Keep `AGENTS.md` as a single source to avoid drift across tool-specific files.
- Make the installer conservative around existing config so real files are not overwritten silently.
- Keep per-machine extras out of the repository so personal paths or external-service conventions do not leak into shared rules.
- Keep global rules tech-stack agnostic by default. Add domain rules conditionally only when they are reusable across projects and have explicit activation criteria; concrete stack constraints still belong in project-level `AGENTS.md`.
- Keep security analysis, design, implementation, testing, and review proportional to the task's actual risk and explicit threat model. Without a concrete risk and failure consequence, do not add code, tests, or gates for theoretical attack surfaces.
