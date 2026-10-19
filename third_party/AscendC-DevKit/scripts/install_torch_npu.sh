#!/usr/bin/env bash
# Ascend torch / torch_npu 一键安装脚本（独立于 CANN 安装）
# 用法：
#   ./scripts/install_torch_npu.sh [选项]
#   ./scripts/install_torch_npu.sh --help
#
# 说明：
# - 只负责安装 Python 侧的 torch 与 torch_npu；CANN toolkit / 驱动请用
#   scripts/install_cann_env.sh 单独安装。
# - 默认版本 2.6.0，与 CANN 8.0.RC3 / torch_npu 2.6.0 实测组合对齐；CANN 不同
#   请用 --torch-version 覆盖。
# - 三种安装来源（优先级递减）：
#     1) --torch-wheel / --torch-npu-wheel 显式指定本地 wheel
#     2) --pkg-dir 扫描目录里的 torch-*.whl / torch_npu-*.whl
#     3) pip 在线安装（默认公网清华镜像；华为内网请用 --pip-index-url 指定）
# - 前置依赖：torch_npu 运行期需要 CANN toolkit 与 NPU 驱动，安装前请先装好 CANN
#   并 source set_env.sh；否则 wheel 装得上但 import / .npu() 会失败。

set -uo pipefail

# ========== 默认配置 ==========
# 默认与 CANN 8.0.RC3 / torch_npu 2.6.0 实测组合对齐；CANN 不同请用 --torch-version 覆盖。
TORCH_VERSION="2.6.0"
TORCH_WHEEL=""
TORCH_NPU_WHEEL=""
PKG_DIR=""
PIP_INDEX_URL=""
# 公网默认 pip 镜像（清华）。华为内网请用 --pip-index-url 指定内网源。
DEFAULT_PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
NON_INTERACTIVE=false
DRY_RUN=false

# ========== 帮助 ==========
usage() {
    cat <<EOF
Ascend torch / torch_npu 一键安装脚本

Usage:
  $0 [options]

Options:
  --torch-version VER    torch/torch_npu 版本 [default: 2.6.0]
  --torch-wheel PATH     指定本地 torch wheel（覆盖 pip）
  --torch-npu-wheel PATH 指定本地 torch_npu wheel（覆盖 pip）
  --pkg-dir DIR          扫描该目录下的 torch-*.whl / torch_npu-*.whl 作为本地 wheel
  --pip-index-url URL    pip 在线安装时使用的镜像 [default: 公网清华镜像；华为内网请显式指定]
  --dry-run              只打印安装计划，不执行安装
  -y, --yes              非交互模式，默认确认
  -h, --help             显示本帮助

Example:
  # 1. 在线安装默认版本
  $0

  # 2. 指定 torch_npu 版本（如 CANN 版本不同）
  $0 --torch-version 2.5.0

  # 3. 用本地 wheel 安装
  $0 --torch-wheel /data/torch-2.6.0.whl --torch-npu-wheel /data/torch_npu-2.6.0.whl

  # 4. 从包目录扫描 wheel（与 install_cann_env.sh --pkg-dir 指向同一目录即可）
  $0 --pkg-dir /data/cann-pkgs

  # 5. 华为内网
  $0 --pip-index-url https://mirrors.tools.huawei.com/pypi/simple
EOF
}

# ========== 参数解析 ==========
while [ $# -gt 0 ]; do
    case "$1" in
        --torch-version) TORCH_VERSION="$2"; shift 2 ;;
        --torch-wheel) TORCH_WHEEL="$2"; shift 2 ;;
        --torch-npu-wheel) TORCH_NPU_WHEEL="$2"; shift 2 ;;
        --pkg-dir) PKG_DIR="$2"; shift 2 ;;
        --pip-index-url) PIP_INDEX_URL="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        -y|--yes) NON_INTERACTIVE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

# ========== 工具函数 ==========
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

