# L4：P11 实施——重读回灌缩减 + 冲刷可观测（step-113）

> L3：`14-analysis-context-economy.md`（冻结）。TDD：先红后绿。
> 改动四件：B1 切片物化+prompt 指针、A 读纪律行、C compaction 计数、UT/ST。

## 1. 改动清单（按实施顺序）

### 1.1 UT 先行（红）

新增 `tests/ut/orchestration/test_codegen_staging_slices.py`：

- **B1 物化**（驱动 `_materialize_inputs`）：
  - 多模板 State → `staging/tiling_results/<T>.json` 各切片存在，内容 =
    `{<T>: <原段>}`；**合并等价**：切片 dict 合并 == 原 `state.tiling_results`；
  - 单模板 → 一个切片（内容=单体顶层）；`tiling_results=None/{}`
    → 无切片目录（单体也不写，既有行为）；
  - 模板名含路径非法字符（`T/1:x`）→ sanitize 落盘且可读回；sanitize 后碰撞
    （`T/1` 与 `T:1`）→ 跳过切片 + 不抛错（单体仍写）；
  - **单体照写**（并存）。
- **prompt 指针**：含 staging 的 prompt 注入行指向 `tiling_results/`（切片目录），
  不再指单体文件路径。
- **source-guard**：coder SKILL 含切片指针与读纪律（「分段」「整文件」关键词），
  新增段落零算子名（§1.12）。

扩展 `tests/ut/capabilities/test_opencode_backend.py`：

- **C 计数**：SSE 事件流注入 2 个 `session.compacted` 事件 → `metrics["compactions"]`
  == 2；无事件 → 键为 0；按 spawn 重置（两次 spawn 独立计数）。

### 1.2 B1：`src/ascendc_devkit/orchestration/stages/codegen.py`

1. `_materialize_inputs` 在 tiling_results.json 写出后追加切片段：
   sanitize（`re.sub(r'[^A-Za-z0-9._-]+', '_', name)`）→ 唯一性断言 → 碰撞/
   空名 WARN+跳过 → 逐键写 `tiling_results/<safe>.json`（`_json_text({key: val})`
   包裹形态）。
2. `:2181` prompt 注入行改指 `tiling_results/`（按当前实现模板读对应切片；
   跨模板一致性核对读相邻切片；勿整目录通读）——读通路唯一，不再注入单体路径。

### 1.3 A：`.claude/skills/ascendc-op-dev-coding/SKILL.md`

1. 文件表 :64 行：`tiling_results/<模板>.json`（per-template 切片；原单体=
   全貌视图，跨模板核对可用）。
2. 蓝图优先级 :73 行：按当前实现模板读对应切片。
3. 读纪律一行（2026-09-02 修正：有序过程+自服回退，非绝对禁令——绝对禁令无
   回退通道会复现 P15 的「定位失败→瞎猜/违规」失败模式；先例论证已收回）：
   先定位后读段（grep 键路径 → limit/offset 段读）；**定位失败（不确定要看
   哪段）时允许整文件读**；禁止的只是跳过定位尝试的无差别整读。

### 1.4 C：`src/ascendc_devkit/capabilities/agent/`

1. `opencode_sse.py`：`_EVT_SESSION_COMPACTED = "session.compacted"` +
   `is_session_compacted(event)` 判定函数。
2. `opencode_backend.py`：消费循环增 `_compactions` 计数（spawn 级重置，同
   `step_reasoning_chars` 惯例）→ `_build_result` metrics 固定键 `compactions`
   （int；0 也写——消费方可判「有观测」）；N>0 时事实性日志一行（实测数字，
   无判断词）。sdk 侧无等价事件，键不写（注释言明缺失≠零冲刷）。

## 2. 不做的事（防走样）

- 不删/不移 staging 单体（并存，读通路唯一由 prompt 保证）。
- 不设 compaction WARN 阈值（无算术依据；下批数据立阈值再议）。
- 不动 A5 regbase skill（其对 tiling_results 零引用——取证已证，无消费可指）。
- 不切分 general_design 等其余文件（A 软引导覆盖；收益集中于字节大头）。

## 3. 验证

- 全量 UT（--quick）+ 全量 ST 默认模式。
- grep 审计：新增 skill 行零算子名零 docs/plan 编号。
- 下批端到端判据（L3 §5）：tiling_results 整文件读占比 81% → 显著降；
  compaction 间隔基线 21-32min 是否拉长；`compactions` metrics 在批日志/events
  可见可汇总。

## 4. 风险与回退

- 模型不按切片读（软指针执行度）→ C 的重读观测可判；不达标再评估收紧
  （如 prompt 强化/切片目录唯一化），不预建强制结构。
- sanitize 碰撞回退常态化（某设计模板名习惯性冲突）→ 属产物命名问题，
  交设计侧 skill 约束（模板名用标识符），不在物化层兜底改名。
