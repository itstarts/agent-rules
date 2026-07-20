# Contributing

**简体中文** | [English](#english)

欢迎贡献通用工程规则、安装脚本和文档改进。这个仓库带有明确的主观取向，适合 fork 后按个人或团队习惯调整；上游只接收适合跨项目复用的内容。

## 接受的改动

- 技术栈无关、跨项目通用的工程纪律，以及跨项目可复用且触发条件明确的领域规则。
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

## 发版流程

1. 从最新且干净的 `main` 创建发布开发分支，确定符合语义化版本的 `vX.Y.Z`。
2. 在开发分支准备 Release notes 草稿并运行 README 中的完整验证命令；此时的结果只用于合入前检查，不作为最终发布审计。
3. 提交并合入 `main`，等待合入提交的 CI 成功，并确认本地 `main` 工作区干净且与远端同步。
4. 只在上述精确且干净的最终 `main` 提交上执行 Git 历史安全扫描：
   - 首次发布扫描当前树，以及 `git rev-list --all` 返回的全部可达历史；
   - 后续发布可使用最近一个已发布、已完成全量审计且未发生移动、删除或重建的 release tag 作为 `BASELINE_TAG`，只扫描当前树和 `BASELINE_TAG..HEAD`；
   - 使用增量范围前，必须确认 GitHub Release 存在、本地与远端 tag 身份一致、tag 是当前发布提交的祖先；任一条件不满足、历史被改写、基线不可验证或增量扫描异常时，回退到全量扫描。
   安全扫描至少检查凭证和密钥、本机绝对路径、个人隐私，以及误提交的生成物或大文件；匹配结果不得在公开日志中回显敏感值。
5. 根据最终验证与审计事实定稿 Release notes，并确认待创建的 annotated tag 将指向当前 `main` 提交。
6. 在本地创建 annotated tag，确认其 peeled commit 与 `main` 一致；推送 tag 后再次核对远端 tag 身份。已发布的 release tag 不得移动、覆盖、删除或复用。
7. 使用已经定稿的 notes 创建 GitHub Release，名称只使用对应版本号（如 `v1.2.3`），不附加主题、副标题或其它文本；再以只读方式核对 tag、Release 与 `main` 提交一致，且公开文案完整。
8. 删除已合入的本地和远端开发分支。

## Release notes 模板

Release notes 固定以 `## 本版内容` 开头。变更部分按 `Added`、`Changed`、`Fixed`、`Removed`、`Security` 的顺序保留实际适用的分类，空分类省略；最后保留 `### Verification` 和完整变更链接。

```markdown
## 本版内容

### Added

- 面向使用者的新增内容。

### Changed

- 面向使用者的行为或流程变化。

### Verification

- 实际执行并通过的验证与发布审计。

**完整变更**: https://github.com/<owner>/<repo>/compare/vPREVIOUS...vCURRENT
```

首次发布没有上一版本，末行改为 `**完整源码**: https://github.com/<owner>/<repo>/tree/vCURRENT`。Release notes 只记录当前版本事实，不写临时排障过程、未完成事项或无法验证的声明。

## English

Contributions are welcome for general engineering rules, installer behavior, and documentation. This repository is intentionally opinionated, so forks are encouraged for personal or team-specific preferences; upstream changes should be broadly reusable across projects.

### Accepted Changes

- Tech-stack-agnostic, cross-project engineering discipline, plus cross-project domain rules with explicit activation criteria.
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

### Release Process

1. Create a release development branch from a clean, up-to-date `main` and select a semantic `vX.Y.Z` version.
2. Prepare a draft of the release notes on the development branch and run the complete validation commands from the README. These results are pre-merge checks, not the final release audit.
3. Merge into `main`, wait for CI on the merge commit to pass, and confirm that local `main` is clean and synchronized with the remote.
4. Run the Git-history security audit only on that exact, clean final `main` commit:
   - for the first release, audit the current tree and all reachable history returned by `git rev-list --all`;
   - for later releases, the latest published release tag may be used as `BASELINE_TAG` only after a full audit and only while it has not been moved, deleted, or recreated; audit the current tree and `BASELINE_TAG..HEAD`;
   - before using the incremental range, verify that the GitHub Release exists, local and remote tag identities match, and the tag is an ancestor of the release commit. Fall back to a full audit after rewritten history, an unverifiable baseline, or any incremental-scan anomaly.
   At minimum, audit credentials and secrets, machine-specific absolute paths, private data, and unintended generated or oversized files. Never echo matched secret values into public logs.
5. Finalize the release notes from the final validation and audit facts, and confirm that the intended annotated tag will point to the current `main` commit.
6. Create the annotated tag locally and verify that its peeled commit matches `main`. Push the tag, then verify the remote tag identity. A published release tag must never be moved, overwritten, deleted, or reused.
7. Create the GitHub Release with the finalized notes. Use only the corresponding version number (for example, `v1.2.3`) as its name; do not append a theme, subtitle, or any other text. Then read back and verify that the tag, Release, and `main` resolve to the same commit and that the public notes are complete.
8. Delete the merged local and remote development branches.

### Release Notes Template

Release notes always start with `## 本版内容`. Keep only applicable Keep a Changelog categories in this order: `Added`, `Changed`, `Fixed`, `Removed`, and `Security`. End with `### Verification` and the full-change link.

```markdown
## 本版内容

### Added

- User-facing additions.

### Changed

- User-facing behavior or workflow changes.

### Verification

- Validation and release-audit evidence actually completed.

**完整变更**: https://github.com/<owner>/<repo>/compare/vPREVIOUS...vCURRENT
```

For the first release, replace the final line with `**完整源码**: https://github.com/<owner>/<repo>/tree/vCURRENT`. Release notes contain current-version facts only, not temporary debugging history, unfinished work, or unverified claims.
