#!/bin/bash
# ============================================================================
# self_evolve_op E2E — moe_re_routing operator (cann-bench L3, ①↔② alignment)
#
# 目的：验证 self-evolution 全链路在 L3 复杂算子（多输入多输出 + 可选输入 +
#       int8）上正确运行。链路：requirement → design → test_design → codegen
#       → deploy → precision_debug → cannbench_adapt → cannbench_eval
#       moe_re_routing 在 cann-bench 有 task（tasks/level3/moe_re_routing/）：
#       - test_design 直接加载 cann-bench cases.csv（20 case，含 null 可选输入
#         per_token_scales、int8 tokens，不调 LLM）
#       - precision_debug 用 cann-bench golden.py（entry=moe_re_routing、
#         input_type=torch）做 ① 本地预检；cannbench_eval 用 cann-bench 自带
#         kernel_eval（调 get_input + 多输出逐个比对）做 ② 权威评分
#       golden/cases 均 CLI 显式传入（13 E1：golden_source/cases_source 已从
#       profile 删除，不做 {op}/{N} 运行期代换）。moe_re_routing 无预构建源码，
#       codegen 从零生成；含 LLM 调用，L3 难度，预计耗时 40 分钟～数小时。
#
# 用法:
#   bash scripts/e2e_self_evolve.sh
#
# 前置依赖:
#   - /home/x00584171/code/cann-bench  （外部只读依赖，需先 clone）
#   - NPU 驱动 + CANN 工具链可用（ascendc-devkit run 会在 dispatch 期预检）
#
# 环境变量覆盖（有默认值）:
#   OP_DIR       算子目录（默认 cann-bench examples/.../ops/moe_re_routing；codegen 生成源码至此）
#   REPO_ROOT_OVERRIDE  cann-bench 仓库根
#   REQUIREMENT  需求文档（默认 cann-bench tasks/level3/moe_re_routing/proto.yaml —— 单一真相源）
#   GOLDEN       verify 精度 golden.py（默认 cann-bench tasks/level3/moe_re_routing/golden.py）。
#   GOLDEN_ENTRY golden 入口函数名（默认 moe_re_routing）
#   GOLDEN_INPUT_TYPE  golden 期望输入类型（默认 torch）
#   CASES        cann-bench cases.csv 路径（默认 tasks/level3/moe_re_routing/cases.csv）。
#                传 CASES= 则 test_design 走 LLM 链路（无外部用例）。
#   CHIP_VERSION  设计目标芯片代际码(canonical A2/A3/A5);不传则不指定 → CLI probe 本机硬件。
#                 CLI 旧 --chip-version 已废弃(P29),现映射 --design-target-chip(编译 soc_version 权威源;
#                 A2=910B/A3=910C/A5=950;编译期固定,跨代际二进制不可执行)
#   NPU_ID        NPU 卡号
#   SKIP_INSTALL  1=跳过 pip install
#   WORKFLOW_TIMEOUT  全局 workflow 超时秒(默认 13200=3h40m;0=禁用;首次/resume 共用)
#   STAGE_TIMEOUT     单 stage 超时秒(默认 4800;0=禁用;首次/resume 共用)
#   OUTPUT_ROOT       输出根目录(默认 cwd/output;可设为绝对路径便于平台收集)
# ============================================================================
set -uo pipefail

# torch_npu autoload 冲突兜底：某些 torch_npu 版本不自我关闭 device-backend autoload，
# 导致 NPU 子进程 import torch_npu 时 npu 被注册两次 → RuntimeError "npu and npu"
# （cannbench_eval 的 Evaluator 初始化即崩，20260709-094500 跑崩于此）。autoload=0 是
# torch_npu 官方推荐值。stage 层（cannbench_eval/deploy）已 setdefault 兜底，此处再
# export 一份：让直接跑的子进程也免疫、并自文档化本链路依赖该变量。${:-0} 尊重已有值。
export TORCH_DEVICE_BACKEND_AUTOLOAD="${TORCH_DEVICE_BACKEND_AUTOLOAD:-0}"

# CANN set_env.sh 只加了 lib64/，aarch64-linux/lib64/ 也需要加入。
# 注意：嵌套路径 cann-9.1.0/cann-9.1.0/ 下的库版本不兼容（libge_runner_v2.so
# 缺少符号），必须用顶层 aarch64-linux/lib64/ 而非嵌套路径，否则会覆盖正确库。
_CANN_HOME="${ASCEND_HOME_PATH:-/usr/local/Ascend/cann-9.1.0}"
export LD_LIBRARY_PATH="${_CANN_HOME}/aarch64-linux/lib64:${_CANN_HOME}/lib64:${LD_LIBRARY_PATH}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"   # 固定 cwd=devkit 根：ascendc-devkit output_root 默认=cwd/output，
                  # 须落仓内 + 首次/resume 同 workspace（从任意目录起都对）
