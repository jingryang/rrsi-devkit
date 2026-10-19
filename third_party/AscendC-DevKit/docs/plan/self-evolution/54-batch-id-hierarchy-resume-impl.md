# 54 — 批跑分层 ID（batch_id / execution_id）+ 合一 resume + 脚本瘦身（L4）

> 工作线：self-evolution / 批跑 20260715 非 429 问题收口（疑似 5/6/7 + run_id 缺口）
> 状态：**L4（方案 E，用户拍板，实施中）**
> 取代：`52-batch-script-refactor-impl.md`（旧"瘦身 manifest 生成器 + sidecar"方案——有 run_id 缺口且留 `.runid.<op>` 并行态；本方案治本取代之，52 保留作历史）
> 关联 L3：`50-non429-issues-analysis.md` §3/§4/§5（疑似 6/7/5）、`41-batch-fusion-analysis.md`（两阶段解耦）

## 0. 方案定论（用户逐轮拍板）

四把尺子筛掉的中间方案（留此仅作决策溯源，勿再走）：
- ~~X' diff output/ 反推 run_id~~：从副作用反推框架已知信息，可诊断性/可扩展性/架构合理全不过。
- ~~W new_run_id 注入 + `.runid.<op>` sidecar~~：仍留并行态（sidecar 与 output/ 重复记 run_id）。
- ~~D 框架 runs 查询 CLI 发现~~：可行但新增查询面，且未对齐"批跑/单算子 resume 复用"。

**方案 E（定论）**：分层 ID + 文件系统即映射 + 合一 resume。
- `execution_id` = 现有 `run_id` 语义（一个算子的一次执行；run 目录内容零变化）。
- `batch_id` = 一次批跑的唯一 ID（`new_run_id()` 同款 ts+uuid 格式）。
- 目录：**单算子 `output/<exec>/`（flat，零变化）；批跑 `output/<batch_id>/<exec>/`（nested）**。
- **文件系统即映射**：`ls output/<batch_id>/` = 该批的算子执行目录，**不引入 batch.json 索引文件**（索引永远有与实际目录不一致的风险，目录结构不会）。
- **合一 `--resume <id>`**：内部按**位置**（非字符串，因 batch_id/exec_id 同格式）判三态。
- `execution_id` 由 **batch_runner 预生成注入** dispatch（保证 `output/<batch_id>/<exec>/` 在 dispatch 时即落位）；**单算子 run.py 不注入 → dispatch 自生成**（"单算子与当前一致"保住）。
- **Workspace 零改**：nesting 由 batch_runner 给每 task scope `output_root=<根>/<batch_id>` 表达，`Workspace.create(output_root=...)` 自然落到 nested 路径。

覆盖收口：疑似 5（双通路 §2.5）、疑似 6（`sort|tail`）、疑似 7（`RESUME` 泄漏）、run_id 从未对调用方暴露的预存缺口。

## 1. 数据模型

| 概念 | 身份 | 目录 | 谁生成 |
|---|---|---|---|
| 单算子执行 | `run_id`（= execution_id） | `output/<run_id>/`（flat，不变） | dispatch 内 `Workspace.create`（run_id=None → `new_run_id()`） |
| 批跑 | `batch_id` | `output/<batch_id>/`（装 exec 子目录） | batch_runner `new_run_id()` |
| 批内算子执行 | `execution_id`（= run_id） | `output/<batch_id>/<execution_id>/` | batch_runner 预生成 `new_run_id()`，注入 dispatch |

resume 句柄：**1 个 ID**。单算子 → `--resume <run_id>`；批跑 → `--resume <batch_id>`（续全批）或 `--resume <execution_id>`（续批内单算子，复用单算子 resume）。

## 2. 框架改动（逐文件，单算子路径零变化）

