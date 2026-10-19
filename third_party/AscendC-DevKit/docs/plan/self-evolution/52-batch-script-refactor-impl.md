# 52 — batch_self_evolve.sh 瘦身为 manifest 生成器（L4 实施方案）

> 工作线：self-evolution / 批跑 20260715 非 429 问题收口
> 状态：**L4 方案（待实施）**
> 覆盖问题：L3 疑似 5（§2.5 双通路架构债）+ 疑似 6（`sort|tail -1`）+ 疑似 7（`RESUME=1` 泄漏）
> 关联：L3 `50-non429-issues-analysis.md` §5/§6/§7、L3 `41-batch-fusion-analysis.md`（两阶段解耦）、L4 `42-batch-fusion-impl.md`（框架 `--batch` 已交付）

## 1. 背景

框架 `ascendc-devkit run --batch`（`batch_runner.py`）已完整实现：
- `ThreadPoolExecutor` 并发调度
- `NPUSlotManager` subprocess 级卡池
- manifest YAML 驱动（`top_defaults` + `tasks[]`，字段 1:1 = `run_cmd` CLI dest）
- RESUME 支持（manifest 项写 `resume_from` 即续跑）
- 1 项自动退化单算子 dispatch

当前 `batch_self_evolve.sh` 仍使用自建的 FIFO/fork/wait/concurrency 控制，与框架 `--batch` 并存——§2.5 双通路债务。脚本 ~350 行中约 200 行是框架已覆盖的职责（并发调度 / 卡池 / 状态追踪 / 结果汇总）。本次将脚本瘦身为"worktree 准备 + manifest 生成器"，删除已被框架取代的逻辑。

## 2. 职责重新划分

| 职责 | 当前（shell 自建） | 改造后 |
|------|-------------------|--------|
| CANN 环境 setup | shell source set_env.sh | 保留，不变 |
| worktree 创建/复用 | shell git worktree add | **保留**——仓侧职责，不进 Python（§1.7） |
| task 层级解析 | shell resolve_task_level() | **保留**——仓侧职责（§41-batch-fusion §2.2c） |
| task 文件校验 | shell 逐个校验 proto.yaml/golden.py | **保留**——manifest 生成前的加载期校验（§1.3） |
| manifest 生成 | 无（shell 直接调 e2e） | **新增**——YAML 写入 `WORKTREE_ROOT/manifest.yaml` |
| 并发调度 | shell fork + wait + PID 收集 | **删**——框架 `ThreadPoolExecutor` |
| 卡池分配 | shell mkfifo FIFO + read/echo | **删**——框架 `NPUSlotManager` |
| 活性互斥 | shell flock(.lock.$op) | **删**——框架 `ThreadPoolExecutor` 保证每 task 一线程 |
| .status/.runid 文件 | shell 自管理 | **删**——框架 `output/<run_id>/` 自包含 |
| RESUME 判定 | shell 读 .status/.runid → 分支 | **转为** manifest `resume_from` 字段 |
| per-op 日志 | shell 重定向到 logs/batch_<op>.log | **删**——框架 `output/<run_id>/run.log` 自包含 |
| 结果汇总 | shell 读 .status + grep run_id | **转为** 框架 `BatchResult.summary()` |
| worktree 清理 | shell git worktree remove | 保留 |

## 3. 改动（脚本级）

### 3.1 删除的逻辑（~200 行 → 删除）

- **L134-144**：`detect_npu_count()` + `MAX_CONCURRENT` 计算。框架 `resolve_card_pool()` 四级 fallback 已覆盖。
- **L188-193**：FIFO 卡池（`mkfifo` / `exec 3<>` / `echo $c >&3`）。框架 `NPUSlotManager` 已覆盖。
- **L214-308**：`run_one()` 函数整体。框架 `run_batch()` + `_dispatch_one()` 已覆盖（含 flock / card get-put / 首次 vs 续跑分支 / task 校验 / e2e 调用 / status 写入 / 结果汇总）。
- **L310-316**：`for op in ... run_one "$op" & ... wait`。框架 `ThreadPoolExecutor` + `futures` 已覆盖。
- **L318-333**：结果汇总。框架 `BatchResult.summary()` 已覆盖。
- **L146-157**：`exec > >(tee)` 自重定向。改为简单输出到终端 + manifest 文件，per-op 日志由框架管理。

