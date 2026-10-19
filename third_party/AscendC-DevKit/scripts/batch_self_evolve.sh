#!/bin/bash
# ============================================================================
# batch_self_evolve.sh — 多算子并发生成 + cann-bench 评测（worktree 隔离）
#
# 形态（方案 E，docs/plan/self-evolution/54-*.md）：瘦身为「worktree 准备 +
# manifest 生成器」，并发/卡池/状态/续跑全交给工程 `ascendc-devkit run --batch`
# 与 `--resume`。脚本不再自造 fork/FIFO/sidecar（§2.5 双通路收口）。
#
# 分层 ID（方案 E）：
#   - 首跑 `run --batch manifest.yaml` → 工程生成 batch_id，每算子一个
#     execution_id(=run_id)，产物落 output/<batch_id>/<execution_id>/。
#   - 续跑 `run --resume <batch_id>` → 工程列 output/<batch_id>/ 下的 execution
#     目录（文件系统即批→算子映射，无索引文件），逐个复用单算子 resume。
#   - 续跑单算子 `run --resume <execution_id>` → 只续批内某一个（复用单算子 resume）。
#   脚本只记 1 个 batch_id（.batch_id），不再维护 per-op .runid/.status/.lock。
#
# 用法:
#   bash scripts/batch_self_evolve.sh                  # 首跑头部 DEFAULT_TASKS
#   DRY_RUN=1 bash scripts/batch_self_evolve.sh        # 仅生成 manifest + 校验，不派发（无 LLM 成本）
#   RESUME=1 bash scripts/batch_self_evolve.sh         # 续跑最近一批（读 .batch_id）
#   BATCH_ID=<id> RESUME=1 bash scripts/batch_self_evolve.sh   # 显式 batch_id 续跑
#   WORKTREE_ROOT=<旧路径> RESUME=1 bash scripts/batch_self_evolve.sh  # 多历史 batch 时显式指定
#
# 算子任务约定（声明式路径）: DEFAULT_TASKS 直接列出每个算子的 task 目录，
#   相对 $CANN_BENCH 根（如 tasks/level2/<op> 或 bench_lab/kernel_bench/level2/<op>）。
#   算子名 = golden.py 顶层入口函数（§1.13 golden 权威；目录 basename 在
#   task_XXXX_aten_<op> 类数据源下带前缀、与真实算子名不符，按 basename 定
#   golden_entry/op_dir/eval operator 会错位）。worktree 是 cann-bench 完整检出，
#   task 目录相对结构一致，脚本拼 <worktree>/<task_rel> 定位——不再跨源探索、
#   无需 TASK_LEVEL 消歧。
#   数据源（tasks/ vs bench_lab/...）由清单路径显式声明（想换数据源改路径即可）。
#   proto.yaml 需求（必需） golden.py 精度 golden（必需，entry 从 golden.py 派生）
#   cases.csv 测试用例（可选；缺省则 test_design 走 LLM 链路）
#
# 环境变量:
#   RESUME            1=续跑（复用上次 batch_id，框架续跑所有未完成算子）
#   DRY_RUN           1=仅生成 manifest + 加载期校验，不 run --batch 派发（验证清单/路径用）
#   BATCH_ID          续跑时显式指定 batch_id（否则读 WORKTREE_ROOT/.batch_id）
#   CANN_BENCH        cann-bench 基仓（默认 ~/code/cann-bench）
#   CHIP_VERSION      设计目标芯片代际码（A2/A3/A5；不传则 CLI probe 本机）
#   CANN_ENV_SCRIPT   启动前 source 的 CANN set_env（默认 cann-9.1.0-beta.3；置空=沿用当前 shell）
#   NPU_COUNT         显式卡数覆盖（默认 npu-smi 探测，回退 8）
#   WORKTREE_ROOT    worktree 根（首次默认 <devkit>/../cann-bench-batch/<ts>；续跑复用/自动找最新）
#   KEEP_WORKTREES   1=保留（默认）；0=跑完清理
#   SKIP_INSTALL     1=跳过 pip install -e devkit
#
# 日志: logs/batch_<ts>.log（工程 run 全量输出，含 batch_id / per-op exec_id / 结果汇总）
#
# 临时任务机制（首跑模式）：任务目录存在但含未跟踪文件 → 显式临时 commit（标记
#   temp(transient-batch)，只收未跟踪文件，不碰他人改动）→ 批结束（含中断路径）自动
#   git reset --mixed 回 commit 前 HEAD（文件留在磁盘回 untracked 态，不删除）。
#   判定：目录不存在走既有 FAIL；目录存在且 ls-files --others 非空 → 触发。
#   RESUME 模式不触发（worktree 已含任务文件）。SIGKILL 逃逸由下轮遗留检测提示。
#
# 注意：每个算子是真实 LLM 全流程 self_evolve_op（分钟级 + token 成本），属 heavy_llm。
# ============================================================================
set -uo pipefail

