# P65 — 跨代 chip 兼容矩阵 — 实施方案（第四层）

> 层级：**第四层 / 实施方案**。具体改哪个函数、什么顺序、怎么验证。
> 依据：L3 `38-cross-gen-compat-analysis.md`（选定的选项 A）；L1 `06-problems.md` P65。

---

## 0. 改动总览

| # | 文件 | 改动 |
|---|---|---|
| 1 | `src/ascendc_devkit/domain/chip.py` | 新增 `MEMBASE`/`REGBASE` 常量 + `_CHIP_PROGRAMMING_MODEL` + `_RUNTIME_SUPPORTED_MODELS` + `chip_programming_model()` + `runtime_supports_design()` |
| 2 | `src/ascendc_devkit/adapters/npu/detect.py` | import + `chip_mismatch_reason` 的 `design == runtime` → `runtime_supports_design(design, runtime)`；文案「不匹配」→「不兼容」+ docstring 更新 |
| 3 | `src/ascendc_devkit/orchestration/stages/design_substages.py` | import + `_cross_generation_gate_fires` 的 `design == runtime` → `runtime_supports_design(design, runtime)` |
| 4 | `src/ascendc_devkit/orchestration/stages/codegen.py` | import + `_programming_model_for` 改调 `chip_programming_model` + meta.json 拆 design/runtime 双源 |
| 5 | `src/ascendc_devkit/orchestration/stages/deploy.py` | `_template_vars` 编译目标改 `runtime or design` |
| 6 | `src/ascendc_devkit/orchestration/stages/context.py` | L186 注释更新（仅注释） |

---

## 1. domain/chip.py（单一权威源，§1.9/§2.5）

在 `chip_display_name` 后新增「编程模型 + 跨代兼容」节：

```python
MEMBASE = "Membase"   # A2/A3 — traditional AscendC Vector (SIMD)
REGBASE = "Regbase"   # A5    — VF entry + RegTensor (SIMT)

_CHIP_PROGRAMMING_MODEL = {A2: MEMBASE, A3: MEMBASE, A5: REGBASE}
_RUNTIME_SUPPORTED_MODELS = {
    A2: frozenset({MEMBASE}),
    A3: frozenset({MEMBASE}),
    A5: frozenset({MEMBASE, REGBASE}),   # A5 向后兼容 Membase
}

def chip_programming_model(chip: str) -> str:
    return _CHIP_PROGRAMMING_MODEL.get((chip or "").strip(), MEMBASE)

def runtime_supports_design(design_chip: str, runtime_chip: str) -> bool:
    if not is_known_generation(runtime_chip):
        return False   # 未知 runtime → False，交调用方走「无法校验」分支（§3.7）
    return chip_programming_model(design_chip) in _RUNTIME_SUPPORTED_MODELS[runtime_chip]
```

要点：domain 返回**纯模型名**；skill 契约字面量 `"{chip} {model}"` 拼装留 codegen（分层）。未知/空 → `MEMBASE`（保守回退，沿用 codegen 旧语义）。

---

## 2. detect.py（PRIMARY + SECONDARY build gate 共用入口）

- import 追加 `runtime_supports_design`
- gate 主体 `if design == runtime: return None` → `if runtime_supports_design(design, runtime): return None`
- 「不匹配」文案 → 「不兼容」+ 改述为「A5 Regbase 产物不可降级到 A2/A3」
- docstring 的「forward-compat not allowed」改述为「兼容按编程模型，低代际 Membase 向前兼容 A5」（原 framing 已错）

「无法校验」分支（runtime 未知）不动——矩阵化后仍只在 runtime 未知时触发，文案正确。

---

## 3. design_substages.py（design 前跨代确认软门）

- import 追加 `runtime_supports_design`
- `_cross_generation_gate_fires`：`if design == runtime: return False` → `if runtime_supports_design(design, runtime): return False`
- 弹窗 actions() / transition() retarget/confirm **不动**：兼容组合不再弹；真不兼容（A5 design + A2/A3 runtime）才弹，文案「跨代产物无法本机 build/run」+「改打本机」均正确

---

## 4. codegen.py（meta.json skill 契约源 + programming_model 派生）

