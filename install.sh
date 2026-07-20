#!/usr/bin/env bash
# 在新机器 / 已有配置的机器上,把本仓库的全局规则接到各 AI agent。
#
# 用法:
#   ./install.sh                       # 接 Codex + Claude(默认)
#   ./install.sh codex claude gemini   # 指定要接的工具
#   ./install.sh codex-agents          # 显式安装 Codex 自定义角色
#   ./install.sh codex-agent-routing   # 显式安装 Sub Agent 动态路由 Hook
#   CLAUDE_MODE=import ./install.sh     # Claude 用 @import(保留专属补充),默认 symlink
#
# 本机专属补充:
#   把不进仓库、只在本机生效的规则放到 ~/.agent-rules-local/<tool>.md
#   (例如 ~/.agent-rules-local/codex.md)。安装时会自动叠加到对应工具:
#     - 支持 import 的工具(Claude):用 @import 引入,随 git pull 自动同步。
#     - 不支持 import 的工具(Codex/Gemini):生成"仓库源 + 专属"的拼接文件;
#       仓库源更新后重跑 ./install.sh 即可重新拼接同步。
#
# 幂等:重复运行安全。已存在的真实文件 / 指向别处的软链会先备份成 *.bak.<时间戳>。

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SRC="$REPO/AGENTS.md"
CODEX_AGENTS_HELPER="$REPO/scripts/codex_agents.py"
CODEX_AGENT_ROUTING_HELPER="$REPO/scripts/codex_agent_routing_install.py"
CLAUDE_MODE="${CLAUDE_MODE:-symlink}"
LOCAL_DIR="${AGENT_RULES_LOCAL:-$HOME/.agent-rules-local}"

if [[ "$CLAUDE_MODE" != "symlink" && "$CLAUDE_MODE" != "import" ]]; then
  echo "✗ 非法 CLAUDE_MODE=$CLAUDE_MODE(仅支持 symlink / import)" >&2
  exit 2
fi

if [[ ! -f "$SRC" ]]; then
  echo "✗ 找不到源文件 $SRC,仓库是否完整?" >&2
  exit 1
fi