# —— 默认算子清单（唯一来源）：每项是相对 $CANN_BENCH 的 task 目录路径（含 proto.yaml/
#    golden.py）。换算子/换数据源直接改这里。首次与 RESUME 同用此清单。 ——
DEFAULT_TASKS=(
    tasks/level1/gelu
    # tasks/level2/rms_norm
    tasks/level3/add_rms_norm_dynamic_quant
    # tasks/level3/moe_re_routing
    tasks/level3/unique
    tasks/level2/interpolate_custom
    tasks/level3/mse_loss_cross_entropy_loss_custom
    tasks/level2/upsample_custom
)

DEVKIT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEVKIT"   # 固定 cwd=devkit 根：output_root 默认=cwd/output，须落仓内 + 首/续同 workspace
# ---- CANN 环境：默认 source beta.3（本机 shell 默认 cann-9.0.0，错配致算子仓 build 不过；
#      置 CANN_ENV_SCRIPT= 沿用当前 shell，或指向当地 set_env.sh）。早于一切子进程 source。----
# Use the default only when the variable is unset; an explicitly empty value
# means "reuse the current shell environment" as documented above.
CANN_ENV_SCRIPT="${CANN_ENV_SCRIPT-/usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh}"
if [[ -n "$CANN_ENV_SCRIPT" ]]; then
    if [[ -f "$CANN_ENV_SCRIPT" ]]; then
        # set_env.sh 以 export VAR=...:$VAR 引用未设变量；set -u 下报 unbound 且 export 行不
        # 完成 → CANN 路径未落地。source 前临时关 -u、source 完恢复（只豁免这一段）。
        # shellcheck disable=SC1090
        set +u; source "$CANN_ENV_SCRIPT"; set -u
    else
        echo "[FATAL] CANN_ENV_SCRIPT 指定的文件不存在: $CANN_ENV_SCRIPT（置空 CANN_ENV_SCRIPT= 可沿用当前 shell）" >&2
        exit 1
    fi
fi

LOG_DIR="$DEVKIT/logs"
mkdir -p "$LOG_DIR"

CANN_BENCH="${CANN_BENCH:-/home/x00584171/code/cann-bench}"
CHIP="${CHIP_VERSION:-}"
# repo_profile：worktree 检出在 cann-bench-batch/<ts>/<op>/，路径段 cann-bench-batch
# 不在 op_dir_resolver 的 known profile 列表（cann-bench/omni-ops/...）→ 解析 unmatched。
# 显式声明 profile 让 resolve_op_dir 走 profile_override 正确加载（否则加载期校验 raise；
# 也恢复 reference_roots/build_in_repo gate 等依赖 profile 的能力）。脚本默认为 cann-bench 仓。
REPO_PROFILE="${REPO_PROFILE:-cann-bench}"
KEEP_WORKTREES="${KEEP_WORKTREES:-1}"
DRY_RUN="${DRY_RUN:-0}"

# ---- 续跑模式判定 ----
RESUME_MODE=0
[[ "${RESUME:-}" == "1" ]] && RESUME_MODE=1

