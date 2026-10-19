# L4 实施方案：孤儿产物自动搬回 + prompt 注入工作目录绝对路径

> 对应问题：F1（孤儿产物不可见）、F2（证据不反哺收集）、F3（batch 下 KEEP）、F8（反馈无执行保障）、F10（预算空转）。
> 目标：模型把产物写错目录时，框架**确定性修复**（搬回），不依赖 LLM 自觉；并在源头降低路径幻觉概率。

## 一、背景与责任界定

| 层 | 责任 |
|----|------|
| 模型 | 写错目录（路径幻觉）、thinking 空转、收到纠正仍不遵守——**不可改** |
| 框架 | 检测到孤儿产物却无法确定性修复，只能靠重试 + 反馈空转到预算耗尽——**可改，本次修** |

**核心洞察**：框架已通过 `_harvest_relocation_evidence` 精确定位孤儿产物（`actual_path` 证据在手），且 `transition` 的 MOVE 分支已实现（`shutil.move` + `wd = ev.wd`），只是被 `result["decision"]` 门控——非交互 batch 永远选 KEEP。**缺的只是"非交互下自动走 MOVE"这一个短路。**

## 二、方案 A：非交互 batch 下自动搬回

### 改动点 1：`_DesignSubstage.transition` 非交互短路

文件：`src/ascendc_devkit/orchestration/stages/design_substages.py`（约 724 行）

在现有 `if wd is None and "decision" in result and state.pending_relocation:` 分支**之前**，加非交互短路：

```python
# 非交互 batch 自动搬回：evidence 已证明文件存在且是本次 agent 写的，
# 搬回是确定性修复（不是猜测），不依赖 LLM 自觉。搬回后 wd=ev.wd 走正常
# 解析路径——解析失败（内容坏）→ schema_violation → 正常重试，不引入新 halt。
# 防御：move 前检查 target 是否已存在，绝不静默覆盖（详见「防御性 move」节）。
if (wd is None and state.pending_relocation and state.non_interactive):
    ev = state.pending_relocation
    actual = Path(ev.actual_path)
    if actual.is_file():
        target = Path(ev.wd) / ev.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            same = os.path.samefile(actual, target)  # OSError → False
            if not same:
                Logger.warn(f"[{self.name}] 自动搬回跳过：wd 已有同名不同产物 {target}，拒绝覆盖；走 missing（重新生成）")
                return None, state.with_updates(pending_relocation=None)
            # samefile → 幂等，落回解析路径
            wd = ev.wd
        else:
            shutil.move(str(actual), str(target))
            Logger.warn(f"[{self.name}] 自动搬回孤儿产物 {actual} → {target}（非交互 batch 确定性修复）")
            wd = ev.wd
    else:
        # 证据指向的文件不存在（可能已被清理）→ 走既有 missing 路径
        return None, state.with_updates(pending_relocation=None)
```

**搬回后语义**（复用既有路径，不新增 halt）：
- 搬回成功 + 解析通过 → stage 成功，产物被消费 ✅
- 搬回成功 + 解析失败（内容坏）→ `schema_violation` → **正常重试**修内容 ✅
- 文件不存在 → 走 `_missing_artifact_error` → 正常重试 ✅
- **target 已存在不同文件** → 拒绝覆盖，走 `_missing_artifact_error` → 正常重试 ✅
- **target 是同一文件（hardlink）** → 幂等跳过，落回解析路径 ✅

### 改动点 2：`RelocationEvidence` 增加 batch 目录校验（防跨 run 误搬）

`_harvest_relocation_evidence`（约 140-197 行）当前有 3 重约束（文件名匹配、transcript 证据、wd 之外）。加第 4 重：**candidate 与 wd 属于不同 batch 目录（`output/<batch_id>`）时拒搬**。判据用 `_batch_dir_anchor(path)`：从 path 向上找含 `artifacts` 子目录的 run_dir，返回其父（batch 目录）。

**关键修正**（实施中发现）：任一取不到 batch 锚点（UT 临时目录 / 写到仓根的 stray）→ **放行**，不拒。原因是前 3 重约束已足够，锚点只是额外防跨 run 的保险——若锚点不确定就误杀，会破坏既有合法场景（既有测试 `test_finds_write_outside_wd` 用无 artifacts 树的 `tmp_path/wd` + `tmp_path/op`）。只有**能明确判定两者属于不同 batch** 才拒。