### 3.2 修改的逻辑（~80 行）

**L117**（疑似 6 修复）：
```bash
# 旧：字典序误选
WORKTREE_ROOT="$(ls -d "$DEVKIT/../cann-bench-batch"/*/ 2>/dev/null | sort | tail -1)"
# 新：按 mtime 取最新
WORKTREE_ROOT="$(ls -dt "$DEVKIT/../cann-bench-batch"/*/ 2>/dev/null | head -1)"
```

**L286**（疑似 7 修复）：随 `run_one()` 删除而不再存在——RESUME 逻辑改为 manifest `resume_from` 字段，不再通过环境变量传递。

### 3.3 新增的逻辑（~50 行）

**manifest 生成**（替代原来的 `run_one` → `bash "$E2E"` 派发）：

```bash
# ---- 准备 manifest 条目 ----
MANIFEST="$WORKTREE_ROOT/manifest.yaml"

# 探测可用卡数（仅作 manifest cards 兜底；框架 resolve_card_pool 也会探）
NPU_COUNT="${NPU_COUNT:-$(npu-smi info 2>/dev/null | grep -cE '^\| [0-9]+ +\|' || echo 8)}"

cat > "$MANIFEST" <<YAML
# batch self_evolve_op — 由 batch_self_evolve.sh 自动生成
cards: [$(seq -s ', ' 0 $((NPU_COUNT - 1)))]
design_concurrency: ${#OPS[@]}
non_interactive: true
on_decision: default
workflow_timeout_sec: 20000
stage_timeout_sec: 4800
tasks:
YAML

for op in "${OPS[@]}"; do
    wt="$WORKTREE_ROOT/$op"
    runid_file="$WORKTREE_ROOT/.runid.$op"
    status_file="$WORKTREE_ROOT/.status.$op"

    # RESUME：跳过已完成
    if [[ "$RESUME_MODE" -eq 1 && "$(cat "$status_file" 2>/dev/null)" == "0" ]]; then
        progress "SKIP  $op (已完成 .status=0)"
        continue
    fi

    # worktree 准备
    if [[ ! -d "$wt" ]]; then
        progress "WT-ADD $op"
        if ! git -C "$CANN_BENCH" worktree add --detach "$wt" 2>&1; then
            progress "FAIL  $op reason=worktree_add"
            continue
        fi
    else
        progress "WT-REUSE $op"
    fi

    rid=""
    [[ "$RESUME_MODE" -eq 1 ]] && rid="$(cat "$runid_file" 2>/dev/null)"

    if [[ -n "$rid" ]]; then
        # —— 续跑 ——
        progress "RESUME $op run_id=$rid"
        cat >> "$MANIFEST" <<YAML
  - op_dir: $wt/examples/aclnn_launch_example/csrc/ops/$op
    repo_root: $wt
    resume_from: "$rid"
YAML
    else
        # —— 从头跑 ——
        level="$(resolve_task_level "$wt" "$op")"
        if [[ "$level" == AMBIGUOUS:* ]]; then
            progress "FAIL  $op reason=ambiguous_level"
            continue
        fi
        if [[ -z "$level" ]]; then
            progress "FAIL  $op reason=no_proto"
            continue
        fi
        task="$wt/tasks/$level/$op"
        if [[ ! -f "$task/proto.yaml" || ! -f "$task/golden.py" ]]; then
            progress "FAIL  $op reason=missing_task_files"
            continue
        fi
        progress "RUN   $op level=$level"
        cat >> "$MANIFEST" <<YAML
  - op_dir: $wt/examples/aclnn_launch_example/csrc/ops/$op
    repo_root: $wt
    workflow: self_evolve_op
    requirement_path: $task/proto.yaml
    golden_path: $task/golden.py
    golden_entry: $op
    golden_input_type: torch
YAML
        [[ -f "$task/cases.csv" ]] && echo "    cases_path: $task/cases.csv" >> "$MANIFEST"
        [[ -n "$CHIP" ]] && echo "    design_target_chip: $CHIP" >> "$MANIFEST"
    fi
done

# ---- 调框架批跑 ----
progress "DISPATCH  ascendc-devkit run --batch $MANIFEST"
ascendc-devkit run --batch "$MANIFEST"
RC=$?

# ---- 结果 ----
if [[ "$RC" -eq 0 ]]; then
    echo ""; echo "═══ 全部通过 ═══"
else
    echo ""; echo "═══ 有失败（详见 output/<run_id>/run.log） ═══"
fi
[[ "$KEEP_WORKTREES" == "1" ]] && echo "[keep] worktree 保留于 $WORKTREE_ROOT"
exit $RC
```

