#!/usr/bin/env bash
# Python 环境一键安装脚本（基于 pyenv）
#
# 用途：在 Ubuntu/Debian 上通过 pyenv 安装指定版本 Python 并设为全局默认。
# 本工程要求 requires-python>=3.11，本脚本默认安装 3.11.12。
#
# 用法：
#   ./scripts/install_python.sh [options]
#   ./scripts/install_python.sh --help
#
# 说明：
# - 自动处理本环境已知的两个坑：/tmp 以 noexec 挂载（改用自定义 TMPDIR）、
#   内网代理自签 HTTPS 证书（--insecure 同时作用于 git clone 与 python-build 下载）。
# - 全程幂等：pyenv 已 clone / Python 已装 / .bashrc 已配置 时均跳过，可反复执行。
# - 不破坏系统 python：仅向 ~/.pyenv 安装、向 ~/.bashrc 追加配置。

set -uo pipefail

# ========== 默认配置 ==========
PYTHON_VERSION="3.11.12"
PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
SCOPE="global"            # global | none
INSECURE=false
SKIP_DEPS=false
NON_INTERACTIVE=false
DRY_RUN=false

# python-build 用的临时目录（规避 /tmp noexec）
BUILD_TMPDIR="${BUILD_TMPDIR:-$HOME/.pyenv-tmp}"

# pyenv 构建依赖（pyenv wiki 推荐的 Debian/Ubuntu 全集）
BUILD_DEPS=(
    make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev
    libsqlite3-dev wget curl llvm libncursesw5-dev xz-utils tk-dev
    libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev git
)

# ========== 帮助 ==========
usage() {
    cat <<EOF
Python 环境一键安装脚本（基于 pyenv）

Usage:
  $0 [options]

Options:
  --version VER          要安装的 Python 版本 [default: 3.11.12]
  --pyenv-root PATH      pyenv 安装目录 [default: \$HOME/.pyenv]
  --scope SCOPE          安装后设置方式: global(全局默认) | none(仅装不设默认) [default: global]
  --build-tmpdir PATH    python-build 临时目录（规避 /tmp noexec）[default: \$HOME/.pyenv-tmp]
  --skip-deps            跳过 apt 安装构建依赖（已装好时用）
  --insecure             跳过 HTTPS 证书校验（内网代理/自签证书环境需要）
  --dry-run              只打印计划，不执行安装
  -y, --yes              非交互模式，默认确认
  -h, --help             显示本帮助

Example:
  # 1. 默认安装 3.11.12 并设为全局默认
  $0

  # 2. 内网代理（自签证书）环境
  $0 --insecure -y

  # 3. 仅装 3.12，不改默认（避免影响系统脚本）
  $0 --version 3.12.7 --scope none

  # 4. 安装后人工 pyenv local 在项目目录绑定
  $0 --scope none && cd /path/to/project && pyenv local 3.11.12
EOF
}

# ========== 参数解析 ==========
while [ $# -gt 0 ]; do
    case "$1" in
        --version) PYTHON_VERSION="$2"; shift 2 ;;
        --pyenv-root) PYENV_ROOT="$2"; shift 2 ;;
        --scope) SCOPE="$2"; shift 2 ;;
        --build-tmpdir) BUILD_TMPDIR="$2"; shift 2 ;;
        --skip-deps) SKIP_DEPS=true; shift ;;
        --insecure) INSECURE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -y|--yes) NON_INTERACTIVE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

case "$SCOPE" in
    global|none) ;;
    *) echo "ERROR: --scope 仅支持 global|none"; exit 1 ;;
esac

# ========== 工具函数 ==========
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