# moe_re_routing 的 cann-bench task 在 tasks/level3/moe_re_routing/；算子源码由 codegen
# 生成到 examples/aclnn_launch_example/csrc/ops/moe_re_routing/（cann-bench CMake 用 glob
# 自动收录；cannbench_adapt 负责补 __init__.py wrapper 等 glue）。
OP_DIR="${OP_DIR:-/home/x00584171/code/cann-bench/examples/aclnn_launch_example/csrc/ops/moe_re_routing}"
# banner 显示用的算子名从 OP_DIR 派生（单一真相源 = 实际生成源码的目录），
# 而非硬编码字面量——OP_DIR 经 env 覆盖跑别的算子时 banner 随之正确，不自相矛盾（P133/§1.12）。
OP_NAME="$(basename "$OP_DIR")"
REPO="${REPO_ROOT_OVERRIDE:-/home/x00584171/code/cann-bench}"
# 需求直接取自 cann-bench task 目录（单一真相源，零漂移）：proto.yaml 是结构化算子规格
# （formula / attrs expert_token_num_type|idx_type / inputs tokens|expert_token_num_per_rank|per_token_scales?
# / outputs permute_tokens|permute_per_token_scales|permute_token_idx|expert_token_num / dtypes）。
REQUIREMENT="${REQUIREMENT:-$REPO/tasks/level3/moe_re_routing/proto.yaml}"
# cann-bench task 目录是双文件需求：proto.yaml（结构化规格，确定性解析源）+
# desc.md（自然语言需求：精度标准/边界/调用示例）。desc.md 不参与确定性解析，但作
# 为附加需求材料（--requirement-aux）进 requirement 工作目录供 agent 阅读。此处
# 由脚本负责发现同目录 desc.md（框架不做隐式扫描，§1.12 不耦合 cann-bench 布局）。
AUX_OPTS=()
_req_dir="$(dirname "$REQUIREMENT")"
if [[ -f "$_req_dir/desc.md" ]]; then
    AUX_OPTS=(--requirement-aux "$_req_dir/desc.md")
fi
# 13 E1：golden 与 cases 均 CLI 显式传入（golden_source/cases_source 已从 profile 删除，
# 不再做 {op}/{N} 代换）。moe_re_routing 默认指向 cann-bench tasks/level3/moe_re_routing/
# 下的 golden.py/cases.csv。golden 入口 = moe_re_routing（4 输出 tuple）；input_type=torch。
GOLDEN="${GOLDEN:-$REPO/tasks/level3/moe_re_routing/golden.py}"
GOLDEN_ENTRY="${GOLDEN_ENTRY:-moe_re_routing}"
GOLDEN_INPUT_TYPE="${GOLDEN_INPUT_TYPE:-torch}"
CASES="${CASES:-$REPO/tasks/level3/moe_re_routing/cases.csv}"
CHIP="${CHIP_VERSION:-}"   # 设计目标代际码(canonical A2/A3/A5);空则不传 → CLI probe 本机硬件
                             # （A2=910B/A3=910C;编译 soc_version 编译期固定,跨代际二进制不可执行,
                             #  故必须匹配硬件。CLI click.Choice 仅认 A2/A3/A5）
NPU="${NPU_ID:-}"   # 留空不传 → card pool 自动选空闲卡（device 探活保可用）
# 必须在 banner(下方 echo)引用前赋默认,否则 set -u 会在引用未绑定变量时误杀脚本。
# banner 之后、CONTROL_OPTS 复用它;单一真相源,勿在别处再赋默认。
OUTPUT_ROOT="${OUTPUT_ROOT:-output}"

echo "═══════════════════════════════════════════════════════════════"
echo "  self_evolve_op E2E: $OP_NAME operator (cann-bench L3, ①↔② alignment)"
echo "  op_dir:       $OP_DIR"
echo "  repo:         $REPO"
echo "  requirement:  $REQUIREMENT  (cann-bench task)"
echo "  requirement_aux: ${AUX_OPTS[*]:-(none → 同目录无 desc.md)}"
echo "  golden:       $GOLDEN"
echo "  golden_entry: $GOLDEN_ENTRY"
echo "  golden_input_type: $GOLDEN_INPUT_TYPE"
echo "  cases:        ${CASES:-(none → LLM test-design chain)}"
echo "  chip:         ${CHIP:-(未指定→probe 本机)}"
echo "  npu:          ${NPU:-auto (pool)}"
echo "  output_root:  $OUTPUT_ROOT"
echo "═══════════════════════════════════════════════════════════════"