### 3.4 保留不变的逻辑（~80 行）

- CANN 环境 setup（L62-92）——完全不变
- `DEFAULT_OPS` 定义（L64-72）——完全不变
- `RESUME_MODE` 判定（L103-105）——完全不变
- WORKTREE_ROOT / TS 确定（L113-129）——只修 L117 的 `sort|tail -1` → `ls -dt|head -1`
- git 前置校验（L175-177）——完全不变
- `pip install -e`（L179-186）——完全不变
- `resolve_task_level()` 函数（L199-211）——完全不变
- worktree 清理（L335-343）——完全不变
- `progress()` 函数——保留，简化为写 header + 进度行（不再写 per-op tee 日志）

## 4. 删除的依赖

- `$E2E`（`scripts/e2e_self_evolve.sh`）——不再调子进程 e2e，框架 `--batch` 直接调 dispatch
- FIFO 文件 `$WORKTREE_ROOT/.cards.*`
- `.lock.$op` flock 文件
- `.status.$op` 文件——改为读 `output/<run_id>/`（run 自包含）
- `.runid.$op` 文件——保留读取（RESUME 从它取 run_id），但不再写入（框架管理）
- `logs/batch_<op>.log` per-op 日志——改为 `output/<run_id>/run.log`（框架管理）
- `logs/batch_progress_<ts>.log` 进度流——框架 `BatchResult.summary()` 替代

## 5. 脚本行数变化

| 区域 | 旧 | 新 | 变化 |
|------|----|----|------|
| CANN env + 配置 | ~55 行 | ~55 行 | 不变 |
| NPU 探测 + 卡池 | ~30 行 | ~5 行 | -25（框架接管） |
| 日志重定向 | ~12 行 | ~3 行 | -9 |
| `run_one()` 函数 | ~95 行 | 0 | -95（框架接管） |
| 派发 + wait + 汇总 | ~35 行 | ~5 行 | -30 |
| manifest 生成 | 0 | ~50 行 | +50 |
| worktree 清理 | ~12 行 | ~12 行 | 不变 |
| **总计** | **~350 行** | **~130 行** | **-220 行** |

## 6. 实施顺序

1. 备份当前脚本（`cp batch_self_evolve.sh batch_self_evolve.sh.bak`）。
2. 重写脚本（删除 §3.1 逻辑 + 新增 §3.3 manifest 生成）。
3. 验证：用 1-2 个算子测试首次跑 → 检查 manifest YAML 正确生成 → `ascendc-devkit run --batch` 正常调度。
4. 验证续跑：`RESUME=1` 模式 → 检查 manifest 中已完成算子被跳过、未完成算子带 `resume_from`。
5. 清理旧 batch 目录中的 `.lock.*` / `.cards.*` 残留文件（框架不再使用）。

## 7. 验证

- **UT**：框架 `--batch` 路径已有 UT 覆盖（`batch_runner.py` / `run_cmd`），脚本改动不涉及 Python 代码，无需新 UT。
- **ST**：真实 2 算子批跑（首次 + 续跑），验证 manifest 生成正确 + 框架调度正常。
- **边界**：1 项退化（只有 1 个算子时框架走同步 dispatch）、全部已完成（RESUME 时无待跑项→manifest tasks=空→框架报错，需脚本层先判空）。

## 8. 不改（关键边界）

- **框架 `--batch` 代码**：零改动。框架能力已完整，脚本只是换个方式调用它。
- **`e2e_self_evolve.sh`**：不删。单算子 e2e 仍有独立使用场景（手动 `bash scripts/e2e_self_evolve.sh`）。
- **`batch_runner.py` 的 `RunOutcome`**：不补 `run_id` 字段（当前实现 `run_id=None`）。run_id 可通过 `output/` 目录推断，属可观测性增强，不在本 L4 范围。
- **worktree 隔离策略**：不变。每个算子仍是独立 git worktree。
