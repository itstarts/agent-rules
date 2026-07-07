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
