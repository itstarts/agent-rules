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
| `codex/agent-routing.toml` | 模型别名、角色默认路由、风险升档和运行时功能门禁 |
| `scripts/codex_agent_router.py` | `PreToolUse` 路由 Hook |

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

角色文件包含 `name`、精简的路由 `description`、`developer_instructions`、`nickname_candidates` 和 `sandbox_mode`，不再静态写入 `model` 或 `model_reasoning_effort`。分析与评审角色默认为 `read-only`；明确实现角色默认为 `workspace-write`。父会话实时权限仍会重新施加，因此角色文件表达可审计默认值和职责边界，不是不可绕过的权限边界。模型与 `reasoning_effort` 集中由 `agent-routing.toml` 管理，模型升级时只需更新该文件的别名映射。

## Codex 角色路由

优先选择与当前产物和任务边界最匹配的一个角色：

| 当前任务或产物 | 首选角色 |
|---|---|
| 需求、用户场景、范围和验收标准 | `product_analyst` |
| 架构、模块边界、数据流和公共契约 | `architect` |
| 需求规格或实施计划 | `spec_plan_reviewer` |
| 代码、diff、PR 和实现证据 | `reviewer` |
| 数据模型、迁移、事务、锁和并发 | `data_consistency_reviewer` |
| 重量任务、项目级高风险修改或明确要求的最终门禁 | `final_gate_reviewer` |
| 页面目标、信息架构、线框和状态方案 | `ui_ux_designer` |
| 批准设计与实际截图的视觉验收 | `visual_reviewer` |
| 明确分配且互不重叠的后端或前端实现 | `worker_backend` / `worker_frontend` |
| 测试策略、fixture、测试辅助工具和验证 | `test_engineer` |
| 多模块只读探索或无匹配领域的通用实现 | 内置 `explorer` / `worker` |

单点查找和轻量局部修改直接由主代理完成。一个产物门禁默认只使用一个主要评审角色；只有数据一致性或视觉验收确实构成独立风险时才叠加专项评审。`final_gate_reviewer` 只核对当前任务已触发且适用的门禁，安装、运行或部署证据仅在任务实际涉及这些行为时要求。并行写入只用于文件范围独立、共享契约已冻结的任务。

`tests/fixtures/codex_agent_routing_cases.json` 保存代表性的委派和不委派案例，用于变更角色描述或路由规则时复核角色覆盖、最大子代理数量和内置角色回退边界。

### 角色默认 model + effort

`routine` 派发使用角色默认路由。Sol、Terra、Luna 是稳定的策略层级名，具体模型标识位于 `agent-routing.toml` 的 `[models]`，不会散落在角色文件或 `AGENTS.md` 中。

| 角色 | 模型层级 | `reasoning_effort` |
|---|---|---|
| `architect`、`data_consistency_reviewer` | Sol | `xhigh` |
| `final_gate_reviewer` | Sol | `max` |
| `reviewer`、`spec_plan_reviewer` | Sol | `high` |
| `worker_backend`、`worker_frontend`、内置 `worker` / `default` | Sol | `high` |
| `ui_ux_designer` | Sol | `medium` |
| `test_engineer` | Terra | `high` |
| `product_analyst`、`visual_reviewer`、内置 `explorer` | Terra | `medium` |

这组默认值描述角色通常需要的能力，不代表任务风险。主 Agent 必须再根据实际影响选择路由等级：

| `ROUTING_CLASS` | 行为 |
|---|---|
| `routine` | 使用角色默认值 |
| `complex` | 至少提升到 Sol + `high` |
| `critical` | 至少提升到 Sol + `xhigh`；`final_gate_reviewer` 保留 `max` |
| `mechanical` | 仅对输入输出明确的机械任务使用 Luna + `medium` |

当前运行时动态覆盖只开放 Sol 和 Terra。Luna 虽已配置为策略层级，但尚未加入 `dynamic_tiers`；`mechanical` 派发会被明确拒绝，不会静默改用 Terra。以后运行时支持 Luna 时，更新 `[models].luna` 并把 `luna` 加入 `dynamic_tiers`，无需修改角色文件。

### 自动切换流程与边界

主 Agent 根据任务语义和影响分级，不按“权限”“迁移”等孤立关键词猜测；例如只核对权限标签可以是 `routine`，真正修改权限契约才是 `critical`。派发消息必须包含：

```text
ROUTING_CLASS=critical
ROUTING_REASON=修改公开权限契约并影响既有调用方
```

为兼容尚未升级的既有派发，两个标记都完全缺失时使用角色的 `routine` 默认值，并向当前任务补充 `missing-routing-markers` 提示；只写一个、重复、拼写错误或格式错误都会拒绝，不会把疑似标记静默当作默认值。

`codex_agent_router.py` 在 `PreToolUse` 阶段拦截 `Agent`，读取角色默认值与风险等级，取能力更高的一组配置，并把 `model` 和 `reasoning_effort` 写回派发输入。显式覆盖要求 `fork_turns` 为 `"none"` 或正整数；完整历史 `"all"` 只能继承父 Agent，Hook 会拒绝这种组合。未受管理的 agent type 保持不变。

Hook 只负责当前一次派发，不能在子 Agent 已运行后原地更换模型。子 Agent 发现范围或风险升级时返回 `ESCALATION_REQUIRED`；主 Agent停止沿用旧结果，以更高 `ROUTING_CLASS` 重新派发。这实现了可审计的自动选型和受控升档，但不替代用户批准、权限、安全、测试或评审门禁。

角色安装和路由 Hook 安装都以 Codex 根目录本身的目录描述符 `root_fd` 获取非阻塞独占锁，不创建持久锁文件。两类安装器还会互相检查进行中 journal。锁内访问从 `root_fd` 逐级使用 no-follow 和 `dir_fd` 操作，并在关键写入前复核根目录设备号和 inode；即使根路径被替换，旧事务也不会写入替代目录。

备份完成并 `fsync` 后，事务才发布 schema-versioned `journal.toml`，随后逐个安装角色、原子替换配置并持久化进度。恢复会先把确定性对象名和输入/输出摘要写入 journal，再创建恢复对象；每次 rename 前复核对象身份。状态从 `install-in-progress` 到 `committed`；异常事务经 `recover-in-progress` 到 `recovered`，成功事务撤销时经 `restore-in-progress` 到 `restored`。目标已经处于事务创建态或事务前态时可幂等续跑，出现第三种状态则停止，避免覆盖并发修改。

## 设计取舍

- 保持 `AGENTS.md` 单源，避免多个工具文件内容漂移。
- 安装脚本默认保守处理既有配置，避免无提示覆盖真实文件。
- 本机专属补充不进仓库，避免把个人机器路径或外部服务约定污染到共享规则。
- 全局规则默认保持技术栈无关；只有跨项目可复用且触发条件明确的领域规则可以条件化加入，具体栈约束仍放到项目级 `AGENTS.md`。
- 安全分析、设计、实现、测试和评审按任务实际风险与明确威胁模型收缩到最小充分范围；没有具体风险和失败后果时，不为理论攻击面增加代码、测试或门禁。
