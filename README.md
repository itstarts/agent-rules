# agent-rules

**简体中文** | [English](README.en.md)

[![CI](https://github.com/itstarts/agent-rules/actions/workflows/ci.yml/badge.svg)](https://github.com/itstarts/agent-rules/actions/workflows/ci.yml)

跨 AI 编码工具共用的工程规则集合。以 `AGENTS.md` 为唯一规则源，安装脚本负责把它接入本机的 Codex、Claude Code 和 Gemini CLI 配置。

## 快速开始

```bash
git clone https://github.com/itstarts/agent-rules.git ~/agent-rules
cd ~/agent-rules
./install.sh                      # 默认接入 Codex + Claude Code
./install.sh codex claude gemini  # 可选接入 Gemini CLI
./install.sh codex-agents         # 显式安装 Codex 全局自定义角色
```

安装后会接入这些位置：

| 工具 | 目标文件 |
|------|----------|
| Codex | `~/.codex/AGENTS.md` |
| Claude Code | `~/.claude/CLAUDE.md` |
| Gemini CLI | `~/.gemini/GEMINI.md` |
| Codex custom agents | `${CODEX_HOME:-~/.codex}/agents/*.toml` |

安装脚本会优先使用软链或 Claude import，让规则随仓库更新同步。**请保留 clone 目录，不要移动或删除**；软链 / import 模式按绝对路径引用本仓库，目录移动后全局配置会失效。

已有目标文件时，脚本会按目标类型处理：真实文件会备份为 `*.bak.<timestamp>.<pid>`；指向本仓库源的软链会跳过；部分生成模式会先移除旧软链再写入新文件。完整行为见 [安装细节](docs/install.md)。

`codex-agents` 是独立、显式入口，不会改变无参数或 `codex` 目标的既有行为。它安装 11 个版本化角色并保守补齐 `[agents]` 三个治理键；事务、冲突和恢复命令见 [安装细节](docs/install.md#codex-全局自定义角色)，角色路由和轻量 effort 策略见 [工作原理](docs/how-it-works.md#codex-角色路由)。

## 常见用法

### 本机专属补充

把只在本机生效的规则放到 `~/.agent-rules-local/<tool>.md`，例如 `~/.agent-rules-local/codex.md`。安装脚本会自动把仓库源和本机补充叠加。详见 [安装细节](docs/install.md#本机专属补充)。

### 项目级规则

把项目模板复制到目标项目根目录，并按项目技术栈裁剪：

```bash
cd /path/to/your-project
cp ~/agent-rules/project-template.md ./AGENTS.md
ln -s AGENTS.md ./CLAUDE.md
```

项目级规则会覆盖和细化全局规则。模板见 [project-template.md](project-template.md)。

## 文档

| 文档 | 内容 |
|------|------|
| [AGENTS.md](AGENTS.md) | 全局工程规则源 |
| [project-template.md](project-template.md) | 项目级规则模板 |
| [docs/install.md](docs/install.md) | 安装、迁移、恢复和本机补充 |
| [docs/how-it-works.md](docs/how-it-works.md) | 文件职责、同步方式、角色路由和轻量 effort 策略 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献规则 |
| [SECURITY.md](SECURITY.md) | 安全问题报告 |

## 开发与验证

```bash
git diff --check
bash -n install.sh
shellcheck install.sh
python3 -B scripts/validate_codex_agents.py
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

CI 会执行 Bash 语法检查、ShellCheck、Codex 角色校验、全部 Python 测试和隔离 `HOME` 的安装冒烟测试。若本机未安装 `shellcheck`，至少运行 `bash -n install.sh`，并依赖 CI 补齐 ShellCheck 验证。

## License

[MIT](LICENSE) © itstarts
