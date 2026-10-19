# L3 方案分析 — TensorSpec.dtype 多 dtype 支持

> 状态：已冻结（2026-07-21）
> 对应 L1：P1

## 问题重述

`OperatorSpec.from_dict()` 解析 `requirement.json` 时，将 `dtype: ["fp16","fp32","bf16"]` 截断为
`dtype: "fp16"`。`TensorSpec.dtype` 类型为 `str`，无法承载多 dtype。信息在领域模型层丢失，
下游所有从 `state.requirement` 派生的渠道（prompt 摘要、materialize 副本）均拿不到完整信息。

## 候选方案

### 方案 A：materialize 改为拷贝原始文件，不经过领域对象序列化

将 `_materialize_inputs` 从 `dataclasses.asdict(state.requirement) → file` 改为直接拷贝上游
stage 产出的原始 `requirement.json` 文件。

**优点**：原始文件无损，agent 工作目录下的副本和原始文件逐字节一致。

**缺点**：
- prompt 中的 `_requirement_summary` 仍然从 `state.requirement` 派生，和 materialize 的副本
  来自不同源头——两个渠道可能不一致（prompt 说 `"fp16"`，文件说 `["fp16","fp32","bf16"]`），
  agent 面临矛盾信息。
- 违反"state 是唯一权威源"的框架不变式。文件拷贝绕过了 state，引入第二数据源。
- 没有修根因——`TensorSpec.dtype` 仍然是 `str`，任何直接读取 `state.requirement` 的代码
  （如 `perf.py`、未来的新 consumer）仍然拿到截断后的值。

**结论**：不选。治标不治本，引入不一致。

### 方案 B：在 prompt 注入层补偿——`_requirement_summary` 改读原始文件

去掉 2000 char 的 cap，或让 summary 直接从原始 `requirement.json` 文件生成而非从 state 派生。

**优点**：prompt 端信息完整。

**缺点**：
- 仍然双源：state 和原始文件信息不一致。
- `_requirement_summary` 的定位是"从 state 快速摘要"，不是"重新读文件"。改变语义增加了耦合。
- 没有修 `TensorSpec` 本身——materialize 副本仍然是截断的，和 prompt 矛盾。

**结论**：不选。和方案 A 同类问题，只是换了一个补丁位置。

### 方案 C：`TensorSpec.dtype` 类型从 `str` 扩展为 `str | list[str]`，删除截断

**改动点**：
1. `TensorSpec.dtype: str | list[str]`（默认值 `""` 不变）
2. 删除 `operator.py:119-120` 的 `isinstance(ts.dtype, list)` → `replace(ts, dtype=ts.dtype[0])`
3. 唯一需要 scalar dtype 的 consumer（`perf.py:109`）在自己的边界显式抽取：`dtype[0] if isinstance(dtype, list) else dtype`
4. 序列化路径（`dataclasses.asdict` → `json.dumps`）零改动——list 自然序列化为 JSON 数组
5. 单 dtype 的 `str` 值 100% 向后兼容

**优点**：
- 根因修复——`state.requirement` 从源头保留完整信息
- prompt 和 materialize 副本两个渠道从同一 state 派生，一致且完整
- consumer 适配在自身边界完成，不入领域模型
- 不影响单 dtype 算子（`dtype: "fp16"` 仍作为 `str` 直接使用）

**缺点**：
- consumer 需要感知 `str | list[str]`（目前只有一个 consumer——`perf.py:109`）
- 未来新 consumer 若忘记处理 list 情况，会用 list 当 str（如 `f"_{dtype}"` 会变成 `"_['fp16', 'fp32', 'bf16']"`）
  ——但这是**可诊断的**（结果明显错误或直接 crash），而非静默截断。优于现状。

**结论**：✅ 选择方案 C。

## 方案 C 的四把尺子评估

| 尺子 | 判定 | 说明 |
|------|------|------|
| 可维护 | ✅ | 不变式成立：需求声明什么 dtype，`TensorSpec` 就完整携带。不再有信息在解析层消失。 |
| 可扩展 | ✅ | 任何多 dtype 算子自动正确，零追加改动。 |
| 可诊断 | ✅ | consumer 若误把 list 当 str，结果明显异常或 crash——比静默截断强。信息丢失不再静默。 |
| 架构合理 | ✅ | `TensorSpec` 负责承载事实（完整 dtype 信息），consumer 在自己层决定怎么消费（取首/遍历/断言单 dtype）。不越层兜底。 |