### 2.1 `infra/workspace.py` — 抽 `new_run_id()` 单一源
- 现状：`Workspace.create` 内联 `ts = datetime.now(...).strftime(...); short = uuid.uuid4().hex[:6]; run_id = f"{ts}-{short}"`（:43-46）。
- 改：抽模块级 `def new_run_id() -> str`（同 ts+uuid 逻辑），`Workspace.create(run_id=None)` 内 `run_id = run_id or new_run_id()`。
- 单一源：`new_run_id()` 是 run_id/exec_id/batch_id 三种身份的唯一生成点。

### 2.2 `application/dispatcher.py` — 兑现调用方注入 run_id（1 行）
- :580 `workspace = Workspace.create(output_root=output_root)` → `Workspace.create(output_root=output_root, run_id=task_request.get("run_id"))`。
- 单算子：`task_request` 无 `run_id` 键 → `Workspace.create(run_id=None)` → `new_run_id()` 自生成（行为零变化）。
- 批跑：batch_runner 已注入 `task_request["run_id"]=exec_id` → 直接用 → `output_root/<exec>/`（output_root 已被 scope 成 `<根>/<batch_id>`）→ 落 `output/<batch_id>/<exec>/`。

### 2.3 `application/batch_runner.py` — batch_id 分层 + nested + resume-by-batch

**BatchManifest / load_manifest**：无改动（manifest 仍 `cards/design_concurrency/top_defaults/tasks`）。

**run_batch（首次批跑）**：
```python
def run_batch(manifest, card_pool, progress_callback=None) -> BatchResult:
    from ascendc_devkit.infra.workspace import new_run_id
    batch_id = new_run_id()
    root = manifest.output_root or "output"            # 新：BatchManifest 加 output_root 字段
    nested_root = f"{root}/{batch_id}"
    tasks = manifest.tasks
    # 为每 task 注入 run_id(exec_id) + scoped output_root
    for t in tasks:
        t.setdefault("run_id", new_run_id())           # 预生成 exec_id
        t["output_root"] = nested_root                 # scope → output/<batch_id>/
    ...（ThreadPoolExecutor / _dispatch_one 不变，dispatch 落 nested 路径）...
    return BatchResult(batch_id=batch_id, results=[...])
```
- `_dispatch_one`：`RunOutcome.run_id = tr.get("run_id")`（已预生成，确定性填充，取代旧 None）。
- `BatchResult` 加 `batch_id: str` 字段；`summary()` 含 batch_id + 每 op 的 exec_id。

**resume-by-batch（新函数）**：
```python
def resume_batch(batch_id, output_root="output", ...) -> BatchResult:
    batch_dir = Path(output_root) / batch_id
    # 文件系统即映射：列 exec 子目录
    exec_dirs = [d for d in batch_dir.iterdir() if (d/"state_snapshot.json").exists()]
    if not exec_dirs: raise ConfigError(...)           # 空 batch / 不存在
    tasks = [{"resume_from": d.name, "output_root": str(batch_dir)} for d in exec_dirs]
    manifest = BatchManifest(cards=None, design_concurrency=None, top_defaults={}, tasks=tasks)
    pool = resolve_card_pool(manifest, cli_cards=...)  # 需显式 cards（manifest 无）
    return run_batch_resume(manifest, pool, ...)       # run_batch 的 resume 变体：不重新生成 batch_id/exec_id
```
- 注：resume 走 `_dispatch_one` 的 `resume_from` 分支（已存在，跳过 op_dir resolve）→ dispatch resume 分支 → `Workspace.from_existing(exec_id, output_root=batch_dir)` → 从 `output/<batch_id>/<exec>/` 恢复。**复用单算子 resume 全链路**。

### 2.4 `cli/commands/run.py` — 合一 `--resume <id>`（位置判据三态）

