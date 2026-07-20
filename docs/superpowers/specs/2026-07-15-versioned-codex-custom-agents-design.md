# Codex 全局自定义子代理角色治理与安装设计规格

> 状态：已完成，作为历史设计记录保留
> 初始批准：2026-07-15
> 效率修订批准：2026-07-18
> 动态路由修订批准：2026-07-20
> 当前源码：`codex/agents/`、`codex/agent-routing.toml`、`scripts/codex_agents.py`、`scripts/codex_agent_router.py`、`scripts/codex_agent_routing_install.py`、`scripts/validate_codex_agents.py`
> 当前使用文档：`README.md`、`docs/install.md`、`docs/how-it-works.md`
> 压缩说明：本文件保留当前有效设计、关键取舍和恢复契约；原始阶段门禁、逐轮评审记录和完整实施过程可从 Git 历史中的 `adf69d5` 查看。

## 1. 目标与完成状态

本设计让仓库成为 Codex 全局 custom agents 的版本化单一来源，并提供显式、保守、可恢复的本机安装闭环。

已完成结果：

1. 仓库管理 11 个全局角色，角色源码可评审、可版本控制且不含本机私密信息。
2. `./install.sh codex-agents` 是独立入口，不改变无参数、`codex`、`claude` 或 `gemini` 的既有行为。
3. 安装器只接管 `managed-agents.txt` 声明的角色和 `[agents]` 三个键。
4. 角色使用逐文件绝对软链，未管理角色可以共存。
5. 安装事务具备全局 preflight、目录锁、备份、durable journal、回滚、recover 和 restore。
6. 仓库源码、隔离安装、本机安装和 Codex 配置均有自动化验证。
7. 角色名称统一使用小写字母、数字和下划线，可直接作为 `spawn_agent` 的 agent name。

## 2. 范围与非目标

### 2.1 范围

- `codex/agents/` 中的角色源码和受管理索引；
- `install.sh` 的 `codex-agents`、`codex-agents-recover`、`codex-agents-restore` 分派；
- `scripts/codex_agents.py` 的配置合并、安装事务和恢复协议；
- `scripts/validate_codex_agents.py` 的源码与安装结果校验；
- `codex/agent-routing.toml` 的模型层级、角色默认值、风险升档和运行时功能门禁；
- `codex-agent-routing` 的 Hook 安装、recover 和 restore；
- `[agents]` 的 `max_threads`、`max_depth`、`interrupt_message`；
- 中英文安装、工作原理和入口文档；
- 隔离测试、故障注入、CI 和本机生效验证。

### 2.2 非目标

- Claude Code 或 Gemini 的角色格式；
- 项目级 `.codex/agents/`；
- 替换整个 `config.toml`；
- 管理主会话全局默认模型、Provider、认证、MCP、插件、profile 或 Skill；
- 管理 `job_max_runtime_seconds` 或 `[agents.<role>]`；
- 通用 full-stack、部署型运维、安全或发布角色；
- 自动删除未管理角色、已移出索引的旧角色或历史备份；
- 通过固定哈希、签名或同一用户恶意进程对抗扩大本地安装协议。

## 3. Codex 官方契约

本设计依据 Codex custom-agent 和配置契约：

- 个人角色位于 `~/.codex/agents/`，项目角色位于 `.codex/agents/`；
- 独立角色 TOML 必须包含 `name`、`description`、`developer_instructions`；
- `nickname_candidates`、`model`、`model_reasoning_effort`、`sandbox_mode`、`mcp_servers` 和 `skills.config` 等字段可选；
- 省略的可选字段从父会话继承；
- Codex 以 `name` 识别角色，文件名与 `name` 保持一致是仓库约定；
- `[agents]` 支持 `max_threads`、`max_depth`、`job_max_runtime_seconds` 和 `interrupt_message`；
- 父会话的实时 sandbox 和 approval 会在创建子代理时重新施加，角色文件不是不可绕过的权限边界。

官方来源：

- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md)
- [Environment variables](https://learn.chatgpt.com/docs/config-file/environment-variables.md)
- [Config basics](https://learn.chatgpt.com/docs/config-file/config-basic.md)

custom-agent 配置格式仍可能演进，因此仓库保留字段白名单、严格解析、当前 CLI doctor 和实际角色冒烟验证。

## 4. 角色源码与 schema

### 4.1 源码布局

```text
codex/
└── agents/
    ├── managed-agents.txt
    ├── architect.toml
    ├── data_consistency_reviewer.toml
    ├── final_gate_reviewer.toml
    ├── product_analyst.toml
    ├── reviewer.toml
    ├── spec_plan_reviewer.toml
    ├── test_engineer.toml
    ├── ui_ux_designer.toml
    ├── visual_reviewer.toml
    ├── worker_backend.toml
    └── worker_frontend.toml
```

`codex/agents/` 不使用项目级自动加载语义；只有显式安装后，个人 Codex 根目录才加载这些角色。这样可以区分仓库候选源码与真实全局安装结果。

`managed-agents.txt` 是安装器接管范围的唯一索引：

- 每行一个不带扩展名的角色名；
- 必须排序且不能重复；
- 索引集合必须与角色 TOML 集合完全一致；
- 新增或删除角色必须显式修改索引，目录扫描不会自动扩大所有权。

### 4.2 命名和允许字段

- 文件名为 `<name>.toml`；
- `name` 只允许小写 ASCII 字母、数字和下划线；
- 文件名与 `name` 必须完全一致；
- 角色名和全部 `nickname_candidates` 均保持唯一；
- 角色源码不得包含用户名、个人绝对路径、凭证、Provider 地址、内部会话 ID 或临时产物。

允许字段：

```text
name
description
developer_instructions
nickname_candidates
sandbox_mode
```

平台支持可选 `model` 和 `model_reasoning_effort`，但本仓库受管理角色不静态写入这两个字段。模型与 effort 集中由 `codex/agent-routing.toml` 管理：

- `routine` 使用角色默认路由；
- `complex` 至少提升到 Sol + `high`；
- `critical` 至少提升到 Sol + `xhigh`，`final_gate_reviewer` 保留 `max`；
- `mechanical` 仅在运行时支持时使用 Luna + `medium`；当前 Luna 未加入 `dynamic_tiers`，因此明确拒绝而不降级。

具体模型标识只在 `[models]` 中维护。`scripts/codex_agent_router.py` 读取 `managed-agents.txt` 与 policy 的同一角色集合，因此新增索引角色不需要修改 router 的硬编码名单。

### 4.3 description 与 instructions

`description` 只承担路由信息，必须明确：

- 何时使用；
- 何时不要使用；
- `read-only` 或 `workspace-write`；
- 是否允许修改 production code。

公共操作边界放在 `developer_instructions`，不在所有 description 中重复。单个 description 最多 120 个字符，受管理角色合计最多 1100 个字符。

只读角色必须禁止文件写入、依赖安装、长期服务、Git/发布和外部状态改变。写角色只允许修改主代理明确分配的范围，并禁止覆盖其他执行者修改、扩大公共契约或通过弱化校验掩盖问题。

## 5. 角色职责

| 角色 | sandbox | 使用场景 | 明确排除 |
|---|---|---|---|
| `product_analyst` | read-only | 需求、用户场景、范围和验收标准 | 架构、实现、发明业务规则 |
| `architect` | read-only | 架构、模块边界、数据流和公共契约 | 实施、文件修改、替用户批准 |
| `spec_plan_reviewer` | read-only | 需求规格或实施计划评审 | 代码评审、实施、替用户批准 |
| `reviewer` | read-only | 代码、diff、PR 和实现证据 | 规格/计划、最终门禁、实施 |
| `data_consistency_reviewer` | read-only | 数据模型、迁移、事务、锁、并发和恢复 | 普通后端实现 |
| `final_gate_reviewer` | read-only | 重量任务、高风险修改或明确要求的最终门禁 | 修改候选结果、补造证据 |
| `ui_ux_designer` | read-only | 信息架构、视觉方向、线框和状态方案 | production code、发明业务规则 |
| `visual_reviewer` | read-only | 批准设计与实际截图的视觉验收 | 实现、重定义设计 |
| `worker_backend` | workspace-write | 明确分配的后端实现和测试 | 前端、部署/发布、未批准高风险契约 |
| `worker_frontend` | workspace-write | 明确分配的前端实现和测试 | 后端、部署/发布、视觉验收 |
| `test_engineer` | workspace-write | 测试策略、fixture、测试辅助工具和验证 | 默认修改 production code、弱化测试 |

不新增自定义 `explorer`，因为 Codex 已提供内置只读探索角色；没有匹配自定义角色的通用实现使用内置 `worker`。不新增 `fullstack-worker` 或部署角色，避免扩大写入与外部状态边界。

## 6. 路由、并发和门禁

全局治理值固定为：

```toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
```

- `max_threads = 4` 是资源上限，不是并行目标；
- `max_depth = 1` 允许主代理直接委派，但禁止子代理继续扇出；
- `interrupt_message = true` 保留中断的模型可见证据；
- 不设置 `job_max_runtime_seconds`，因为当前没有 `spawn_agents_on_csv` 批处理需求。

委派规则：

1. 单点查找和轻量局部修改由主代理直接完成。
2. 按当前产物选择一个最具体角色；一个产物门禁默认只有一个主要评审者。
3. 数据一致性或视觉验收构成独立风险时，才叠加专项评审。
4. `final_gate_reviewer` 只在重量任务、项目级高风险修改或明确要求时触发，只核对已触发且适用的证据。
5. 并行写入只用于文件范围独立、共享契约已冻结的任务。
6. 没有匹配自定义角色时，使用内置 `explorer` 或 `worker`。
7. `tests/fixtures/codex_agent_routing_cases.json` 保存代表性的委派和不委派案例。

2026-07-20 动态路由修订要求主 Agent 在派发消息中记录 `ROUTING_CLASS` 和 `ROUTING_REASON`。`PreToolUse` Hook 同时接受 canonical `spawn_agent` 与兼容别名 `Agent`，对省略 `agent_type` 的调用使用内置 `default` 路由，并把 `model` 与 `reasoning_effort` 写回派发输入。完整历史 `fork_turns = "all"` 不能显式覆盖模型，因此拒绝；子 Agent 返回 `ESCALATION_REQUIRED` 后由主 Agent 提高等级重新派发。

## 7. 安装设计

### 7.1 显式入口与目标解析

安装入口：

```bash
./install.sh codex-agents
```

恢复入口：

```bash
./install.sh codex-agents-recover <transaction-id>
./install.sh codex-agents-restore <transaction-id>
```

目标解析：

1. `CODEX_HOME` 非空时使用其值，且该目录必须已存在。
2. 未设置 `CODEX_HOME` 时使用 `$HOME/.codex`，缺失时可安全创建。
3. 角色目标为 `<Codex 根>/agents`，配置目标为 `<Codex 根>/config.toml`。
4. 解析后的目标不得位于当前仓库内。
5. `agents` 目录本身若是软链则停止，不沿目录软链接管未知位置。

无参数安装仍默认处理 `codex claude`；`./install.sh codex` 仍只处理全局 `AGENTS.md`。角色和 `[agents]` 配置只能通过显式 `codex-agents` 入口改变。

### 7.2 逐文件软链和冲突

每个受管理角色使用独立绝对软链，不接管整个 `agents` 目录：

- 指向当前源码的软链视为 ready；
- 损坏软链在事务提交阶段备份链接文本后修复；
- 指向其他有效目标的软链视为未知所有权冲突，零写入停止；
- 可解析且 `name` 匹配的普通旧角色先备份再迁移；
- 不可解析、名称不匹配、目录或特殊文件零写入拒绝；
- 未管理角色保持不变。

仓库移动会使绝对软链失效。移动后重新运行 `./install.sh codex-agents` 并执行安装校验。

### 7.3 `config.toml` 合并

安装器只管理 `[agents]` 三个键，不重写整个配置：

- 配置必须是普通文件且可由 `tomllib` 完整解析；
- `[agents]` 不存在时追加确定性表；
- 只补兼容的缺失键，已兼容时不改写；
- 未管理键、子表、注释和其它表保持原位；
- quoted key、dotted key、inline table、重复表或无法证明父表边界的结构安全拒绝；
- 任一受管理值冲突时零写入停止，不提供静默 `--force`；
- 显式 `multi_agent = false` 时停止，不自行改为 `true`；
- 候选配置再次解析，并与原解析树做只增加批准键的深度比较；
- 同目录临时文件使用不宽于原文件的权限，新文件默认 `0600`；
- 原子替换前后复核原文件身份、内容和唯一真实 `[agents]` 表头。

## 8. 事务、回滚和恢复

### 8.1 preflight 与目录锁

安装器先执行零写入筛查。存在任一冲突时，不创建 agents 目录、备份、journal、角色软链或配置。

筛查通过后：

1. 以 no-follow 方式打开规范化 Codex 根目录，获得 `root_fd`。
2. 使用 `fcntl.flock` 获取非阻塞独占锁，不创建持久锁文件。
3. 锁内从头重做完整 preflight，不复用锁外结论。
4. 所有根目录内访问从 `root_fd` 使用 `dir_fd`、`O_NOFOLLOW` 和对应 `*at` 语义完成。
5. 每次关键写入前比较路径当前身份与 `fstat(root_fd)`；根路径被替换时停止后续提交。
6. 平台缺少所需锁、`dir_fd` 或 no-follow 能力时明确失败，不退化为无锁实现。

### 8.2 备份与 durable journal

transaction ID 格式固定为 UTC 时间戳和 12 位小写十六进制随机后缀：

```text
20260715T120000Z-a1b2c3d4e5f6
```

事务目录位于：

```text
<Codex 根>/.agent-rules-backups/codex-agents/<transaction-id>/
```

安全边界：

- 目录必须是当前用户拥有的真实目录，不允许软链、特殊文件或 group/other 可写；
- 事务目录权限不宽于 `0700`，普通备份和 journal 不宽于 `0600`；
- 普通文件保存原始字节，软链保存类型和链接文本，不在备份树中创建可跟随软链；
- 先完整写入并 `fsync` 备份，再持久化并原子发布 schema-versioned `journal.toml`；
- durable journal 发布前不得修改任何目标；
- 每完成一个目标后持久化进度，全部验证通过后状态变为 `committed`；
- 输出只包含受管理动作、名称、备份路径和键名，不打印无关配置内容。

journal 状态：

```text
install-in-progress -> committed
install-in-progress -> recover-in-progress -> recovered
committed -> restore-in-progress -> restored
```

发现任一进行中事务时，普通安装拒绝开始新事务，并报告 transaction ID 和匹配的恢复入口。

### 8.3 回滚、recover 和 restore

失败回滚只处理仍精确等于本事务产物的目标。目标被其他执行者修改时，停止自动回滚并保留备份，不覆盖较新状态。

`recover` 和 `restore`：

1. 必须显式提供 transaction ID，不猜测“最新”事务。
2. 首次写入前验证 journal、备份、目标集合、所有者、权限、schema 和路径归属。
3. 取得与安装相同的目录锁并重新执行完整 preflight。
4. 每个目标只允许处于精确事务创建态或精确事务前态；第三种状态停止。
5. 配置恢复只移除本事务新增键，保留安装后的合法无关配置变化。
6. 受管理键或父表结构被修改时，整个首次恢复零写入拒绝。
7. 每个恢复目标完成后持久化进度，可在目标替换后、进度落盘前再次中断并幂等续跑。
8. 完成后保留 journal 和备份作为审计证据，不自动清理历史。

历史兼容只允许普通安装扫描忽略 schema v1 且状态为 `recovered` 或 `restored` 的已完成记录。显式 `recover`/`restore` 不解释旧 schema；其它 schema 不匹配或进行中旧事务仍安全拒绝。

交互冲突的“只备份、不安装”是独立阶段：只有 stdin/stdout 均为 TTY 且用户明确确认时，才在同一锁内创建内容寻址的幂等快照并停止；默认和非交互冲突保持零写入。

## 9. 校验与测试契约

### 9.1 角色校验

`scripts/validate_codex_agents.py` 至少检查：

- 索引排序、唯一性及与 TOML 集合一致；
- TOML 语法、必填字段、允许字段和文件名/name 一致；
- role name 与 nickname 唯一且格式有效；
- sandbox 与 instructions 边界一致；
- 可选 reasoning effort 使用允许值；
- description 路由标记、单文件 120 字符和总量 1100 字符上限；
- 个人路径、凭证形态、Provider URL 和内部会话形态；
- 安装目标是指向对应仓库源码的精确软链。
- 路由 policy 的模型、运行时层级、风险等级和角色集合与 `managed-agents.txt` 一致。

### 9.2 自动化覆盖

测试使用临时 `HOME` / `CODEX_HOME`，不得读取真实个人配置。覆盖：

- 顶层命令分派及 Python 3.11/`tomllib` 前置条件；
- 首次安装、幂等安装、普通角色迁移、损坏软链修复和未知冲突；
- 配置解析、表边界、兼容补键、冲突和无关字段保留；
- 根目录、agents 目录和目标对象重绑定；
- 锁竞争、pre-journal 与逐目标故障注入；
- durable journal、回滚、recover、restore 和再次中断续跑；
- schema v1 已完成历史兼容与显式旧恢复拒绝；
- 19 个角色路由、风险升档、Luna 门禁、内置回退、不委派和并行边界案例；
- 中英文文档和 CI 契约。

仓库验证入口：

```bash
git diff --check
bash -n install.sh
shellcheck install.sh
python3 -B scripts/validate_codex_agents.py
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

安装后额外验证：

```bash
python3 -B scripts/validate_codex_agents.py --installed-root "${CODEX_HOME:-$HOME/.codex}"
codex --strict-config doctor --json
```

doctor 必须按检查项归因：`config.load` 成功是配置证据；非交互环境的 `TERM=dumb`、凭证或其它独立检查失败不能误判为角色配置错误。

## 10. 风险与取舍

| 风险 | 缓解 |
|---|---|
| custom-agent schema 演进 | 字段白名单、官方文档复核、严格配置 doctor、实际角色冒烟 |
| read-only 默认被父会话权限覆盖 | sandbox 与 instructions 双重表达边界，验证实际权限 |
| 描述过宽或角色重叠 | description 长度上限、职责矩阵、19 个路由案例、每个产物一个主要评审角色 |
| 覆盖同名个人角色 | 仅显式入口接管；可迁移旧角色先备份，未知所有权冲突停止 |
| 配置损坏或丢失无关值 | 完整解析、只补三键、深度等价比较、原子替换和事务恢复 |
| 仓库移动导致软链损坏 | 识别损坏链接，备份并重建；文档要求重跑安装和验证 |
| 安装或恢复中断 | root_fd 锁、durable journal、逐目标进度、双态复核和幂等续跑 |
| 测试泄露本机配置 | 临时 HOME、脱敏输出、禁止测试读取真实配置 |

安全工作按实际风险和失败后果保持最小充分：保留路径逃逸、误写/误删、配置损坏、真实崩溃恢复、权限和并发边界；不为同一用户主动篡改本机私有状态或极端指令级竞态继续增加签名、固定哈希或重复身份协议。

角色 TOML 不使用固定 SHA-256。事务摘要只用于备份/恢复内容相等性和内容寻址。

## 11. 批准与完成记录

批准链：

```text
spec_independent_review: APPROVED
spec_user_approval: approved
plan_review_status: APPROVED
plan_user_approval: approved
implementation_review: APPROVED
final_gate_review: APPROVED
implementation_gate: complete
```

主要完成节点：

- `c50df17`：增加 Codex 全局角色治理与安装实现；
- `e0b1cbe`：修复 Linux inode 复用导致的测试误报；
- `75327a6`：统一 custom-agent 下划线命名；
- `31b5248`：精简角色路由、增加轻量 effort 和路由评测；
- `adf69d5`：上述效率优化合入 `main` 并完成本机安装与 CI 验证。

2026-07-18 完成证据：

- 11 个仓库角色和 11 个本机安装目标通过 validator；
- 完整 Python 测试 93 项通过；
- Bash 语法、ShellCheck、JSON、diff 和 GitHub Actions CI 通过；
- 本机配置保持 `max_threads = 4`、`max_depth = 1`、`interrupt_message = true`、`multi_agent = true`；
- 当前 Codex 协作接口已能按真实 custom-agent type 启动并回传 reviewer，2026-07-15 的 named-agent 能力缺口仅作为历史上下文保留在 Git 历史中。

当前操作和恢复方式以 `docs/install.md` 为准，角色路由和 effort 策略以 `docs/how-it-works.md` 为准；本文件不再作为实施门禁或待办清单。
