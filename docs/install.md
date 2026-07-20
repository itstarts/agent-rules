# 安装细节

[English](install.en.md)

`install.sh` 把仓库内的 `AGENTS.md` 接入本机 AI 编码工具配置。脚本只处理 Codex、Claude Code 和 Gemini CLI；其它工具按其自身文档配置。

## 支持的平台

- macOS / Linux：默认支持 Bash 与 `ln -s`。
- Windows：Claude 可使用 import 模式；Codex / Gemini 的软链模式通常需要开发者模式或管理员权限。无法创建软链时，需要按工具手动配置，或为 Codex/Gemini 准备本机补充文件后由脚本生成拼接文件。

## 基本用法

```bash
./install.sh                      # 默认接入 codex claude
./install.sh codex claude gemini  # 显式指定工具
CLAUDE_MODE=import ./install.sh claude
```

环境变量：

- `CLAUDE_MODE=symlink|import`：Claude 默认使用 `symlink`；设置为 `import` 时写入 `@<AGENTS.md>` 引用。
- `AGENT_RULES_LOCAL=/path/to/local-rules`：覆盖本机专属补充目录，默认是 `~/.agent-rules-local`。

## 安装模式

| 模式 | 适用场景 | 同步方式 |
|------|----------|----------|
| 纯软链 | Codex/Gemini 无本机补充；Claude 默认模式 | `git pull` 更新仓库后自动生效 |
| Claude import | `CLAUDE_MODE=import` 或存在 Claude 本机补充 | `git pull` 更新仓库后自动生效 |
| 拼接文件 | Codex/Gemini 存在本机补充 | 更新仓库或补充文件后重跑 `./install.sh` |

软链和 import 按绝对路径引用当前 clone。安装后请保留 clone 目录，不要移动或删除；换位置时重新 clone 并重跑安装脚本。

## Codex 全局自定义角色

角色安装是显式入口，不包含在默认安装或 `codex` 目标中：

```bash
./install.sh codex-agents
```

该入口要求 Python 3.11+ 和标准库 `tomllib`，不会安装依赖。Codex 根目录默认是 `~/.codex`；设置 `CODEX_HOME` 时使用该目录，且显式目录必须已经存在。

仓库的 `codex/agents/managed-agents.txt` 精确声明 11 个受管理角色。安装器在 Codex 根目录的 `agents/` 中创建逐文件绝对软链，不接管整个目录，也不修改未管理角色。仓库移动后绝对软链会失效；把仓库移动到新位置后重新运行 `./install.sh codex-agents` 并执行校验。

安装器只管理：

```toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
```

`codex-agents` 不管理全局 `config.toml` 中的模型、Provider、认证、MCP、插件、`job_max_runtime_seconds`、角色子表及其它配置；动态模型与 effort 由下文独立的路由入口管理。显式 `multi_agent = false` 或不兼容结构会安全停止。配置不存在时以 `0600` 创建；现有配置通过 `tomllib` 完整解析，只补缺失兼容键，并从同一 Codex 根文件系统内的事务 staging 原子替换。

每次发生实际变更都会输出 transaction ID，格式为 UTC 时间戳和随机后缀。角色旧文件、损坏软链元数据和配置备份保存在 Codex 根目录下的受保护事务目录；目录权限不宽于 `0700`，普通备份和 `journal.toml` 不宽于 `0600`。事务先持久化备份与 journal，再修改目标。

默认或非交互冲突不会产生任何备份或安装变更。只有交互终端中输入“只备份”明确确认时，安装器才创建内容摘要命名的幂等冲突快照并停止；该路径不会安装角色或修改配置。

异常终止留下的进行中事务会阻止新安装。按错误消息中的 transaction ID 执行：

```bash
./install.sh codex-agents-recover 20260715T120000Z-a1b2c3d4e5f6
```

成功安装后需要撤销该事务时执行：

```bash
./install.sh codex-agents-restore 20260715T120000Z-a1b2c3d4e5f6
```

`recover` 恢复异常中断事务，`restore` 撤销已提交事务；两者都使用同一目录锁和 journal 状态机，可在再次中断后幂等续跑。恢复只处理该事务的受管理角色和新增配置键，并保留安装后的无关合法配置变化。

安装后验证仓库源码和本机目标：

```bash
python3 -B scripts/validate_codex_agents.py
python3 -B scripts/validate_codex_agents.py --installed-root "${CODEX_HOME:-$HOME/.codex}"
codex --strict-config doctor --json
```

受管理角色使用逐文件软链，仓库更新后内容会自动同步，不需要重复安装。为确保客户端重新读取角色描述，更新角色源码后建议新开 Codex 任务。

## Codex 子代理动态路由

路由 Hook 是另一个显式入口，不包含在默认安装、`codex` 或 `codex-agents` 目标中：

```bash
./install.sh codex-agent-routing
```

该入口同样要求 Python 3.11+，不安装依赖。它在 Codex 根目录的 `config.toml` 中增加一个带专用起止标记的 inline Hook；匹配范围只有 `PreToolUse` 的 `^Agent$`。Codex 的工具别名覆盖会让该 matcher 同时捕获 canonical `spawn_agent`，router 接受这两个 `tool_name`。Hook 命令按绝对路径引用仓库内的 `scripts/codex_agent_router.py`，后者读取 `codex/agent-routing.toml`，因此同一 clone 内更新模型标识或路由表后无需重装。移动 clone、切换 Python 可执行文件或变更安装块格式后，应重跑安装器。