confirm() {
    if [ "$NON_INTERACTIVE" = true ]; then
        return 0
    fi
    read -r -p "$1 [y/N] " ans
    case "$ans" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

# 在 --pkg-dir 下扫描 wheel：参数 (变量名, 文件名 pattern)，命中则赋值给变量名。
scan_wheel() {
    local var="$1" pattern="$2" found=""
    if [ -n "$PKG_DIR" ]; then
        found=$(find "$PKG_DIR" -maxdepth 1 -type f -name "*.whl" 2>/dev/null | grep -iE "$pattern" | head -1)
    fi
    printf -v "$var" '%s' "$found"
}

# ========== 前置检查 ==========
log "torch / torch_npu 安装准备..."
command -v python3 >/dev/null 2>&1 || fail "未找到 python3，请先用 scripts/install_python.sh 安装 Python"
command -v pip >/dev/null 2>&1 || fail "未找到 pip（python3 -m pip 也不可用），请先配置好 pip"

if [ -n "${ASCEND_TOOLKIT_HOME:-}" ]; then
    log "  当前 ASCEND_TOOLKIT_HOME: $ASCEND_TOOLKIT_HOME"
else
    log "  当前 ASCEND_TOOLKIT_HOME: 未设置（torch_npu 运行期需要 CANN，请先装好并 source set_env.sh）"
fi

# torch 当前状态检测（关键：发现 CPU-only 版本时自动重装）
TORCH_IS_CPU=false
if python3 -c "import torch" >/dev/null 2>&1; then
    TORCH_INFO=$(python3 -c "import torch; print(torch.__version__)" 2>/dev/null)
    log "  torch: $TORCH_INFO"
    if echo "$TORCH_INFO" | grep -q "+cpu"; then
        log "  警告: torch 是 CPU-only 版本 (+cpu)，将自动卸载并重装为 NPU 版"
        TORCH_IS_CPU=true
    fi
else
    log "  torch: 未安装"
fi

# torch_npu 当前状态检测
if python3 -c "import torch_npu; print(torch_npu.__version__)" >/dev/null 2>&1; then
    CUR_TN=$(python3 -c "import torch_npu; print(torch_npu.__version__)" 2>/dev/null)
    log "  torch_npu: $CUR_TN"
else
    log "  torch_npu: 未安装"
fi

# 扫描 --pkg-dir 下的 wheel（未显式指定 wheel 时作为候选来源）
if [ -z "$TORCH_WHEEL" ] && [ -z "$TORCH_NPU_WHEEL" ] && [ -n "$PKG_DIR" ]; then
    [ ! -d "$PKG_DIR" ] && fail "包目录不存在: $PKG_DIR"
    log "扫描包目录: $PKG_DIR"
    scan_wheel TORCH_WHEEL     "torch-.*\\.whl$"
    scan_wheel TORCH_NPU_WHEEL "torch_npu-.*\\.whl$"
    [ -n "$TORCH_WHEEL" ]     && log "  识别到 torch wheel:     $(basename "$TORCH_WHEEL")"
    [ -n "$TORCH_NPU_WHEEL" ] && log "  识别到 torch_npu wheel: $(basename "$TORCH_NPU_WHEEL")"
fi

# 仅在需要走 pip 在线安装时才解析 / 校验 pip 镜像
NEED_PIP=true
if [ -n "$TORCH_WHEEL" ] && [ -n "$TORCH_NPU_WHEEL" ]; then
    NEED_PIP=false
fi
if [ "$NEED_PIP" = true ]; then
    log ""
    log "当前 pip 配置:"
    python3 -m pip config list 2>/dev/null | sed 's/^/  /' || true

    if [ -z "$PIP_INDEX_URL" ]; then
        PIP_INDEX_URL=$(python3 -m pip config list 2>/dev/null | grep '^global.index-url=' | cut -d= -f2- | tr -d "'" || true)
        if [ -z "$PIP_INDEX_URL" ]; then
            PIP_INDEX_URL="$DEFAULT_PIP_INDEX_URL"
            log "  未检测到 pip index-url，默认使用公网镜像: $PIP_INDEX_URL（华为内网请用 --pip-index-url 指定）"
        else
            log "  使用 pip 配置的 index-url: $PIP_INDEX_URL"
        fi
    else
        log "  使用命令行指定的 index-url: $PIP_INDEX_URL"
    fi
fi

# ========== 安装前确认 ==========
log ""
log "安装计划:"
log "  torch / torch_npu 版本: $TORCH_VERSION"
if [ -n "$TORCH_WHEEL" ] && [ -n "$TORCH_NPU_WHEEL" ]; then
    log "  安装来源: 本地 wheel"
    log "    torch:     $TORCH_WHEEL"
    log "    torch_npu: $TORCH_NPU_WHEEL"
else
    log "  安装来源: pip 在线安装 (index-url: $PIP_INDEX_URL)"
    log "    torch==$TORCH_VERSION torch_npu==$TORCH_VERSION numpy pyyaml"
fi

if [ "$DRY_RUN" = true ]; then
    log ""
    log "DRY RUN 完成，未执行任何安装。"
    exit 0
fi

if [ "$NON_INTERACTIVE" = false ]; then
    confirm "确认开始安装?" || { log "已取消"; exit 0; }
fi

# ========== 安装 torch / torch_npu ==========
# 已装且版本符合则跳过；否则按 wheel / pip 顺序安装。
if python3 -c "import torch_npu; print(torch_npu.__version__)" >/dev/null 2>&1; then
    log "torch_npu 已安装，跳过安装（如需强制重装：先 pip uninstall torch_npu，或用本地 wheel --force-reinstall）"
else
    # 如果是 CPU-only torch，先卸载，否则 torch_npu 装上也跑不了 .npu()
    if [ "$TORCH_IS_CPU" = true ]; then
        log "卸载 CPU-only torch..."
        pip uninstall torch -y || true
    fi

    log "安装 torch / torch_npu (版本: $TORCH_VERSION)"
    if [ -n "$TORCH_WHEEL" ] && [ -n "$TORCH_NPU_WHEEL" ]; then
        log "  使用指定 wheel: $TORCH_WHEEL, $TORCH_NPU_WHEEL"
        pip install --force-reinstall --no-deps "$TORCH_WHEEL" "$TORCH_NPU_WHEEL" || fail "torch/torch_npu wheel 安装失败"
    else
        log "  从 pip 安装: torch==$TORCH_VERSION torch_npu==$TORCH_VERSION numpy pyyaml"
        log "  使用 index-url: $PIP_INDEX_URL"
        if pip install "torch==$TORCH_VERSION" "torch_npu==$TORCH_VERSION" numpy pyyaml --index-url "$PIP_INDEX_URL"; then
            :
        else
            # 主镜像失败时，尝试官方 PyPI 作为 fallback（与默认清华镜像互为备份）
            fallback_url="https://pypi.org/simple"
            log "  主镜像安装失败，尝试 fallback: $fallback_url"
            if pip install "torch==$TORCH_VERSION" "torch_npu==$TORCH_VERSION" numpy pyyaml --index-url "$fallback_url" --trusted-host "pypi.org"; then
                :
            else
                fail "pip 安装 torch/torch_npu 失败。建议检查 pip 配置、网络，或从官网下载对应 wheel 用 --torch-wheel / --torch-npu-wheel 指定。"
            fi
        fi
    fi
fi

# ========== 验证 ==========
log ""
log "===== 验证 ====="
python3 -c "import torch; print('torch:', torch.__version__)" 2>&1 | head -1
if python3 -c "import torch_npu; print('torch_npu:', torch_npu.__version__, 'device_count:', torch_npu.npu.device_count())" 2>&1 | head -1; then
    log "torch_npu 导入验证通过"
else
    log "警告: torch_npu 导入/初始化失败——wheel 可能装好但运行期缺 CANN/驱动，"
    log "      请确认已安装 CANN (scripts/install_cann_env.sh) 并 source set_env.sh。"
fi

log ""
log "安装完成。下一步:"
log "  source /usr/local/Ascend/set_env.sh   # 若尚未 source CANN 环境"
log "  python3 -c 'import torch_npu; print(torch_npu.__version__)'"
