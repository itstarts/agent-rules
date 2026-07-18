# Codex 全局自定义子代理角色治理与安装实施记录

> 状态：已完成，作为历史实施记录保留
> 初始计划批准：2026-07-15
> 效率修订批准：2026-07-18
> 依据：`docs/superpowers/specs/2026-07-15-versioned-codex-custom-agents-design.md`
> 压缩说明：本文件由实施计划整理为完成记录；原始逐步 TDD 清单、47 个未勾选计划项和八轮详细评审流水可从 Git 历史中的 `adf69d5` 查看。

## 1. 目标与边界

目标是把 11 个 Codex 全局 custom agents 纳入仓库单一来源，提供显式、幂等、可恢复的安装入口，保守管理 `[agents]` 三个键，并验证仓库源码、本机安装和 Codex 实际加载状态。

实施边界：

- `install.sh` 继续承担顶层命令分派；
- `scripts/codex_agents.py` 使用 Python 3.11+ 标准库实现配置合并、锁、备份、journal、安装、recover 和 restore；
- `scripts/validate_codex_agents.py` 校验角色源码和安装目标；
- `tests/` 使用临时 `HOME` / `CODEX_HOME` 和 Unix 故障注入；
- `codex/agents/` 是角色源码和接管索引的唯一来源；
- 安装采用逐文件绝对软链。

保持不动：

- Claude Code 与 Gemini 角色格式；
- `config.toml` 中除三个受管理键外的内容；
- 未管理角色和历史备份；
- 默认无参数、`codex`、`claude`、`gemini` 安装行为；
- 公共模型、Provider、认证、MCP、插件和 Skill 配置；
- 自动发布、部署、tag 或 release。

## 2. 完成的文件范围

### 2.1 角色与索引

- `codex/agents/managed-agents.txt`
- `codex/agents/*.toml`：11 个受管理角色

### 2.2 安装与校验

- `install.sh`
- `scripts/codex_agents.py`
- `scripts/validate_codex_agents.py`

### 2.3 测试

- `tests/test_codex_agent_roles.py`
- `tests/test_codex_agents_dispatch.py`
- `tests/test_codex_config_merge.py`
- `tests/test_codex_agents_install.py`
- `tests/test_codex_agents_recovery.py`
- `tests/test_codex_agents_concurrency.py`
- `tests/test_codex_docs_ci.py`
- `tests/fixtures/codex_agent_routing_cases.json`

### 2.4 文档与 CI

- `.github/workflows/ci.yml`
- `README.md` / `README.en.md`
- `docs/install.md` / `docs/install.en.md`
- `docs/how-it-works.md` / `docs/how-it-works.en.md`
- 本规格与实施记录

`AGENTS.md` 的风险相称规则曾在原始实施期间独立批准并更新，但 2026-07-18 的角色效率优化和本次文档压缩均未修改它。

## 3. 实施顺序与结果

| 阶段 | 结果 | 主要验证 |
|---|---|---|
| 1. 角色源码与 validator | 11 个角色、索引、字段和职责边界完成 | TOML、名称、sandbox、nickname、卫生检查 |
| 2. 顶层命令分派 | 新增 install/recover/restore，普通目标兼容 | 参数、组合、Python 前置条件 |
| 3. 根目录与锁 | 完成零写入筛查、`root_fd`、`flock`、no-follow | 路径、能力、锁竞争、根替换 |
| 4. 配置合并 | 只补 `[agents]` 三键并原子替换 | TOML 结构、无关值保留、冲突拒绝 |
| 5. 安装事务 | 完成备份、durable journal、角色与配置提交 | 首次安装、迁移、幂等、故障注入 |
| 6. recover / restore | 完成显式恢复、双态复核和幂等续跑 | 中断恢复、配置保留、第三状态拒绝 |
| 7. 隔离集成 | 完成临时 HOME/CODEX_HOME 与并发回归 | 安装、恢复、权限、对象重绑定 |
| 8. 文档与 CI | 完成中英文文档及 Linux CI | 文档契约、ShellCheck、完整测试 |
| 9. 仓库验证 | 完成静态、测试和范围检查 | diff、AST、validator、测试 |
| 10. 本机安装 | 完成 11 个软链与三键配置 | installed validator、doctor、冒烟 |
| 11. 独立评审 | finding 修复后全部收敛 | reviewer、专项评审、final gate |

所有行为变更均按测试先行实现。文档和机械调整使用静态、解析、链接和 diff 检查，不制造无意义的行为测试。

## 4. 最终实现摘要

### 4.1 角色治理

- 11 个角色名称使用小写字母、数字和下划线；
- 8 个分析/评审角色默认为 `read-only`；
- 3 个实现/测试角色默认为 `workspace-write`；
- `managed-agents.txt` 是受管理集合单源；
- description 只保留路由信息，公共操作限制放入 instructions；
- 单个 description 最多 120 字符，总量最多 1100 字符；
- `product_analyst`、`ui_ux_designer`、`visual_reviewer` 使用 `model_reasoning_effort = "medium"`；
- 其它角色继承父会话模型和 reasoning effort；
- 16 个路由案例覆盖全部自定义角色、内置回退、不委派和并行边界。

### 4.2 安装与配置

```toml
[agents]
max_threads = 4
max_depth = 1
interrupt_message = true
```

- `codex-agents` 是唯一修改角色目标和上述三键的入口；
- 配置完整解析后只补兼容缺失键；
- 未管理值和子表保持不动；
- 冲突或无法证明安全的结构零写入停止；
- 角色使用逐文件绝对软链，未管理角色可以共存；
- 仓库更新后软链内容自动同步，客户端重新加载建议新开 Codex 任务。

