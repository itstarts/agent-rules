# agent-rules

跨 AI 编码工具共用的工程规则:以 `AGENTS.md` 为唯一源,一处维护,Codex、Claude Code、Cursor、Copilot 等自动同步。

## 文件

| 文件 | 用途 |
|------|------|
| `AGENTS.md` | **唯一真实源**:全局通用工程纪律,去技术栈耦合,适合所有项目 |
| `CLAUDE.md` | 软链 → `AGENTS.md`,供 Claude Code 读取 |
| `project-template.md` | 项目级规范模板,承载 SQL/DB、MQ、资金/权限/脱敏等栈相关与业务强约束 |
| `install.sh` | 安装脚本:建全局软链 / 拼接,幂等、自动备份、支持本机专属补充 |

## 快速开始(全局生效)

> 适用平台:macOS / Linux(依赖 Bash 与 `ln -s`)。Windows 上 Claude 可用 import 模式;Codex / Gemini 走软链或拼接,需开发者模式 / 管理员权限还原软链,或参照「手动等价操作」自行处理。
> 这是一份**可直接用、也鼓励 fork 后按自己团队改写**的规则集——`AGENTS.md` 含明确的主观取向(如默认中文沟通、特定任务分级体系),照搬前请确认是否符合你的习惯。

```bash
git clone https://github.com/itstarts/agent-rules.git ~/agent-rules
cd ~/agent-rules
./install.sh                      # 默认接 Codex + Claude Code
./install.sh codex claude gemini  # 也接 Gemini CLI
```

> **软链 / Claude import 模式下,clone 目录请固定保留,不要移动或删除**:这两种模式按绝对路径指向该目录,目录一旦移走,对应工具的全局配置会立即失效;换位置请重新 clone 并重跑 `./install.sh`。(拼接模式已把内容写死到目标文件,不依赖 clone 目录,但仓库源更新后仍需重跑 `./install.sh` 重新拼接。)

装完后,各工具如何随仓库更新同步:

- **纯软链**(无本机专属补充的 Codex/Gemini,以及软链模式的 Claude):直接链到仓库 `AGENTS.md`,`git pull` 后自动生效。
- **Claude import 文件**(有专属补充或 `CLAUDE_MODE=import`):import 是动态读取被引用文件,`git pull` 更新源后**自动生效**,无需重跑。
- **拼接文件**(有专属补充的 Codex/Gemini,因这类工具不支持 import,只能把内容拼死):`git pull` 后需**重跑 `./install.sh`** 重新拼接。

`install.sh` 可重复运行且安全:纯软链且已正确指向仓库时自动跳过;import / 拼接目标每次重跑都会重新生成(原真实文件先备份成 `*.bak.<时间戳>`,原软链先移除再写,绝不顺链接覆盖源)。

## 已有 AGENTS / CLAUDE 配置的机器

若 `~/.codex/AGENTS.md`、`~/.claude/CLAUDE.md`、`~/.gemini/GEMINI.md` 已是真实文件,`install.sh` 会先备份再接入。接入前先判断旧内容怎么办:

1. **旧内容已被仓库覆盖** → 直接 `./install.sh`,旧文件留作 `.bak`。
2. **旧内容有仓库没有、想全机器共享的规则** → 先并入仓库 `AGENTS.md` 并提交,再 `./install.sh`。
3. **旧内容是本机/本工具专属**(特定 wrapper、外部服务、机器环境细节) → 放本机专属补充(见下),不进仓库。

对比旧内容与仓库源的差异:

```bash
diff <(sort -u ~/.codex/AGENTS.md) <(sort -u ~/agent-rules/AGENTS.md)
grep '^#' ~/.codex/AGENTS.md   # 看旧文件有哪些小节
```

## 本机专属补充

不进仓库、只在某台机器生效的规则,放到 `~/.agent-rules-local/<工具>.md`(如 `codex.md` / `claude.md` / `gemini.md`;目录可用环境变量 `AGENT_RULES_LOCAL` 覆盖)。`install.sh` 检测到后自动叠加:

- **支持 import 的工具(Claude)**:写入 import 文件,引入仓库源 + 专属文件,`git pull` 后自动同步。内容形如:
  ```
  @/Users/<你>/agent-rules/AGENTS.md
  @/Users/<你>/.agent-rules-local/claude.md
  ```
  (`@` 后是绝对路径;Claude 的 import 支持相对/绝对/`~` 路径,递归最多 4 层。)
- **不支持 import 的工具(Codex / Gemini)**:生成「仓库源 + 专属」的拼接文件;仓库源更新后**重跑 `./install.sh`** 重新拼接。

想给 Claude 加专属补充,推荐放 `~/.agent-rules-local/claude.md`(脚本会自动以 `@import` 引入,重跑不丢)。不要在生成的 `~/.claude/CLAUDE.md` 里手动追加段落——每次重跑 `install.sh` 都会重写该文件,手动内容会丢失。`CLAUDE_MODE=import ./install.sh claude` 仅用于在无专属补充时也强制走 import 模式。

