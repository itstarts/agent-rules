# Codex 全局自定义子代理角色治理与安装实施计划

> 状态：用户已批准（`plan_user_approval: approved`）
> 日期：2026-07-15
> 依据：已批准的 `docs/superpowers/specs/2026-07-15-versioned-codex-custom-agents-design.md`
> 门禁：用户已批准规格和计划，实施门禁已打开；按本计划执行实现、验证、本机安装和实施后独立评审。
> 后续兼容修订：9 个复合角色按用户要求改为下划线名称，并补充旧连字符已完成 journal 的只读兼容；进行中事务与恢复校验保持严格。
> 后续效率修订：2026-07-18 用户批准精简路由描述、适用门禁、轻量 reasoning effort、路由评测集和索引单源；安装事务、角色数量、sandbox 与并发配置保持不变。

## 1. 目标与实施边界

**目标：** 将 11 个 Codex 全局 custom agents 纳入仓库单一来源，提供显式、安全、幂等、可恢复的安装入口，保守合并 `[agents]` 三个受管理键，并验证仓库源码、本机安装结果和 Codex 实际加载状态。

**实现架构：**

- `install.sh` 继续承担兼容的顶层命令分派；现有无参数、`codex`、`claude`、`gemini` 行为保持不变。
- `scripts/codex_agents.py` 使用 Python 3.11+ 标准库实现角色安装、配置合并、目录锁、备份、journal、恢复和卸载；Bash 不重复实现高风险事务逻辑。
- `scripts/validate_codex_agents.py` 负责仓库角色 schema、职责边界、公共仓库卫生和安装一致性校验。
- `tests/` 使用 `unittest`、临时 `HOME`/`CODEX_HOME`、子进程和 Unix 故障注入验证行为；不读取真实个人配置。
- `codex/agents/` 是 11 个角色及受管理索引的唯一源码；安装采用逐文件绝对软链。

**主代理所有权：**

- 主代理直接负责 `install.sh`、`scripts/codex_agents.py`、配置合并、事务/journal、恢复协议、最终整合和本机安装。
- 如使用子代理，只能分配互不重叠的只读分析、测试草案、文档草案或独立评审；不得让并行执行者共同修改安装器或事务核心。

**非目标：**

- 不修改 Claude Code 或 Gemini 的角色格式。
- 不覆盖整个 `config.toml`，不管理模型、Provider、认证、MCP、插件、Skill、项目或其他配置。
- 不新增依赖，不修改 lockfile。
- 不大范围重写 `AGENTS.md`。
- 不 push、merge、rebase、tag、release 或部署。
- 不删除未受管理角色或历史备份。
- 不在本计划阶段提前实施。

## 2. 预期文件集合

### 新增

- `codex/agents/managed-agents.txt`
- `codex/agents/architect.toml`
- `codex/agents/data_consistency_reviewer.toml`
- `codex/agents/final_gate_reviewer.toml`
- `codex/agents/product_analyst.toml`
- `codex/agents/reviewer.toml`
- `codex/agents/spec_plan_reviewer.toml`
- `codex/agents/test_engineer.toml`
- `codex/agents/ui_ux_designer.toml`
- `codex/agents/visual_reviewer.toml`
- `codex/agents/worker_backend.toml`
- `codex/agents/worker_frontend.toml`
- `scripts/codex_agents.py`
- `scripts/validate_codex_agents.py`
- `tests/test_codex_agent_roles.py`
- `tests/test_codex_agents_dispatch.py`
- `tests/test_codex_config_merge.py`
- `tests/test_codex_agents_install.py`
- `tests/test_codex_agents_recovery.py`
- `tests/test_codex_agents_concurrency.py`
- `tests/test_codex_docs_ci.py`

### 修改

- `install.sh`
- `.github/workflows/ci.yml`
- `README.md`
- `README.en.md`
- `docs/install.md`
- `docs/install.en.md`
- `docs/how-it-works.md`
- `docs/how-it-works.en.md`

### 保持不动

- `AGENTS.md`
- `project-template.md`
- 与本任务无关的旧规格和计划
- 本机未受管理角色
- `config.toml` 中除三个批准键外的全部内容

## 3. 实施任务

### Task 1：建立测试基线和 11 个角色源码

**Files:**

- Create: `tests/test_codex_agent_roles.py`
- Create: `scripts/validate_codex_agents.py`
- Create: `codex/agents/managed-agents.txt`
- Create: `codex/agents/*.toml`（固定 11 个角色）

**接口契约：**

- `managed-agents.txt` 每行一个按字典序排列的角色名，不含扩展名。
- 校验器默认读取仓库 `codex/agents/`；支持 `--source-dir <path>` 和只读的 `--installed-root <Codex root>`。
- 成功退出 `0`；schema、集合、职责或卫生问题退出非零，只输出文件名、字段名和问题类别，不回显完整 instructions 或本机配置。

- [ ] **Step 1.1：先写角色校验失败测试**

