# Security Policy

**简体中文** | [English](#english)

## 报告安全问题

如果你发现安装脚本、文档指令或仓库配置存在安全问题，请优先使用 GitHub 的 private vulnerability reporting / Security Advisory 功能。若仓库未启用该入口，请开一个只包含最小信息的 issue，请维护者提供私下联系方式。

不要在公开 issue 中贴出 token、密钥、私有路径、完整本机配置或其它敏感信息。

## 安装脚本安全边界

`install.sh` 会写入以下用户目录目标：

- `~/.codex/AGENTS.md`

脚本会备份既有真实文件，拒绝把仓库内路径作为安装目标，并避免顺着旧软链覆盖源文件。更多细节见 [docs/install.md](docs/install.md)。

## English

### Reporting Security Issues

If you find a security issue in the installer, documentation instructions, or repository configuration, prefer GitHub private vulnerability reporting / Security Advisories. If that channel is not enabled, open a public issue with only minimal information and ask maintainers for a private contact path.

Do not post tokens, secrets, private paths, full local config, or other sensitive information in public issues.

### Installer Security Boundaries

`install.sh` writes to these user-level targets:

- `~/.codex/AGENTS.md`

The script backs up existing real files, refuses repository-internal install targets, and avoids writing through old symlinks onto their sources. See [docs/install.en.md](docs/install.en.md) for details.