适合放这里的内容:依赖特定 wrapper / 外部评审服务的调用纪律、某机器特有的路径或环境约定——这些不该污染跨工具通用源。

## 项目级生效(单个项目)

把模板复制进项目根目录,按该项目技术栈裁剪:

```bash
cd /path/to/your-project
cp ~/agent-rules/project-template.md ./AGENTS.md  # 供 Codex 等读取,按项目裁剪
ln -s AGENTS.md ./CLAUDE.md                                 # 供 Claude Code 读取
```

项目级规则与全局叠加。优先级(见 `AGENTS.md` 头部):用户指令 > 项目级 > 全局 > 系统默认。

## 工作原理

不同工具读不同文件名,且大多不能互换:

- **`AGENTS.md`** 是 Linux Foundation 旗下 Agentic AI Foundation 主导的开放标准,被 Codex、Cursor、Copilot、Aider、Windsurf、Zed、Jules、Devin 等 20+ 工具**原生读取**。这类工具直接读项目根目录或自身约定位置的 `AGENTS.md`,无需本仓库桥接;`install.sh` 只负责把全局源接到 `~/.codex/AGENTS.md`、`~/.claude/CLAUDE.md`、`~/.gemini/GEMINI.md` 三处(即 `codex` / `claude` / `gemini` 三个工具名),其余工具的全局接入需按其文档自行配置。
- **Claude Code** 只读 `CLAUDE.md`(不读 `AGENTS.md`),但支持 `@import`(相对/绝对/`~` 路径,递归最多 4 层)。
- **Gemini CLI** 读 `GEMINI.md`。

因此以 `AGENTS.md` 为唯一源,其余"只认自家文件名"的工具用软链或 import 桥接:能软链的软链(随 `git pull` 自动同步),需叠加本机专属的用拼接 / import。

### 手动等价操作

通常用 `install.sh` 即可。下面是脚本背后做的事,供排查参考。注意:这些裸命令**不含脚本的备份与防覆盖逻辑**,`ln -sf` 会直接覆盖目标已有的真实文件或软链,执行前请自行确认目标无需保留;日常安装请优先用 `install.sh`。

```bash
REPO=~/agent-rules
mkdir -p ~/.codex ~/.claude                    # install.sh 会自动建,手动操作需自己建
ln -sf "$REPO/AGENTS.md" ~/.codex/AGENTS.md    # Codex(无专属补充时)
ln -sf "$REPO/AGENTS.md" ~/.claude/CLAUDE.md   # Claude(软链方式)
# 或 Claude import 方式:把 ~/.claude/CLAUDE.md 写成 `@<REPO 绝对路径>/AGENTS.md` 再追加专属段落
```

## 卸载与恢复

`install.sh` 不修改源仓库,只在 `~/.codex/AGENTS.md`、`~/.claude/CLAUDE.md`、`~/.gemini/GEMINI.md` 三处建立软链 / 写入文件(并按需 `mkdir -p` 创建缺失的父目录),接入前会把原有真实文件备份成同目录下的 `*.bak.<时间戳>.<pid>`。要还原:

```bash
# 1. 删除本工具建立的软链 / 生成文件(按你接入过的工具选)
rm -f ~/.codex/AGENTS.md ~/.claude/CLAUDE.md ~/.gemini/GEMINI.md

# 2. 若安装前本来就有自己的配置,从备份恢复(文件名以实际时间戳为准)
ls -t ~/.codex/AGENTS.md.bak.*        # 找到最近一次备份
mv ~/.codex/AGENTS.md.bak.<时间戳>.<pid> ~/.codex/AGENTS.md
```

删除软链不影响源仓库;之后删掉 clone 目录即可完全移除。

## 维护与注意事项

- 改全局规则只改 `AGENTS.md`(唯一源)。改完之后如何生效:
  - **软链 / import 模式**(默认的 Claude,以及无本机专属补充的 Codex/Gemini):自动跟随,无需额外操作;跨机器 `git push` / `git pull` 即可。
  - **拼接模式**(本机有专属补充的 Codex/Gemini):改完源或改完 `~/.agent-rules-local/<工具>.md` 后,需**重跑 `./install.sh <工具>`** 重新拼接。
- 软链能被 git 跟踪(存为链接本身),clone 后保留。
- **Windows** clone 还原软链需管理员权限或开发者模式,否则软链会变成普通文本文件 —— 此时改用 import 方式。

## 贡献

欢迎 fork 改成自己的版本。也欢迎对**通用工程纪律**(去技术栈耦合的部分)提 Issue 或 PR;涉及个人 / 团队主观偏好的规则(沟通语言、任务分级口径等)请在自己的 fork 里调整,不强求并入上游。

## License

[MIT](LICENSE) © itstarts
