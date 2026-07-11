# Allow Read-Only Network Lookups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 允许 agent 自主进行只读联网查询，同时保留对外部环境调试、安装、下载、发布和推送等有副作用操作的授权要求。

**Architecture:** `AGENTS.md` 继续作为唯一规则源，仅调整联网权限相关文字。安装脚本和工具接入方式保持不变，合并后通过默认安装将更新后的规则接入 Codex 和 Claude Code。

**Tech Stack:** Markdown、Bash、Git

## Global Constraints

- 只读联网查询包括搜索公开信息和查阅官方文档。
- 连接外部环境调试仍需用户批准。
- 安装依赖、联网下载、发布、推送及其他会改变本地或外部状态的操作仍需用户批准。
- 不修改 README、安装脚本或项目模板。
- 不泄露密钥、令牌、凭证或个人隐私。

---

### Task 1: 调整联网查询规则

**Files:**
- Modify: `AGENTS.md:69`

**Interfaces:**
- Consumes: `AGENTS.md` 的“安全与敏感信息”“依赖与第三方文档”“命令与权限”三组规则。
- Produces: 自主只读联网查询与有副作用操作授权之间的明确权限边界。

- [x] **Step 1: 修改安全章节的联网规则**

将原规则：

```markdown
- 不主动连接外部环境或发起联网调用；确有需要时先说明用途并获得用户批准。
```

替换为：

```markdown
- 可自主进行只读联网查询，包括搜索公开信息和查阅官方文档；查询时不得提交或泄露密钥、令牌、凭证、个人隐私等敏感信息。
- 连接外部环境进行调试或执行会改变外部状态的操作，仍需先说明用途并获得用户批准。
```

- [x] **Step 2: 明确第三方文档可自主查询**

将原规则：

```markdown
- 涉及第三方库、框架、SDK、CLI、云服务或 API 的用法、配置、迁移和调试时，在符合联网与权限规则的前提下优先查询最新官方文档。
```

替换为：

```markdown
- 涉及第三方库、框架、SDK、CLI、云服务或 API 的用法、配置、迁移和调试时，可自主联网查询对应版本的最新官方文档。
```

- [x] **Step 3: 检查权限条款一致性**

Run:

```bash
rg -n -C 2 '联网|外部环境|安装依赖|推送' AGENTS.md
```

Expected: 只读查询明确允许；外部环境调试、安装依赖、联网下载、发布和推送仍需用户批准；不存在要求只读查询逐次批准的旧条款。

- [x] **Step 4: 运行文档和安装脚本检查**

Run:

```bash
git diff --check
bash -n install.sh
```

Expected: 两个命令均退出码为 `0`。

- [x] **Step 5: 运行隔离 HOME 安装冒烟测试**

Run:

```bash
tmp_home="$(mktemp -d)"
HOME="$tmp_home" ./install.sh
test -L "$tmp_home/.codex/AGENTS.md"
test -L "$tmp_home/.claude/CLAUDE.md"
test "$(readlink "$tmp_home/.codex/AGENTS.md")" = "$(pwd -P)/AGENTS.md"
test "$(readlink "$tmp_home/.claude/CLAUDE.md")" = "$(pwd -P)/AGENTS.md"
```

Expected: 安装脚本输出 Codex、Claude Code 接入成功，四个 `test` 命令均退出码为 `0`。

- [x] **Step 6: 提交规则和计划**

Run:

```bash
git add AGENTS.md docs/superpowers/plans/2026-07-11-allow-network-lookups.md
git commit -m "docs: 允许自主联网查询"
```

Expected: 生成新的文档提交，工作区无未提交变更。

### Task 2: 推送、合并和本地安装

**Files:**
- Verify: `AGENTS.md`
- Execute: `install.sh`

**Interfaces:**
- Consumes: `codex/allow-network-lookups` 上已验证的规则提交。
- Produces: 更新后的远端 `main`、已删除的开发分支，以及接入新规则的本机 Codex 和 Claude Code 配置。

- [ ] **Step 1: 推送开发分支**

Run:

```bash
git push -u origin codex/allow-network-lookups
```

Expected: 远端开发分支创建成功，并设置 upstream。

- [ ] **Step 2: 合并到主分支**

Run:

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff codex/allow-network-lookups -m "merge: 允许自主联网查询"
```

Expected: `main` 包含设计、计划和规则修改，合并无冲突。

- [ ] **Step 3: 验证合并结果**

Run:

```bash
git diff --check origin/main...main
bash -n install.sh
rg -n -C 2 '联网|外部环境|安装依赖|推送' AGENTS.md
```

Expected: 格式和脚本语法检查通过，权限边界与 Task 1 一致。

- [ ] **Step 4: 推送主分支**

Run:

```bash
git push origin main
```

Expected: 远端 `main` 更新到本地合并提交。

- [ ] **Step 5: 删除开发分支**

Run:

```bash
git branch -d codex/allow-network-lookups
git push origin --delete codex/allow-network-lookups
```

Expected: 本地和远端开发分支均删除，`main` 保留全部提交。

- [ ] **Step 6: 安装到本机并验证**

Run:

```bash
./install.sh
```

Expected: Codex 和 Claude Code 默认目标安装或确认已就绪；目标文件包含或引用当前仓库的 `AGENTS.md`。
