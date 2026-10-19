#!/usr/bin/env bash
# Ascend CANN 环境一键安装脚本（只负责 CANN 包：driver/firmware/toolkit/kernel/nnal）
# 用法：
#   本地模式: ./scripts/install_cann_env.sh --pkg-dir /path/to/cann-pkgs [选项]
#   在线模式: ./scripts/install_cann_env.sh [选项]
#   ./scripts/install_cann_env.sh --help
#
# 说明：
# - 本地模式：读取用户提供的本地包目录，适合已提前下载好 CANN 包的场景。
# - 在线模式：未指定 --pkg-dir 时，自动从华为 OBS 仓库下载对应版本/架构/芯片的
#   toolkit 与 ops 包，下载到临时目录后执行安装。
# - 下载页面参考：https://www.hiascend.com/cann/download （按平台/版本取 toolkit 与 ops
#   两个 .run 地址，填入脚本的 resolve_online_urls()）
# - 驱动安装需要 root；toolkit/kernel/firmware 等用户态包可用普通用户装到 --prefix。

set -uo pipefail

# ========== 默认配置 ==========
# 在线下载地址按平台写在 resolve_online_urls() 里（搜该函数名）。
# 换 CANN 版本 / 加平台(A3 等)：改 resolve_online_urls() 一个 case 即可，CLI 无需动。

PKG_DIR=""
PREFIX="/usr/local/Ascend"
SET_ENV_FILE=""
INSTALL_DRIVER=false
AUTO_DOWNLOAD=false
NON_INTERACTIVE=false
DRY_RUN=false
DOWNLOAD_DIR=""
INSECURE=false
# 即使已装相同版本也强制重装 toolkit/kernel（用于排查、修复损坏安装）。
FORCE=false

# --- SoC 平台 ---
# 留空则自动探测（npu-smi / asys）。可显式：平台代号 A2/A3/A5，或 chip id 910b/910c/950。
SOC=""

# ========== 帮助 ==========
usage() {
    cat <<EOF
Ascend CANN 环境一键安装脚本

Usage:
  本地模式: $0 --pkg-dir /path/to/cann-pkgs [options]
  在线模式: $0 [options]

Local mode options:
  --pkg-dir DIR          本地 CANN 包目录（.run / .tar.gz 等）

Online mode options:
  --soc SOC              平台代号或 chip id [default: 自动探测]
                         支持 A2 / A3 / A5（或 910b / 910c / 950）
                         各平台的 CANN 版本与下载地址在脚本 resolve_online_urls() 中维护
  --download-dir DIR     在线包下载目录 [default: 临时目录]
  --auto-download        显式允许在线下载（未指定 --pkg-dir 时默认启用）

Common options:
  --prefix PATH          安装前缀 [default: /usr/local/Ascend]
  --set-env PATH         生成 set_env.sh 的路径 [default: 自动写入 PREFIX]
  --install-driver       同时安装/升级 NPU 驱动（需要 root，在线模式暂不支持）
  --insecure             下载时跳过 HTTPS 证书校验（部分内网/代理环境需要）
  --force                即使已装相同版本也强制重装 toolkit/kernel
  --dry-run              只打印安装计划，不执行下载/安装
  -y, --yes              非交互模式，默认确认
  -h, --help             显示本帮助

Example:
  # 1. 在线安装（SoC 自动探测；CANN 版本与下载地址见 resolve_online_urls()）
  $0 --prefix /usr/local/Ascend

  # 2. 显式指定平台
  $0 --soc A2 --prefix /usr/local/Ascend

  # 3. 本地安装（不装驱动，适合驱动已存在的环境）
  $0 --pkg-dir /data/cann-pkgs --prefix /usr/local/Ascend

  # 4. 装驱动 + 全套（需要 root）
  sudo $0 --pkg-dir /data/cann-pkgs --install-driver

  # 5. 生成环境脚本后使用
  source /usr/local/Ascend/set_env.sh
EOF
}

# ========== 参数解析 ==========
while [ $# -gt 0 ]; do
    case "$1" in
        --pkg-dir) PKG_DIR="$2"; shift 2 ;;
        --prefix) PREFIX="$2"; shift 2 ;;
        --set-env) SET_ENV_FILE="$2"; shift 2 ;;
        --install-driver) INSTALL_DRIVER=true; shift ;;
        --auto-download) AUTO_DOWNLOAD=true; shift ;;
        --soc) SOC="$2"; shift 2 ;;
        --download-dir) DOWNLOAD_DIR="$2"; shift 2 ;;
        --insecure) INSECURE=true; shift ;;
        --force) FORCE=true; shift ;;
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