# 先验证完整参数，再执行任何目标，避免错误参数造成部分安装。
TOOLS=("$@")
[[ ${#TOOLS[@]} -eq 0 ]] && TOOLS=(codex claude)

require_codex_agents_python() {
  if ! python3 -c 'import sys, tomllib; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    echo "✗ codex-agents 需要 Python 3.11+ 及标准库 tomllib" >&2
    return 2
  fi
}

if [[ "${TOOLS[0]}" == "codex-agents-recover" || "${TOOLS[0]}" == "codex-agents-restore" ]]; then
  if [[ ${#TOOLS[@]} -ne 2 || ! "${TOOLS[1]}" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ ]]; then
    echo "✗ ${TOOLS[0]} 必须独占命令行并接收一个合法 transaction ID" >&2
    exit 2
  fi
  action="${TOOLS[0]#codex-agents-}"
  require_codex_agents_python
  exec python3 "$CODEX_AGENTS_HELPER" "$action" "${TOOLS[1]}"
fi

if [[ "${TOOLS[0]}" == "codex-agent-routing-recover" ||
      "${TOOLS[0]}" == "codex-agent-routing-restore" ]]; then
  if [[ ${#TOOLS[@]} -ne 2 || ! "${TOOLS[1]}" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ ]]; then
    echo "✗ ${TOOLS[0]} 必须独占命令行并接收一个合法 transaction ID" >&2
    exit 2
  fi
  action="${TOOLS[0]#codex-agent-routing-}"
  require_codex_agents_python
  exec python3 "$CODEX_AGENT_ROUTING_HELPER" "$action" "${TOOLS[1]}"
fi

for t in "${TOOLS[@]}"; do
  case "$t" in
    codex|claude|gemini|codex-agents|codex-agent-routing) ;;
    codex-agents-recover|codex-agents-restore|codex-agent-routing-recover|codex-agent-routing-restore)
      echo "✗ $t 必须独占命令行并接收一个 transaction ID" >&2
      exit 2
      ;;
    *)
      echo "✗ 未知工具名:$t(支持 codex / claude / gemini / codex-agents / codex-agent-routing)" >&2
      exit 2
      ;;
  esac
done

# 把路径规范化成"父目录解析软链后 + 文件名"的真实绝对路径(目标文件本身可不存在)。
# 调用前提:调用方应已对目标父目录执行 mkdir -p(本脚本所有写入路径均如此),
# 以保证父目录存在、能被解析;父目录不存在时退回原样返回,此时上层 assert 已无意义,
# 故新增写入路径时务必保持"先 mkdir -p 再 assert/写入"的顺序。
canonicalize() {
  local p="$1" dir base
  dir="$(dirname "$p")"; base="$(basename "$p")"
  # 父目录必须存在才能解析;调用方已先 mkdir -p,这里兜底:不存在则原样返回
  if [[ -d "$dir" ]]; then
    printf '%s/%s\n' "$(cd "$dir" && pwd -P)" "$base"
  else
    printf '%s\n' "$p"
  fi
}

# 安全断言:绝不把仓库内路径当作写入目标(规范化后比较,防 ../ 或软链父目录绕过)
assert_outside_repo() {
  local target; target="$(canonicalize "$1")"
  if [[ "$target" == "$SRC" || "$target" == "$REPO" || "$target" == "$REPO/"* ]]; then
    echo "✗ 拒绝写入仓库内路径 $1(规范化为 $target,可能覆盖源文件);目标应在 \$HOME 下" >&2
    exit 2
  fi
}

# 备份已存在的真实文件 / 指向别处的软链;指向本仓库源的软链视为已就绪(仅供纯软链模式判断跳过用)
backup_if_needed() {
  local target="$1"
  assert_outside_repo "$target"
  if [[ -L "$target" ]]; then
    [[ "$(readlink "$target")" == "$SRC" ]] && return 1
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    local bak
    bak="$target.bak.$(date +%Y%m%d%H%M%S).$$"
    mv "$target" "$bak"
    echo "  备份原文件 → $bak"
  fi
  return 0
}

# 为"写入真实文件内容"准备目标:任何已存在的 symlink 都先移除(避免写入顺链接覆盖源),
# 真实文件则备份。保证随后的 `> target` 写的是全新普通文件。
prepare_write_target() {
  local target="$1"
  assert_outside_repo "$target"
  if [[ -L "$target" ]]; then
    # 软链(无论指向哪里)一律删除,绝不顺链接写入
    rm -f "$target"
    echo "  移除原软链 $target"
  elif [[ -e "$target" ]]; then
    local bak
    bak="$target.bak.$(date +%Y%m%d%H%M%S).$$"
    mv "$target" "$bak"
    echo "  备份原文件 → $bak"
  fi
}

# 返回某工具的本机专属补充文件路径(存在则回显,否则空)
local_extra() {
  local tool="$1"
  local f="$LOCAL_DIR/$tool.md"
  [[ -f "$f" ]] && echo "$f"
}

# 纯软链接到仓库源(无本机专属时用,可随 git pull 自动同步)
link_to_src() {
  local target="$1"
  mkdir -p "$(dirname "$target")"
  if backup_if_needed "$target"; then
    ln -s "$SRC" "$target"
    echo "  软链 $target → $SRC"
  else
    echo "  已就绪(指向本仓库),跳过 $target"
  fi
}

# 拼接生成:仓库源 + 本机专属(给不支持 import 的工具)
concat_with_extra() {
  local target="$1" extra="$2"
  mkdir -p "$(dirname "$target")"
  prepare_write_target "$target"
  {
    echo "<!-- 自动生成:仓库源 + 本机专属。勿手改;改源请改 $SRC,改专属请改 $extra,然后重跑 install.sh -->"
    echo
    cat "$SRC"
    echo
    echo "<!-- ↓↓↓ 本机专属补充(来自 $extra) -->"
    echo
    cat "$extra"
  } > "$target"
  echo "  拼接生成 $target(仓库源 + $extra)"
}

# 不支持 import 的工具:有专属则拼接,无专属则纯软链
install_concat_tool() {
  local tool="$1" target="$2"
  echo "[$tool]"
  local extra; extra="$(local_extra "$tool")" || true
  if [[ -n "$extra" ]]; then concat_with_extra "$target" "$extra"; else link_to_src "$target"; fi
}

install_codex()  { install_concat_tool codex  "$HOME/.codex/AGENTS.md"; }
install_gemini() { install_concat_tool gemini "$HOME/.gemini/GEMINI.md"; }
install_codex_agents() { require_codex_agents_python && python3 "$CODEX_AGENTS_HELPER" install; }
install_codex_agent_routing() {
  require_codex_agents_python && python3 "$CODEX_AGENT_ROUTING_HELPER" install
}

# Claude 支持 import:symlink 模式或 import 模式
install_claude() {
  echo "[claude]"
  local target="$HOME/.claude/CLAUDE.md"
  local extra; extra="$(local_extra claude)" || true
  # 有本机专属时强制走 import(软链无法叠加)
  if [[ "$CLAUDE_MODE" == "import" || -n "$extra" ]]; then
    mkdir -p "$(dirname "$target")"
    prepare_write_target "$target"
    {
      echo "@$SRC"
      echo
      if [[ -n "$extra" ]]; then echo "@$extra"; else echo "## Claude 专属补充"; echo; fi
    } > "$target"
    echo "  写入 import:$target(@仓库源${extra:+ + @$extra})"
  else
    link_to_src "$target"
  fi
}

echo "源:$SRC"
echo "本机专属目录:$LOCAL_DIR$([[ -d "$LOCAL_DIR" ]] || echo '(不存在,无专属补充)')"
echo "接入工具:${TOOLS[*]}"
echo
for t in "${TOOLS[@]}"; do
  case "$t" in
    codex)  install_codex ;;
    claude) install_claude ;;
    gemini) install_gemini ;;
    codex-agents) install_codex_agents ;;
    codex-agent-routing) install_codex_agent_routing ;;
  esac
done
echo
echo "✓ 完成。"
echo "  - 纯软链 / import 的工具:git pull 更新仓库源后自动同步。"
echo "  - 拼接生成的工具(含本机专属):git pull 后重跑 ./install.sh 重新拼接。"