### 4.3 事务与恢复

- 锁外零写入筛查，锁内完整重做 preflight；
- 所有根内操作绑定 `root_fd`，使用 `dir_fd` 和 no-follow；
- 备份全部 durable 后才原子发布 journal；
- journal 记录固定目标、事务前态、事务创建态、状态和逐目标进度；
- 角色与配置使用同文件系统临时对象加原子 rename；
- 写入前复核根、agents 目录、目标和 transaction 对象身份；
- 自动回滚只处理仍等于本事务产物的目标；
- `recover` 和 `restore` 支持再次中断后的幂等续跑；
- 配置恢复只移除本事务新增键，保留无关合法修改；
- schema v1 已完成 `recovered`/`restored` 记录只在普通安装扫描中作为历史兼容忽略，显式恢复仍拒绝旧 schema。

## 5. 评审 finding 的收敛结果

原始实施经历多轮独立评审。为保留可恢复信息而不重复完整流水，finding 合并为以下主题。

### 5.1 原子性与对象身份

- 安装和恢复从 unlink/create 改为同文件系统临时对象加原子 rename；
- 根目录、agents 目录、角色、配置和 transaction 临时对象记录设备号/inode；
- 每次关键 rename、rmdir 和回滚前复核对象身份、类型和内容；
- 路径被替换时，后续写入仍绑定原 `root_fd`，不写入替代目录。

### 5.2 journal 与崩溃恢复

- 备份先于 journal durable；
- journal 在隐藏 staging 中完整写入并原子发布；
- 每个状态只允许封闭字段集合和合法转换；
- 恢复计划先持久化确定性对象名和输入/输出身份，再修改目标；
- 目标替换后、进度落盘前中断可由双态复核识别并续跑；
- 合法 journal 临时文件导致的 pre-journal 崩溃可安全清理和重试。

### 5.3 配置合并与恢复

- TOML 表头识别覆盖注释、字符串、quoted/dotted key 和子表；
- 安装候选与原解析树做只增加批准键的深度比较；
- 恢复候选重新计算并验证，只移除本事务新增键；
- 安装后的合法无关配置变化得到保留；
- 受管理值或父表结构变化时恢复零写入拒绝。

### 5.4 范围与风险相称

- 现实可靠性问题继续作为阻断 finding；
- 同 UID 主动篡改私有 terminal journal、极端指令级竞态等超出明确威胁模型的问题记录为非阻断残余；
- 不增加固定哈希、签名、重复身份协议或对应对抗测试；
- 事务摘要只服务内容相等性、备份恢复和内容寻址。

### 5.5 跨平台与历史兼容

- Linux inode 复用测试改用 sibling replacement/rename，不修改生产安装器；
- 旧连字符角色名统一为下划线；
- schema v1 已完成历史记录不会永久阻断新安装；
- 进行中、被篡改或显式恢复的旧记录仍严格拒绝。

## 6. 验证证据

### 6.1 2026-07-15 初始实现完成证据

- 11 个角色通过源码和安装目标 validator；
- 完整 Python 测试在当时为 81 项；
- Bash 语法、Python AST、diff whitespace 和 CI 通过；
- 真实安装确认 11 个软链、三键配置和 `multi_agent = true`；
- `config.load = ok`；doctor 的非交互终端失败按独立检查归因；
- 实施评审、数据一致性评审、规格计划评审和最终门禁均为 `APPROVED`。

上述数量是当时的历史快照，不代表当前测试总数。

### 6.2 2026-07-18 效率优化完成证据

- 角色 description 总量从 1729 字符降至 822 字符；
- 三个轻量只读角色增加 `medium` effort，复杂角色继续继承父会话；
- `final_gate_reviewer` 只核对已触发且适用的门禁；
- validator 使用索引单源，并校验 effort、单项和总描述预算；
- 新增 16 个代表性路由案例；
- 定向测试 15 项、完整 Python 测试 93 项通过；
- 源码和本机安装 validator、Bash、ShellCheck、JSON、diff 与 GitHub Actions CI 通过；
- 独立 `reviewer` 初审 finding 修复后复审为 `APPROVED`；
- `31b5248` 经 `adf69d5` 合入 `main`，开发分支和已合入历史分支已清理；
- 从最终 `main` 执行 `./install.sh codex-agents`，本机报告 `codex-agents already ready`。

### 6.3 当前验证入口

```bash
git diff --check
bash -n install.sh
shellcheck install.sh
python3 -B scripts/validate_codex_agents.py
python3 -B -m unittest discover -s tests -p 'test_*.py'
python3 -B scripts/validate_codex_agents.py --installed-root "${CODEX_HOME:-$HOME/.codex}"
codex --strict-config doctor --json
```

## 7. 当前状态与后续维护

```text
spec_user_approval: approved
plan_user_approval: approved
implementation_review: APPROVED
final_gate_review: APPROVED
implementation_gate: complete
```

本文件不再表示开放门禁或待办事项。后续维护按以下入口恢复：

1. 当前角色内容和字段：`codex/agents/*.toml`。
2. 受管理集合：`codex/agents/managed-agents.txt`。
3. 安装和恢复操作：`docs/install.md`。
4. 角色路由和 effort 策略：`docs/how-it-works.md`。
5. 完整设计约束：同主题规格文档。
6. 原始逐步计划与评审流水：Git 历史中的 `adf69d5`。

未来新增角色、改变 sandbox、改变 `[agents]` 所有权、修改恢复协议或扩大外部状态权限，必须重新评估任务等级并取得相应批准；普通文案、路由案例和验证说明可按现有边界做小步维护。
