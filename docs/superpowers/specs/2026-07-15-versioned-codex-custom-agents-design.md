# Codex 全局自定义子代理角色治理与安装设计规格

> 状态：用户已批准（`spec_user_approval: approved`）
> 日期：2026-07-15
> 范围：设计已批准，允许据此创建和评审实施计划；计划获用户明确批准前，不得修改角色源码、安装器、CI、本机角色或本机 Codex 配置。
> 独立评审：`APPROVED`；独立 read-only 会话已直接加载角色 TOML，并以必填字段、`sandbox_mode`、有效 sandbox 和独立上下文完成身份与独立性校验。
> 命名兼容修订：用户确认 `spawn_agent` 名称只接受小写字母、数字和下划线后，9 个复合角色名改用下划线；第 3.2 节仍保留修改前本机基线名称，其余角色清单与契约使用当前名称。
> 效率修订：2026-07-18 用户批准“全部优化”，角色描述改为精简路由信息，轻量只读角色采用 `medium` reasoning effort，最终门禁仅核对适用证据，并新增路由评测集；角色数量、sandbox 和并发治理保持不变。

## 1. 背景与目标

当前 Codex 自定义子代理角色只存在于个人 Codex 目录中，没有仓库内的版本控制来源，也没有与全局规则相同等级的安装、冲突处理、测试和生效验证。现有 `install.sh` 只接入 `AGENTS.md`，不会管理 custom agents 或 `[agents]` 并发配置。

本任务要让仓库成为 11 个 Codex 全局角色的唯一源码，并建立以下闭环：

1. 角色源码可评审、可版本控制、无本机私密信息。
2. 安装入口显式，不改变现有 `codex` 安装行为。
3. 安装只接管明确声明的角色文件和 `[agents]` 三个键。
4. 已有配置、未管理角色和未知冲突得到保守处理。
5. 仓库源码、安装结果、Codex 实际加载状态均有验证证据。
6. 角色职责、读写权限、外部操作和委派边界清晰且可自动检查。

## 2. 任务边界与门禁

本任务属于重量任务，原因是它同时影响安装器、个人全局 Codex 配置、子代理写权限和多 Agent 运行边界。流程必须保持：

`规格设计 → 独立评审 → 用户明确批准 → 实施计划 → 独立评审 → 用户明确批准 → 实施 → 验证 → 独立评审 → 最终门禁评审`

当前计划阶段只允许：

- 维护本规格的批准记录；
- 创建、修订实施计划；
- 只读核对仓库、规格、现有实现和验证条件；
- 对实施计划进行独立只读评审。

当前计划阶段禁止：

- 创建 `codex/agents/*.toml`；
- 修改 `install.sh`、CI、README 或安装文档；
- 修改 `$CODEX_HOME` / `~/.codex` 下的任何文件；
- commit、push、merge、rebase、tag 或 release。

## 3. 已确认现状

### 3.1 仓库基线

开始本阶段时已重新核对：

- 分支为 `main`，工作区和暂存区干净；HEAD 为 `0be4ec963fe38f74a6ced2cd998a876a0788f53b`。
- 已在修改前创建开发分支 `codex/versioned-custom-agent-roles`。
- 仓库通过 `AGENTS.md`、`install.sh`、中英文 README 和 `docs/` 管理全局工程规则。
- `install.sh` 当前只支持 `codex`、`claude`、`gemini`；`codex` 目标只管理 `$HOME/.codex/AGENTS.md`。
- CI 当前执行 Bash 语法检查、ShellCheck 和隔离 `HOME` 的规则安装冒烟测试。
- 仓库中已有的 `2026-07-11-allow-network-lookups` 规格和计划与本任务无关，本任务不复用、不修改它们。
- 仓库范围内没有更深层的 `AGENTS.md`。

### 3.2 本机 Codex 基线（脱敏检查）

当前会话未设置 `CODEX_HOME`，因此个人 Codex 根目录使用默认位置。只提取任务相关字段后确认：

- Codex CLI 版本为 `0.144.3`。
- 个人 agents 目录中有 6 个普通 TOML 文件，没有软链：
  - `product-analyst`
  - `architect`
  - `reviewer`
  - `worker-backend`
  - `worker-frontend`
  - `test-engineer`
- 6 个文件均包含 `name`、`description`、`developer_instructions`、`nickname_candidates`、`sandbox_mode` 和 `model_reasoning_effort`。
- 3 个分析/评审角色是 `read-only`；3 个执行/测试角色是 `workspace-write`。
- 本机配置可由 Python 标准库 `tomllib` 完整解析。
- `[features].multi_agent = true`。
- 不存在 `[agents]` 表，也没有文本重复的 `[agents]` 表头。
- 检查未输出模型、Provider、MCP、认证、插件、项目或其他无关配置值。

### 3.3 官方契约

本规格依据 2026-07-15 刷新的官方 Codex manual，相关原始页面为：

- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md)
- [Environment variables](https://learn.chatgpt.com/docs/config-file/environment-variables.md)
- [Config basics](https://learn.chatgpt.com/docs/config-file/config-basic.md)

已确认的官方事实：

1. 个人 custom agents 放在 `~/.codex/agents/`，项目级 custom agents 放在 `.codex/agents/`。
2. 每个独立角色 TOML 必填 `name`、`description`、`developer_instructions`。
3. `nickname_candidates`、`model`、`model_reasoning_effort`、`sandbox_mode`、`mcp_servers` 和 `skills.config` 等字段可选；省略时从父会话继承。
4. Codex 用 `name` 识别角色；文件名与 `name` 相同是推荐约定，但文件名不是身份来源。
5. `[agents]` 支持 `max_threads`、`max_depth`、`job_max_runtime_seconds` 和 `interrupt_message`。
6. 当前默认 `max_threads = 6`、`max_depth = 1`、`interrupt_message = true`；本任务仍显式安装批准后的目标值以形成稳定、可审计的个人配置。
7. `max_depth = 1` 允许根会话创建直接子代理，但禁止子代理继续创建更深层后代。
8. 角色 `sandbox_mode` 可以覆盖角色默认配置，但父会话的实时 sandbox/approval 覆盖会在创建子代理时重新施加。角色文件因此不是不可绕过的权限边界。
9. custom agent 文件是普通 Codex session 配置层，格式仍可能随产品成熟而演进。
10. `CODEX_HOME` 是 Codex 状态根目录，默认是 `~/.codex`；显式设置时该目录必须已经存在。

安装到 `$CODEX_HOME/agents` 是由“个人 agents 位于 `~/.codex/agents`”和“`CODEX_HOME` 替代默认 Codex 状态根目录”共同得出的设计推论。实施阶段必须再用隔离 `CODEX_HOME` 和实际 Codex 运行时验证该推论，不能只靠静态文档宣称生效。

## 4. 总体设计决策

### 4.1 仓库角色源码布局

采用：

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

决策理由：

- `codex/agents/` 明确表示“供 Codex 安装的仓库源码”，不会被维护本仓库的 Codex 会话当作项目级 `.codex/agents/` 自动加载。
- `managed-agents.txt` 每行一个不带扩展名的角色名，是安装器接管范围的唯一索引；安装器不通过“目录内所有文件”隐式扩大接管范围。
- 角色 TOML 是角色内容的唯一源码；索引只声明受管理集合，不复制描述或权限策略。
- 校验要求索引集合与目录中受管理 TOML 集合完全一致，防止遗漏安装或意外接管。

命名规则：

- 文件名为 `<name>.toml`；`name` 只使用小写 ASCII 字母、数字和下划线，以兼容 `spawn_agent` 的名称约束。
- 文件名必须与 TOML 的 `name` 完全一致。
- 角色名全局唯一；所有 `nickname_candidates` 在 11 个受管理角色之间也全局唯一。
- 角色源码不得包含用户名、个人绝对路径、凭证、Provider 地址、MCP 私密配置、内部会话 ID 或临时产物。

### 4.2 不采用 `.codex/agents/`

不把全局角色源码放在仓库 `.codex/agents/`。该目录具有项目级自动加载语义，会导致：

- 维护本仓库时 11 个“全局角色候选”提前成为项目级角色；
- 安装前后测试无法区分项目级加载和个人全局加载；
- 独立评审可能使用到尚未安装、尚未批准的候选角色；
- 角色作用域与仓库源码职责混淆。

### 4.3 安装入口

采用显式入口：

```bash
./install.sh codex-agents
```

兼容性规则：

- `./install.sh` 仍默认安装 `codex claude`，行为不变。
- `./install.sh codex` 仍只管理全局 `AGENTS.md`，不修改角色或 `config.toml`。
- 用户可显式组合 `./install.sh codex codex-agents`。
- `codex-agents` 是唯一允许写入个人 agents 目录和 `[agents]` 三个键的入口。
- 不增加隐式环境变量或默认路径触发角色安装。

否决的方案：

| 方案 | 优点 | 否决理由 |
|---|---|---|
| 扩展现有 `codex` 目标 | 命令少 | 会让既有用户无意间修改全局 `config.toml` 和角色目录，破坏兼容性 |
| 默认安装包含 `codex-agents` | 新机器更省步骤 | 将侵入性配置修改放入无参数默认行为，不符合最小惊讶原则 |
| 完全独立的新安装脚本 | 隔离清晰 | 重复现有路径保护、备份和 CLI 分派逻辑，增加维护面 |

### 4.4 安装目标解析

目标根目录按以下规则确定：

1. `CODEX_HOME` 非空时使用其值；该目录必须已存在，否则停止，不自行创建或猜测。
2. 未设置 `CODEX_HOME` 时使用 `$HOME/.codex`；缺失时可创建。
3. 角色目标为 `<Codex 根目录>/agents`，配置目标为 `<Codex 根目录>/config.toml`。
4. 路径在解析父目录软链后不得位于当前仓库内，防止安装器回写源码。
5. `agents` 目标本身若是软链则停止，避免通过接管整个目录间接覆盖未知位置。
6. 不输出 Codex 根目录中的无关文件或配置内容。

### 4.5 逐文件绝对软链

每个受管理角色使用独立软链指向当前仓库的绝对源码路径，不接管整个 agents 目录。

选择逐文件软链的原因：

- 仓库更新后角色内容立即同步，不需要复制后重复安装。
- 未管理角色可以与受管理角色共存。
- 安装器能够按文件识别、备份和恢复冲突。
- 删除或新增受管理角色时不影响其他个人角色。

不采用整目录软链，因为它会遮蔽或删除用户未受管理的角色。不采用普通复制作为主方案，因为复制会产生仓库与安装结果漂移；复制只用于备份。

绝对软链会在仓库移动后失效。恢复规则为：

- 指向当前源码的软链：已就绪，跳过。
- 指向已不存在目标的损坏软链：preflight 只将其标记为可修复；进入提交阶段后才备份该软链本身、替换为当前源码软链并报告“已修复”。这覆盖仓库移动后的恢复。
- 指向仍存在的其他目标的软链：视为未知所有权冲突，只读报告后停止，不创建备份、不自动接管。
- 普通文件：只有当它是可解析的角色 TOML，且 `name` 与受管理文件名一致时，才视为可迁移的同名旧角色；先备份，再替换为软链。
- 普通文件不可解析、`name` 不匹配，或目标是目录/特殊文件：只读报告后停止，不创建备份、不自动覆盖。

所有目标先完成全局只读 preflight；存在阻断冲突时，不创建备份、不安装新软链、不修改 `config.toml`，因此重复失败运行不会累积文件。只有全部 preflight 通过后才进入受锁保护的提交阶段。

### 4.6 受管理文件的移除

当前任务只新增并管理固定 11 个角色，不删除其他角色。以后若仓库索引移除一个曾受管理角色，安装器不得仅凭“当前索引已无此名字”自动删除本机文件；删除需要独立的显式迁移设计和用户批准。

## 5. `[agents]` 配置治理

### 5.1 唯一受管理值

安装器只管理：

```toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
```

明确不管理：

- `job_max_runtime_seconds`；
- `[agents.<role>]` 等其他角色表；
- `[features]`、模型、Provider、认证、MCP、插件、项目、通知、profile 或其他任何配置。

`[features].multi_agent = true` 若已存在必须原样保留。若显式为 `false`，安装器应停止并提示其与本任务目标冲突，但不得自行改为 `true`。若该键缺失，保持缺失，并由当前 Codex 运行时验证 multi-agent 可用性。

### 5.2 解析与写入策略

`codex-agents` 可要求 Python 3.11+，只使用标准库 `tomllib`；现有 `codex`、`claude`、`gemini` 目标不新增此要求。缺少可用 `tomllib` 时立即停止，不安装依赖、不联网下载解析器。

配置处理顺序：

1. 若 `config.toml` 不存在，准备创建只含上述 `[agents]` 表的新文件。
2. 若存在，必须是普通文件；软链、目录或特殊文件均只读报告后停止，绝不顺链接读取或写入。
3. 写前用 `tomllib` 解析完整文件；解析失败时默认零写入停止，原文件和 Codex 根目录树保持不变。
4. 检查解析后的 `agents` 是否为表，并通过保守的文本结构检查排除重复表、内联表、dotted-key 冲突或无法安全定位的写法。
5. `[agents]` 不存在时，在文件末尾追加一个确定性表。
6. `[agents]` 存在且三个目标值完全兼容时视为已就绪，不改写文件；其他未管理键原样保留并仅报告键名。
7. `[agents]` 存在、受管理键缺失且没有无法安全处理的结构时，只在父 `[agents]` 表头之后、首个真实后续表头之前插入缺失键；`[agents.<role>]` 和其他子表保持原位。不重排、不重写、不删除其他键。
8. 文本定位必须识别 TOML 注释、单/双引号字符串和多行字符串，不能把其中形似 `[agents]` 的文本当作表头；quoted key、dotted key、内联表或任何无法证明父表边界的结构均原样拒绝。
9. 任一受管理键值不兼容时默认零写入停止，不提供静默 `--force`；仅可按第 5.3 节在独立、明确确认的备份阶段创建冲突快照。
10. 若修改混合包含未管理键或子表的 `[agents]` 结构无法证明只影响目标键，默认零写入停止；不借助全量 TOML 重写器格式化整个配置。
11. 写入使用同目录临时文件和原子替换；临时文件权限不宽于原文件，默认新文件权限为 `0600`。
12. 替换前再次解析临时文件，并比较完整解析树：新树只能比旧树多出批准目标的缺失键，其他值必须深度相等。
13. 替换前重新核对原 `config.toml` 的文件身份和原始字节摘要仍与 preflight 一致；发生变化立即停止，不覆盖并发修改。
14. 替换后重新解析最终文件，并检查文本中只有一个真实 `[agents]` 表头。

### 5.3 备份、失败和回滚

- 安装器先执行一次不创建文件、不创建目录的全局只读筛查；发现任何阻断冲突时立即返回，因此默认失败路径保持整个既有 Codex 根目录树零变化。筛查通过后，对已存在的规范化 Codex 根目录以只读、no-follow 方式打开目录描述符 `root_fd`，记录其 `fstat` 设备号和 inode，并用 Python 标准库 `fcntl.flock` 获取 OS 级非阻塞独占锁；不再通过创建持久锁文件实现互斥。未设置 `CODEX_HOME` 且默认根目录不存在时，可在筛查通过后安全创建根目录，再立即打开并锁定其目录描述符；后续失败时只有在该目录仍由本进程创建、路径身份仍匹配且保持空目录时才删除，否则保留并如实报告。
- 取得锁后，角色、配置、备份、journal、恢复和回滚的所有根目录内访问都必须从 `root_fd` 开始，使用 Python `dir_fd`、`follow_symlinks=False`、`O_NOFOLLOW` 及对应的 `openat`/`fstatat`/`renameat`/`unlinkat` 语义逐级操作；不得重新拼接 Codex 根绝对路径后打开或写入目标。每次关键写入前及最终提交前还要将根路径当前 `lstat` 身份与 `fstat(root_fd)` 比较；路径被重命名、替换或消失时立即停止后续提交，只能通过仍锁定的 `root_fd` 对旧 inode 中本事务已创建且身份匹配的对象安全回滚，绝不解析或写入替代路径。即使身份检查后发生竞态，实际写入仍绑定旧 `root_fd`，不会落入新目录。
- 目录锁覆盖“锁内完整 preflight → 变更复核 → 备份与 journal 持久化 → 角色应用 → 配置替换 → 验证 → 回滚/提交”。获得锁后必须从头重做完整 preflight，不能复用锁外筛查结论；锁内发现冲突时不得创建备份、journal、角色目录或配置。无法立即获得锁时不等待、不产生其他变更；运行平台、Python 实现或文件系统没有可验证的目录独占锁与所需 `dir_fd`/no-follow 操作语义时明确失败，不退化为无锁、持久锁文件或按绝对路径写入。
- preflight 记录每个目标的 `lstat` 身份、文件类型、软链文本或普通文件字节摘要。每次备份、替换和回滚前重新核对；对象发生变化时停止，不覆盖并发产生的新状态。
- transaction ID 由安装器生成，格式固定为 UTC 时间戳加 12 位小写十六进制随机串，例如 `20260715T120000Z-a1b2c3d4e5f6`；任何外部输入的 ID 必须完全匹配 `^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$`，禁止路径分隔符、`.` / `..` 和其他字符。
- 每次实际替换普通角色文件或 `config.toml` 前，在 `<Codex 根目录>/.agent-rules-backups/codex-agents/<transaction-id>/` 创建权限为 `0700` 的事务目录。先验证 Codex 根目录属于当前用户，再从其直接子项 `.agent-rules-backups` 起逐级通过 `lstat` 验证为当前用户拥有的真实目录，不允许软链、特殊文件或 group/other 可写；创建和访问使用目录句柄、no-follow 与排他语义，并在每次关键操作前复核。
- 备份文件使用无跟随链接、排他创建，所有者为当前用户，权限不得宽于原文件且绝不宽于 `0600`，不得覆盖已有备份。普通文件按原始字节保存；软链备份以权限为 `0600` 的普通元数据文件保存原文件类型和链接文本，不在备份树中创建可跟随的软链。配置备份和恢复清单中的任意路径规范化后都必须位于当前事务目录内。
- 对提交阶段确定要修复的损坏软链，备份只保存软链本身的类型和链接文本，不读取或复制其目标内容；指向其他有效目标的未知软链仍在只读 preflight 阶段停止。
- 默认阻断 preflight 不创建任何快照。仅当运行在交互 TTY 且用户对当前冲突明确确认“只备份、不安装”时，才进入独立的备份阶段：重新获得/持有同一锁并复核冲突对象未变化，使用内容摘要派生的幂等快照名安全复制后停止，不安装角色、不修改配置。非交互运行或用户未确认时保持零写入。
- 角色和配置应用处于同一安装事务：配置 preflight 先完成；所有会被替换的普通文件/软链先安全复制到事务目录。耐久化顺序固定为：逐个完整写入并 `fsync` 每个普通备份/软链元数据文件，`fsync` 事务目录使备份目录项落盘，再完整写入并 `fsync` schema-versioned journal 临时文件，以原子 rename 发布为 `journal.toml`，最后按从内到外顺序 `fsync` 事务目录及其父目录。只有上述步骤全部成功，journal 状态为 `install-in-progress` 且记录足够恢复的受管理前态和唯一目标集合后，才允许首次目标变更；不得让 durable journal 引用尚未 `fsync` 的备份。
- 每完成一个目标变更，安全更新并持久化 journal 的进度；全部角色链接、配置替换和验证完成后，原子将 journal 状态切换为 `committed` 并再次持久化。成功事务的 journal 即恢复清单，不另行晚写一份可能缺失的清单。
- 任一步失败时，仅当当前目标仍精确等于本事务创建的链接或配置内容时才移除并恢复；若用户或其他进程已修改目标，停止自动回滚、保留备份并报告人工恢复步骤，绝不把较新的状态覆盖成旧备份。
- journal 必须是当前用户拥有、权限为 `0600` 的普通文件且不可为软链；包含 schema version、规范化 Codex 根目录、transaction ID、唯一的受管理目标、安装前文件类型/事务内备份位置、三个受管理键原先是否存在、本事务创建的目标身份、当前操作状态与逐目标进度。显式恢复入口读取时验证 schema、所有者、类型、权限、路径归属、目标无重复，且每个恢复目标精确属于当前 Codex 根目录和仓库受管理集合；任一不满足即零写入拒绝。
- 后续安装扫描历史事务时，仅允许忽略 schema v1、transaction ID 精确匹配且状态为 `recovered` 或 `restored` 的已完成记录；该兼容判断只用于确认历史记录不会阻断新安装，不读取旧恢复语义，也不允许显式 `recover`/`restore` 接受旧 schema。其他 schema 不匹配、无效字段和进行中状态仍零写入拒绝。发现 `install-in-progress`、`recover-in-progress` 或 `restore-in-progress` journal 时不得开始新事务；应报告对应 transaction ID，并要求使用第 5.4 节与 journal 状态匹配的入口续跑。`committed` journal 供正常卸载/恢复使用。
- 安装器输出只包含动作、受管理文件名、备份路径和受管理键名，不打印配置值之外的任何原文；敏感配置不会进入日志。

### 5.4 成功安装后的恢复与卸载

恢复入口固定为：

```bash
./install.sh codex-agents-restore <transaction-id>
```

异常终止恢复入口固定为：

```bash
./install.sh codex-agents-recover <transaction-id>
```

两个入口都是显式操作，不在普通安装或重复安装中隐式执行；没有 transaction ID 时不得猜测“最新”事务。`restore` 接受 `committed` 或同一事务的 `restore-in-progress` journal，`recover` 接受 `install-in-progress` 或同一事务的 `recover-in-progress` journal，并共同遵循：

1. 先完成不写入的 journal、备份和全部目标校验，再获得与安装相同的目录独占锁并从头复核。首次写入前，`restore`/`recover` 分别把 journal 原子持久化为 `restore-in-progress`/`recover-in-progress`，记录固定目标顺序、每个目标的事务创建态、应恢复的事务前态和逐目标进度；该状态转换遵循与安装 journal 相同的临时文件 `fsync`、原子 rename 和目录 `fsync` 协议。
2. 每次续跑时，每个目标只允许处于两种可验证状态之一：尚未撤销的精确事务创建态，或已经撤销的精确事务前态。前者按 journal 执行一次恢复；后者视为上次在“目标替换成功、进度落盘前”中断并直接补记完成。任何第三种状态都在本轮首个写入前整笔拒绝，不覆盖并发或用户修改。
3. 配置恢复允许安装后出现无关字段或其他表的合法变化，并必须原样保留；只要三个受管理键仍等于本事务写入值、父 `[agents]` 表边界仍可安全定位，就只撤销本事务新增的键。受管理键值、父表表示或相关结构发生变化时，整个恢复零写入拒绝。不得用整份 `config.toml` 备份覆盖安装后产生的其他合法修改。
4. 若配置在安装前不存在，只有当前文件仍仅包含该事务创建且未变化的 `[agents]` 内容时才删除整个文件；已有其他配置时只移除本事务新增键，并仅在父表确实为空且没有子表时移除表头。
5. 配置目标在恢复状态转换前记录当前输入身份和确定性恢复输出身份；若配置原子替换后、进度持久化前中断，续跑可由恢复输出身份识别为已完成。进入 `restore-in-progress`/`recover-in-progress` 后若出现未记录的无关配置修改，也按第三种状态安全拒绝并转人工处理，不猜测合并；这不影响首次恢复 preflight 对既有无关配置变化的保留能力。
6. 每完成一个恢复目标，先确认目标精确等于事务前态，再原子持久化对应进度。所有目标完成后，journal 分别转换为 `restored` 或 `recovered` 并持久化；同一入口对进行中状态可幂等续跑，对完成状态只报告已完成，不重复修改。
7. 任一受管理角色目标发生后续修改，或配置的受管理键/父表结构发生后续修改，或备份缺失、journal 不一致、路径/所有者/schema 校验失败或无法证明安全时，整个首次恢复在写入前停止；续跑阶段发现第三种状态时停止后续目标并给出基于已持久化进度和备份的人工步骤，绝不回改已安全恢复的目标或覆盖新状态。
8. 恢复成功后保留恢复清单和备份作为审计证据，不自动删除历史；清理历史备份不在本任务范围内。

## 6. 角色 schema 与共同治理规则

### 6.1 仓库允许字段

当前角色源码允许：

- `name`
- `description`
- `developer_instructions`
- `nickname_candidates`
- `sandbox_mode`
- `model_reasoning_effort`（可选）

虽然官方 schema 允许更多 session 配置键，本任务不在角色中加入 `model`、`mcp_servers`、`skills.config`、网络、approval 或 Provider 配置。

仅 `product_analyst`、`ui_ux_designer` 和 `visual_reviewer` 固定 `model_reasoning_effort = "medium"`。这三个角色属于边界明确的轻量只读工作，成本分层不改变文件权限或业务契约。架构、实现、测试、代码评审、数据一致性和最终门禁角色继续省略该字段并继承父会话，避免降低复杂任务能力或绑定单一 Provider；所有角色均不固定 `model`。

### 6.2 description 契约

每个 `description` 必须用中文优先、保留必要英文关键词，并明确：

- 何时使用；
- 何时不要使用；
- `read-only` 或 `workspace-write`；
- 是否允许修改生产代码；

description 是角色选择依据，不应变成完整操作手册；依赖、长期服务、Git/发布和外部状态等公共边界保留在 `developer_instructions`。单个 description 最多 120 个字符，11 个角色合计最多 1100 个字符。自动校验会检查上述语义标记和长度，但人工评审仍要判断描述是否清晰、无重叠、可用于正确路由。

### 6.3 只读角色共同规则

所有只读角色必须：

- `sandbox_mode = "read-only"`；
- 不修改、创建、删除或重命名文件；
- 不安装依赖；
- 不启动本地长期服务；
- 不 commit、push、merge、tag、release；
- 不改变外部系统、远程资源或 Stitch 资源；
- 只返回分析、方案、finding、证据和待确认问题。

由于父会话实时权限覆盖可能重新施加，`sandbox_mode = "read-only"` 只表示角色默认值和可审计意图。最终验证必须检查实际启动角色的有效权限；主代理也不得在高权限父会话中用只读角色执行写操作。

### 6.4 写角色共同规则

所有写角色必须：

- `sandbox_mode = "workspace-write"`；
- 只修改主代理明确分配的文件、测试和边界；
- 不回滚、覆盖或混入其他执行者的修改；
- 不自行扩大到公共契约、数据、权限、部署、CI 或发布；
- 不自行安装依赖；
- 不自行 commit 或操作分支，除非主代理在用户授权范围内明确要求；
- 不改变外部系统或远程资源；
- 不通过默认值、吞异常、静默降级、放宽校验、跳过状态/权限检查或删除测试掩盖问题；
- 修改后返回准确的文件范围、验证命令、结果和残留风险。

## 7. 11 个角色设计

| 角色 | 默认 sandbox | 何时使用 | 明确排除 | 生产代码 |
|---|---|---|---|---|
| `product_analyst` | read-only | 需求澄清、用户场景、验收标准、范围和非目标 | 架构决策、实现、替用户发明业务规则 | 禁止 |
| `architect` | read-only | 架构、模块边界、数据流、公共契约和技术取舍 | 实施、文件修改、代替用户批准高风险方案 | 禁止 |
| `reviewer` | read-only | 代码、diff、PR 和实现证据评审 | 规格/计划评审、泛泛风格建议、实施 | 禁止 |
| `worker_backend` | workspace-write | 明确分配的后端实现和后端测试 | 前端、部署、CI、发布、无授权的契约/数据/迁移/权限/事务/外部接口变更 | 仅分配范围内允许 |
| `worker_frontend` | workspace-write | 明确分配的前端实现和前端测试 | 发明业务流程/字段/权限/契约、后端、部署、视觉验收 | 仅分配范围内允许 |
| `test_engineer` | workspace-write | 测试策略、fixture、测试辅助工具和相关验证 | 默认不修改生产代码；不通过弱化测试制造通过 | 默认禁止；仅用户和主代理同时明确授权时最小修改 |
| `spec_plan_reviewer` | read-only | 独立评审需求规格和实施计划 | 具体代码评审、实施、批准用户门禁 | 禁止 |
| `final_gate_reviewer` | read-only | 重量任务、项目级高风险修改或明确要求的最终门禁，核对已触发且适用的证据 | 修改候选结果、替代缺失证据 | 禁止 |
| `data_consistency_reviewer` | read-only | 数据模型、迁移、事务、锁、隔离、并发、幂等、重试、回滚和共享状态 | 普通后端实现、直接修改迁移/生产代码 | 禁止 |
| `ui_ux_designer` | read-only | 页面目标、路径、信息架构、视觉方向、Token、线框、响应式、状态和可访问性方案 | 编写生产代码、发明业务字段/权限/流程/契约、未经授权修改 Stitch | 禁止 |
| `visual_reviewer` | read-only | 按批准设计和实际截图核对还原、响应式、状态、键盘、焦点和可访问性 | 修改实现、承担前端实现者职责、重新定义设计 | 禁止 |

### 7.1 现有角色收紧点

`product_analyst`：

- 从“需求研究”收紧到需求澄清、用户场景、验收标准、范围和非目标。
- 明确不做架构决策，不编写实现，不把未知业务规则写成结论。

`architect`：

- 保留只读架构设计职责。
- 明确只产出方案、边界、风险和规则草案，不直接实施。
- 公共契约和数据模型只做分析，不越过用户批准门禁。

`reviewer`：

- description 明确限定代码、diff、PR 和实现证据。
- 规格/计划转交 `spec_plan_reviewer`，最终门禁转交 `final_gate_reviewer`。
- 只报告高置信、可操作 finding，附文件位置、影响和验证缺口。

`worker_backend`：

- 公共契约、数据模型、迁移、权限、事务、外部接口的改变必须已有用户明确批准并由主代理明确分配。
- 不处理前端、部署、CI、发布和无关配置。

`worker_frontend`：

- 不发明业务流程、字段、权限或公共契约。
- 已有批准设计时只负责实现，不同时担任视觉验收者。
- 不修改后端、数据库、部署、CI 或发布内容。

`test_engineer`：

- 默认写范围仅限测试、fixture 和测试辅助工具。
- 发现生产代码问题先返回主代理。
- 只有用户和主代理同时明确授权、且无并行写冲突时，才可修改最小相关生产代码。

### 7.2 新增评审角色输出契约

`spec_plan_reviewer` 的最终结论只能是：

- `APPROVED`：没有阻断问题，规格/计划可进入下一批准门禁；
- `CHANGES_REQUESTED`：存在可修复的明确问题；
- `BLOCKED`：缺少关键输入、权限或独立评审能力，无法形成可靠结论。

`final_gate_reviewer` 只核对当前任务已触发且适用的批准、规格/计划、最新 diff、测试、任务级评审和未解决项。安装、运行、部署或外部生效证据只在任务实际涉及对应行为时要求。全部适用门禁满足后才能输出 `APPROVED`，且不能把“已修改但未验证”当作通过。

### 7.3 暂不新增的角色

不新增：

- `explorer`：Codex 已有内置角色，长期职责重叠。
- `fullstack-worker`：模糊前后端边界并扩大写范围。
- 泛化 `general-reviewer`：与 `reviewer` 重叠。
- 可部署的 `devops-worker`：会把外部状态改变引入全局默认角色。
- 无当前证据支持的性能、安全或发布专项角色。

## 8. 并发、嵌套与委派治理

目标值：

```toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
```

设计含义：

- `max_threads = 4` 是本任务选择的个人全局保守治理上限，用于限制并发资源消耗；不假设根线程是否计数，也不把当前会话暴露的槽位数量推广为 CLI、桌面端和 IDE 的统一运行时事实。
- `max_depth = 1` 允许主代理直接委派，但禁止子代理继续扇出，降低失控、冲突和上下文扩散风险。
- `interrupt_message = true` 保留中断可见证据，便于主代理判断结果是否完整。
- 不设置 `job_max_runtime_seconds`，沿用运行时/单次调用默认值。

委派规则：

1. 每次委派前检查当前会话实际加载的个人 agents 目录。
2. 按 `name` 和 `description` 选择最具体角色。
3. 存在匹配全局角色但当前运行时不能按 name 启动时，默认停止该次委派并报告能力缺口；当前任务的独立评审可使用第 12 节经用户明确批准的“独立 read-only 会话 + 精确角色配置”机制，不得仅靠 task name 冒充角色身份。
4. 只有不存在匹配全局角色时才使用内置或通用角色。
5. 最终报告记录任务、实际 agent name、是否为全局 custom agent、结论和能力缺口。
6. `max_threads` 是上限，不是并行目标；只有边界清楚且无共享写状态的任务才并行。
7. 单点查找和轻量局部修改由主代理直接完成；一个产物门禁默认只使用一个主要评审角色，专项评审只在数据一致性或视觉验收构成独立风险时叠加。
8. 角色描述或路由规则变化时，使用 `tests/fixtures/codex_agent_routing_cases.json` 复核自定义角色、内置 `explorer`/`worker` 回退、不委派边界和最大子代理数量。

## 9. 校验与测试设计

### 9.1 角色静态校验

使用 Python 3.11+ 标准库，不新增第三方依赖。至少检查：

- 每个 TOML 可解析；
- 必填字段存在、类型正确、非空；
- 只出现本规格允许字段；
- 文件名与 `name` 一致；
- `managed-agents.txt` 与 TOML 文件集合完全一致，索引是受管理角色集合的唯一来源；
- role name 唯一，格式符合约定；
- nickname 列表非空、单文件内唯一、跨角色唯一，只含官方允许字符；
- 只读/写角色的 `sandbox_mode` 与职责矩阵一致；
- description 包含使用/排除、sandbox 和生产代码边界，单文件及总量不超过批准上限；
- 可选 `model_reasoning_effort` 只能使用官方允许值，当前轻量角色固定为 `medium`；
- 写角色 instructions 包含不覆盖他人修改、不扩展范围、不自行安装依赖/commit/外部操作、不掩盖问题；
- 只读角色 instructions 包含禁止文件修改、依赖安装、长期服务、Git/发布和外部状态改变；
- 不包含绝对个人路径、用户名、密钥/令牌形态、Provider 地址、会话 ID 或临时路径。
- 路由评测集至少覆盖全部受管理角色、内置回退、无需委派、专项评审和并行写入边界。

### 9.2 安装器测试矩阵

在隔离临时目录中覆盖：

1. 未设置 `CODEX_HOME` 的首次安装。
2. 未设置 `CODEX_HOME` 的重复安装和输出幂等。
3. 显式且已存在的 `CODEX_HOME` 安装。
4. 显式但不存在的 `CODEX_HOME` 拒绝。
5. 11 个逐文件软链均指向仓库对应源码。
6. 未管理角色安装前后内容和文件类型不变。
7. 同名可解析普通角色文件被备份并迁移。
8. 指向当前源码的软链跳过。
9. 损坏软链备份并修复。
10. 指向其他有效目标的软链只读拒绝，原链接保持且重复失败不产生备份。
11. 同名不可解析文件、name 不匹配文件、目录和特殊目标拒绝。
12. 整个 agents 目录为软链时拒绝。
13. `HOME`、`CODEX_HOME` 或父目录软链把目标解析到仓库内时拒绝。
14. 任一 preflight 冲突时不产生部分角色安装或配置修改。
15. 同一 Codex 根目录的两个安装进程通过根目录描述符互斥，锁外筛查不创建持久对象，第二个进程无法立即获得锁时不产生变更；不支持可靠目录锁或所需 `dir_fd`/no-follow 语义的平台明确失败。
16. preflight 后、提交前由外部进程修改角色目标或配置时停止且不覆盖。
17. 事务中途各故障点按目标身份安全回滚；目标已被外部修改时不覆盖新状态。
18. 配置备份目录/文件在不同 `umask` 和原权限下仍分别不宽于 `0700`/`0600`，同名竞争与备份失败不改变原文件。
19. 默认和非交互配置冲突在首次及重复失败后整个既有 Codex 根目录树零变化，且不会出现持久锁文件；交互 TTY 明确确认备份时只生成一个内容一致的幂等快照且不安装。
20. transaction ID 路径穿越、备份祖先软链/目录替换、非当前用户对象、journal 软链/篡改/schema 错误/重复目标/越界路径均零写入拒绝；同时证明普通安装扫描只忽略 schema v1 且 transaction ID 匹配、状态为 `recovered`/`restored` 的两种已完成历史，显式恢复入口仍拒绝这两种旧 schema 记录。
21. 在每个备份写入/`fsync`、journal 发布、角色与配置变更故障点强制终止子进程；只有全部备份先耐久化后才允许 durable `install-in-progress` journal，后续安装拒绝，并可用 `codex-agents-recover` 确定性恢复。
22. 成功安装后 `codex-agents-restore` 覆盖：首次安装、普通文件迁移、损坏软链修复、配置原先不存在、配置无关字段在安装后变化仍成功保留、受管理键/父表结构变化时零写入拒绝。
23. 在 `codex-agents-recover` 和 `codex-agents-restore` 的状态转换、每个目标替换及每次进度持久化故障点强制终止；重复同一命令能够识别事务创建态/事务前态并幂等续跑，最终分别得到 `recovered`/`restored`，第三种目标状态安全拒绝且不覆盖。
24. 在取得目录锁后及每个关键写入点注入“重命名原 Codex 根目录并在原路径创建替代目录”，分别覆盖受管理目标原先存在和不存在的场景；证明旧事务的全部操作始终绑定已锁 `root_fd`、不会写入替代目录、会因根路径身份变化停止并安全回滚，且两个进程不会同时写入同一根目录 inode。

### 9.3 `config.toml` 测试矩阵

至少覆盖：

1. 配置不存在时安全创建，权限不宽于 `0600`。
2. 配置存在但无 `[agents]` 时追加，所有原解析值与原文本主体保持。
3. `[agents]` 已有三个兼容值时完全不改文件。
4. `[agents]` 缺少部分受管理键时只添加缺失键。
5. `[agents]` 包含未管理兼容键、`[agents.foo]` 或多个子表时，缺失键只插入父表正文并保留所有子表。
6. 任一受管理键值冲突时默认零写入拒绝；只有交互 TTY 明确确认的独立备份阶段可创建幂等快照，原配置始终不变。
7. quoted key、dotted key、内联表和无法安全定位的混合结构默认零写入拒绝。
8. 重复 `[agents]`、无效 TOML 或 `agents` 非表时拒绝。
9. `config.toml` 是软链、目录或特殊文件时拒绝且不顺链接写入。
10. `[features].multi_agent = true` 和所有无关配置字段原样保留。
11. `[features].multi_agent = false` 时拒绝且不修改。
12. 修改前后完整解析树除三个目标键外深度相等。
13. 修改后完整 TOML 可解析且只有一个 `[agents]` 表头。
14. 注释、单/双引号字符串和多行字符串中形似 `[agents]` / `[agents.foo]` 的文本不会被识别为表头。
15. preflight 后配置字节变化时停止；回滚前配置不再等于本事务产物时不覆盖。
16. 恢复时无关配置变化被保留并成功撤销本事务新增键；受管理键或父表结构变化时整个恢复零写入拒绝。
17. 输出不包含模型、Provider、MCP、认证或其他无关配置值。

### 9.4 仓库级验证

实施后的最低命令集由批准计划精确化，但必须包含：

```bash
git diff --check
test -z "$(git diff --no-index --check /dev/null docs/superpowers/specs/2026-07-15-versioned-codex-custom-agents-design.md 2>&1)"
git status --short
bash -n install.sh
shellcheck install.sh
python3 -B <role-validator>
python3 -B -m unittest <targeted-tests>
```

若本机没有 ShellCheck，只能记录“本机未执行，依赖 CI”，不能声称通过。

CI 使用系统现有 Bash、ShellCheck 和 Python 标准库，不通过 pip/npm/Homebrew 增加依赖。现有规则安装测试保持，新增角色测试与其隔离，避免故障归因混杂。

## 10. 文档设计

实施阶段同步更新：

- `README.md` / `README.en.md`：只增加简短入口、目标位置和详细文档链接，保持 README 为入口页。
- `docs/install.md` / `docs/install.en.md`：记录 `codex-agents`、Python 前置条件、`CODEX_HOME`、备份、冲突、恢复、卸载和验证命令。
- `docs/how-it-works.md` / `docs/how-it-works.en.md`：解释 `codex/agents` 单源、逐文件软链、角色作用域、`[agents]` 三键所有权、权限继承和门禁角色。
- `.github/workflows/ci.yml`：增加角色 schema 和隔离安装测试，不改变发布行为。

文档不得包含当前机器的用户名、绝对路径、真实 Provider/MCP/认证配置或内部评审会话信息。示例统一使用 `$HOME`、`$CODEX_HOME`、`$REPO` 或 `/path/to/...`。

## 11. 实施与本机验证边界

只有 spec 和 plan 都明确批准后才可实施。实施必须先写失败测试，确认失败原因与本规格一致，再做最小实现。

仓库验证通过后，才运行批准计划规定的实际本机安装。实际安装后至少验证：

- 11 个受管理目标都是指向仓库对应源码的软链，内容一致；
- 未管理角色仍存在且未改变；
- `config.toml` 完整可解析；
- `[agents]` 三个有效值正确，无重复表；
- `multi_agent` 仍有效；
- `codex --strict-config doctor --json` 的实际 `checks.config.load` 为通过；doctor 的其他失败按检查项归因，不把当前版本不存在的 multi-agent check 当作门禁；
- multi-agent 和 custom-agent 可用性通过实际子代理/角色冒烟与可观察结果验证，不由配置文件存在或 doctor 推断；
- 非交互环境的 `TERM=dumb` 不误判为角色配置错误；
- 能按 name 启动一个已安装的只读角色完成最小冒烟评审；不能启动时报告能力缺口，不伪造成功。

实际安装会改变个人 Codex 状态，只能在用户批准实施计划后执行。当前规格阶段不得执行。

## 12. 独立评审与最终门禁

规格阶段：

- 优先使用当前已安装的全局 `architect` 进行独立只读评审。
- 当前运行时能够按 name 启动并回传实际角色身份时，记录该原生身份作为首选证据。
- 当前运行时不能按 name 启动时，使用用户已明确批准的等价门禁：启动全新、ephemeral、有效 sandbox 为 `read-only` 的独立 Codex 会话；该会话直接读取当前个人 `architect.toml`，不与固定哈希或仓库模板比较，允许用户保留本机自定义内容。
- 独立会话使用 `tomllib` 验证 TOML 可解析、`name = "architect"`、`description` 与 `developer_instructions` 是非空字符串、`sandbox_mode = "read-only"`，然后把当前文件的 `developer_instructions` 作为本次评审约束。
- 等价门禁必须记录角色配置来源、必填字段校验、文件声明 sandbox、会话有效 sandbox、独立上下文和评审结论。评审过程中若用户修改角色文件，应放弃旧结论并重新评审；本门禁不通过固定哈希限制合法的本机自定义。
- task name、显示昵称或在提示词中自称 `architect` 均不是证据；没有直接加载并完成上述字段校验的通用代理不得计作独立评审。
- 修复有效 finding 后由同一渠道复审至收敛。

计划阶段：

- 以批准规格为唯一设计依据。
- 优先由 `architect` 评审整体方案，必要时由 `reviewer` 补充检查测试和安装风险。
- 角色尚未由本仓库安装、且运行时仍不能回传原生 named-agent 身份时，可沿用上述独立 read-only 会话机制，但必须分别加载并校验实际使用的角色文件。
- 计划必须通过后再次等待用户明确批准。

实施后：

- `reviewer` 评审最新 diff、安装器与配置安全、测试缺口。
- `data_consistency_reviewer` 仅在实现实际涉及事务/锁/共享状态等一致性逻辑时触发；不机械调用。
- 新角色安装后由 `spec_plan_reviewer` 核对规格、计划和实现范围。
- 最后由 `final_gate_reviewer` 综合全部证据；只有 `APPROVED` 才能报告任务完成。
- 若运行时仍不能回传原生 named-agent 身份，独立评审会话必须直接加载本机安装目标对应的角色 TOML，并另行验证安装目标与仓库源码一致；原生 named-agent 冒烟仍单独执行并如实报告能力缺口，不能用 task name 伪造通过。

## 13. 风险与缓解

### 13.1 风险相称的安全边界

2026-07-15 用户明确批准将全局 `AGENTS.md` 的“风险相称、最小充分安全工作”规则立即应用于本任务。后续安全分析、设计、实现、测试和评审以实际风险、数据敏感度和明确威胁模型为上限：保留路径逃逸、误写/误删、配置损坏、真实崩溃不可恢复、权限边界和公开不可信输入等现实风险的必要校验；不再为同一用户主动篡改本机私有 transaction/journal、使用保留名称伪造 staging、最终指令级 TOCTOU 抢占或其它理论攻击面扩展协议、代码、测试和阻断门禁。

本任务不对角色 TOML 使用固定 SHA-256；角色配置只校验 TOML、必填字段、精确 `name`、允许字段和声明的 `sandbox_mode`。事务中已有的内容摘要仅用于持久化备份/恢复过程中的内容相等性和内容寻址，属于持久化数据完整性用途，不扩展为角色源码签名或本机自定义限制。已有实现和测试无需仅为简化而反向重构；新增校验必须证明现有校验不足以覆盖一个范围内、可复现且后果明确的现实风险。

在此边界下，合法 journal 临时文件导致的真实崩溃不可重试仍是阻断问题；“pre-journal 崩溃后又移动仓库”、同 UID 主动篡改自洽 terminal journal/恢复进度、在校验窗口注入保留名称或非空目录等复合或对抗场景记录为非阻断残余。安全拒绝并保留现场、允许人工清理，不要求继续增加 staging 清单、签名、哈希绑定或更多故障注入。

| 风险 | 缓解 |
|---|---|
| custom agent schema 继续演进 | 允许字段白名单、官方文档复核、严格配置 doctor、实际 named-agent 冒烟 |
| 角色 `read-only` 被父会话实时权限覆盖 | 在描述和 instructions 双重禁止写操作，验证实际权限，不把角色默认值宣称为硬边界 |
| 修改 `config.toml` 破坏私密或未知配置 | 独占锁、变更前复核、`tomllib` 全量解析、仅三键补丁、深度等价比较、安全备份、原子替换、脱敏输出 |
| 同名个人角色被无提示覆盖 | 只有显式 `codex-agents` 接管；可迁移旧角色先备份，未知所有权冲突停止 |
| 仓库移动导致绝对软链损坏 | 识别损坏链接，备份后重建；文档要求重跑安装和验证 |
| 安装进程或恢复/卸载自身异常终止后留下部分状态 | 无持久写入的目录独占锁、所有操作绑定已锁 `root_fd`、根路径身份复核、目标双态复核、备份先于 journal 耐久化、安装与恢复逐步状态持久化、可幂等续跑的 crash recovery 和配置原子替换 |
| 描述过宽或评审角色重叠导致错误委派 | description 长度上限、角色职责矩阵、16 个路由案例、每个产物一个主要评审角色、按 name/description 路由 |
| 测试泄露本机配置 | 全部测试使用隔离 `HOME`/`CODEX_HOME`，禁止读取真实配置，输出只含受管理字段 |

## 14. 非目标

本任务不包括：

- Claude Code 或 Gemini 的角色格式；
- 替换整个 `config.toml`；
- 修改模型、Provider、认证、MCP、插件或 Skill；
- 项目级 `.codex/agents`；
- 通用 full-stack、explorer、部署型运维角色或无证据的专项角色；
- 大范围重写 `AGENTS.md`；
- 修改无关旧规格和计划；
- 自动删除未管理角色或历史备份；
- 发布、push、merge、rebase、tag 或 release。

## 15. 规格批准项

用户批准本规格即表示批准以下设计选择进入实施计划阶段：

1. `codex/agents/` + `managed-agents.txt` 为仓库单一角色来源。
2. 使用显式 `./install.sh codex-agents`，保持现有 `codex` 和默认安装行为兼容。
3. 使用逐文件绝对软链，不接管整个 agents 目录。
4. 只管理 `[agents]` 的 `max_threads = 4`、`max_depth = 1`、`interrupt_message = true`。
5. `codex-agents` 可要求 Python 3.11+ 标准库 `tomllib`，但不安装依赖。
6. 受管理键冲突或无法证明安全的配置结构默认零写入停止，不提供静默强制覆盖；只有交互 TTY 中用户明确确认时才执行独立的“只备份、不安装”阶段。
7. 角色源码不固定 `model`；仅三个轻量只读角色固定 `model_reasoning_effort = "medium"`，其余角色继承父会话。
8. 采用本规格定义的 6 个收紧角色、5 个新增角色和职责矩阵。
9. 安装使用独占事务锁、安全备份和变更前持久化 journal，并分别提供异常终止恢复与 committed 事务卸载入口；恢复只撤销受管理角色目标和本事务新增的三个键，保留无关配置变化。

本规格没有需要在批准前额外选择的开放方案；若独立评审发现阻断问题，将先修订并重新评审，再请求批准。

## 16. 完成标准

规格阶段完成必须同时满足：

- 本规格覆盖源码布局、安装入口、冲突/备份/幂等/恢复、配置合并、角色职责、并发边界、测试、文档、安全和本机验证。
- 独立只读评审为 `APPROVED`。
- 规格独立评审完成并提交用户批准时，本任务产生的变更只包含本规格及创建分支产生的预期状态，没有实现文件或计划文档；进入获准的计划阶段后可新增本规格声明的计划文档。执行期间出现的无关用户变更必须单独识别、保持不动并在交付中说明，不得混入本任务完成声明。
- `git diff --check` 通过；规格尚未跟踪时还必须执行 no-index whitespace 检查，并用 `git status --short` 证明变更集合。
- 向用户提交规格路径、关键选择、评审结论和批准门禁状态。

2026-07-15 用户已明确回复“批准 spec”。规格阶段门禁结果为：

```text
spec_user_approval: approved
plan_path: docs/superpowers/plans/2026-07-15-versioned-codex-custom-agents.md
plan_review_status: APPROVED
plan_user_approval: approved
implementation_gate: open
```

## 17. 当前评审记录

2026-07-15 已确认当前运行时不能回传可验证的原生 named custom-agent 身份。用户随后明确批准调整独立评审门禁：允许全新、ephemeral、有效 sandbox 为 read-only 的独立会话直接加载并校验匹配角色 TOML，以必填字段、文件声明 sandbox、会话有效权限和独立上下文作为评审证据，不再要求原生 named-agent 身份，也不使用固定哈希限制本机自定义。

本次规格评审使用的角色与独立性证据：

```text
reviewer_config: $CODEX_HOME/agents/architect.toml（当前会话未设置 CODEX_HOME 时为默认个人目录）
toml_parseable: PASS
name_equals_architect: PASS
description_nonempty: PASS
developer_instructions_nonempty: PASS
declared_sandbox_mode: read-only
effective_sandbox: read-only
independent_context: true
sha256_check: not-performed
```

独立评审共完成五轮，并由同一等价门禁渠道复审至收敛：

1. 第一轮 `CHANGES_REQUESTED`：8 个安装事务、配置边界和验证问题均已修订。
2. 第二轮 `CHANGES_REQUESTED`：4 个零写入、journal 信任边界、崩溃恢复和配置恢复问题均已修订。
3. 第三轮 `CHANGES_REQUESTED`：3 个锁文件零写入、备份耐久化和恢复续跑问题均已修订。
4. 第四轮 `CHANGES_REQUESTED`：1 个根目录 inode 重绑定导致锁绕过的问题已通过 `root_fd`/`dir_fd` 与故障注入设计修订。
5. 第五轮 `APPROVED`：前述问题全部收敛，未发现新的高置信阻断 finding。

当前门禁状态：

```text
spec_independent_review: APPROVED
spec_user_approval: approved
plan_path: docs/superpowers/plans/2026-07-15-versioned-codex-custom-agents.md
plan_review_status: APPROVED
plan_user_approval: approved
implementation_gate: open
```