新增 resolver（放 `application/`，L2 纯逻辑，UT 易测）：
```python
def resolve_resume_target(id_, output_root="output"):
    """按位置判 id 是 flat-run / top-batch / nested-exec。返回 ('single', run_id, output_root)
    或 ('batch', batch_id, output_root)；都不中 raise ConfigError。"""
    base = Path(output_root)
    direct = base / id_
    if (direct / "state_snapshot.json").exists():      # 态1：flat 单算子 run
        return ("single", id_, output_root)
    if direct.is_dir():                                 # 态2：top-level batch 目录
        kids = [d for d in direct.iterdir() if (d/"state_snapshot.json").exists()]
        if kids:
            return ("batch", id_, output_root)
    matches = list(base.glob(f"*/{id_}"))               # 态3：nested exec
    matches = [m for m in matches if (m/"state_snapshot.json").exists()]
    if len(matches) == 1:
        return ("single", id_, str(matches[0].parent)) # output_root = output/<batch_id>
    if len(matches) > 1:
        raise ConfigError(..., f"id 命中多个 nested exec: {matches}")
    raise ConfigError(..., f"output/ 下找不到 run/batch: {id_}")
```
判据纯位置（目录直接含 state_snapshot = run；含 run 子目录 = batch；都不中 glob nested），**字符串同格式无歧义**。

run.py `run_cmd`：
- `--resume <id>`（既有参数，语义扩展）→ `resolve_resume_target` → `single` 走 `dispatch(resume_from=id)`（既有）；`batch` 走 `batch_runner.resume_batch`（新）。
- `--batch` 与 `--resume` 互斥（加载期校验，§1.3）。
- `--batch` 首跑后打印 `batch_id`（用户续跑句柄）。

### 2.5 不做（YAGNI，用户原则）
- 不加 `ascendc-devkit runs list` CLI（resume 靠 batch_id 句柄即可；列出 run 是投机性扩展，非本方案必需）。
- 不引入 batch.json（文件系统即映射）。

## 3. 脚本改动 `scripts/batch_self_evolve.sh`（~350 → ~140 行）

**删**：`run_one()` 整体、FIFO 卡池（`mkfifo`/`exec 3<>`/`echo >&3`）、`detect_npu_count`/`MAX_CONCURRENT`、fork+wait+PID、`.runid.<op>`/`.status.<op>`/`.lock.<op>` sidecar、`sort|tail` 目录猜测（疑似6）、从头跑分支的 `RESUME` env 泄漏（疑似7，随 `run_one` 删除消失）、run_id grep 捕获、`exec > >(tee)` 自重定向。

**留**：CANN env setup（含 `set +u; source; set -u`）、`DEFAULT_OPS`、`WORKTREE_ROOT`/`TS`、git 前置校验、`pip install -e`、`resolve_task_level()`、worktree 建立/复用/清理、task 文件校验。

**新（manifest 生成 + 调框架）**：
```bash
# 首/续统一生成 manifest（resume 项带 resume_from，由脚本读 .batch_id 决定是否续跑）
MANIFEST="$WORKTREE_ROOT/manifest.yaml"
cat > "$MANIFEST" <<YAML
cards: [$(seq -s ', ' 0 $((NPU_COUNT-1)))]
design_concurrency: ${#OPS[@]}
non_interactive: true
on_decision: default
workflow: self_evolve_op
mode: new
workflow_timeout_sec: ${WORKFLOW_TIMEOUT:-20000}
stage_timeout_sec: ${STAGE_TIMEOUT:-4800}
tasks:
YAML
for op in "${OPS[@]}"; do
    wt="$WORKTREE_ROOT/$op"
    [[ -d "$wt" ]] || git -C "$CANN_BENCH" worktree add --detach "$wt"
    level="$(resolve_task_level "$wt" "$op")"; task="$wt/tasks/$level/$op"
    # task 文件校验（proto.yaml/golden.py）...（保留既有校验）
    cat >> "$MANIFEST" <<YAML
  - op_dir: $wt/examples/aclnn_launch_example/csrc/ops/$op
    repo_root: $wt
    requirement_path: $task/proto.yaml
    golden_path: $task/golden.py
    golden_entry: $op
    golden_input_type: torch
YAML
    [[ -f "$task/cases.csv" ]] && echo "    cases_path: $task/cases.csv" >> "$MANIFEST"
    [[ -n "$CHIP" ]] && echo "    design_target_chip: $CHIP" >> "$MANIFEST"
done
# 续跑：读 .batch_id（1 个 ID，非 N 个 sidecar）
if [[ "$RESUME_MODE" -eq 1 && -f "$WORKTREE_ROOT/.batch_id" ]]; then
    BID="$(cat "$WORKTREE_ROOT/.batch_id")"
    ascendc-devkit run --resume "$BID"          # resolver 判 batch → resume_batch
else
    ascendc-devkit run --batch "$MANIFEST" | tee /dev/stderr | grep -oE 'batch_id: [0-9]{8}-[0-9]{6}-[a-f0-9]{6}' | head -1 | awk '{print $2}' > "$WORKTREE_ROOT/.batch_id"
fi
```
（最终形态以实现为准；关键：续跑句柄 = 1 个 `.batch_id`，或用户直接 `run --resume <batch_id>`。）