```python
def _batch_dir_anchor(path) -> "Path | None":
    p = path
    while p.parent != p:
        if (p / "artifacts").is_dir():
            return p.parent
        p = p.parent
    return None

# 第 4 重：wd_batch 与 cand_batch 都能解析且不同 → 拒搬；任一 None → 放行。
wd_batch = _batch_dir_anchor(wd_resolved)
cand_batch = _batch_dir_anchor(candidate.resolve())
if wd_batch is not None and cand_batch is not None and wd_batch != cand_batch:
    continue
```

## 三、方案 B：prompt 注入工作目录绝对路径（源头降概率）

### 改动点 3：`_output_boundary` 从静态方法改实例方法，注入 cwd 绝对路径

文件：`src/ascendc_devkit/orchestration/stages/design_substages.py`

现状（541 行）：
```python
def _output_boundary() -> str:
    return (
        "只产出上列文件，且必须写入当前工作目录（相对路径）；"
        "算子目录（op_dir，若上文提及）是只读参考，不是产出位置。"
        "不要将上游产物（如 design_spec / tiling_strategy 等）"
        "复制到当前工作目录。")
```

改为接收 `state`，在开头注入 cwd 绝对路径：
```python
def _output_boundary(self, state: "State") -> str:
    wd = self._working_dir(state)
    wd_hint = (f"当前工作目录（cwd）的完整路径为：{wd}\n"
               f"请用 `pwd` 验证你所在目录，用相对路径写入产物；"
               f"禁止使用绝对路径（绝对路径易拼错）。\n"
               if wd else "")
    return (
        f"{wd_hint}"
        "只产出上列文件，且必须写入当前工作目录（相对路径）；"
        "算子目录（op_dir，若上文提及）是只读参考，不是产出位置。"
        "不要将上游产物（如 design_spec / tiling_strategy 等）"
        "复制到当前工作目录。")
```

### 改动点 4：4 个调用点传 state

`_build_prompt`（576 行）、另 3 处（931、1110、1935 行）改为 `self._output_boundary(state)`。

## 四、为什么两个方案一起实施

| 维度 | 方案 A（自动搬回） | 方案 B（prompt 绝对路径） |
|------|-------------------|--------------------------|
| 作用层 | 失败后**修复** | 失败前**预防** |
| 机制 | 确定性（框架搬回） | 概率性（降低模型拼错概率） |
| 依赖模型能力 | 不依赖 | 部分依赖（模型仍可能不遵守） |
| 单独实施效果 | 能救"写错目录"的所有场景 | 只能减少"写错目录"的发生率 |

**两个互补**：B 降低发生率（源头），A 兜住漏网之鱼（结果）。A 是主兜底（确定性），B 是辅助加固（概率性）。只做 A，模型每次写错都多花一次搬回+重试；只做 B，模型一旦仍写错就无兜底。**合在一起：能预防的预防，预防不了的确定性修复。**

## 五、验证方案

### UT（tests/ut/orchestration/test_design_substages.py，已实施）

新增测试类（10 用例），已全部通过：

1. **非交互 + pending_relocation + 文件存在** → transition 自动搬回，wd 变为 ev.wd，产物可被 `_locate_artifact` 找到。✅
2. **非交互 + pending_relocation + 文件不存在** → 清 pending_relocation，走 missing 路径。✅
3. **交互模式**（non_interactive=False）→ 仍走 AskUserQuestion MOVE/KEEP（行为不变）。✅
4. **跨 run 防误搬** → candidate 在另一 batch 目录（两者锚点可解析且不同）→ 证据被拒。✅
5. **`_output_boundary` 注入** → prompt 含 `当前工作目录（cwd）的完整路径为：<wd>`，且含"pwd 验证""禁止拼写绝对路径"。✅
6. **无 workspace 时** → `_output_boundary` 返回原边界（不注入）。✅
7. **同 batch 孤儿 detailed 返回** → `(path, None)`，可搬回。✅
8. **跨 batch detailed 返回** → `(None, "cross_batch")`，供 WARN。✅
9. **防御：target 已存在不同文件** → 拒绝覆盖，清证据走 missing，wd 原产物保持原样。✅
10. **防御：target 是同一文件（hardlink）** → 幂等跳过，落回解析路径。✅

### 防御性 move（不静默覆盖，§1.2 可诊断）

