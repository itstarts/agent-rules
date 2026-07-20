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
| `codex/agent-routing.toml` | Model aliases, role defaults, risk escalation, and runtime feature gates |
| `scripts/codex_agent_router.py` | `PreToolUse` routing Hook |

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

Each managed role's filename exactly matches its TOML `name`, and managed names contain only lowercase letters, digits, and underscores so they can be passed directly as a `spawn_agent` agent name.

Role files contain `name`, a concise routing `description`, `developer_instructions`, `nickname_candidates`, and `sandbox_mode`. They no longer pin `model` or `model_reasoning_effort`. Analysis and review roles default to `read-only`; explicitly scoped implementation roles default to `workspace-write`. A parent session's live permission policy is reapplied, so role files express auditable defaults and responsibility boundaries rather than an unbypassable security boundary. Models and `reasoning_effort` are centralized in `agent-routing.toml`, so a model upgrade changes only its alias mapping.

## Codex Role Routing

Prefer the single role that best matches the current artifact and task boundary:

| Current task or artifact | Preferred role |
|---|---|
| Requirements, user scenarios, scope, and acceptance criteria | `product_analyst` |
| Architecture, module boundaries, data flow, and public contracts | `architect` |
| Requirements specifications or implementation plans | `spec_plan_reviewer` |
| Code, diffs, PRs, and implementation evidence | `reviewer` |
| Data models, migrations, transactions, locks, and concurrency | `data_consistency_reviewer` |
| Final gate for heavyweight work, project-level high-risk changes, or an explicit request | `final_gate_reviewer` |
| Page goals, information architecture, wireframes, and state design | `ui_ux_designer` |
| Visual verification against an approved design and actual screenshots | `visual_reviewer` |
| Explicitly assigned, non-overlapping backend or frontend implementation | `worker_backend` / `worker_frontend` |
| Test strategy, fixtures, test helpers, and validation | `test_engineer` |
| Multi-module read-only exploration or generic implementation without a matching custom role | built-in `explorer` / `worker` |

The main agent handles single-point lookups and lightweight local edits directly. Use one primary review role per artifact gate by default; add a specialist only when data consistency or visual verification is a distinct risk. `final_gate_reviewer` checks only gates that were triggered and are applicable to the current task. Installation, runtime, or deployment evidence is required only when the task actually includes those actions. Parallel writes are reserved for independent file scopes with a frozen shared contract.

`tests/fixtures/codex_agent_routing_cases.json` stores representative delegation and no-delegation cases for checking role coverage, child-agent limits, and built-in fallback boundaries whenever descriptions or routing rules change.

### Default model + effort by role

A `routine` dispatch uses the role default. Sol, Terra, and Luna are stable policy-tier names. Concrete model identifiers live under `[models]` in `agent-routing.toml` instead of being repeated in role files or `AGENTS.md`.

| Role | Model tier | `reasoning_effort` |
|---|---|---|
| `architect`, `data_consistency_reviewer` | Sol | `xhigh` |
| `final_gate_reviewer` | Sol | `max` |
| `reviewer`, `spec_plan_reviewer` | Sol | `high` |
| `worker_backend`, `worker_frontend`, built-in `worker` / `default` | Sol | `high` |
| `ui_ux_designer` | Sol | `medium` |
| `test_engineer` | Terra | `high` |
| `product_analyst`, `visual_reviewer`, built-in `explorer` | Terra | `medium` |

These defaults describe the capability usually needed by a role; they do not classify task risk. The main agent also selects a route class from actual impact:

| `ROUTING_CLASS` | Behavior |
|---|---|
| `routine` | Use the role default |
| `complex` | Raise to at least Sol + `high` |
| `critical` | Raise to at least Sol + `xhigh`; keep `max` for `final_gate_reviewer` |
| `mechanical` | Use Luna + `medium` only for mechanical work with explicit inputs and outputs |

Dynamic runtime overrides currently enable Sol and Terra only. Luna is present as a policy tier but is not yet in `dynamic_tiers`; a `mechanical` dispatch is explicitly denied instead of silently falling back to Terra. When the runtime supports Luna, update `[models].luna` and add `luna` to `dynamic_tiers`; role files do not need to change.

### Automatic switching flow and limits

The main agent classifies semantic impact, not isolated keywords such as “permission” or “migration.” Checking a permission label may be `routine`; changing a public permission contract is `critical`. Every dispatch message includes:

```text
ROUTING_CLASS=critical
ROUTING_REASON=Changes a public permission contract and affects existing callers
```

For compatibility with existing dispatches that have not been updated yet, a message with both markers completely absent uses the role's `routine` default and adds `missing-routing-markers` context. A partial, duplicate, misspelled, or malformed marker is denied instead of being silently treated as a default.

At `PreToolUse`, `codex_agent_router.py` intercepts `Agent`, combines the role default with the risk class, chooses the stronger configuration, and writes `model` plus `reasoning_effort` back into the dispatch input. Explicit overrides require `fork_turns` to be `"none"` or a positive integer. Full history with `"all"` can only inherit from the parent, so the Hook denies that combination. Unmanaged third-party agent types are unchanged.

The Hook controls one dispatch; it cannot replace the model of a Sub Agent that is already running. When a child discovers a larger scope or risk, it returns `ESCALATION_REQUIRED`. The main agent stops relying on the lower route and dispatches again with a higher `ROUTING_CLASS`. This provides auditable automatic selection and controlled escalation without replacing user approval, permission, security, test, or review gates.

Both the role installer and routing-Hook installer take a non-blocking exclusive lock on the Codex root directory descriptor itself, named `root_fd`, without creating a persistent lock file. They also check each other's in-progress journals. All in-root access starts from `root_fd` and uses no-follow and `dir_fd` operations. The installer rechecks the root device and inode before critical writes, so replacing the root path cannot redirect an old transaction into the replacement directory.

After backups are complete and `fsync` has made them durable, the transaction publishes a schema-versioned `journal.toml`, installs roles one by one, atomically replaces config, and persists progress. Recovery first journals deterministic object names plus input/output digests, then creates recovery objects and rechecks their identities before every rename. State moves from `install-in-progress` to `committed`; interrupted work moves through `recover-in-progress` to `recovered`, while reversal of a committed transaction moves through `restore-in-progress` to `restored`. Resume accepts only the transaction-created state or exact pre-transaction state; any third state stops to avoid overwriting concurrent changes.

## Design Tradeoffs

- Keep `AGENTS.md` as a single source to avoid drift across tool-specific files.
- Make the installer conservative around existing config so real files are not overwritten silently.
- Keep per-machine extras out of the repository so personal paths or external-service conventions do not leak into shared rules.
- Keep global rules tech-stack agnostic by default. Add domain rules conditionally only when they are reusable across projects and have explicit activation criteria; concrete stack constraints still belong in project-level `AGENTS.md`.
- Keep security analysis, design, implementation, testing, and review proportional to the task's actual risk and explicit threat model. Without a concrete risk and failure consequence, do not add code, tests, or gates for theoretical attack surfaces.