# ---- task 列表：头部 DEFAULT_TASKS 唯一来源（去重保险）----
#    每项是相对 $CANN_BENCH 的 task 目录路径（如 tasks/level2/<op>）。basename 即算子名。
TASKS=("${DEFAULT_TASKS[@]}")
mapfile -t TASKS < <(printf '%s\n' "${TASKS[@]}" | awk '!seen[$0]++')
[[ ${#TASKS[@]} -gt 0 ]] || { echo "[FATAL] DEFAULT_TASKS 为空，请编辑脚本头部清单" >&2; exit 2; }

# ---- WORKTREE_ROOT / TS：首次新建，续跑按 mtime 找最新（修疑似6：旧 sort|tail
#      字典序误选 sixops_* 等非时间戳前缀目录；ls -dt 按修改时间取最新）----
if [[ "$RESUME_MODE" -eq 1 ]]; then
    if [[ -z "${WORKTREE_ROOT:-}" ]]; then
        WORKTREE_ROOT="$(ls -dt "$DEVKIT/../cann-bench-batch"/*/ 2>/dev/null | head -1)"
        WORKTREE_ROOT="${WORKTREE_ROOT%/}"   # 去尾斜杠
        if [[ -z "$WORKTREE_ROOT" ]]; then
            echo "[FATAL] RESUME=1 但找不到历史 batch 目录（$DEVKIT/../cann-bench-batch/<ts>/）" >&2
            echo "        显式指定: WORKTREE_ROOT=<旧路径> RESUME=1 bash $0 ..." >&2
            exit 1
        fi
    fi
    TS="$(basename "$WORKTREE_ROOT")"
else
    TS="$(date +%Y%m%d_%H%M%S)"
    WORKTREE_ROOT="${WORKTREE_ROOT:-$DEVKIT/../cann-bench-batch/$TS}"
fi
mkdir -p "$WORKTREE_ROOT"

# ---- batch_id（续跑句柄）：续跑时 BATCH_ID env > WORKTREE_ROOT/.batch_id ----
BATCH_ID="${BATCH_ID:-}"
if [[ "$RESUME_MODE" -eq 1 ]]; then
    if [[ -z "$BATCH_ID" && -f "$WORKTREE_ROOT/.batch_id" ]]; then
        BATCH_ID="$(cat "$WORKTREE_ROOT/.batch_id" 2>/dev/null || true)"
    fi
    if [[ -z "$BATCH_ID" ]]; then
        echo "[FATAL] 续跑需要 batch_id：设 BATCH_ID=<id>，或确保 $WORKTREE_ROOT/.batch_id 存在" >&2
        echo "        （batch_id 见首次跑日志 logs/batch_${TS}.log 的 'batch_id:' 行）" >&2
        exit 1
    fi
fi

# ---- 卡数（仅作 manifest cards / 续跑 --cards 兜底；框架 resolve_card_pool 也会探）----
# 数「卡主行」（首格=NPU号+名字合并格：序号后跟非竖线内容；与 infra/npu_smi.py
# _CARD_ROW 同形）——子行（Chip/Bus：序号后仍是竖线）天然被排除，多芯卡不会高估。
detect_npu_count() {
    if [[ -n "${NPU_COUNT:-}" ]]; then
        # 逃生口校验：非正整数（含 0/负/非数字/前导零八进制陷阱）当场响亮退出——
        # 否则 bash 算术静默得 -1 → seq 输出空 → manifest cards: [] → 错误现场
        # （任务级卡池空）离根因（env 敲错）非常远（§1.2 可诊断）。
        [[ "$NPU_COUNT" =~ ^[1-9][0-9]*$ ]] || {
            echo "NPU_COUNT 必须为正整数, got: '$NPU_COUNT'" >&2; exit 2; }
        echo "$NPU_COUNT"; return
    fi
    local n; n=$(npu-smi info 2>/dev/null | grep -cE '^\| *[0-9]+ +[^|[:space:]]') || true
    [[ -z "$n" || "$n" -eq 0 ]] && n=8
    echo "$n"
}
NPU_COUNT_VAL="$(detect_npu_count)"
CARDS="$(seq -s ',' 0 $((NPU_COUNT_VAL - 1)))"   # "0,1,...,N-1"

progress() { echo "[$(date '+%F %T')] $*"; }

# ---- 前置校验 ----
if ! git -C "$CANN_BENCH" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[FATAL] $CANN_BENCH 不是 git 仓，无法 worktree" >&2; exit 1
fi

# 一次性装 devkit（续跑跳过）：避免并发子进程 pip install 互踩。
if [[ "${SKIP_INSTALL:-0}" != "1" ]]; then
    echo "[install] pip install -e $DEVKIT"
    if ! pip install -e "$DEVKIT"; then
        echo "[FATAL] devkit 安装失败" >&2; exit 1
    fi
fi
export SKIP_INSTALL=1

LOG="$LOG_DIR/batch_${TS}.log"

echo "═══════════════════════════════════════════════════════════════"
if [[ "$RESUME_MODE" -eq 1 ]]; then
    echo "  batch self_evolve_op — 续跑  [batch_id=$BATCH_ID]"
else
    echo "  batch self_evolve_op — worktree 隔离并发（首跑）"
fi
echo "  task(${#TASKS[@]}):        ${TASKS[*]}"
echo "  cann-bench 基仓: $CANN_BENCH"
echo "  worktree 根:     $WORKTREE_ROOT"
echo "  卡数:            $NPU_COUNT_VAL  (cards=$CARDS)"
echo "  chip:            ${CHIP:-(未指定→probe 本机)}    保留 worktree: $KEEP_WORKTREES"
echo "  总日志:          $LOG"
echo "═══════════════════════════════════════════════════════════════"

# ---- 临时任务提交（首跑前置）：任务目录含未跟踪文件 → 临时 commit，批毕自动 reset ----
# 触发判据：目录存在 && ls-files --others --exclude-standard 非空（覆盖整目录 untracked 与
# tracked 目录新增文件的混合形态；--exclude-standard 天然排除 __pycache__ 等 gitignore 项）。
# 安全设计（共享机器）：暂存区非空拒绝跑（防卷入他人暂存）；只 add 未跟踪文件；reset 前校验
# HEAD 仍为本轮临时 commit；reset 用 --mixed（文件留盘回 untracked，不删）；trap 兜中断路径。
_TEMP_BASE_SHA=""
_TEMP_SHA=""
_temp_reset() {
    if [[ -n "$_TEMP_SHA" && -d "$CANN_BENCH" ]]; then
        local cur; cur="$(git -C "$CANN_BENCH" rev-parse HEAD 2>/dev/null || true)"
        if [[ "$cur" == "$_TEMP_SHA" ]]; then
            git -C "$CANN_BENCH" reset --mixed "$_TEMP_BASE_SHA" >>"$LOG" 2>&1
            progress "TEMP-RESET OK  HEAD ${_TEMP_SHA:0:8} → ${_TEMP_BASE_SHA:0:8}（任务文件回 untracked 态，未删除）"
        else
            echo "[WARN] TEMP-RESET 跳过：HEAD=${cur:0:8} 非本轮临时 commit ${_TEMP_SHA:0:8}（期间有他人提交落入）。人工执行: git -C $CANN_BENCH reset --mixed $_TEMP_BASE_SHA" >&2
        fi
    fi
}

if [[ "$RESUME_MODE" -eq 0 ]]; then
    # 遗留检测：上轮 SIGKILL/断电逃逸 trap 留下的临时 commit（只提示，不自动删）。
    # 注意须显式 HEAD 作正根：只写 --not --remotes 时 git 不再隐式加 HEAD，遍历集为空。
    _leftover="$(git -C "$CANN_BENCH" log --oneline HEAD --grep='temp(transient-batch)' --not --remotes -3 2>/dev/null)"
    if [[ -n "$_leftover" ]]; then
        echo "[WARN] 发现未 reset 的历史临时 commit（上轮异常终止？）：" >&2
        echo "$_leftover" >&2
        echo "        人工清理: git -C $CANN_BENCH reset --mixed <上方提交的父提交>" >&2
    fi
    # 暂存区断言：非空即拒（共享机器防卷入他人暂存内容）
    if [[ -n "$(git -C "$CANN_BENCH" diff --cached --name-only)" ]]; then
        echo "[FATAL] cann-bench 暂存区非空，为避免卷入拒绝临时 commit；处理后重试（git restore --staged . 或自行提交）" >&2
        exit 1
    fi
    _temp_tasks=()
    for task_rel in "${TASKS[@]}"; do
        if [[ -d "$CANN_BENCH/$task_rel" ]] && \
           [[ -n "$(git -C "$CANN_BENCH" ls-files --others --exclude-standard -- "$task_rel")" ]]; then
            _temp_tasks+=("$task_rel")
        fi
    done
    if [[ ${#_temp_tasks[@]} -gt 0 ]]; then
        _TEMP_BASE_SHA="$(git -C "$CANN_BENCH" rev-parse HEAD)"
        git -C "$CANN_BENCH" ls-files --others --exclude-standard -z -- "${_temp_tasks[@]}" \
            | xargs -0 -r git -C "$CANN_BENCH" add --
        if ! git -C "$CANN_BENCH" commit -m "temp(transient-batch): ${_temp_tasks[*]}（批毕自动 reset）" >>"$LOG" 2>&1; then
            # 还原暂存区：trap 此刻未装（commit 成功才装），不还原则 add 进去的文件
            # 滞留共享暂存区，会被他人后续 commit 卷走
            git -C "$CANN_BENCH" restore --staged -- "${_temp_tasks[@]}" 2>/dev/null || true
            echo "[FATAL] 临时 commit 失败（已还原暂存区；见 $LOG）" >&2; exit 1
        fi
        _TEMP_SHA="$(git -C "$CANN_BENCH" rev-parse HEAD)"
        trap '_temp_reset' EXIT
        trap 'exit 130' INT TERM
        progress "TEMP-COMMIT ${#_temp_tasks[@]} 任务: ${_temp_tasks[*]} sha=${_TEMP_SHA:0:8}（批毕自动 reset 回 ${_TEMP_BASE_SHA:0:8}）"
    fi
fi

# 首跑创建的 worktree（op 名，非 basename）——清理用；RESUME 模式为空数组。
_CREATED_WTS=()

if [[ "$RESUME_MODE" -eq 1 ]]; then
    # ===================== 续跑：run --resume <batch_id> =====================
    # 框架列 output/<batch_id>/ 下 execution 目录，逐个复用单算子 resume；
    # 卡池、并发、状态全由框架管（NPUSlotManager + ThreadPoolExecutor）。
    progress "RESUME batch_id=$BATCH_ID"
    ascendc-devkit run --resume "$BATCH_ID" --cards "$CARDS" 2>&1 | tee "$LOG"
    RC=${PIPESTATUS[0]}
else
    # ===================== 首跑：建 worktree + 生成 manifest + run --batch =====================
    MANIFEST="$WORKTREE_ROOT/manifest.yaml"
    progress "生成 manifest: $MANIFEST"
    cat > "$MANIFEST" <<YAML
# batch self_evolve_op — 由 batch_self_evolve.sh 自动生成（方案 E）
cards: [$CARDS]
design_concurrency: ${#TASKS[@]}
repo_profile: $REPO_PROFILE
non_interactive: true
on_decision: default
workflow: self_evolve_op
mode: new
workflow_timeout_sec: ${WORKFLOW_TIMEOUT:-36000}
stage_timeout_sec: ${STAGE_TIMEOUT:-0}
tasks:
YAML

    declare -A _seen_basename=()   # m2: 加载期 basename 去重（§1.3）
    for task_rel in "${TASKS[@]}"; do
        # 加载期校验（§1.3）：task_rel 必须是相对 $CANN_BENCH 的路径（声明式，不探索）
        if [[ "$task_rel" == /* ]]; then
            progress "FAIL  $task_rel reason=abs_path（DEFAULT_TASKS 用相对 \$CANN_BENCH 路径，如 tasks/level2/<op>；勿用绝对路径）"
            continue
        fi
        if [[ ! -d "$CANN_BENCH/$task_rel" ]]; then
            progress "FAIL  $task_rel reason=no_task_dir（$CANN_BENCH/$task_rel 不存在；核对 DEFAULT_TASKS 路径拼写与数据源 tasks/bench_lab）"
            continue
        fi
        if [[ ! -f "$CANN_BENCH/$task_rel/golden.py" ]]; then
            progress "FAIL  $task_rel reason=missing_task_files（$task_rel/golden.py 缺失）"
            continue
        fi
        # op = golden 入口函数名（§1.13 golden 权威）。目录 basename 在
        # task_XXXX_aten_<op> 类数据源下带前缀、与真实算子名不符——按 basename 定
        # golden_entry / op_dir / op_name / eval operator 会全错位（20260818 批
        # 3/3 halt golden_entry_missing 实证）。golden.py 顶层函数经排除 harness
        # 契约辅助 get_input 后须恰好 1 个作为入口；否则加载期 FAIL（§1.3），不猜测。
        op="$(python3 - "$CANN_BENCH/$task_rel/golden.py" <<'PY'
import ast, sys
tree = ast.parse(open(sys.argv[1], encoding="utf-8").read())
fns = [n.name for n in tree.body
       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
fns = [f for f in fns if f != "get_input"]
print(fns[0] if len(fns) == 1 else "")
PY
)"
        if [[ -z "$op" ]]; then
            progress "FAIL  $task_rel reason=golden_entry_ambiguous（$task_rel/golden.py 顶层函数经排除 get_input 后非恰好 1 个 → 无法确定 golden 入口）"
            continue
        fi
        # m2: 加载期校验（§1.3）——同 op 名不同路径会 worktree 目录冲突
        if [[ -n "${_seen_basename[$op]:-}" ]]; then
            progress "FAIL  $op reason=dup_basename（$task_rel 与 ${_seen_basename[$op]} 同 golden 入口 $op → worktree 目录 \$WORKTREE_ROOT/$op 冲突；改名或去重）"
            continue
        fi
        _seen_basename["$op"]="$task_rel"
        wt="$WORKTREE_ROOT/$op"
        # worktree 准备：已存在则复用，否则 add（仓侧职责，不进 Python §1.7）
        if [[ -d "$wt" ]]; then
            progress "WT-REUSE $op"
        else
            progress "WT-ADD   $op"
            if ! git -C "$CANN_BENCH" worktree add --detach "$wt" >>"$LOG" 2>&1; then
                progress "FAIL  $op reason=worktree_add（见 $LOG）"
                continue
            fi
        fi
        _CREATED_WTS+=("$op")   # 记录实际创建/复用的 worktree（清理按 op 名，非 basename）
        # task 目录（worktree 是 cann-bench 完整检出，相对结构一致）+ 文件校验（§1.3）
        task="$wt/$task_rel"
        if [[ ! -f "$task/proto.yaml" || ! -f "$task/golden.py" ]]; then
            progress "FAIL  $op reason=missing_task_files（$task_rel/proto.yaml 或 golden.py 缺失）"
            continue
        fi
        cases_line=""
        [[ -f "$task/cases.csv" ]] && cases_line=$'\n    cases_path: '"$task/cases.csv"
        # cann-bench task 双文件需求：desc.md 是 proto.yaml 之外的自然语言需求（精度/
        # 边界/示例），作 requirement_aux_paths 进 requirement 工作目录供 agent 阅读。
        # 由脚本负责发现（框架不隐式扫描目录，§1.12）。
        aux_line=""
        [[ -f "$task/desc.md" ]] && aux_line=$'\n    requirement_aux_paths: ['"$task/desc.md"']'
        chip_line=""
        [[ -n "$CHIP" ]] && chip_line=$'\n    design_target_chip: '"$CHIP"
        progress "RUN   $op src=$task_rel"
        cat >> "$MANIFEST" <<YAML
  - op_dir: $wt/examples/aclnn_launch_example/csrc/ops/$op
    repo_root: $wt
    requirement_path: $task/proto.yaml
    golden_path: $task/golden.py
    golden_entry: $op
    golden_input_type: torch${cases_line}${aux_line}${chip_line}
YAML
    done

    # manifest tasks 非空校验（全失败则不派发）。task 条目缩进 2 空格 "  - op_dir:"。
    task_count=$(grep -cE '^[[:space:]]*- op_dir:' "$MANIFEST" || true)
    if [[ "$task_count" -eq 0 ]]; then
        echo "[FATAL] manifest 无有效 task（所有算子 worktree/校验失败），见 $LOG" >&2
        exit 1
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        progress "DRY_RUN  manifest 已生成 + 加载期校验通过（$task_count tasks），跳过 run --batch 派发"
        echo "  manifest: $MANIFEST"
        RC=0
    else
        progress "DISPATCH  ascendc-devkit run --batch $MANIFEST  ($task_count tasks)"
        ascendc-devkit run --batch "$MANIFEST" 2>&1 | tee "$LOG"
        RC=${PIPESTATUS[0]}
        # 捕获 batch_id（工程 click.echo "batch_id: ..." 到 stderr，已并入 tee 的 $LOG）
        BATCH_ID="$(grep -oE 'batch_id: [0-9]{8}-[0-9]{6}-[0-9a-f]{6}' "$LOG" 2>/dev/null | head -1 | awk '{print $2}')"
        if [[ -n "$BATCH_ID" ]]; then
            echo "$BATCH_ID" > "$WORKTREE_ROOT/.batch_id"
            echo "  batch_id: $BATCH_ID  （续跑: RESUME=1 bash $0；续单算子: ascendc-devkit run --resume <execution_id>）"
        fi
    fi
fi

# ---- 清理 ----
if [[ "$KEEP_WORKTREES" != "1" ]]; then
    # 按首跑实际创建的 worktree（op 名 = golden 入口）清理——basename 与 op 已脱钩
    # （§1.13 golden entry 派生），按 basename 删会漏删泄漏。
    for op in "${_CREATED_WTS[@]}"; do
        git -C "$CANN_BENCH" worktree remove --force "$WORKTREE_ROOT/$op" 2>/dev/null || true
    done
    echo "[cleanup] worktree 已清理（保留可设 KEEP_WORKTREES=1）"
else
    echo "[keep] worktree 保留于 $WORKTREE_ROOT"
fi

exit "$RC"