覆盖：缺文件、额外文件、TOML 解析失败、必填字段缺失/空值、未知字段、文件名/name 不一致、角色名或 nickname 重复、非法 nickname、sandbox 与职责不一致、description/instructions 缺少边界、个人路径或敏感形态。

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agent_roles.py'
```

Expected: 因校验器和角色源码尚未实现而失败，失败原因与测试目标一致。

- [ ] **Step 1.2：实现最小角色校验器**

只使用 `argparse`、`pathlib`、`re`、`tomllib` 等标准库。允许字段固定为：

```text
name
description
developer_instructions
nickname_candidates
sandbox_mode
model_reasoning_effort  # 仅批准的轻量只读角色可选
```

不得把 `model`、Provider、MCP 或绝对本机路径写入仓库角色。`model_reasoning_effort` 仅按规格批准的轻量角色策略使用；其他角色继承父会话。

- [ ] **Step 1.3：建立角色索引和 11 个 TOML**

11 个角色的字段、职责、边界和指令只依据已批准规格第 6～8 节编写。现有本机角色文件只作为安装迁移目标接受脱敏、只读的文件类型/name 检查，不作为仓库角色源码内容来源；不得把本机自定义或规格外规则带入仓库。

- [ ] **Step 1.4：运行角色定向测试与卫生检查**

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agent_roles.py'
python3 -B scripts/validate_codex_agents.py
private_path="/$(printf '%s' Users)/"
local_user="z$(printf '%s' yy)"
! rg -n "$private_path|$local_user|api[_-]?key|access[_-]?token|bearer|session[_-]?id|localhost:[0-9]+" codex/agents scripts/validate_codex_agents.py tests/test_codex_agent_roles.py
```

Expected: 测试和校验器退出 `0`，卫生扫描无匹配。

### Task 2：先测试并扩展顶层命令分派

**Files:**

- Create: `tests/test_codex_agents_dispatch.py`
- Modify: `install.sh`
- Create: `scripts/codex_agents.py`（仅建立 CLI 骨架和安全的只读参数解析）

**接口契约：**

```bash
./install.sh codex-agents
./install.sh codex codex-agents
./install.sh codex-agents-recover <transaction-id>
./install.sh codex-agents-restore <transaction-id>
```

- `codex-agents` 可与现有普通目标组合。
- `recover`/`restore` 必须独占命令行且精确接收一个 transaction ID。
- 无参数默认仍是 `codex claude`；`./install.sh codex` 仍不安装角色或修改 `config.toml`。

- [ ] **Step 2.1：先写分派失败测试**

覆盖默认行为、现有三个目标、显式组合、恢复参数缺失/过多/非法、恢复命令与普通目标混用、未知目标，以及 Python 版本/tomllib 不满足时只影响 `codex-agents`。

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agents_dispatch.py'
```

Expected: 新入口相关用例失败；现有入口基线用例通过。

- [ ] **Step 2.2：最小修改 `install.sh`**

先完成全量参数校验，再执行任何目标，避免未知参数导致部分安装。`codex-agents*` 仅调用仓库内 Python 辅助脚本，不改变现有函数的行为。

- [ ] **Step 2.3：实现 Python CLI 骨架**

建立 `install`、`recover`、`restore` 子命令，解析并验证 transaction ID；未实现的事务路径必须明确失败，不能静默成功。

- [ ] **Step 2.4：验证分派兼容性**

Run:

```bash
bash -n install.sh
python3 -B -m unittest discover -s tests -p 'test_codex_agents_dispatch.py'
```

Expected: 均退出 `0`；隔离 HOME 中无参数和 `codex` 行为与修改前一致。

### Task 3：实现只读 preflight、Codex 根解析和目录锁

**Files:**

- Modify: `scripts/codex_agents.py`
- Create: `tests/test_codex_agents_install.py`
- Create: `tests/test_codex_agents_concurrency.py`

**核心边界：**

- 显式 `CODEX_HOME` 必须已存在；未设置时可安全创建缺失的 `$HOME/.codex`。
- 锁外筛查零写入；筛查通过后只读打开 `root_fd`，记录设备号/inode，以非阻塞 `flock` 独占。
- 锁内从头重做 preflight。
- 所有根内操作使用 `dir_fd`、`O_NOFOLLOW` 和 `*at` 等价语义；不按绝对路径重新打开目标。
- 任一平台缺少可靠 `flock`、`dir_fd` 或 no-follow 支持时明确失败。

- [ ] **Step 3.1：先写路径和锁失败测试**

覆盖显式缺失 `CODEX_HOME`、根/父目录解析回仓库、根或 `agents` 为软链、非当前用户/危险权限（在平台允许时）、锁竞争、目标存在与不存在时的根目录替换。

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agents_install.py'
python3 -B -m unittest discover -s tests -p 'test_codex_agents_concurrency.py'
```

Expected: 新增用例因路径/锁能力尚未实现而失败；必须核对失败来自目标行为缺失，而不是语法、导入或测试夹具错误。只有确认红灯正确后才进入 Step 3.2。

- [ ] **Step 3.2：实现纯只读筛查与能力检查**

能力检查只判断实际需要的 `os.supports_dir_fd`、`O_NOFOLLOW`、`O_DIRECTORY` 和 `fcntl.flock`，不根据平台名猜测。

- [ ] **Step 3.3：实现 `root_fd` 锁和身份复核**

所有后续帮助函数显式接收目录 fd；关键写前和提交前比较根路径当前身份与 `fstat(root_fd)`。根路径被替换时不得写入替代目录。

- [ ] **Step 3.4：运行路径/并发定向测试**

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agents_install.py'
python3 -B -m unittest discover -s tests -p 'test_codex_agents_concurrency.py'
```

Expected: 路径和锁用例通过；所有测试只操作临时目录。

### Task 4：先测试并实现保守的 `config.toml` 合并

**Files:**

- Create: `tests/test_codex_config_merge.py`
- Modify: `scripts/codex_agents.py`

**受管理键：**

```toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
```

- [ ] **Step 4.1：先写完整配置矩阵失败测试**

覆盖配置不存在、无 `[agents]`、完全兼容、部分缺键、父表后有一个或多个子表、注释/字符串中的伪表头、quoted/dotted/inline 表、重复表、无效 TOML、`agents` 非表、目标为软链/目录/特殊文件、`multi_agent=true/false/缺失`、无关字段深度相等、输出脱敏。

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_config_merge.py'
```