# 按平台解析在线下载地址：设置 TOOLKIT_URL / OPS_URL / CANN_VERSION_INFO。
# 地址里的 __ARCH__ 占位由调用处替换为实际架构(aarch64/x86_64)。
# 【换 CANN 版本 / 加平台只改这里】地址取自 https://www.hiascend.com/cann/download
resolve_online_urls() {
    TOOLKIT_URL=""; OPS_URL=""; CANN_VERSION_INFO=""
    case "$1" in
        A2|910B|910b)
            # A2 (Ascend 910B)，CANN 9.1.0-beta.3（A2 最新）。
            # 注意：toolkit 与 ops 在两个不同 OBS 桶、不同目录下。
            CANN_VERSION_INFO="9.1.0-beta.3 (A2 / Ascend 910B)"
            TOOLKIT_URL="https://ascend-cann-open.obs.cn-north-4.myhuaweicloud.com/CANN/CANN%209.1.0-beta.3/Ascend-cann_9.1.0-beta.3_linux-__ARCH__.run"
            OPS_URL="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.T6/Ascend-cann-910b-ops_9.1.0-beta.3_linux-__ARCH__.run"
            ;;
        A5|950)
            # A5 (Ascend 950)，CANN 9.1.T6。
            # TODO: 以官网为准核对；若不同请替换下面两条。
            CANN_VERSION_INFO="9.1.T6 (A5 / Ascend 950)"
            TOOLKIT_URL="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.T6/Ascend-cann-toolkit_9.1.0-beta.3_linux-__ARCH__.run"
            OPS_URL="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.T6/Ascend-cann-950-ops_9.1.0-beta.3_linux-__ARCH__.run"
            ;;
        A3|910C|910c)
            # TODO: 填 A3 (Ascend 910C) 官方下载地址后启用。
            return 1
            ;;
        *) return 1 ;;
    esac
    return 0
}

# 从硬件自动探测平台代号（A2/A3/A5/...）。优先 asys（Chip Name 最准），
# 其次 npu-smi（带超时，部分芯片 npu-smi 会卡）。识别不了返回空。
detect_soc() {
    local raw=""
    if command -v asys &>/dev/null; then
        raw=$(asys info -r=status 2>/dev/null | grep -iE 'Chip Name' | head -1)
    fi
    if [ -z "$raw" ] && command -v npu-smi &>/dev/null; then
        raw=$(timeout 10 npu-smi info 2>/dev/null | grep -E '^\| *[0-9]' | head -1)
    fi
    case "$(printf '%s' "$raw" | tr -d ' ')" in
        *910B*|*910b*) echo "A2" ;;
        *910C*|*910c*) echo "A3" ;;
        *950*)        echo "A5" ;;
        *910A*|*910a*) echo "910a" ;;
        *310B*|*310b*) echo "310b" ;;
        *310P*|*310p*) echo "310p" ;;
        *310*)        echo "310" ;;
        *910*)        echo "910" ;;
        *)            echo "" ;;
    esac
}

# ========== 前置检查 ==========
log "系统检测中..."
ARCH=$(uname -m)
OS_NAME=$(cat /etc/os-release 2>/dev/null | grep '^ID=' | cut -d= -f2 | tr -d '"')
OS_VERSION=$(cat /etc/os-release 2>/dev/null | grep '^VERSION_ID=' | cut -d= -f2 | tr -d '"')
log "  架构: $ARCH"
log "  OS: $OS_NAME $OS_VERSION"

# NPU 检测
# 在部分环境（如 950）下 npu-smi info 可能卡住很长时间，优先使用 asys；
# 未装 CANN 时 asys 不可用，再降级到带超时的 npu-smi。
detect_npu() {
    if command -v asys &>/dev/null; then
        local info
        info=$(asys info -r=status 2>/dev/null | head -20 || true)
        if [ -n "$info" ]; then
            log "  NPU (asys):"
            printf '%s\n' "$info" | sed 's/^/    /'
            return 0
        fi
    fi
    if command -v npu-smi &>/dev/null; then
        local info
        if command -v timeout &>/dev/null; then
            info=$(timeout 10s npu-smi info 2>/dev/null | grep -E '^\| *[0-9]' | head -1 || true)
        else
            info=$(npu-smi info 2>/dev/null | grep -E '^\| *[0-9]' | head -1 || true)
        fi
        if [ -n "$info" ]; then
            log "  NPU (npu-smi): $info"
        else
            log "  NPU: npu-smi 未返回信息（驱动可能未安装或命令超时）"
        fi
    else
        log "  NPU: 未找到 asys / npu-smi（驱动可能未安装）"
    fi
}
detect_npu

