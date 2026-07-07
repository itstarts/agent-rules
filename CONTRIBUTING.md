# Contributing

**简体中文** | [English](#english)

欢迎贡献通用工程规则、安装脚本和文档改进。这个仓库带有明确的主观取向，适合 fork 后按个人或团队习惯调整；上游只接收适合跨项目复用的内容。

## 接受的改动

- 技术栈无关、跨项目通用的工程纪律。
- `install.sh` 的安全性、可移植性和幂等性改进。
- README、安装文档、项目模板和开源治理文档改进。
- CI 或验证流程改进。

## 规则变更原则

- 保持规则可执行，避免只表达价值观但无法落地。
- 不把单个团队、单台机器或单个业务域的偏好写进全局规则。
- 高风险工程边界应说明原因和后果。
- 保持中英文文档结构大体同步。

## 提交前检查

```bash
git diff --check
bash -n install.sh
shellcheck install.sh
```

如果本机没有 `shellcheck`，请至少运行 `bash -n install.sh`，并在 PR 中说明未本地运行 ShellCheck。

## English

Contributions are welcome for general engineering rules, installer behavior, and documentation. This repository is intentionally opinionated, so forks are encouraged for personal or team-specific preferences; upstream changes should be broadly reusable across projects.

### Accepted Changes

- Tech-stack-agnostic engineering discipline.
- Safety, portability, and idempotency improvements for `install.sh`.
- README, install docs, project templates, and open-source governance docs.
- CI or verification workflow improvements.

### Rule Change Principles

- Keep rules actionable instead of only stating values.
- Do not put single-team, single-machine, or business-domain preferences into global rules.
- Explain reasons and consequences for high-risk engineering boundaries.
- Keep Chinese and English documentation broadly aligned.

### Before Opening a PR

```bash
git diff --check
bash -n install.sh
shellcheck install.sh
```

If `shellcheck` is not installed locally, run at least `bash -n install.sh` and mention that ShellCheck was not run locally.