Expected: 合并实现尚缺失的用例失败。

- [ ] **Step 4.2：实现解析、文本定位和候选生成**

先用 `tomllib` 解析完整树，再用保守状态机识别真实表头和父表边界。无法证明只修改三个批准键时拒绝，不使用全量 TOML 重写器。

- [ ] **Step 4.3：实现同目录临时文件和候选配置复核**

临时文件必须通过 `root_fd`/no-follow 在 `config.toml` 同目录排他创建；权限不得宽于原文件，新文件固定为 `0600`。候选写入前必须满足：完整 TOML 可解析、旧解析树除新增批准键外深度相等、只有一个真实 `[agents]` 表头、原配置身份和字节摘要未变化。

- [ ] **Step 4.4：实现替换后的最终配置复核**

原子替换后，通过 `root_fd` 重新安全打开最终普通文件，重新解析完整 TOML，验证最终解析树等于已批准候选且文本中只有一个真实 `[agents]` 表头。测试覆盖临时文件创建、权限设置、候选复核、原子替换、最终重开/解析和唯一表头每个失败点；任一失败按 journal 和目标身份规则安全停止/回滚。

- [ ] **Step 4.5：运行配置定向测试**

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_config_merge.py'
```

Expected: 全部退出 `0`，无测试读取真实 `$HOME/.codex/config.toml`。

### Task 5：实现安装事务、备份和 durable journal

**Files:**

- Modify: `scripts/codex_agents.py`
- Modify: `tests/test_codex_agents_install.py`
- Modify: `tests/test_codex_agents_concurrency.py`

**状态机：**

```text
preflight-only
  -> install-in-progress
  -> committed
```

- [ ] **Step 5.1：先写安装事务失败测试**

覆盖首次安装、重复安装、普通同名角色迁移、当前源码软链跳过、损坏软链修复、未知有效软链拒绝、不可解析/name 不匹配/目录/特殊目标拒绝、未管理角色不变、配置冲突零写入、交互确认只备份不安装、并发目标变化不覆盖，以及发现 `install-in-progress`、`recover-in-progress`、`restore-in-progress` journal 时拒绝新事务。

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agents_install.py'
python3 -B -m unittest discover -s tests -p 'test_codex_agents_concurrency.py'
```

Expected: 新增事务用例因备份/journal/安装状态机尚未实现而失败；失败原因必须与批准规格一致，不能是测试基础设施错误。只有确认红灯正确后才进入 Step 5.2。

- [ ] **Step 5.2：实现安全事务目录和 transaction ID**

transaction ID 严格匹配批准正则。备份祖先、事务目录、journal 和所有恢复路径都通过 `root_fd` 逐级验证所有者、类型、权限、no-follow、唯一性和路径归属。

普通安装的锁外筛查和锁内完整 preflight 都必须查找并验证进行中 journal；发现 `install-in-progress`、`recover-in-progress` 或 `restore-in-progress` 时，在任何新事务写入前拒绝，脱敏报告 transaction ID 和与状态匹配的 recover/restore 命令。故障注入后再次运行普通安装必须证明整个 Codex 根零写入。

- [ ] **Step 5.3：实现交互冲突的独立幂等快照协议**

默认和非交互冲突始终零写入。只有 stdin/stdout 均为交互 TTY、用户对当前冲突明确确认“只备份、不安装”时，才在同一目录锁内从头复核冲突对象，并用冲突对象身份和内容摘要派生确定性快照名排他创建快照；重复运行复用已验证的同一快照，不累积备份。该阶段始终不创建安装 journal、不安装角色、不修改配置。测试通过函数级注入模拟 `isatty` 和确认输入，不增加生产测试开关。

- [ ] **Step 5.4：实现备份先于 journal 的耐久化顺序**

严格执行：

```text
逐个写入并 fsync 备份文件
-> fsync 事务目录
-> 写入并 fsync journal 临时文件
-> 原子 rename 发布 journal
-> 从内到外 fsync 目录链
-> 首次目标变更
```

软链备份保存为普通元数据文件，不在备份树创建可跟随链接。

- [ ] **Step 5.5：实现角色软链和配置原子替换**

每步写前复核根和目标身份；配置替换使用 Task 4 的同目录临时文件、权限和最终重开校验协议；每步完成后原子持久化 journal 进度；最终验证后转换为 `committed`。失败回滚只能触碰仍精确等于本事务产物的目标。

- [ ] **Step 5.6：实现无生产后门的故障注入测试夹具**

测试通过导入模块并向事务运行器注入回调，在 Unix fork 子进程中于备份、`fsync`、journal 发布、角色替换、配置替换和进度持久化点调用 `os._exit`；生产 CLI 不暴露测试环境变量或隐藏 failpoint。

- [ ] **Step 5.7：运行安装和故障注入测试**

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agents_install.py'
python3 -B -m unittest discover -s tests -p 'test_codex_agents_concurrency.py'
```

Expected: 全部通过；durable journal 永不引用未持久化备份。

### Task 6：实现可幂等续跑的 recover 和 restore

**Files:**

- Create: `tests/test_codex_agents_recovery.py`
- Modify: `scripts/codex_agents.py`
- Modify: `tests/test_codex_agents_dispatch.py`

**状态机：**

```text
install-in-progress -> recover-in-progress -> recovered
committed           -> restore-in-progress -> restored
```

- [ ] **Step 6.1：先写恢复状态机失败测试**

覆盖 ID 缺失/非法、journal schema/所有者/权限/路径/重复目标错误、备份缺失、目标处于事务创建态/事务前态/第三种状态、配置无关变化保留、受管理键或父表变化拒绝、配置原先不存在，以及完成状态重复调用。restore 场景必须逐项包含：首次安装、普通角色文件迁移、损坏软链修复、部分受管理键原先已存在、父表有未管理键、父表有子表、只有父表确实为空且无子表时移除表头。

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agents_recovery.py'
python3 -B -m unittest discover -s tests -p 'test_codex_agents_dispatch.py'
```