# 当前 CANN 检测
if [ -n "${ASCEND_TOOLKIT_HOME:-}" ]; then
    log "  当前 ASCEND_TOOLKIT_HOME: $ASCEND_TOOLKIT_HOME"
else
    log "  当前 ASCEND_TOOLKIT_HOME: 未设置"
fi

# （CANN 版本与下载地址按平台在 resolve_online_urls() 中维护，无需在此推导。）

# 确定工作模式
ONLINE_MODE=false
if [ -z "$PKG_DIR" ]; then
    ONLINE_MODE=true
fi

# 解析 SoC：显式 --soc 优先，否则自动探测（npu-smi/asys）。
# 在线模式必需（用来选 kernels 包）；本地模式仅用于展示（包名来自目录扫描）。
if [ -z "$SOC" ]; then
    SOC=$(detect_soc)
    if [ -n "$SOC" ]; then
        log "自动探测 SoC 平台: $SOC"
    else
        log "未能自动探测 SoC 平台"
    fi
fi
if [ -z "$SOC" ]; then
    if [ "$ONLINE_MODE" = true ]; then
        fail "在线模式必须知道 SoC，请用 --soc 指定（A2/A3/A5 或 910b/910c/950）"
    else
        SOC="(未指定)"
    fi
fi
log "  SoC: $SOC"

# 在线模式前置检查
if [ "$ONLINE_MODE" = true ]; then
    if [ "$INSTALL_DRIVER" = true ]; then
        fail "在线安装暂不支持驱动包自动下载，请改用 --pkg-dir 提供本地驱动包，或省略 --install-driver"
    fi
    if ! command -v wget &>/dev/null && ! command -v curl &>/dev/null; then
        fail "在线安装需要 wget 或 curl，请先安装其中一个"
    fi
    if [ -z "$DOWNLOAD_DIR" ]; then
        DOWNLOAD_DIR=$(mktemp -d -t cann_download.XXXXXX)
    fi
    mkdir -p "$DOWNLOAD_DIR" || fail "无法创建下载目录: $DOWNLOAD_DIR"
    log "在线安装模式: SoC $SOC, 架构 $ARCH（CANN 版本与下载地址见下方清单）"
    log "下载目录: $DOWNLOAD_DIR"
fi

# ========== 包识别 / 下载 ==========
declare -A PKGS

# 本地模式：扫描目录
detect_pkg() {
    local key="$1" pattern="$2"
    local found
    found=$(find "$PKG_DIR" -maxdepth 1 -type f \( -name "*.run" -o -name "*.tar.gz" -o -name "*.zip" \) | grep -iE "$pattern" | head -1)
    PKGS[$key]="$found"
    if [ -n "$found" ]; then
        log "  识别到 [$key]: $(basename "$found")"
    else
        log "  未识别 [$key]"
    fi
}

# 在线模式：构造 URL 并下载到 download_dir
# 部分内网/代理环境会遇到自签名证书，若 INSECURE=true 或首次下载因证书失败，
# 则使用 --no-check-certificate 重试一次。
download_pkg() {
    local name="$1" url="$2" out="$3"
    if [ -f "$out" ]; then
        log "  [$name] 文件已存在，跳过下载: $out"
        return 0
    fi
    log "  [$name] 下载: $url"
    log "         -> $out"

    local wget_extra=""
    [ "$INSECURE" = true ] && wget_extra="--no-check-certificate"

    if command -v wget &>/dev/null; then
        local logfile="$out.wget.log"
        if wget --show-progress $wget_extra -O "$out" "$url" 2>"$logfile"; then
            rm -f "$logfile"
            return 0
        fi
        # 若因证书失败且未显式 --insecure，尝试自动重试一次
        if [ "$INSECURE" = false ] && grep -qiE 'certificate|self-signed|verify' "$logfile" 2>/dev/null; then
            log "  [$name] 证书校验失败，使用 --no-check-certificate 重试..."
            rm -f "$out" "$logfile"
            if wget --show-progress --no-check-certificate -O "$out" "$url" 2>"$logfile"; then
                rm -f "$logfile"
                return 0
            fi
        fi
        rm -f "$out" "$logfile"
    elif command -v curl &>/dev/null; then
        local curl_extra=""
        [ "$INSECURE" = true ] && curl_extra="-k"
        if curl -fSL --progress-bar $curl_extra -o "$out" "$url"; then
            return 0
        fi
        if [ "$INSECURE" = false ]; then
            log "  [$name] curl 下载失败，使用 -k 重试..."
            rm -f "$out"
            if curl -fSLk --progress-bar -o "$out" "$url"; then
                return 0
            fi
        fi
    fi
    rm -f "$out"
    return 1
}