`shutil.move` 默认会覆盖 target。自动搬回分支加防御：move 前检查 `target`（wd/文件名）是否已存在——
- **target 不存在** → 正常搬回。
- **target 与源是同一文件**（`os.path.samefile`，如 hardlink）→ 幂等跳过，落回解析路径。
- **target 是另一文件** → **拒绝覆盖**，WARN + 清证据走 missing（重新生成），wd 原产物保持原样。

正常流程下 wd 里不该有该产物（`_locate_artifact` 失败才触发搬回），此防御是防未来改动破坏该前提 + 防并发/残留的 last-resort（§1.2 宽容兜底）。

### 回归（已跑）

- `test_design_substages.py`：122 passed（含 6 新 + 116 既有，既有测试适配了 `_output_boundary` 签名 + batch anchor 判据）。
- 相关编排测试（tiling_forkjoin / detailed_design_intake / fail_strategy / docgen_render / test_design_stage / loopback_summary）：108 passed。
- **全量 `tests/ut --quick`：3628 passed, 3 deselected, 0 failed** —— 无回归。

### 既有测试适配记录

- `test_output_boundary_restates_cwd_is_sole_output`：`_output_boundary()` → `_output_boundary(State.empty())`（签名变更）。
- `TestHarvestRelocationEvidence.*`：batch anchor 判据"任一 None 放行"后无需改（原本会因无 artifacts 树被拒）。
- 新增 `TestRelocationEvidenceDetailed`：验证 detailed 变体返回 `(path, reason)`，跨 batch → `(None, "cross_batch")`。

### 可诊断性补强（§1.2 可诊断，问题发生时日志准确）

| 场景 | 日志 | 来源 |
|------|------|------|
| 检测到同 batch 孤儿产物 | `[stage] 检测到 {file} 写入了 wd 之外的 {path}（同 batch），将自动搬回` | `_missing_artifact_error` 新 Logger |
| 自动搬回成功 | `[stage] 自动搬回孤儿产物 {from} → {to}` | 既有（方案 A 改动点 1） |
| 搬回后解析失败 | `→ schema_violation: ...` | 既有 `_error` + runner:647 |
| 自动搬回跳过（文件已不存在） | `[stage] 自动搬回跳过：证据指向的孤儿产物 {path} 已不存在` | 新 Logger（改动点 1 else 分支） |
| 跨 batch 拒搬 | `[stage] 检测到 {file} 写入了另一 batch 目录，拒搬，走重新生成路径` | `_missing_artifact_error` 新 Logger（基于 detailed reason） |

关键设计：跨 batch 拒搬的日志**不在 `_harvest_relocation_evidence` 内部打**（它是纯函数，被 `_sweep_located_strays` 复用，内部打 warn 会误报 sweep）。改为返回 `(path, reason)` 的 detailed 变体，由 `_missing_artifact_error` 根据 reason 决定是否 WARN。

### 环境注意

本仓 `ascendc_devkit` 是 editable install，**指向 `/home/x0022770/code/AscendC-DevKit/src`（另一路径）**。跑本仓测试必须 `PYTHONPATH=/home/x00584171/code/AscendC-DevKit/src` 覆盖（PYTHONPATH 在 sys.path 优先于 site-packages .pth）。否则 pytest 加载的是旧代码，新测试会"假失败"（`has _batch_dir_anchor: False`）。

## 六、四把尺子评估

| 尺子 | 评估 |
|------|------|
| 可维护 | 复用既有 `RelocationEvidence` + MOVE 分支；`_output_boundary` 改签名，4 调用点同步；不新增概念 |
| 可扩展 | 所有设计子阶段（general-design/tiling/template-division/intake/validate）走同一 `_DesignSubstage.transition` + `_output_boundary`，一次改动全生效 |
| 可诊断 | 搬回记 WARN（from→to）；prompt 注入是可见的；不静默操作 |
| 架构合理 | 落在 transition（已持有证据）+ prompt 构造（`_output_boundary`），不越层；符合 §1.2"宽容兜底做 last resort" |

## 七、范围界定（不做的事）

- **不新增 halt**：搬回后一切失败都复用既有重试/错误路径（schema_violation / missing_artifact / infra）。
- **不改预算配置**：F10 的预算与失败模式匹配是另一项工作，不在本次范围。
- **不处理 thinking 空转**（F4/F9）：属 resume 策略，另一项工作。