Expected: 新增恢复用例因状态机尚未实现而失败；核对失败来自 recover/restore 行为缺失。只有确认红灯正确后才进入 Step 6.2。

- [ ] **Step 6.2：实现恢复前全局只读校验**

install/recover/restore 共用同一锁协议：先完成锁外零写入筛查，再打开并锁定 `root_fd`，锁内从头重做完整 preflight；所有访问绑定 `dir_fd`/no-follow，关键写前复核根路径身份。首次恢复在任何写入前验证全部目标；只有两种允许状态。配置先根据当前合法输入生成确定性恢复输出，并将输入/输出身份持久化到 journal。

未设置 `CODEX_HOME` 且默认根由本进程创建后，任何 install/recover/restore 失败都只能在根目录路径身份仍等于已锁 `root_fd`、仍由本进程创建且为空时删除；否则保留并脱敏报告。增加创建后锁失败、preflight 失败和根路径替换测试。

- [ ] **Step 6.3：实现逐目标幂等续跑**

目标仍是事务创建态时恢复一次；已是事务前态时补记进度；第三种状态停止且不覆盖。journal 必须记录每个角色的精确安装前类型/字节或链接文本，以及三个受管理键各自在安装前是否存在。restore 只删除本事务新增键，恢复精确角色前态；受管理结构变化时整笔零写入拒绝。每步确认目标后再持久化进度，最终转换为完成状态。

- [ ] **Step 6.4：对恢复每个写点执行强制终止测试**

使用与 Task 5 相同的注入夹具覆盖状态转换、每个目标替换、配置替换和每次进度持久化；重复同一命令必须在无并发修改时最终收敛。

- [ ] **Step 6.5：运行恢复定向测试**

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_agents_recovery.py'
python3 -B -m unittest discover -s tests -p 'test_codex_agents_dispatch.py'
```

Expected: 全部通过；恢复不会用旧配置备份覆盖安装后的无关合法变化。

### Task 7：完成隔离安装集成、并发和安全回归测试

**Files:**

- Modify: `tests/test_codex_agents_install.py`
- Modify: `tests/test_codex_agents_concurrency.py`
- Modify: `tests/test_codex_config_merge.py`

- [ ] **Step 7.1：覆盖隔离 HOME 与显式 CODEX_HOME**

至少验证首次安装、重复安装、11 个软链目标、未管理角色保留、无关配置保留、兼容 `[agents]` 幂等，以及显式不存在 `CODEX_HOME` 拒绝。

- [ ] **Step 7.2：覆盖双进程与根目录重绑定**

用进程间事件协调两个安装进程，验证同一根 inode 只有一个写者；在每个关键点重命名根目录并放置替代目录，证明旧事务绝不写入替代目录并按 journal 安全停止/恢复。

- [ ] **Step 7.3：覆盖权限、umask 和输出脱敏**

验证事务目录不宽于 `0700`、备份/journal/config 不宽于 `0600`，且输出不包含配置原文、模型、Provider、MCP、认证或其他无关值。

- [ ] **Step 7.4：运行全部 Python 测试**

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

Expected: 全部通过，无真实个人目录写入。

### Task 8：更新 CI 和中英文文档

**Files:**

- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/install.md`
- Modify: `docs/install.en.md`
- Modify: `docs/how-it-works.md`
- Modify: `docs/how-it-works.en.md`
- Create: `tests/test_codex_docs_ci.py`

- [ ] **Step 8.1：先写文档/CI 契约检查**

所有本任务的文档/CI 契约断言统一写入 `tests/test_codex_docs_ci.py`：要求 CI 调用角色校验和全部 unittest，README 保持入口页，详细安全/恢复语义存在于安装和工作原理文档，中英文对应入口和关键命令一致。不得把这些断言分散到本步骤未执行的其他测试文件。

Run:

```bash
python3 -B -m unittest discover -s tests -p 'test_codex_docs_ci.py'
```

Expected: 新增文档/CI 契约用例因 CI 和文档尚未更新而失败；核对失败定位到缺失入口或说明。只有确认红灯正确后才进入 Step 8.2。

- [ ] **Step 8.2：扩展 CI**

保留现有 Bash/ShellCheck/规则安装冒烟；增加 Python 角色校验和 `unittest discover`。不使用 pip/npm/Homebrew，不改变发布行为。

- [ ] **Step 8.3：更新 README 中英文入口**

只增加 `codex-agents` 简介、显式安装命令、目标目录和详细文档链接，不把事务细节堆入 README。

- [ ] **Step 8.4：更新安装和工作原理文档**

中英文同步记录 Python 3.11+、`CODEX_HOME`、逐文件软链、受管理索引、三个配置键、冲突、只备份阶段、transaction ID、recover/restore、权限、仓库移动和验证命令。

- [ ] **Step 8.5：运行文档和 CI 静态检查**

Run:

```bash
git diff --check
bash -n install.sh
python3 -B scripts/validate_codex_agents.py
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

Expected: 全部退出 `0`。

### Task 9：完成仓库级验证

**Files:**

- Verify: 本计划列出的全部新增和修改文件

- [ ] **Step 9.1：检查实际 diff 和范围**

Run:

```bash
git status --short
git diff --stat
git diff --cached --stat
git diff --check
git diff --cached --check
git diff -- AGENTS.md project-template.md
git diff --cached -- AGENTS.md project-template.md
git ls-files --others --exclude-standard
```

然后使用同一个 Bash 进程合并三类路径并与统一 allowlist 比较：

```bash
allowed=(
  .github/workflows/ci.yml
  AGENTS.md
  README.en.md
  README.md
  codex/agents/architect.toml
  codex/agents/data_consistency_reviewer.toml
  codex/agents/final_gate_reviewer.toml
  codex/agents/managed-agents.txt
  codex/agents/product_analyst.toml
  codex/agents/reviewer.toml
  codex/agents/spec_plan_reviewer.toml
  codex/agents/test_engineer.toml
  codex/agents/ui_ux_designer.toml
  codex/agents/visual_reviewer.toml
  codex/agents/worker_backend.toml
  codex/agents/worker_frontend.toml
  docs/how-it-works.en.md
  docs/how-it-works.md
  docs/install.en.md
  docs/install.md
  docs/superpowers/plans/2026-07-15-versioned-codex-custom-agents.md
  docs/superpowers/specs/2026-07-15-versioned-codex-custom-agents-design.md
  install.sh
  scripts/codex_agents.py
  scripts/validate_codex_agents.py
  tests/test_codex_agent_roles.py
  tests/test_codex_agents_concurrency.py
  tests/test_codex_agents_dispatch.py
  tests/test_codex_agents_install.py
  tests/test_codex_agents_recovery.py
  tests/test_codex_config_merge.py
  tests/test_codex_docs_ci.py
)
actual="$({
  git diff --name-only
  git diff --cached --name-only
  git ls-files --others --exclude-standard
} | sort -u)"
expected="$(printf '%s\n' "${allowed[@]}" | sort -u)"
test "$actual" = "$expected"
```

Expected: staged、unstaged 和 untracked 三类路径规范化合并后，精确等于第 2 节文件、本任务规格、本计划及用户后续明确批准的 `AGENTS.md` 规则修改组成的 allowlist；文件处于哪一种 Git 状态不影响合法性，也不要求 staging 或 commit。`project-template.md` 和旧规格/计划无本任务 diff；出现额外文件或缺失预期文件时命令失败。

- [ ] **Step 9.2：逐个检查所有未跟踪文件的空白错误**

Run:

```bash
failed=0
while IFS= read -r -d '' file; do
  output="$(git diff --no-index --check /dev/null "$file" 2>&1)" || rc=$?
  rc="${rc:-0}"
  if [[ "$rc" -gt 1 || -n "$output" ]]; then
    printf '%s\n' "$output"
    failed=1
  fi
  unset rc