# ========== 版本比对 / 跳过逻辑 ==========
# 同版本已装则跳过该包的下载与安装（toolkit/kernel）。--force 可强制重装。
declare -A SKIP_PKG
TOOLKIT_INSTALL="$PREFIX/ascend-toolkit"

# 从 .run 包文件名提取版本号。
# Ascend-cann_9.1.0-beta.3_linux-aarch64.run           → 9.1.0-beta.3
# Ascend-cann-toolkit_9.0.0_linux-aarch64.run          → 9.0.0
# Ascend-cann-910b-ops_9.1.0-beta.3_linux-aarch64.run  → 9.1.0-beta.3
pkg_version_from_name() {
    basename "$1" | sed -E 's/.*cann[^_]*_//; s/_linux.*//'
}

# 读取已安装包版本（toolkit/ops）。查 <root>/<arch>-linux/ascend_{kind}_install.info 的 version=。
# install root 候选（按优先级）：$ASCEND_TOOLKIT_HOME → $TOOLKIT_INSTALL/latest →
#   $TOOLKIT_INSTALL/cann-* → $PREFIX/cann-*。找不到输出空。
installed_version() {
    local kind="$1" info="ascend_${kind}_install.info"
    local roots=()
    [ -n "${ASCEND_TOOLKIT_HOME:-}" ] && roots+=("$ASCEND_TOOLKIT_HOME")
    roots+=("$TOOLKIT_INSTALL/latest")
    local d
    for d in "$TOOLKIT_INSTALL"/cann-* "$PREFIX"/cann-* ; do
        [ -d "$d" ] && roots+=("$d")
    done
    local f
    for f in "${roots[@]/%//$ARCH-linux/$info}"; do
        if [ -f "$f" ]; then
            grep -E "^version=" "$f" | head -1 | cut -d= -f2
            return 0
        fi
    done
}

# 比对【包版本】与【已装版本】：相同（且非 --force）则置 SKIP_PKG[key]=true。
# 参数: key  pkg_path  kind(toolkit|ops)
reconcile_skip() {
    local key="$1" pkg="$2" kind="$3"
    [ -z "$pkg" ] && return 0
    local pkg_ver inst_ver
    pkg_ver=$(pkg_version_from_name "$pkg")
    if [ -z "$pkg_ver" ]; then
        log "  [$key] 无法从包名解析版本，按需安装"
        return 0
    fi
    inst_ver=$(installed_version "$kind")
    if [ -z "$inst_ver" ]; then
        log "  [$key] 未检测到已装版本 → 安装 $pkg_ver"
    elif [ "$inst_ver" = "$pkg_ver" ]; then
        if [ "$FORCE" = true ]; then
            log "  [$key] 已装 $inst_ver 与包 $pkg_ver 相同；--force 指定，强制重装"
        else
            log "  [$key] 已装 $inst_ver 与包 $pkg_ver 相同 → 跳过（--force 可强制重装）"
            SKIP_PKG[$key]=true
        fi
    else
        log "  [$key] 已装 $inst_ver → 升级到 $pkg_ver"
    fi
}

