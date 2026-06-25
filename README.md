# agent-rules

跨 AI 编码工具共用的工程规则仓库。一份源,Codex 和 Claude Code 都能用。

## 为什么这样组织

- **Codex CLI** 自动读取 `AGENTS.md`,但不支持 `@import` 导入语法(纯文本拼接)。
- **Claude Code** 只读取 `CLAUDE.md`(不原生读 `AGENTS.md`),但支持 `@import`(相对/绝对/`~` 路径,递归最多 4 层)。

因此本仓库以 `AGENTS.md` 为**唯一真实源**,`CLAUDE.md` 用软链接指向它。改一处,两个工具同时生效,零重复、零漂移。

> `AGENTS.md` 是 Linux Foundation 旗下 Agentic AI Foundation 主导的开放标准,被 Codex、Cursor、Copilot、Aider、Windsurf、Zed、Jules、Devin 等 20+ 工具原生读取。新增这类工具无需额外配置;只有"只认自家文件名"的工具(Claude Code → `CLAUDE.md`、Gemini CLI → `GEMINI.md`)才需软链桥接。

## 新机器快速开始

```bash
# 1. clone(换成你的 GitHub 地址)
git clone https://github.com/<你的用户名>/agent-rules.git ~/WorkSpace/agent-rules

# 2. 一键安装全局规则(默认接 Codex + Claude Code)
cd ~/WorkSpace/agent-rules
./install.sh

# 想同时接 Gemini CLI:
./install.sh codex claude gemini
```

`install.sh` 幂等可重复运行:已正确指向本仓库的配置自动跳过,已存在的真实配置会先备份成 `*.bak.<时间戳>` 再建软链,不会丢内容。之后 `git pull` 更新 `AGENTS.md`,所有工具自动同步。

若希望 Claude Code 在共享规则之外保留专属补充,用 import 模式安装:

```bash
CLAUDE_MODE=import ./install.sh claude
# 生成的 ~/.claude/CLAUDE.md 形如:
#   @~/WorkSpace/agent-rules/AGENTS.md
#   ## Claude 专属补充
#   ...
```


## 文件

| 文件 | 用途 |
|------|------|
| `AGENTS.md` | 全局通用工程纪律(唯一源,去技术栈耦合,适合所有项目) |
| `CLAUDE.md` | 软链接 → `AGENTS.md`,供 Claude Code 读取 |
| `project-template.md` | 项目级规范模板,承载 SQL/DB、MQ、资金/权限/脱敏等栈相关与业务强约束 |
| `install.sh` | 新机器一键安装脚本(建全局软链,幂等、自动备份) |

## 手动安装:全局生效(install.sh 的等价操作)

> 通常直接用上面的 `install.sh` 即可。下面是脚本背后做的事,供手动操作或排查参考。

```bash
REPO=~/WorkSpace/agent-rules

# Codex 全局(~/.codex/AGENTS.md):不支持 import,用软链直接指向源
mkdir -p ~/.codex
ln -sf "$REPO/AGENTS.md" ~/.codex/AGENTS.md

# Claude Code 全局(~/.claude/CLAUDE.md):两种方式二选一
# 方式 A —— 软链(与 Codex 完全一致,无 Claude 专属补充):
mkdir -p ~/.claude
ln -sf "$REPO/AGENTS.md" ~/.claude/CLAUDE.md

# 方式 B —— import(想在全局规则之外追加 Claude 专属指令时用):
#   把 ~/.claude/CLAUDE.md 写成:
#     @~/WorkSpace/agent-rules/AGENTS.md
#     ## Claude 专属补充
#     ...
```

软链方式下,克隆仓库后无需复制内容;`git pull` 更新源文件即同步生效。

> 注意:方式 A 会覆盖你现有的 `~/.claude/CLAUDE.md`。若已有内容想保留,先备份,或改用方式 B 的 import。

## 安装:项目级生效(单个项目)

把模板复制进项目根目录,按该项目实际技术栈裁剪:

```bash
REPO=~/WorkSpace/agent-rules
cd /path/to/your-project

cp "$REPO/project-template.md" ./AGENTS.md   # 供 Codex 读取,按项目裁剪
ln -s AGENTS.md ./CLAUDE.md                  # 供 Claude Code 读取
```

项目级规则会与全局规则叠加;`AGENTS.md` 头部已说明优先级:用户指令 > 项目级 > 全局 > 系统默认。

## 软链接与 Git

- 软链接能被 git 跟踪(存储为链接本身),clone 后保留。
- macOS / Linux 原生支持。Windows 需管理员权限或开发者模式,否则改用 import 方式。

## 维护

只改 `AGENTS.md`(源)。`CLAUDE.md` 是软链,自动跟随。