## 4. 实施顺序（TDD 红→绿）

1. `new_run_id()`（workspace.py）+ UT。
2. dispatch 兑现 `task_request["run_id"]` 注入 + UT（传/不传 run_id 两种）。
3. `BatchManifest.output_root` 字段 + batch_runner：batch_id 生成、每 task 注入 run_id+scoped output_root、`RunOutcome.run_id` 填充、`BatchResult.batch_id` + UT。
4. `resolve_resume_target` 三态 + UT（flat-run / top-batch / nested-exec / 0 命中 / 多命中）。
5. `resume_batch`（列目录重建 manifest → run_batch resume 变体）+ UT。
6. run.py 合一 `--resume` 路由 + `--batch`/`--resume` 互斥 + 打印 batch_id + UT。
7. 脚本瘦身（ST 结构：manifest 生成 + run --batch + resume）。

## 5. 验证

- **UT**：上述 1-6 全 mock（StubBackend / monkeypatch dispatch），§3.8 纯逻辑。重点：单算子 dispatch 行为零回归（不传 run_id 仍 new_run_id 自生成）；resume 三态判据无歧义；nested output_root 正确 scope。
- **ST**：`tests/st/` 加 batch 结构用例（manifest 生成 + `run --batch` 调度结构 + `run --resume <batch_id>` 续跑结构），非 heavy_llm、非 NPU 真实链路（mock dispatch）。
- **heavy_llm（§3.11，用户决策跑/不跑）**：真实多算子批跑全流程（首次 + 续跑），守护 batch_id 分层 + nested 目录 + 合一 resume 端到端。交付前由用户在关键节点决策跑一次。

## 6. 边界 / 不改

- **单算子 run.py 路径零变化**：不注入 run_id、output_root flat、`--resume <run_id>` 走既有 dispatch resume（resolver 态1）。
- **`e2e_self_evolve.sh` 不删**：单算子 e2e 独立场景仍用。
- **既有 `output/<run_id>/` flat 目录**：§1.4 不向后兼容，不做迁移；旧目录自然遗留（dev 产物）。
- **batch.json 不引入**：文件系统即映射（`ls output/<batch_id>/`）。
- **`runs list` CLI 不加**：YAGNI。

## 7. 与既有框架的契合

- §2.5 单通路：批跑 = 单算子 resume 的批量编排（resume_batch 复用 run_batch + dispatch resume），无双通路。
- §2.3 文件契约：`output/<batch_id>/<exec>/` 自包含，对称于 `output/<run_id>/`。
- §1.7 仓自闭环：output_root 仍指仓内 `output/`。
- §1.2 四把尺子：可维护（new_run_id 单一源、无 sidecar）、可扩展（合一 resume 任何调用方）、可诊断（文件系统即映射、resume 判据位置无歧义、batch_id 确定性）、架构合理（单算子零改、batch=单算子编排）。