done < <(git ls-files --others --exclude-standard -z)
test "$failed" -eq 0
```

Expected: 每个未跟踪文件只有“文件与 `/dev/null` 不同”产生的允许退出码 `1`，没有 whitespace diagnostic；任何输出或退出码大于 `1` 都失败。若系统 Git 被只读环境的临时缓存告警污染，使用仓库环境中已验证的 fallback Git 复核并记录原因，不能把污染结果声称为通过。

- [ ] **Step 9.3：运行最低完整验证集**

Run:

```bash
bash -n install.sh
python3 -B scripts/validate_codex_agents.py
python3 -B -m unittest discover -s tests -p 'test_*.py'
if command -v shellcheck >/dev/null 2>&1; then shellcheck install.sh; else echo 'ShellCheck unavailable; rely on CI'; fi
```

Expected: Bash、角色校验和 unittest 通过；ShellCheck 实际执行时必须通过，缺失时明确记录为未执行。

- [ ] **Step 9.4：运行公共仓库卫生检查**

Run:

```bash
private_path="/$(printf '%s' Users)/"
local_user="z$(printf '%s' yy)"
session_prefix="019$(printf '%s' f)"
! rg -n "$private_path|$local_user|api[_-]?key|access[_-]?token|bearer|session[_-]?id|${session_prefix}[0-9a-f-]+" codex scripts tests README.md README.en.md docs/install.md docs/install.en.md docs/how-it-works.md docs/how-it-works.en.md
```

Expected: 无匹配；如出现用于说明禁止事项的通用术语，收紧检查规则并增加回归测试，不通过删除有效安全文案制造通过。

### Task 10：经批准后执行本机安装与运行时验证

**前置门禁：** 只有本计划独立评审为 `APPROVED` 且用户明确回复“批准 plan”或等价表述后执行。

**Files/State:**

- Execute: `install.sh`
- Modify only through approved installer: `$CODEX_HOME/agents` 或默认个人 agents 目录，以及对应 `config.toml` 的三个受管理键

- [ ] **Step 10.1：安装前做脱敏只读基线检查**

只记录受管理角色名、目标文件类型、三个受管理键是否存在和 `multi_agent` 状态；不输出其他配置值。

- [ ] **Step 10.2：执行显式安装**

Run:

```bash
./install.sh codex-agents
```

Expected: 11 个受管理目标安装或确认已就绪；未管理角色保持；配置只新增缺失的批准键；输出给出 transaction ID 和安全备份位置但不泄露配置内容。

- [ ] **Step 10.3：验证安装与仓库源码一致**

Run:

```bash
python3 -B scripts/validate_codex_agents.py --installed-root "${CODEX_HOME:-$HOME/.codex}"
```

Expected: 11 个受管理目标均为指向当前仓库对应源码的软链；内容、name 和 sandbox 一致；未管理角色不被判为错误。

- [ ] **Step 10.4：验证配置和 Codex 加载**

Run:

```bash
codex --strict-config doctor --json
```

Expected: `checks.config.load` 通过；其他 doctor 失败按实际检查项归因，不把网络、认证或 `TERM=dumb` 误判为配置失败。

另用脱敏 Python 检查确认：

```text
max_threads = 4
max_depth = 1
interrupt_message = true
multi_agent 仍有效
只有一个真实 [agents] 表头
```

- [ ] **Step 10.5：执行 named-agent 最小冒烟**

优先按 name 启动一个已安装只读角色；记录实际角色身份和结果。若当前接口仍不能选择或回传 named-agent 身份，明确记录能力缺口，不以 task name 或显示昵称伪造通过。

### Task 11：实施后独立评审与最终门禁

**前置：** 仓库验证和本机安装验证已取得实际证据。

- [x] **Step 11.1：代码与安装安全评审**

使用实际安装的 `reviewer` 对最新 diff、安装器、配置安全、测试缺口和失败路径做独立只读评审。若原生 named-agent 选择仍不可用，按已批准等价门禁直接加载并校验安装目标对应 TOML。

- [x] **Step 11.2：一致性专项评审**

由于实现包含锁、journal、崩溃恢复和共享状态，使用 `data_consistency_reviewer` 复核锁范围、持有时长、持久化顺序、状态机、幂等性和并发竞态。

- [x] **Step 11.3：规格与计划一致性评审**

使用 `spec_plan_reviewer` 对批准规格、批准计划、最新 diff 和验证证据做只读核对。

- [x] **Step 11.4：修复并复审至收敛**

每个有效 finding 先写/补失败测试，再最小修复，重跑受影响测试和最低完整验证集，并由同一渠道复审。

- [x] **Step 11.5：最终全量门禁**

使用 `final_gate_reviewer` 综合核对范围、已触发且适用的批准记录、diff、测试、ShellCheck/CI 状态、能力缺口和未解决项；本任务实际涉及本机安装和运行时冒烟，因此同时核对对应证据。只有结论为 `APPROVED` 才能报告实施完成。

## 4. 计划阶段完成条件

当前计划阶段完成必须同时满足：

- 本计划只以已批准规格为设计依据。
- 准确列出文件、公共命令、TDD 顺序、事务边界、恢复协议、验证命令和评审门禁。
- 独立 read-only `architect` 评审为 `APPROVED`。
- 本阶段没有创建角色源码、测试、脚本实现或本机安装变更。
- staged/unstaged `git diff --check`、精确未跟踪文件集合校验及全部未跟踪文件逐文件 no-index whitespace 检查通过。
- 用户批准计划后的实施阶段状态为：

```text
spec_user_approval: approved
spec_independent_review: APPROVED
plan_review_status: APPROVED
plan_user_approval: approved
implementation_gate: open
```

## 5. 当前评审记录

本计划使用已批准的等价独立评审门禁：全新、ephemeral、有效 sandbox 为 read-only 的独立会话直接加载并校验当前 `architect.toml`。身份与独立性只校验 TOML 可解析、`name = "architect"`、非空 `description`、非空 `developer_instructions`、文件声明 `sandbox_mode = "read-only"`、会话有效 sandbox 和独立上下文；未执行 SHA-256 校验。

独立评审共完成三轮，并由同一等价门禁渠道复审至收敛：

1. 第一轮 `CHANGES_REQUESTED`：8 个设计输入、TDD 红灯、配置替换、交互快照、进行中事务、统一锁、精确恢复和未跟踪文件验证问题均已修订。
2. 第二轮 `CHANGES_REQUESTED`：2 个文档/CI 契约测试入口和 Git 状态无关 allowlist 问题均已修订。
3. 第三轮 `APPROVED`：前述 10 项问题全部收敛，未发现新的 finding。

评审完成时的证据与边界：

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
plan_review_status: APPROVED
findings: []
```

2026-07-15 用户已明确回复“批准 plan”。实施门禁已打开；本机缺少 ShellCheck，留待 CI 或具备 ShellCheck 的环境验证。

## 6. 当前实施与验证记录

2026-07-15 已按批准计划完成候选实现、真实个人 Codex 安装、实施后独立评审和最终门禁。脱敏证据如下：

- 仓库角色校验：11 个受管理角色通过 schema、职责、sandbox、nickname 和公共仓库卫生检查。
- 自动化测试：风险边界收缩后，`python3 -B -m unittest discover -s tests -p 'test_*.py'` 通过，共 81 个测试方法及其子用例组合；新增覆盖合法 journal 临时文件崩溃重试、Python 3.11/`tomllib` 前置条件和历史 schema v1 已完成记录兼容，不包含超出批准威胁模型的新增对抗测试。
- 静态检查：`bash -n install.sh`、Python AST parse、tracked/staged diff whitespace、32 个路径统一 allowlist、全部未跟踪文件 no-index whitespace 检查和公共仓库卫生检查通过。
- 隔离运行时：显式 `CODEX_HOME` 安装、11 个软链验证和 Codex `config.load` 通过；隔离 doctor 的凭证与终端问题不属于配置失败。
- 真实安装：11 个受管理目标均为指向当前仓库源码的软链；`max_threads = 4`、`max_depth = 1`、`interrupt_message = true`、`multi_agent = true` 和唯一真实 `[agents]` 表头已脱敏核验。
- 真实 Codex doctor：`config.load = ok`；总体非零仅来自当前非交互终端检查。
- ShellCheck：本机不可用，尚未执行；CI 已保留 ShellCheck 并新增角色校验与 Python 测试。
- 原生 named-agent 冒烟：当前 Sub Agent 接口仍只暴露 `task_name`，不能选择或回传 `agent_name` / `agent_type`；按批准规则记录为能力缺口，不以 task name 或昵称伪造通过。
- 本机安装 transaction ID、个人目录和其它配置值只保留在本机会话证据中，不写入仓库文档。

