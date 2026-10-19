# L4 实施方案：codegen host-offload 契约门

> 前置 L1 `01-problems.md`、L3 `02-analysis.md`。方案 C：确定性机械门 + 硬门定向 retry。

---

## 改动清单

| 文件 | 改动 |
|---|---|
| `src/ascendc_devkit/orchestration/stages/codegen.py` | `_HOST_ROUNDTRIP_RE` + `_first_host_roundtrip`（注释感知扫描）+ `_plugin_host_offload_error` + 接线到 torch_op 校验 |
| `.claude/skills/ascendc-op-dev-coding/SKILL.md` | 维10 补「框架机械门」说明 |
| `tests/ut/orchestration/test_codegen_host_offload.py` | 判据 UT（正/负/灰区/注释排除） |

## 实现细节

1. **`_HOST_ROUNDTRIP_RE = re.compile(r"\.cpu\(\)|kCPU")`**：命中 `.cpu()` 方法 / `kCPU` 设备枚举。
2. **`_first_host_roundtrip(source) -> (line, pattern)`**：逐行扫描、跟踪 `/* */` 块注释、剥 `//` 行注释后匹配，返回注释之外首个命中的 1-based 行号 + 命中串。
3. **`_plugin_host_offload_error(state, artifacts) -> ErrorFeedback | None`**：遍历 `_plugin_sources`，命中即返回 `ErrorFeedback(error_type="incomplete_output", reason="plugin_host_offload", plugin_file/line/pattern)`。
4. **接线**：`torch_op` 校验处（`_torch_plugin_contract_error` 之后）调用，命中 → `state.with_updates(last_error=...)` → 框架定向 retry codegen。

## 验证

- UT：`tests/ut/orchestration/test_codegen_host_offload.py`（6 例全绿）。
- 真机样本：`moe_re_routing` plugin → 命中 `kCPU@line101`（`.to(torch::kCPU)`）；`foreach_norm` plugin → clean。
- 回归：codegen 相关 UT 全量。
