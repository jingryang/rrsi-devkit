# 72 — PR #28 A5 precision_debug 进度接力 + TilingKey 路由 + 多 dtype 支持（L4 实施方案）

> 工作线：self-evolution / A5 RegBase 算子开发链路收口
> 性质：**L4 实施方案** —— 改哪个文件/函数、什么顺序、怎么验证。
> 状态：**已实施（PR #28，2026-07-24）**。代码改动已随 PR 分支落地；L1/L2/L3 由本步补齐。
> 前置 L1：`72-pr-28-a5-precision-continuity-problems.md`（P1-P5 事实快照）。
> 前置 L3：`72-pr-28-a5-precision-continuity-analysis.md`（D1-D5 决策）。>

---

## 如何读本文档

- 与 L1 的 P1..P5 **严格一一对应**，同序号同顺序。
- 每条自包含：改动点（文件:行）→ 具体改法 → 影响 → 验证。
- §6 为 as-built 汇总。

---

## P1 — A5 跨轮次进度接力：best_snapshot 机制

### 改动点

- `src/ascendc_devkit/orchestration/stages/precision_debug_a5.py`
  - 在 `_load_a5_checkpoint` 中增加 `best_snapshot` 与 `baseline_status` 的加载期校验。
  - 在 `InitBaselineSubstage.transition` 中保留运行时 fail-safe：当 `baseline_status` 非 `passed`/`failed` 时按 `failed` 处理。
  - 各叶子阶段（pipeline_sync / dump_debug / vf_test / finalize）在成功执行后按统一 schema 写入 `best_snapshot`。

- `.claude/skills/ascendc-pipeline-sync-debug/SKILL.md`
- `.claude/skills/ascendc-precision-dump-debug/SKILL.md`
- `.claude/skills/ascendc-precision-vf-debug/SKILL.md`
- `.claude/skills/ascendc-precision-finalize/SKILL.md`
  - 在产出物说明中增加 `best_snapshot` 写入义务与字段定义。

### `best_snapshot` schema

```json
{
  "max_err": 0.001,
  "passed": 18,
  "total": 20,
  "failed_cases": ["case_3", "case_7"],
  "updated_by": "pipeline_sync",
  "updated_round": 1
}
```

### 框架 fallback 重建

当子 agent 未写 `best_snapshot` 时，框架从最近一阶段的 `*_result.json` 中重建：

```python
# 伪代码，实际见 precision_debug_a5.py
def _rebuild_best_snapshot(state):
    for phase in ("pipeline_sync", "dump_debug", "vf_test", "finalize"):
        p = _phase_result_path(state, phase)
        if p.exists():
            raw = json.loads(p.read_text())
            if "max_err" in raw and "failed_cases" in raw:
                return {
                    "max_err": raw["max_err"],
                    "passed": raw.get("passed", 0),
                    "total": raw.get("total", 0),
                    "failed_cases": raw.get("failed_cases", []),
                    "updated_by": f"{phase}_result_fallback",
                    "updated_round": _current_round(state),
                }
    return None
```

### 验证

- UT：构造缺 `best_snapshot` 的 checkpoint，断言框架 fallback 重建正确。
- UT：构造 malformed `baseline_status`，断言加载期 warn + 运行时按 failed 处理。
- heavy_llm（§3.11）：真实 A5 多轮 precision_debug 流程，验证 `best_snapshot` 在各阶段间传递。

---

## P2 — TilingKey 路由方案：去 driver 文件名

### 改动点

- `.claude/skills/ascendc-op-dev-coding/SKILL.md`
  - 删除"TilingKey 路由方案"中引用 `template_division.json` / `coding_index.md` 的条件描述。
  - 保留技术对比表（方案 A/B 的 Host 设置、Kernel 入口、TilingData 绑定、适用场景）。
  - 保留"默认方案 A、仅当设计产物明确要求按 TilingKey 进入不同 kernel class/模板（非 dtype 枚举）才用方案 B"的原则性描述。
  - SELFCHECK 表第 267 行"TilingKey 路由方案一致"项的判据改为"与 staging 设计产物声明的模板划分方式一致"，去掉具体文件名。

- `.claude/agents/ascendc-dev-s4-coding.md`
  - 保留完整 TilingKey 选型表与 `template_division.json` / `coding_index.md` 引用（S4 agent 作为执行者可以引用 driver 文件）。

### 验证

- UT：`tests/ut/orchestration/test_codegen_a5_constraints.py::test_no_external_driver_mechanism` 通过（该测试禁 `coding_index` / `template_division` / `regbase-vf-test` / `vf_verified` / `RECORD_DIR` / `CTX_DRIFT`）。
- 静态 grep：通用 skill 中不再出现 `coding_index` / `template_division.json`。

---

## P3 — 多 dtype numpy 指南：各 skill 自包含副本

### 改动点

- `.claude/skills/ascendc-pipeline-sync-debug/references/multi-dtype-numpy.md`（新增副本）
- `.claude/skills/ascendc-precision-dump-debug/references/multi-dtype-numpy.md`（新增副本）
- `.claude/skills/ascendc-precision-vf-debug/references/multi-dtype-numpy.md`（新增副本）
- `.claude/skills/ascendc-custom-op-precision/references/multi-dtype-numpy.md`（新增副本）
- `.claude/skills/ascendc-precision-finalize/references/multi-dtype-numpy.md`（新增副本）