当前独立评审状态：

```text
implementation_review: APPROVED
data_consistency_review: APPROVED
spec_plan_review: APPROVED
final_gate_review: APPROVED
implementation_gate: complete
```

实施后第一轮三个独立 read-only 评审均为 `CHANGES_REQUESTED`。有效 finding 已按测试先行完成修订：

1. 角色安装和普通文件/软链恢复改为同文件系统临时对象加原子 rename，消除 unlink/create 缺失窗口。
2. 角色、配置和 `agents` 目录记录并复核 preflight 与事务创建态的设备号/inode，覆盖同内容 ABA 替换和目录重绑定。
3. 备份与初始 journal 在隐藏 staging 事务目录中耐久化，正式 transaction ID 目录只在 journal 完整后原子发布；pre-journal 失败不会阻断后续安装。
4. 配置恢复在首次写入前持久化固定输入和确定性输出身份，覆盖配置替换后、进度落盘前的幂等续跑。
5. 恢复把本事务创建且已删除的 `agents` 目录识别为合法前态，可在最终状态落盘前再次中断后续跑。
6. journal 增加严格状态和关键字段类型/身份校验，未知状态在新事务写入前拒绝。
7. 增加锁外只读筛查和锁内完整复核，并覆盖默认根创建后打开/锁阶段失败的安全清理。
8. TOML 表头判断改为精确首段匹配，合法 `[myagents]` / `[user_agents.settings]` 不再误拒绝。
9. Python 导入禁用仓库内 bytecode 缓存生成，并清理评审期间产生的临时 `.pyc`。

实施后第二轮三个独立 read-only 评审仍为 `CHANGES_REQUESTED`。新增和未完全收敛的 finding 已继续按测试先行修订：

1. 恢复计划先把确定性对象名、输入/输出摘要和 `*-in-progress` 状态持久化，再幂等创建对象并逐项记录身份；对象创建后、身份落盘前强制退出可直接续跑。
2. 安装与恢复的角色、配置和 `agents` 目录临时对象在每次 rename/rmdir 前复核设备号、inode、类型和内容/链接文本，拒绝 transaction 源对象 ABA。
3. journal 顶层、payload、角色、配置和恢复计划改为封闭字段集合；所有可执行路径限定为与 transaction ID/角色名绑定的确定名称，未知字段、重复角色、越界路径、缺失备份和宽权限 journal 均在写入前拒绝。
4. 默认 Codex 根保存创建时身份；打开、锁定和失败清理只接受同一设备号/inode，路径被替换时不写入、不删除替代目录。
5. 只有精确指向仓库绝对源码的角色软链才视为 ready；自循环等相对损坏链接进入可回滚迁移路径。
6. 配置恢复用统一结构视图识别 quoted/dotted 无关 TOML 表边界，保留安装后的合法无关配置变化。
7. 配置安装临时文件移入未发布 transaction staging，消除初始 journal 记录前在 Codex 根残留完整配置副本的窗口。
8. 正式验证和 CI 命令在解释器启动层使用 `python3 -B`，不依赖模块内部设置阻止 `.pyc`。
9. 故障矩阵扩展到 9 个 pre-journal 强制退出点、11 个角色安装进度点、11 个角色恢复进度点、配置安装/恢复对象及根目录/agents 目录重绑定。

实施后第三轮三个独立 read-only 评审仍为 `CHANGES_REQUESTED`。有效 finding 已继续按测试先行修订：

1. staging 正式发布前比较路径对象与已打开 transaction fd 的设备号/inode，并在发布后复核正式路径身份。
2. `agents-object` 清理不再递归删除名称命中的任意目录；只允许删除 journal 记录的同一空目录 inode。
3. journal 按状态约束 `restore_plan_ready` 与恢复字段，`committed`/`install-in-progress` 禁止携带恢复计划；ready 角色禁止注入 install path，所有文件组件拒绝 `/`、`.` 和 `..`。
4. 恢复计划持久化输入字节摘要与确定性输出，并在首次目标写入前重新计算转换，拒绝内容自洽但语义被篡改的输出。
5. 角色安装和恢复循环每次写入前复核根目录中的 `agents` 项仍绑定已打开目录 inode；增加“目标替换后、进度 journal 保存前”的 11 角色强制退出矩阵。
6. 恢复前拒绝 group/other 可访问的角色和配置备份；journal 与备份权限分别覆盖。
7. 实施记录更新为真实状态：第三轮复审前已完成一次真实 restore/reinstall 和 `doctor config.load=ok`；第三轮修订后又按最新代码完成 restore/reinstall，11 个安装目标和受管理配置再次验证通过。

实施后第四轮三个独立 read-only 评审仍为 `CHANGES_REQUESTED`。最后三类有效 finding 已修订：

1. staging 发布身份不匹配时，异常清理只处理仍绑定已打开 transaction fd 的原目录；替代目录及 sentinel 保持不动。
2. `install-in-progress`/`committed` 拒绝所有孤立恢复字段，恢复身份字段必须绑定确定 restore object。
3. `recovered`/`restored` 不再仅凭 journal 状态快速返回；返回成功前只读验证 `agents` 目录、所有角色和配置均精确处于事务前态，伪 terminal 状态安全拒绝。

实施后第五轮三个独立 read-only 评审仍为 `CHANGES_REQUESTED`。最后三项有效 finding 已继续按测试先行修订：

