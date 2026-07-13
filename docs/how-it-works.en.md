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

## Design Tradeoffs

- Keep `AGENTS.md` as a single source to avoid drift across tool-specific files.
- Make the installer conservative around existing config so real files are not overwritten silently.
- Keep per-machine extras out of the repository so personal paths or external-service conventions do not leak into shared rules.
- Keep global rules tech-stack agnostic by default. Add domain rules conditionally only when they are reusable across projects and have explicit activation criteria; concrete stack constraints still belong in project-level `AGENTS.md`.
