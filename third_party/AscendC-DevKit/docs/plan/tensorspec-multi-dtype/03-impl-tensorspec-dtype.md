# L4 实施方案 — TensorSpec.dtype 扩展为 str | list[str]

> 对应 L3：方案 C
> 依赖：无（独立改动）

## 改动清单

### 1. `src/ascendc_devkit/domain/operator.py`

#### 1a. TensorSpec.dtype 类型扩展

`TensorSpec` 类中 `dtype` 字段的类型标注从 `str` 改为 `str | list[str]`。
默认值 `""` 不变（无 dtype 信息的 tensor 退回空串，向后兼容单 dtype 路径）。

#### 1b. 删除截断逻辑

在 `_route` 函数内部，删除以下代码：

```python
if isinstance(ts.dtype, list):
    ts = replace(ts, dtype=ts.dtype[0] if ts.dtype else "")
```

`replace` 的 import 如果不再被其他地方使用，同步清理。

### 2. `src/ascendc_devkit/orchestration/stages/perf.py`

这是唯一从 `TensorSpec.dtype` 取 scalar 值的 consumer。在 `primary_dtype` 赋值处
增加 list 处理：若 dtype 为 list，取 `dtype[0]`；否则直接使用。

```python
# 改前
primary_dtype = (op_spec.inputs[0].dtype if op_spec.inputs else "fp16") or "fp16"

# 改后
_raw = (op_spec.inputs[0].dtype if op_spec.inputs else "fp16") or "fp16"
primary_dtype = _raw[0] if isinstance(_raw, list) else _raw
```

### 3. 测试

在 `tests/ut/domain/` 下新增或补充用例：

- `test_tensorspec_preserves_multi_dtype`：`OperatorSpec.from_dict()` 输入 `dtype: ["fp16","fp32","bf16"]`，
  验证 `inputs[0].dtype == ["fp16","fp32","bf16"]`
- `test_tensorspec_scalar_dtype_still_works`：输入 `dtype: "fp16"`（单字符串），
  验证 `inputs[0].dtype == "fp16"`（向后兼容）
- 已有 UT 全量回归（需确保无 consumer 因 dtype 从 str 变 list 而 crash）

## 验证步骤

1. 改 `TensorSpec.dtype` 类型 + 删截断逻辑
2. 改 `perf.py` consumer
3. 写/跑新 UT（两个用例必须红→绿）
4. 跑全量 UT + 非 heavy_llm ST：`pytest tests/ -m "not heavy_llm"`
5. （可选，需用户确认）跑 heavy_llm ST 做端到端回归

## 不改的范围

- `dataclasses.asdict` + `json.dumps` 序列化路径：list 自然序列化为 JSON 数组，零改动
- `_requirement_summary`（prompt 注入）：同上，自动正确
- `_materialize_inputs`（文件 materialize）：同上，自动正确
- design SKILL.md：不需要改——现有步骤指令"读取 requirement.json → 提取支持范围清单"在
  materialize 副本已完整包含多 dtype 后，自然产出正确
- general-design-review SKILL.md：不需要改——CR1 字段校验 + `dtypeSize` 自动补全策略在
  requirement 拿回多 dtype 后，自然触发多模板/多 dtype 分支检查
