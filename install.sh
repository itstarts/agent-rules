#!/usr/bin/env bash
# 在新机器 / 已有配置的机器上,把本仓库的全局规则接到各 AI agent。
#
# 用法:
#   ./install.sh                       # 接 Codex + Claude(默认)
#   ./install.sh codex claude gemini   # 指定要接的工具
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

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO/AGENTS.md"
CLAUDE_MODE="${CLAUDE_MODE:-symlink}"
LOCAL_DIR="${AGENT_RULES_LOCAL:-$HOME/.agent-rules-local}"

if [[ ! -f "$SRC" ]]; then
  echo "✗ 找不到源文件 $SRC,仓库是否完整?" >&2
  exit 1
fi

# 备份已存在的真实文件 / 指向别处的软链;指向本仓库源的软链视为已就绪
backup_if_needed() {
  local target="$1"
  # 安全断言:绝不把仓库源自身当作写入目标,避免覆盖源
  if [[ "$target" == "$SRC" || "$target" == "$REPO/"* ]]; then
    echo "✗ 拒绝写入仓库内路径 $target(可能覆盖源文件);目标应在 \$HOME 下" >&2
    exit 2
  fi
  if [[ -L "$target" ]]; then
    [[ "$(readlink "$target")" == "$SRC" ]] && return 1
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    local bak="$target.bak.$(date +%Y%m%d%H%M%S)"
    mv "$target" "$bak"
    echo "  备份原文件 → $bak"
  fi
  return 0
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
  backup_if_needed "$target" || true
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

# Claude 支持 import:symlink 模式或 import 模式
install_claude() {
  echo "[claude]"
  local target="$HOME/.claude/CLAUDE.md"
  local extra; extra="$(local_extra claude)" || true
  # 有本机专属时强制走 import(软链无法叠加)
  if [[ "$CLAUDE_MODE" == "import" || -n "$extra" ]]; then
    mkdir -p "$(dirname "$target")"
    backup_if_needed "$target" || true
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

TOOLS=("$@")
[[ ${#TOOLS[@]} -eq 0 ]] && TOOLS=(codex claude)

echo "源:$SRC"
echo "本机专属目录:$LOCAL_DIR$([[ -d "$LOCAL_DIR" ]] || echo '(不存在,无专属补充)')"
echo "接入工具:${TOOLS[*]}"
echo
for t in "${TOOLS[@]}"; do
  case "$t" in
    codex)  install_codex ;;
    claude) install_claude ;;
    gemini) install_gemini ;;
    *) echo "未知工具:$t(支持 codex / claude / gemini)" >&2 ;;
  esac
done
echo
echo "✓ 完成。"
echo "  - 纯软链 / import 的工具:git pull 更新仓库源后自动同步。"
echo "  - 拼接生成的工具(含本机专属):git pull 后重跑 ./install.sh 重新拼接。"