安装器不绕过 Codex 的 Hook trust 机制。首次加载非托管 command Hook 时，Codex 可能要求用户检查并信任绝对命令路径；应确认路径指向当前 clone 后再批准。

安装器只接管专用标记内的 Hook 块，并保留其它合法配置和不匹配 `Agent` 的 Hooks。以下情况会在创建事务前安全停止：

- `[features] hooks = false` 或弃用别名 `codex_hooks = false`；
- 同层已存在 `hooks.json`，避免同时加载两种 Hook 配置并产生告警；
- 已存在另一个能匹配 `Agent` 或 canonical `spawn_agent` 的 `PreToolUse` Hook；
- 专用标记缺失一端、重复，或标记内结构被改坏。

路由 Hook 会改写派发输入中的 `model` 和 `reasoning_effort`，保留其它字段。显式覆盖要求 `fork_turns = "none"` 或正整数形式的有限历史；省略 `fork_turns` 或使用 `"all"` 时，运行时只能继承父 Agent，因此 Hook 会拒绝该次派发。未受管理的第三方 agent type 不会被改写。

实际变更使用独立事务命名空间，并与 `codex-agents` 共用 Codex 根目录锁；任一安装器存在进行中事务时，另一个安装器都会停止。异常中断后执行：

```bash
./install.sh codex-agent-routing-recover 20260715T120000Z-a1b2c3d4e5f6
```

撤销已提交的路由安装执行：

```bash
./install.sh codex-agent-routing-restore 20260715T120000Z-a1b2c3d4e5f6
```

恢复和撤销只替换或移除专用标记块，并保留安装后新增的其它合法 `config.toml` 内容；若该托管块已被外部修改，则拒绝覆盖。路由配置、风险等级和 Luna 功能门禁见 [工作原理](how-it-works.md#codex-角色路由)。

## 目标文件与既有配置

| 工具 | 目标文件 |
|------|----------|
| Codex | `~/.codex/AGENTS.md` |
| Claude Code | `~/.claude/CLAUDE.md` |
| Gemini CLI | `~/.gemini/GEMINI.md` |

脚本会先创建缺失的父目录。既有目标按类型处理：

- 真实文件：备份为同目录下的 `*.bak.<timestamp>.<pid>`。
- 指向本仓库 `AGENTS.md` 的软链：视为已就绪并跳过。
- 指向其它位置的软链：纯软链模式会备份；拼接/import 写入模式会先移除旧软链再写入新文件，避免顺着软链覆盖源文件。

脚本拒绝把仓库内路径当作目标写入，防止覆盖源文件。

## 已有配置迁移

若目标文件已有内容，先判断归属：

1. 已被仓库规则覆盖：直接运行 `./install.sh`，保留自动备份。
2. 应跨机器共享：先合入仓库 `AGENTS.md` 并提交，再安装。
3. 只适用于本机或单个工具：放入本机专属补充。

可用下面命令辅助比较：

```bash
diff <(sort -u ~/.codex/AGENTS.md) <(sort -u ~/agent-rules/AGENTS.md)
grep '^#' ~/.codex/AGENTS.md
```

## 本机专属补充

本机补充文件放在 `~/.agent-rules-local/<tool>.md`：

```text
~/.agent-rules-local/codex.md
~/.agent-rules-local/claude.md
~/.agent-rules-local/gemini.md
```

适合放入本机补充的内容包括：特定 wrapper 调用纪律、机器路径、个人外部工具约定。跨项目通用规则应合入仓库 `AGENTS.md`。

Claude 支持 import，安装脚本会写入：

```text
@/path/to/agent-rules/AGENTS.md
@/path/to/.agent-rules-local/claude.md
```

Codex / Gemini 不支持 import 时，脚本会生成“仓库源 + 本机补充”的拼接文件；仓库源或补充文件更新后需要重跑安装脚本。

## 手动等价操作

日常安装优先使用 `install.sh`，因为脚本包含备份和防覆盖逻辑。手动操作只适合排查：

```bash
REPO=~/agent-rules
mkdir -p ~/.codex ~/.claude
ln -s "$REPO/AGENTS.md" ~/.codex/AGENTS.md
ln -s "$REPO/AGENTS.md" ~/.claude/CLAUDE.md
```

不要用 `ln -sf` 覆盖未知目标，除非确认旧文件无需保留。

## 卸载与恢复

删除接入文件：

```bash
rm -f ~/.codex/AGENTS.md ~/.claude/CLAUDE.md ~/.gemini/GEMINI.md
```

如需恢复安装前配置，从备份中选择最近文件：

```bash
ls -t ~/.codex/AGENTS.md.bak.*
mv ~/.codex/AGENTS.md.bak.<timestamp>.<pid> ~/.codex/AGENTS.md
```

删除软链或生成文件不会修改源仓库。确认没有其它工具依赖该 clone 后，可以删除 clone 目录。
