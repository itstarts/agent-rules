# 工作原理

[English](how-it-works.en.md)

本仓库把 `AGENTS.md` 作为唯一规则源，再用软链、Claude import 或拼接文件接入不同工具。

## 文件职责

| 文件 | 职责 |
|------|------|
| `AGENTS.md` | 全局工程规则源 |
| `CLAUDE.md` | 仓库内软链，指向 `AGENTS.md` |
| `project-template.md` | 项目级规则模板 |
| `install.sh` | 本机接入脚本 |
| `codex/agents/` | 版本化 Codex 自定义角色源码 |
| `codex/agents/managed-agents.txt` | 安装器唯一接管范围 |

## 工具文件名差异

不同工具读取的文件名不同：

- Codex 等支持 `AGENTS.md` 的工具可直接读取该文件。
- Claude Code 使用 `CLAUDE.md`，并支持 `@` import。
- Gemini CLI 使用 `GEMINI.md`。

本仓库的安装脚本只负责把全局规则接入 Codex、Claude Code 和 Gemini CLI 的常见全局位置。其它工具如果支持项目根目录的 `AGENTS.md`，通常不需要本仓库做额外桥接；若需要全局配置，应按对应工具文档设置。

## 同步模型

`AGENTS.md` 是唯一源。同步方式取决于安装模式：

- 软链：目标文件指向仓库 `AGENTS.md`。
- Claude import：目标文件包含 `@/path/to/AGENTS.md`。
- 拼接文件：目标文件包含仓库源和本机补充内容。

软链和 import 会随仓库更新自动生效；拼接文件需要重跑 `./install.sh`。

## 全局规则与项目级规则

全局规则适合放跨项目、默认与技术栈无关的工程纪律；广泛可复用且具有明确任务、技术栈和工具触发条件的领域规则也可放在全局规则中。项目级规则用于承载具体业务、技术栈和高风险路径约束。

推荐项目级接入方式：

```bash
cp ~/agent-rules/project-template.md ./AGENTS.md
ln -s AGENTS.md ./CLAUDE.md
```

优先级：

1. 当前用户明确指令
2. 项目级规则
3. 全局规则
4. 默认行为

项目级规则可以细化流程和约束，但不应放宽安全、权限和验证证据要求。

## Codex 角色与事务边界

`AGENTS.md` 是工程规则单源；`codex/agents/` 是 Codex custom agents 的独立单源。源码目录没有项目级 `.codex/agents` 的自动加载语义，只有显式运行 `./install.sh codex-agents` 后，个人 Codex 根目录才通过逐文件绝对软链加载角色。`managed-agents.txt` 防止安装器把目录中未知文件自动纳入管理。

受管理角色的文件名与 TOML `name` 完全一致，并统一使用仅含小写字母、数字和下划线的名称，以便可直接作为 `spawn_agent` 的 agent name 使用。

角色文件只包含 `name`、`description`、`developer_instructions`、`nickname_candidates` 和 `sandbox_mode`。分析与评审角色默认为 `read-only`；明确实现角色默认为 `workspace-write`。父会话实时权限仍会重新施加，因此角色文件表达可审计默认值和职责边界，不是不可绕过的权限边界。

安装事务以 Codex 根目录本身的目录描述符 `root_fd` 获取非阻塞独占锁，不创建持久锁文件。锁内访问从 `root_fd` 逐级使用 no-follow 和 `dir_fd` 操作，并在关键写入前复核根目录设备号和 inode；即使根路径被替换，旧事务也不会写入替代目录。

备份完成并 `fsync` 后，事务才发布 schema-versioned `journal.toml`，随后逐个安装角色、原子替换配置并持久化进度。恢复会先把确定性对象名和输入/输出摘要写入 journal，再创建恢复对象；每次 rename 前复核对象身份。状态从 `install-in-progress` 到 `committed`；异常事务经 `recover-in-progress` 到 `recovered`，成功事务撤销时经 `restore-in-progress` 到 `restored`。目标已经处于事务创建态或事务前态时可幂等续跑，出现第三种状态则停止，避免覆盖并发修改。

## 设计取舍

- 保持 `AGENTS.md` 单源，避免多个工具文件内容漂移。
- 安装脚本默认保守处理既有配置，避免无提示覆盖真实文件。
- 本机专属补充不进仓库，避免把个人机器路径或外部服务约定污染到共享规则。
- 全局规则默认保持技术栈无关；只有跨项目可复用且触发条件明确的领域规则可以条件化加入，具体栈约束仍放到项目级 `AGENTS.md`。
- 安全分析、设计、实现、测试和评审按任务实际风险与明确威胁模型收缩到最小充分范围；没有具体风险和失败后果时，不为理论攻击面增加代码、测试或门禁。