原文件 `.claude/skills/regbase-vf-test/references/multi-dtype-numpy.md` 保留作为 VF 测试的主副本，不影响 `regbase-vf-test` 自身运行。

### 引用路径修改

每个 skill 的 SKILL.md 将外部引用：

```markdown
- `skills/regbase-vf-test/references/multi-dtype-numpy.md`（...）
```

改为内部引用：

```markdown
- `references/multi-dtype-numpy.md`（...）
```

### 验证

- 对每个 precision 叶子 skill 目录做 TUI 模拟复制，确认 `references/multi-dtype-numpy.md` 存在且 SKILL.md 引用的是相对路径。
- 静态 grep：各 skill SKILL.md 中不再出现 `regbase-vf-test/references/multi-dtype-numpy.md`。

---

## P4 — S5 编译重试上限：6 → 30 + 注释

### 改动点

- `src/ascendc_devkit/orchestration/stages/codegen.py:411`
  - 将 `retries.stage5_compile.limit` 从 6 改为 30。
  - 增加注释：
    ```python
    # A5 多 dtype + VF 融合场景下，编译-修复迭代通常需要 20+ 轮，
    # 按内部实验设定上限为 30；若仍超过，按工具链 flakiness 处理。
    ```

- regbase skill 相关配置/测试同步更新上限。

### 验证

- UT：断言 `codegen.py` 中读取到的 `retries.stage5_compile.limit` 为 30。
- 回归：全量 orchestration UT 不因此引入失败。

---

## P5 — `baseline_status` 类型与加载期校验

### 改动点

- `src/ascendc_devkit/orchestration/stages/precision_debug_a5.py`
  - 在 `_load_a5_checkpoint` 中增加：
    ```python
    def _load_a5_checkpoint(state: "State") -> dict:
        p = _a5_checkpoint_path(state)
        if p is None or not p.exists():
            return {}
        try:
            cp = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            Logger.warn(...)
            return {}

        # 加载期校验：baseline_status 必须是 passed/failed
        status = cp.get("baseline_status")
        if status is not None and status not in ("passed", "failed"):
            Logger.warn(f"[PD-A5] baseline_status={status!r} invalid, treating as failed")
            cp["baseline_status"] = "failed"

        # 加载期校验：best_snapshot 必填字段
        snap = cp.get("best_snapshot")
        if snap is not None:
            required = ("max_err", "passed", "total", "failed_cases", "updated_by", "updated_round")
            missing = [k for k in required if k not in snap]
            if missing:
                Logger.warn(f"[PD-A5] best_snapshot missing {missing}, ignoring snapshot")
                cp["best_snapshot"] = None
        return cp
    ```
  - `InitBaselineSubstage.transition` 保留运行时 fail-safe：
    ```python
    status_str = baseline.get("baseline_status", "")
    baseline_passed_bool = (status_str == "passed")
    if status_str not in ("passed", "failed"):
        Logger.warn(...)
    ```

### 验证

- UT：构造 `baseline_status="yes"` 的 checkpoint，断言加载期 warn + 后续按 failed 处理。
- UT：构造缺 `max_err` 的 `best_snapshot`，断言加载期 warn 并把 snapshot 置 None。
- 回归：全量 precision_debug_a5 相关 UT 通过。

---

## §6 as-built 汇总

| P# | 决策 | 实际改动文件 | 测试/验证 |
|---|---|---|---|
| P1 | D1=A：叶子写 + 框架 fallback | `precision_debug_a5.py` + 4 个 A5 skill SKILL.md | UT（fallback/加载期校验）+ heavy_llm（真实 A5 多轮） |
| P2 | D2=A：通用 skill 去 driver 文件名 | `ascendc-op-dev-coding/SKILL.md` | `test_codegen_a5_constraints.py` 通过 |
| P3 | D3=A：各 skill 自包含副本 | 4 个 precision skill 新增 `references/multi-dtype-numpy.md` + SKILL.md 改引用 | 静态 grep + TUI 复制模拟 |
| P4 | D4=A：30 + 注释 | `codegen.py:411` + regbase skill/测试 | UT 断言上限 |
| P5 | D5=A：加载期校验 + 运行时兜底 | `precision_debug_a5.py:77-86` 及 transition 处 | UT 断言 malformed 处理 |

### 未完全覆盖项（随 PR  review 时记录）

- M3（`baseline_status` 加载期校验）在 PR  review 时部分落地：`_load_a5_checkpoint` 已加校验，但 `best_snapshot` 必填字段校验可能未完全覆盖所有字段，需核对 `precision_debug_a5.py` 当前 HEAD。
- M2（多 dtype 指南副本）在 PR  review 时建议通过但未完全确认是否已执行，需核对 5 个 skill 目录。
- M6（S5 上限 30 取值依据）已通过本 L4 注释与记录闭环。

### 后续 follow-up

- A5 端到端真实链路 heavy_llm ST（§3.11）应在 PR 合并前用户决策跑一次，验证 `best_snapshot` 跨阶段传递、TilingKey 选型、多 dtype 指南真实生效。
- 若后续发现 30 轮仍不足，应再评估是工具链 flakiness 还是阈值本身过低，禁止静默继续调高而不留依据。