if [ "$ONLINE_MODE" = true ]; then
    resolve_online_urls "$SOC" \
        || fail "平台 [$SOC] 未配置在线下载地址。请在 resolve_online_urls() 中添加该平台的 toolkit/ops 地址（参考 https://www.hiascend.com/cann/download）"
    [ -z "$TOOLKIT_URL" ] && fail "resolve_online_urls 未设置 TOOLKIT_URL"

    TOOLKIT_URL="${TOOLKIT_URL/__ARCH__/$ARCH}"
    OPS_URL="${OPS_URL/__ARCH__/$ARCH}"
    TOOLKIT_NAME=$(basename "$TOOLKIT_URL")
    OPS_NAME=$(basename "$OPS_URL")

    PKGS[toolkit]="$DOWNLOAD_DIR/$TOOLKIT_NAME"
    PKGS[kernel]="$DOWNLOAD_DIR/$OPS_NAME"

    log "在线包清单 (平台 $SOC, $CANN_VERSION_INFO):"
    log "  toolkit: $TOOLKIT_URL"
    log "  ops:     $OPS_URL"

    # 同版本已装则跳过下载与安装（--force 可强制）
    reconcile_skip toolkit "${PKGS[toolkit]}" toolkit
    reconcile_skip kernel  "${PKGS[kernel]}"  ops

    if [ "$DRY_RUN" = false ]; then
        if [ "${SKIP_PKG[toolkit]:-}" != true ]; then
            download_pkg "toolkit" "$TOOLKIT_URL" "${PKGS[toolkit]}" \
                || fail "toolkit 下载失败：检查网络 / resolve_online_urls() 里 [$SOC] 的 toolkit 地址；OBS 不可达时改用 --pkg-dir 本地包"
        fi
        if [ "${SKIP_PKG[kernel]:-}" != true ]; then
            download_pkg "ops" "$OPS_URL" "${PKGS[kernel]}" \
                || fail "ops 包下载失败：确认 resolve_online_urls() 里 [$SOC] 的 ops 地址正确；OBS 不可达时改用 --pkg-dir 本地包"
        fi
    fi
else
    [ ! -d "$PKG_DIR" ] && fail "包目录不存在: $PKG_DIR"

    log "扫描包目录: $PKG_DIR"
    detect_pkg "driver"    "Ascend.*driver.*\\.run$"
    detect_pkg "toolkit"   "Ascend-cann(-toolkit)?_.*\\.run$"
    detect_pkg "kernel"    "Ascend-cann-(kernels|.*-ops).*\\.run$"
    detect_pkg "firmware"  "Ascend-hdk.*firmware.*\\.run$"
    detect_pkg "nnal"      "Ascend-cann-nnal.*\\.run$"

    # 同版本已装则跳过安装（--force 可强制）
    reconcile_skip toolkit "${PKGS[toolkit]:-}" toolkit
    reconcile_skip kernel  "${PKGS[kernel]:-}"  ops
fi

# 至少要有 toolkit
[ -z "${PKGS[toolkit]:-}" ] && fail "未找到 Ascend-cann-toolkit 安装包。本地模式请确认 --pkg-dir；在线模式请检查版本/架构/网络。"

# ========== 安装前确认 ==========
log ""
log "安装计划:"
log "  工作模式: $([ "$ONLINE_MODE" = true ] && echo "在线安装" || echo "本地安装")"
log "  安装前缀: $PREFIX"
log "  CANN 版本: ${CANN_VERSION_INFO:-(本地包目录)}"
log "  SoC: $SOC"
[ "$INSTALL_DRIVER" = true ] && log "  安装驱动: 是" || log "  安装驱动: 否"
log "  以下 CANN 包将处理:"
for key in driver toolkit kernel firmware nnal; do
    [ -n "${PKGS[$key]:-}" ] || continue
    if [ "${SKIP_PKG[$key]:-}" = true ]; then
        log "    - $key: $(basename "${PKGS[$key]}")  [跳过：已装相同版本]"
    else
        log "    - $key: $(basename "${PKGS[$key]}")"
    fi
done

if [ "$DRY_RUN" = true ]; then
    log ""
    log "DRY RUN 完成，未执行任何下载或安装。"
    exit 0
fi

if [ "$NON_INTERACTIVE" = false ]; then
    confirm "确认开始安装?" || { log "已取消"; exit 0; }
fi

# 运行 .run 安装包：非交互模式下使用 --quiet 自动接受 EULA 并跳过交互。
run_installer() {
    local pkg="$1"; shift
    if [ "$NON_INTERACTIVE" = true ]; then
        bash "$pkg" --quiet "$@"
    else
        bash "$pkg" "$@"
    fi
}

# ========== 安装驱动 ==========
if [ "$INSTALL_DRIVER" = true ]; then
    if [ -n "${PKGS[driver]:-}" ]; then
        if [ "$(id -u)" -ne 0 ]; then
            fail "安装驱动需要 root 权限，请用 sudo 执行。"
        fi
        log "安装驱动: ${PKGS[driver]}"
        run_installer "${PKGS[driver]}" --full --install-path="$PREFIX/driver" || fail "驱动安装失败"
    else
        log "警告: --install-driver 指定但未找到驱动包，跳过"
    fi
fi