confirm() {
    if [ "$NON_INTERACTIVE" = true ]; then return 0; fi
    read -r -p "$1 [y/N] " ans
    case "$ans" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

# 探测某目录是否以 noexec 挂载（python-build 在 noexec 的 /tmp 上会失败）
is_noexec() {
    local d="$1" t
    t=$(mktemp "$d/.noexec_test.XXXXXX" 2>/dev/null) || return 0
    printf '#!/bin/sh\nexit 0\n' > "$t"
    chmod +x "$t" 2>/dev/null
    if "$t" >/dev/null 2>&1; then rm -f "$t"; return 1; else rm -f "$t"; return 0; fi
}

# root 时 SUDO 为空，否则尽量用 sudo；没有 sudo 就直接跑（可能因权限不足在 apt 步骤报错）
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="$(command -v sudo 2>/dev/null || true)"
fi

apt_install() {
    # 设 TMPDIR 规避 apt-key 在 /tmp 的临时文件问题
    env TMPDIR="$BUILD_TMPDIR" DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y --no-install-recommends "$@"
}

# ========== 预检 ==========
log "Python 安装计划: version=$PYTHON_VERSION pyenv_root=$PYENV_ROOT scope=$SCOPE insecure=$INSECURE"
if [ "$DRY_RUN" = true ]; then log "DRY-RUN: 仅打印计划，不执行"; exit 0; fi

command -v apt-get >/dev/null 2>&1 || fail "仅支持 apt-based 系统（Debian/Ubuntu）"

mkdir -p "$BUILD_TMPDIR"
if is_noexec /tmp; then
    log "检测到 /tmp 为 noexec，python-build 将使用临时目录: $BUILD_TMPDIR"
else
    log "/tmp 可执行；仍将 python-build 临时目录指向 $BUILD_TMPDIR 以保持一致"
fi

# ========== Step 1: 安装构建依赖 ==========
if [ "$SKIP_DEPS" = true ]; then
    log "跳过 apt 构建依赖安装（--skip-deps）"
else
    log "安装 Python 构建依赖（apt）..."
    # update 单独跑：本环境 GPG/tmpfile 报错不影响从既有索引装包，故不因 update 失败而中断
    env TMPDIR="$BUILD_TMPDIR" $SUDO apt-get update || log "WARN: apt-get update 有告警，继续尝试安装"
    apt_install "${BUILD_DEPS[@]}" || fail "apt 安装构建依赖失败，请检查 apt 源/权限"
fi

# ========== Step 2: clone pyenv（幂等）==========
clone_pyenv() {
    if [ -x "$PYENV_ROOT/bin/pyenv" ]; then
        log "pyenv 已存在: $PYENV_ROOT/bin/pyenv (跳过 clone)"
        return 0
    fi
    local git_env=()
    [ "$INSECURE" = true ] && git_env+=( "GIT_SSL_NO_VERIFY=1" )
    local urls=(
        "https://gitee.com/mirrors/pyenv.git"
        "https://github.com/pyenv/pyenv.git"
    )
    for url in "${urls[@]}"; do
        log "尝试 clone pyenv: $url"
        if env "${git_env[@]}" git clone --depth=1 "$url" "$PYENV_ROOT"; then
            return 0
        fi
        log "WARN: clone 失败: $url"
    done
    fail "无法 clone pyenv（gitee/github 均失败），请检查网络/代理；可加 --insecure 重试"
}
clone_pyenv

# 激活 pyenv（供本脚本后续 pyenv install/global 使用）
export PYENV_ROOT
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# ========== Step 3: 配置 shell rc（幂等）==========
configure_shell() {
    local rc
    case "$(basename "${SHELL:-/bin/bash}")" in
        zsh) rc="$HOME/.zshrc" ;;
        *)   rc="$HOME/.bashrc" ;;
    esac
    touch "$rc"
    if grep -q "pyenv-config-marker" "$rc" 2>/dev/null; then
        log "$rc 已含 pyenv 配置 (跳过)"
        return 0
    fi
    cat >> "$rc" <<'EOF'

# >>> pyenv-config-marker >>>
export PYENV_ROOT="$HOME/.pyenv"
command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
# <<< pyenv-config-marker <<<
EOF
    log "已在 $rc 追加 pyenv 配置（重开终端或 source $rc 生效）"
}
configure_shell

# ========== Step 4: 安装 Python（幂等）==========
install_python() {
    if [ -d "$PYENV_ROOT/versions/$PYTHON_VERSION" ]; then
        log "Python $PYTHON_VERSION 已安装 (跳过)"
        return 0
    fi
    local build_env=( "TMPDIR=$BUILD_TMPDIR" )
    if [ "$INSECURE" = true ]; then
        build_env+=(
            "PYTHON_BUILD_CURL_OPTS=-k"
            "PYTHON_BUILD_WGET_OPTS=--no-check-certificate"
            "PYTHON_BUILD_HTTPS_IGNORE_CERTIFICATES=1"
            "GIT_SSL_NO_VERIFY=1"
        )
    fi
    log "安装 Python $PYTHON_VERSION ..."
    env "${build_env[@]}" pyenv install -s "$PYTHON_VERSION" \
        || fail "安装 Python $PYTHON_VERSION 失败，详见上方 python-build 输出"
}
install_python

# ========== Step 5: 设为默认（可选）==========
if [ "$SCOPE" = "global" ]; then
    log "设置全局默认 Python: $PYTHON_VERSION"
    pyenv global "$PYTHON_VERSION" || fail "pyenv global 设置失败"
else
    log "scope=none，未设默认；如需在项目目录绑定请执行: pyenv local $PYTHON_VERSION"
fi

# ========== 验证 ==========
log "===== 验证 ====="
installed_ver="$(pyenv exec python --version 2>&1)"
log "pyenv: $(pyenv --version)"
log "已装版本: $(pyenv versions --skip-aliases 2>/dev/null | tr -s ' ' | sed 's/^ //')"
log "目标 Python: $installed_ver ($(pyenv prefix "$PYTHON_VERSION" 2>/dev/null))"
log "pip: $(pyenv exec python -m pip --version 2>&1)"

if pyenv exec python -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
    log "requires-python>=3.11: OK"
else
    log "WARN: 安装的版本低于 3.11，本工程 requires-python>=3.11，请用 --version 指定更高版本"
fi

cat <<EOF

完成。
- 全新交互终端会自动加载 pyenv（已写入 rc 文件）。
- 当前 shell 如需立即生效: source <(tail -n 4 "$HOME/.bashrc") 或重开终端。
- 回退/切换: pyenv global system   # 切回系统 python
            pyenv versions        # 查看已装版本
EOF
