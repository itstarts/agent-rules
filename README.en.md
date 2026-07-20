# agent-rules

[简体中文](README.md) | **English**

[![CI](https://github.com/itstarts/agent-rules/actions/workflows/ci.yml/badge.svg)](https://github.com/itstarts/agent-rules/actions/workflows/ci.yml)

Global engineering rules for Codex. `AGENTS.md` is the single source of truth, and `install.sh` wires it into the local Codex config.

## Quick Start

```bash
git clone https://github.com/itstarts/agent-rules.git ~/agent-rules
cd ~/agent-rules
./install.sh                      # defaults to Codex
./install.sh codex                # explicitly wire up Codex
./install.sh codex-agents         # explicitly install global Codex custom agents
./install.sh codex-agent-routing  # explicitly install model + effort routing
```

The installer wires these targets:

| Tool | Target file |
|------|-------------|
| Codex | `~/.codex/AGENTS.md` |
| Codex custom agents | `${CODEX_HOME:-~/.codex}/agents/*.toml` |
| Codex agent routing Hook | `${CODEX_HOME:-~/.codex}/config.toml` |

The installer prefers symlinks so rules stay in sync with this repository. **Keep the clone directory in place; do not move or delete it.** Symlinks reference this checkout by absolute path, so moving the directory breaks the global config.

Existing targets are handled by type: real files are backed up as `*.bak.<timestamp>.<pid>`; symlinks already pointing at this repository are skipped; some generated-file modes remove an old symlink before writing a new file. See [installation details](docs/install.en.md) for the exact behavior.

`codex-agents` and `codex-agent-routing` are separate explicit targets, so neither changes the existing no-argument or `codex` behavior. The first installs 11 versioned roles and conservatively adds three `[agents]` governance keys. The second installs a `PreToolUse` Hook that writes `model + reasoning_effort` when a Sub Agent is dispatched. See [installation details](docs/install.en.md) for transactions, conflicts, and recovery commands, and [how it works](docs/how-it-works.en.md#codex-role-routing) for role and risk classification.

## Common Usage

### Per-Machine Extras

Put machine-local rules in `~/.agent-rules-local/codex.md`. The installer layers the repository source and the local extra automatically. See [installation details](docs/install.en.md#per-machine-extras).

### Project-Level Rules

Copy the project template into a project root and tailor it to that stack:

```bash
cd /path/to/your-project
cp ~/agent-rules/project-template.md ./AGENTS.md
```

Project-level rules override and refine global rules. See [project-template.md](project-template.md).

## Documentation

| Document | Contents |
|----------|----------|
| [AGENTS.md](AGENTS.md) | Global engineering rule source |
| [project-template.md](project-template.md) | Project-level rule template |
| [docs/install.en.md](docs/install.en.md) | Install, migration, restore, and per-machine extras |
| [docs/how-it-works.en.md](docs/how-it-works.en.md) | File responsibilities, sync modes, role routing, and dynamic model + effort policy |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |
| [SECURITY.md](SECURITY.md) | Security reporting |

## Development and Verification

```bash
git diff --check
bash -n install.sh
shellcheck install.sh
python3 -B scripts/validate_codex_agents.py
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

CI runs Bash syntax checks, ShellCheck, Codex role validation, the complete Python test suite, and isolated-`HOME` install smoke tests. If `shellcheck` is not installed locally, run at least `bash -n install.sh` and rely on CI for ShellCheck coverage.

## License

[MIT](LICENSE) © itstarts