1. schema v1 的 `recovered`/`restored` 不再拥有快速返回兼容旁路；无法按当前 schema 完整验证的旧 journal 明确拒绝。
2. abandoned staging 只在名称、所有权、权限、类型、受管理对象集合、软链目标和可选 journal/目标前态全部可证明时清理；未知 sentinel 或替代目录保持不动并阻止重试。异常清理绑定已打开 transaction fd，路径身份变化时不递归删除替代目录。
3. schema v2 的 `recovered`/`restored` 同时要求全部角色和配置的 `restored = true`，并继续要求真实目标精确处于事务前态；目标碰巧正确但进度缺失或为 false 时安全拒绝。

上述修订完整回归为 78 个测试方法。第六轮三个独立 read-only 评审均为 `CHANGES_REQUESTED`，随后用户明确批准把“风险相称、最小必要安全校验”加入全局 `AGENTS.md` 并立即收缩当前任务：

1. 保留并修复现实可靠性问题：`journal.toml` 临时文件创建后、原子 rename 前真实崩溃时，后续安装能够识别并清理该单个合法临时文件后重试。
2. 补齐批准计划已有但缺失的 Python 3.11/`tomllib` 分派回归；前置条件不满足时只阻断 `codex-agents*`，现有普通目标不受影响。
3. 第六轮提出的同 UID 主动篡改 terminal journal/恢复进度、校验窗口注入保留名称或非空目录、最终指令级竞态，以及“pre-journal 崩溃后再移动仓库”的复合场景，按新批准威胁模型降级为非阻断残余，不再扩展 staging 清单、签名、固定哈希、重复身份协议或相应对抗测试。
4. 已有事务摘要继续只用于备份/恢复内容相等性和内容寻址；角色 TOML 仍只校验结构、必填字段、精确名称和 sandbox，不使用固定 SHA-256。

收缩后的最新验证已通过：81 个测试、仓库与实际安装 validator、`bash -n`、9 个 Python 文件 AST、tracked/staged/untracked whitespace、32 路径精确 allowlist、公共仓库卫生和本机全局 `AGENTS.md` 软链生效检查。

第七轮三个独立 read-only 评审均为 `APPROVED`，且 `findings: []`：

- `reviewer`：确认全局最小必要安全规则、journal 临时文件处理、Python 前置检查和两项回归没有现实功能缺陷。
- `data_consistency_reviewer`：确认合法 journal 临时文件崩溃可重试，未知 staging 项仍拒绝，未重新扩大已排除威胁模型。
- `spec_plan_reviewer`：确认用户批准的范围收缩已同步到 `AGENTS.md`、规格、计划、32 路径 allowlist 和验证证据。

三个会话均精确加载已安装角色 TOML，校验必填字段和声明 sandbox，有效 sandbox 为 read-only，独立上下文为 true，未执行 SHA-256，也未声称原生 named-agent。

随后按最新代码执行真实 restore/reinstall 时暴露一个现实升级兼容问题：个人历史目录中存在 schema v1 的已完成 transaction，新安装扫描把它当作 schema 错误并永久阻断。该问题按测试先行最小修复：新安装扫描只忽略 schema v1 且状态为 `recovered`/`restored` 的历史记录；显式对旧事务执行 recover/restore 仍明确 `schema mismatch`，不猜测旧恢复语义。新增回归与既有旧 schema 拒绝回归同时通过，完整测试为 81 个；修复后真实 reinstall、11 个安装软链和受管理配置再次验证通过。

第八轮针对该兼容修复的窄范围独立复审中，`reviewer` 与 `data_consistency_reviewer` 均为 `APPROVED`、`findings: []`。`spec_plan_reviewer` 提出两项范围内问题：规格仍把所有 schema 不匹配描述为无例外拒绝，以及普通安装扫描的正向回归只覆盖 `restored`。现已最小修订：规格明确该例外只适用于普通安装扫描中的 schema v1 已完成历史，显式恢复入口仍严格拒绝；原回归参数化覆盖 `recovered`/`restored` 两种状态。两项定向正反测试通过，完整 81 个测试再次通过。

`spec_plan_reviewer` 复审上述两项修订后为 `APPROVED`、`findings: []`、`verification_gaps: []`；角色配置、声明与有效 read-only sandbox、独立上下文均验证通过，未执行 SHA-256，未声称原生 named-agent。三类实施评审至此收敛，进入最终静态验证和 final gate。

最终静态验证再次通过：81 个测试、仓库与实际安装的 11 角色 validator、`bash -n`、9 个 Python 文件 AST、全局 `AGENTS.md` 软链、实际受管理配置、精确 32 路径 allowlist、tracked/staged/untracked whitespace、`project-template.md` 未修改及无 `__pycache__`。进入单次 `final_gate_reviewer` 门禁。

单次 `final_gate_reviewer` 最终门禁为 `APPROVED`、`findings: []`。门禁确认交付严格限于 32 个允许路径；81 个测试、仓库与安装目标 validator、脚本与 AST、实际安装、配置、全局规则软链及独立评审证据均满足。非阻断缺口仅为本机未安装 ShellCheck（CI 已配置）以及平台无原生 named-agent 接口（已按用户批准采用独立 read-only 会话加载角色 TOML）。

最终门禁后，用户进一步要求全局安全规则不要过度思考、设计和开发。`AGENTS.md` 已将安全分析、设计、实现、测试和评审统一收缩到实际风险与明确威胁模型下的最小充分范围，并允许项目级规则据此细化或收缩流程；最低边界仍要求最小充分验证、不得绕过已有安全与权限机制、不得违反系统或平台约束。独立只读 Sub Agent 首轮指出项目级规则最低边界表述不足，修订后复审为 `APPROVED`、`findings: []`。