# 安装当前工程 (editable)
if [[ "${SKIP_INSTALL:-0}" != "1" ]]; then
    echo "[install] pip install -e $REPO_ROOT"
    pip install -e "$REPO_ROOT" || { echo "安装失败"; exit 1; }
fi

# 确定性运行控制参数(首次 run 与 resume 共用单一权威源):非交互 + default 决策 +
# 全局/单 stage 超时。显式传既自文档化,又抗 state 污染(历史 snapshot 若被改坏,显式
# 值覆盖回正确态;依赖 Bug A 修复——resume 时非 None 值覆盖 state)。timeout 值经
# WORKFLOW_TIMEOUT/STAGE_TIMEOUT 环境变量覆盖,故 RESUME_OPTS 不再承担 timeout 调整
# (以免与 CONTROL_OPTS 同名参数 click 冲突)。
WORKFLOW_TIMEOUT="${WORKFLOW_TIMEOUT:-13200}"
STAGE_TIMEOUT="${STAGE_TIMEOUT:-4800}"
CONTROL_OPTS=(--non-interactive --on-decision default
  --workflow-timeout "$WORKFLOW_TIMEOUT" --stage-timeout "$STAGE_TIMEOUT"
  --output-root "$OUTPUT_ROOT")

# 13 E1：golden 三参必传 + cases 显式（cases 为空时 test_design 走 LLM 链路）。
ENABLE_STUBBED="${ENABLE_STUBBED:-0}"
STUB_OPTS=()
if [[ "$ENABLE_STUBBED" == "1" ]]; then
    STUB_OPTS=(--enable-stubbed)
fi
ARGS=(--workflow self_evolve_op --op-dir "$OP_DIR" --repo-root "$REPO"
  --requirement "$REQUIREMENT" --mode new
  "${AUX_OPTS[@]}"
  "${CONTROL_OPTS[@]}"
  "${STUB_OPTS[@]}"
  --golden "$GOLDEN" --golden-entry "$GOLDEN_ENTRY" --golden-input-type "$GOLDEN_INPUT_TYPE")
[[ -n "${NPU:-}" ]] && ARGS+=(--npu-id "$NPU")   # 未指定 → card pool 自动选卡
[[ -n "$CHIP" ]] && ARGS+=(--design-target-chip "$CHIP" --runtime-target-chip "$CHIP")
if [[ -n "$CASES" ]]; then
    ARGS+=(--cann-bench-cases "$CASES")
fi

# resume 模式:RESUME=<run_id> bash scripts/e2e_self_evolve.sh
RESUME="${RESUME:-}"
if [[ -n "$RESUME" ]]; then
  # 切勿带 --workflow / --op-dir / --requirement / --golden* 等 A 类参数:
  # --workflow 与 state 冲突会触发 EX_USAGE;其余被 dispatcher resume 分支静默忽略(P31)。
  # 确定性控制参数(CONTROL_OPTS)显式传,与首次 run 同模式;改 timeout 用 WORKFLOW_TIMEOUT/
  # STAGE_TIMEOUT 环境变量,勿放 RESUME_OPTS(否则与 CONTROL_OPTS 同名参数 click 冲突)。
  # 权威日志由 dispatcher 落 output/<RESUME>/run.log(resume 时 append 到首次 run 同一文件)。
  echo "[resume] run_id=$RESUME  权威日志 → output/$RESUME/run.log"
  # RESUME_OPTS:resume 专用额外参数(勿重复 CONTROL_OPTS 已有项)。
  # shellcheck disable=SC2086
  ascendc-devkit run --resume "$RESUME" "${CONTROL_OPTS[@]}" ${RESUME_OPTS:-}
  RC=$?
  echo ""
  echo "exit code: $RC"
  exit "$RC"
fi

# 首次 run:权威日志由 dispatcher 落 output/<run_id>/run.log(自动按 run_id 命名、
# run 目录自包含);run_id 见上方 dispatcher 启动日志,resume 用法见文件头注释。
ascendc-devkit run "${ARGS[@]}"
RC=$?
echo ""
echo "exit code: $RC"
echo "[log]    → output/<run_id>/run.log  (run_id 见上方 dispatcher 日志)"
echo "[resume] RESUME=<run_id> bash scripts/e2e_self_evolve.sh"
exit $RC
