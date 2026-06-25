#!/usr/bin/env bash
# 在新机器上把本仓库的全局规则接到各 AI agent。
# 用法:
#   ./install.sh                # 接 Codex + Claude(默认)
#   ./install.sh codex claude gemini   # 指定要接的工具
#   CLAUDE_MODE=import ./install.sh     # Claude 用 @import 方式(保留专属补充),默认 symlink
#
# 幂等:重复运行安全。已存在且非本仓库软链的配置会先备份成 *.bak.<时间戳>。

set -euo pipefail

# 仓库根目录 = 本脚本所在目录,无论从哪里调用都正确解析
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO/AGENTS.md"
CLAUDE_MODE="${CLAUDE_MODE:-symlink}"

if [[ ! -f "$SRC" ]]; then
  echo "✗ 找不到源文件 $SRC,仓库是否完整?" >&2
  exit 1
fi

# 备份已存在的真实文件 / 指向别处的软链(指向本仓库的软链视为已就绪,跳过)
backup_if_needed() {
  local target="$1"
  if [[ -L "$target" ]]; then
    local cur; cur="$(readlink "$target")"
    [[ "$cur" == "$SRC" ]] && return 1   # 已正确指向本仓库,无需动
  fi
  if [[ -e "$target" || -L "$target" ]]; then
    local bak="$target.bak.$(date +%Y%m%d%H%M%S)"
    mv "$target" "$bak"
    echo "  备份原文件 → $bak"
  fi
  return 0
}

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

install_codex()  { echo "[Codex]";  link_to_src "$HOME/.codex/AGENTS.md"; }
install_gemini() { echo "[Gemini]"; link_to_src "$HOME/.gemini/GEMINI.md"; }

install_claude() {
  echo "[Claude Code]"
  local target="$HOME/.claude/CLAUDE.md"
  if [[ "$CLAUDE_MODE" == "import" ]]; then
    mkdir -p "$(dirname "$target")"
    # import 模式:不覆盖,若已存在则提示手动加一行,避免破坏用户已有内容
    if [[ -f "$target" && ! -L "$target" ]] && grep -q "$SRC" "$target" 2>/dev/null; then
      echo "  已包含 @import,跳过 $target"
    else
      backup_if_needed "$target" || true
      printf '@%s\n\n## Claude 专属补充\n\n' "$SRC" > "$target"
      echo "  写入 import:$target(@$SRC + 专属补充占位)"
    fi
  else
    link_to_src "$target"
  fi
}

TOOLS=("$@")
[[ ${#TOOLS[@]} -eq 0 ]] && TOOLS=(codex claude)

echo "源:$SRC"
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
echo "✓ 完成。git pull 更新源文件后,各工具自动同步(import 模式下专属补充不受影响)。"