- import 追加 `chip_programming_model`
- `_programming_model_for(chip)`：改 `model = chip_programming_model(gen); return f"{gen} {model}" if gen else "Membase"`（保持 `"A5 Regbase"`/`"A2 Membase"` 字面量，不碰 SKILL.md Step4 契约）
- meta.json 物化拆双源：
  ```python
  design_chip = state.design_target_chip or ""
  runtime_chip = state.runtime_target_chip or ""
  compile_chip = runtime_chip or design_chip   # runtime 优先；design 回退
  if design_chip:
      meta = {
          "programming_model": self._programming_model_for(design_chip),  # 风格 ← design
          "chip_code": compile_chip,                                        # 编译目标 ← runtime
          "soc_version": to_soc_version(compile_chip),                      # soc ← runtime
      }
  ```
- validate_inputs gate 不动（调 `chip_mismatch_reason`，已矩阵化）

---

## 5. deploy.py（P54 D3 单一 deploy 链，非死代码）

`_template_vars` 的编译目标 `chip`：
```python
chip = state.runtime_target_chip or state.design_target_chip or ""
```
gate 不动（调 `chip_mismatch_reason`）。

---

## 6. context.py（仅注释）

L186 注释「design drives build (soc_version = to_soc_version(design))」→ 「design drives code STYLE only (programming_model)；COMPILE target (soc_version/chip_code) derived from runtime, design fallback（P65 dual source）」。context 只回填 design_chip，不派生 soc_version——无代码改动。

---

## 7. TDD（先红后绿，§3.1）

### domain UT（`tests/ut/domain/test_chip.py`）
- 新增 `TestChipProgrammingModel`：A2/A3→Membase、A5→Regbase、空/未知→Membase、返回纯模型名（非 skill 字面量）
- 新增 `TestRuntimeSupportsDesign`：(A2,A5)=T、(A3,A5)=T、(A2,A3)=T、(A3,A2)=T、(A5,A2)=F、(A5,A3)=F、(A5,A5)=T、runtime 未知→F

### 反转/新增 chip gate UT
| 文件 | 改动 |
|---|---|
| `test_chip_mismatch_pure.py` | (A2,A5) 由不匹配反转为 None；新增 (A3,A5)/(A2,A3)/(A3,A2)→None、(A5,A3)→真不兼容（保留 both-values + 「不兼容」断言）；validate_inputs 用例 (A2,A5)→errors==[] + 新增 (A5,A2)→chip_error |
| `test_adapters.py::TestChipMismatchReason` | `test_reverse_mismatch_also_reported` 改为 forward-compat None + A2↔A3；「不匹配」→「不兼容」 |
| `test_predesign_chip_gate.py` | 新增 (A2,A5)/(A3,A5)→不 fire、(A2,A3)/(A3,A2)→不 fire；保留 (A5,A2)→fire；header 条件改述 |
| `test_codegen_skill_delivery.py` | 新增 dual-source 用例：design=A2/runtime=A5 → pm="A2 Membase", chip_code="A5", soc="ascend950" |
| `test_deploy.py` | 新增 `_template_vars` forward-compat：design=A2/runtime=A5 → soc="ascend950"/chip="A5"；TestChipGate 新增 forward-compat 过 gate + docstring 改述 |

保留不动：`test_run_chip_flags.py`（CLI 旗标）、`test_state_chip_fields.py`（State 字段）、`test_no_chip_legacy_refs.py`（命名守卫——新 domain 函数形参未用裸 `target_chip`）、ST `test_predesign_chip_gate_resume.py`（用 (A5,A2) 真不兼容，仍触发）。

---

## 8. 验证

1. **UT 全量**（前台）：`pytest tests/ut/domain/test_chip.py tests/ut/orchestration/ tests/ut/adapters/ -m "not heavy_llm"` → 1277 passed
2. **静态守卫**：`grep -rn "design == runtime\|design == state.runtime" src/ascendc_devkit/` → 无残留
3. **命名守卫**：`pytest tests/ut/orchestration/test_no_chip_legacy_refs.py` → 绿
4. **ST 对齐**：`pytest tests/st/test_predesign_chip_gate_resume.py` → 2 passed（(A5,A2) 真不兼容仍触发）
5. **不跑 heavy_llm**（§3.11）：codegen full_pipeline ST 默认不纳入；兼容模式端到端（design=A2/runtime=A5 真跑）留用户在 A5 真机决策

---

## 9. 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-12 | P65 落地：domain 兼容矩阵 + 三 gate 改矩阵 + soc_version runtime 双源 + UT 反转/新增 + ST 对齐。1277 UT passed + 命名/静态守卫绿。 |