# ========== 安装 firmware ==========
if [ -n "${PKGS[firmware]:-}" ]; then
    log "安装 firmware: ${PKGS[firmware]}"
    run_installer "${PKGS[firmware]}" --full --install-path="$PREFIX" || fail "firmware 安装失败"
fi

# ========== 安装 toolkit ==========
if [ "${SKIP_PKG[toolkit]:-}" = true ]; then
    log "跳过 toolkit 安装（已装相同版本）"
else
    log "安装 toolkit: ${PKGS[toolkit]}"
    run_installer "${PKGS[toolkit]}" --install --install-path="$TOOLKIT_INSTALL" || fail "toolkit 安装失败"
fi

# ========== 安装 kernel / ops ==========
if [ -n "${PKGS[kernel]:-}" ]; then
    if [ "${SKIP_PKG[kernel]:-}" = true ]; then
        log "跳过 kernel/ops 安装（已装相同版本）"
    else
        log "安装 kernel/ops: ${PKGS[kernel]}"
        run_installer "${PKGS[kernel]}" --install --install-path="$TOOLKIT_INSTALL" || fail "kernel/ops 安装失败"
    fi
fi

# ========== 安装 nnal ==========
if [ -n "${PKGS[nnal]:-}" ]; then
    log "安装 nnal: ${PKGS[nnal]}"
    run_installer "${PKGS[nnal]}" --install --install-path="$TOOLKIT_INSTALL" || fail "nnal 安装失败"
fi

# ========== 生成 set_env.sh ==========
if [ -z "$SET_ENV_FILE" ]; then
    SET_ENV_FILE="$PREFIX/set_env.sh"
fi

log "生成环境脚本: $SET_ENV_FILE"
mkdir -p "$(dirname "$SET_ENV_FILE")"
cat > "$SET_ENV_FILE" <<EOF
# Ascend CANN 环境变量
# 生成时间: $(date '+%F %T')
# 来源: $0 --prefix $PREFIX

export ASCEND_TOOLKIT_HOME=$TOOLKIT_INSTALL
export ASCEND_HOME_PATH=$TOOLKIT_INSTALL
export ASCEND_OPP_PATH=$TOOLKIT_INSTALL/opp

# driver（若已安装）
if [ -d "$PREFIX/driver/lib64/driver" ]; then
    export LD_LIBRARY_PATH=$PREFIX/driver/lib64/driver:\$LD_LIBRARY_PATH
fi

# toolkit
export LD_LIBRARY_PATH=$TOOLKIT_INSTALL/lib64:\$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=$TOOLKIT_INSTALL/lib64/plugin/opskernel:\$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=$TOOLKIT_INSTALL/lib64/plugin/nnengine:\$LD_LIBRARY_PATH
export PATH=$TOOLKIT_INSTALL/bin:\$PATH
export PATH=$TOOLKIT_INSTALL/compiler/ccec_compiler/bin:\$PATH
export PYTHONPATH=$TOOLKIT_INSTALL/python/site-packages:\$PYTHONPATH

# op plugin
if [ -d "$TOOLKIT_INSTALL/opp/vendors/custom_ops/op_api/lib" ]; then
    export LD_LIBRARY_PATH=$TOOLKIT_INSTALL/opp/vendors/custom_ops/op_api/lib:\$LD_LIBRARY_PATH
fi

# npu-smi
if [ -d "$PREFIX/driver/tools" ]; then
    export PATH=$PREFIX/driver/tools:\$PATH
fi
EOF

# ========== 安装后 NPU 状态检查 ==========
log ""
log "安装后 NPU 状态检查:"
if [ -f "$SET_ENV_FILE" ]; then
    # 在当前 shell 临时 source，以便找到 asys
    (
        # shellcheck source=/dev/null
        . "$SET_ENV_FILE" &>/dev/null
        if command -v asys &>/dev/null; then
            asys info -r=status 2>/dev/null | sed 's/^/  /' || log "  asys info 执行失败"
        else
            log "  未找到 asys（可能 CANN 安装路径不一致），跳过"
        fi
    )
else
    log "  环境脚本不存在，跳过"
fi

# ========== 最终验证 ==========
log ""
log "===== 最终验证 ====="
log ""
log "安装完成。使用方式:"
log "  source $SET_ENV_FILE"
log "  source /usr/local/Ascend/ascend-toolkit/cann/set_env.sh  # 官方环境脚本"
log "  python3 -c 'import acl; print(acl.get_soc_name())'"
log "  asys info -r=status        # 查看 NPU 状态"
log ""
log "若 NPU 驱动未装或版本不匹配，请单独处理驱动。"
