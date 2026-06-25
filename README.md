# agent-rules

跨 AI 编码工具共用的工程规则仓库。一份源,Codex 和 Claude Code 都能用。

## 为什么这样组织

- **Codex CLI** 自动读取 `AGENTS.md`,但不支持 `@import` 导入语法(纯文本拼接)。
- **Claude Code** 只读取 `CLAUDE.md`(不原生读 `AGENTS.md`),但支持 `@import`(相对/绝对/`~` 路径,递归最多 4 层)。

因此本仓库以 `AGENTS.md` 为**唯一真实源**,`CLAUDE.md` 用软链接指向它。改一处,两个工具同时生效,零重复、零漂移。

## 文件

| 文件 | 用途 |
|------|------|
| `AGENTS.md` | 全局通用工程纪律(唯一源,去技术栈耦合,适合所有项目) |
| `CLAUDE.md` | 软链接 → `AGENTS.md`,供 Claude Code 读取 |
| `project-template.md` | 项目级规范模板,承载 SQL/DB、MQ、资金/权限/脱敏等栈相关与业务强约束 |

## 安装:全局生效(机器上所有项目)

> 会让 Codex 与 Claude Code 在每个会话都加载本仓库的全局规则。
> 下面假设仓库克隆在 `~/WorkSpace/agent-rules`,按实际路径替换。

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
