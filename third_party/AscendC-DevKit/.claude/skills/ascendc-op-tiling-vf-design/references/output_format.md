# VF 设计输出格式

> **产物载体（权威）**：本 skill 产出 **`tiling_vf_design.json`**（JSON，`required_keys: ["template","vf_design"]`），
> 机器契约见 `../schema/tiling_vf_design.json`。下方 YAML / Markdown 仅用于**示意 `vf_design` 的字段结构与语义**，
> 字段与 JSON 一一映射——产出时把它们落进 `tiling_vf_design.json` 的 `vf_design` 对象（`vf_layout.vfs[]` →
> `vf_design.vfs[]`，每个 VF 条目内含 `name/function_signature/interface_params/inputs/outputs/compute_ops/
> pseudocode/ub_layout/sync_points`）。**不要产出独立的 .yaml 或 .md 文件。**

## 字段结构示意（原 YAML 形式，映射到 JSON `vf_design`）

### YAML（结构示意，等价于 JSON `vf_design`）

```yaml
vf_design:
  pattern: 4
  vf_count: 3

  # VF 间数据依赖摘要
  data_flow:
    - {from: copy_in, to: vf_0, data: [x]}
    - {from: vf_0, to: vf_1, data: [mean_sq]}
    - {from: vf_1, to: vf_2, data: [rstd]}
    - {from: copy_in, to: vf_2, data: [gamma]}
    - {from: vf_2, to: copy_out, data: [y]}

  vf_layout:
    copy_in:
      - {id: copy_in_x, engine: mte2, api: DataCopyPad, data: [x, gamma]}

    vfs:
      - vf_id: vf_0
        role: reduce_square
        formula: "mean_sq = reduce_sum(x²) / D"
        function_signature: "__aicore__ inline void SquareReduceSum(LocalTensor<half>& xLocal, LocalTensor<float>& dstLocal, uint16_t batchRows, uint16_t numColAlign)"
        interface_params:
          inputs:
            - {name: x, ctype: "LocalTensor<half>&", storage: inQueueX.DeQue, ub_layout: "[batchRows, numColAlign]", dtype: fp16, desc: "输入 x"}
          outputs:
            - {name: dst, ctype: "LocalTensor<float>&", storage: mean_sq_buf, ub_layout: "[batchRows]", dtype: fp32, desc: "每行平方和"}
        inputs:
          - {name: x, from: copy_in_x, dtype: fp16}
        outputs:
          - {name: mean_sq, to: vf_1, dtype: fp32, buf: mean_sq_buf}
        supported_dtype_combinations:
          - inputs: {x: fp16}
            outputs: {mean_sq: fp32}
          - inputs: {x: bf16}
            outputs: {mean_sq: fp32}
          - inputs: {x: fp32}
            outputs: {mean_sq: fp32}
        compute_ops: [Mul(x, x), ReduceSum, Div(D)]

      - vf_id: vf_1
        role: compute_rstd
        formula: "rstd = rsqrt(mean_sq + ε)"
        function_signature: "__aicore__ inline void ComputeRstd(LocalTensor<float>& sumLocal, LocalTensor<float>& dstLocal, uint16_t batchRows, uint16_t numCols, float eps)"
        interface_params:
          inputs:
            - {name: sum, ctype: "LocalTensor<float>&", storage: mean_sq_buf, ub_layout: "[batchRows]", dtype: fp32, desc: "上游平方和"}
          outputs:
            - {name: dst, ctype: "LocalTensor<float>&", storage: rstd_buf, ub_layout: "[batchRows]", dtype: fp32, desc: "rstd"}
        inputs:
          - {name: mean_sq, from: vf_0, dtype: fp32}
          - {name: eps, from: tiling_data, dtype: scalar}
        outputs:
          - {name: rstd, to: vf_2, dtype: fp32, buf: rstd_buf}
        supported_dtype_combinations:
          - inputs: {mean_sq: fp32, eps: scalar}
            outputs: {rstd: fp32}
        compute_ops: [Adds(mean_sq, eps), Rsqrt]

      - vf_id: vf_2
        role: normalize
        formula: "y = x * rstd * γ"
        function_signature: "template <typename DX> __aicore__ inline void ComputeY(LocalTensor<DX>& xLocal, LocalTensor<float>& rstdLocal, LocalTensor<float>& gammaLocal, LocalTensor<DX>& dstLocal, uint16_t batchRows, uint16_t numColAlign)"
        interface_params:
          inputs:
            - {name: x, ctype: "LocalTensor<DX>&", storage: inQueueX.DeQue, ub_layout: "[batchRows, numColAlign]", dtype: DX, desc: "输入 x"}
            - {name: rstd, ctype: "LocalTensor<float>&", storage: rstd_buf, ub_layout: "[batchRows]", dtype: fp32, desc: "上游 rstd"}
            - {name: gamma, ctype: "LocalTensor<float>&", storage: gamma_buf, ub_layout: "[numColAlign]", dtype: fp32, desc: "gamma"}
          outputs:
            - {name: dst, ctype: "LocalTensor<DX>&", storage: y_buf, ub_layout: "[batchRows, numColAlign]", dtype: DX, desc: "输出 y"}
        inputs:
          - {name: x, from: copy_in_x, dtype: DX}
          - {name: rstd, from: vf_1, dtype: fp32}
          - {name: gamma, from: copy_in_x, dtype: fp32}
        outputs:
          - {name: y, to: copy_out, dtype: DX, buf: y_buf}
        supported_dtype_combinations:
          - inputs: {x: fp16, rstd: fp32, gamma: fp32}
            outputs: {y: fp16}
          - inputs: {x: bf16, rstd: fp32, gamma: fp32}
            outputs: {y: bf16}
          - inputs: {x: fp32, rstd: fp32, gamma: fp32}
            outputs: {y: fp32}
        compute_ops: [Mul(x, rstd), Mul(tmp, γ)]

    copy_out:
      - {id: copy_out, engine: mte3, api: DataCopyPad}

  buffer_num: 2
  # sync_points 仅列出跨引擎边界（MTE↔V），VF 间无显式同步
  sync_points:
    - {between: [copy_in, vf_0], mechanism: "EnQue/DeQue", via: inQueue, note: "CopyIn EnQue → VF DeQue"}
    - {between: [vf_2, copy_out], mechanism: "EnQue/DeQue", via: outQueue, note: "VF EnQue → CopyOut DeQue"}
  ub_layout:
    - {name: x_buf, size_ratio: 0.4, resident: true}
    - {name: gamma_buf, size_ratio: 0.1, resident: true}
    - {name: mean_sq_buf, size_ratio: 0.05, resident: false}
    - {name: rstd_buf, size_ratio: 0.05, resident: false}
    - {name: y_buf, size_ratio: 0.4, resident: false}
```

字段定义见 [`vf_design_schema.yaml`](vf_design_schema.yaml)。

## Markdown 渲染版（`template_{模板名}_vf_design.md`）

**必须包含每个 VF 的函数接口定义**（函数签名 + 参数表 + 伪代码）。
格式对标 AscendC RegBase `__aicore__ inline void ComputeXxx(...)` 风格。

```markdown
# {OpName} VF 设计方案

## 1. 概要

| 项目 | 值 |
|------|-----|
| 模式 | 4 — 三 VF 全流水 |
| VF 数 | 3 |
| 依赖 | 串行（vf_1 依赖 vf_0，vf_2 依赖 vf_1） |
| loopCount | CeilDiv(rowsPerCore, batchRows) |
| buffer | 双 buffer |
| 新增函数 | N |

## 2. 数据流

copy_in_x(x, γ) → vf_0 → vf_1 → vf_2 → copy_out(y)

## 3. Process() 主循环

```cpp
// 展示核内主循环结构：CopyIn → VF 调用链 → CopyOut
// 各 VF 的 buffer 生命周期由调用方管理 (AllocTensor / FreeTensor)
```

## 4. VF 函数接口定义

### 4.1 VF_0 — <role>

| | 详情 |
|------|------|
| **角色** | ... |
| **公式** | ... |
| **状态** | **新增函数** |

#### 函数签名
```cpp
__aicore__ inline void ComputeXxx(
    LocalTensor<DX>& xLocal,        // 输入 [rows, stride]
    LocalTensor<float>& dstLocal,    // 输出 [rows]
    uint16_t rows,                   // tiling 参数
    ...)
```

#### 参数表
| 参数 | 类型 | 方向 | 存储 | 说明 |
|------|------|------|------|------|
| ... | ... | in/out/tmp | buf_name | ... |

#### 伪代码
```cpp
// __VEC_SCOPE__ 内的 RegTensor 操作序列
```

### 4.2 VF_1 — <role>
... (同上格式)

### 4.3 VF_2 — <role>
... (同上格式)

## 5. 函数清单

| 函数 | 状态 | 位置 |
|------|------|------|
| ComputeXxx | **新增** | xxx.h |
| ComputeYyy | **新增** | xxx.h |

## 6. UB 分配

| buffer | 声明 | 数据类型 | BUF_NUM | 常驻 |
|--------|------|---------|---------|------|
| inQueueX | TQue<VECIN, 2> | DX | 2 | 否 |
| ... | ... | ... | ... | ... |

## 7. 同步点

| # | 位置 | 机制 | 说明 |
|---|------|------|------|
| 1 | copy_in → vf_0 | `EnQue` / `DeQue` (via inQueue) | CopyIn EnQue → VF DeQue（TQue 流水同步） |
| 2 | vf_2 → copy_out | `EnQue` / `DeQue` (via outQueue) | VF EnQue → CopyOut DeQue（TQue 流水同步） |

> VF 间（vf_0→vf_1→vf_2）同 V 引擎顺序执行，无显式同步。依赖由 `data_flow` 表达。

## 8. 多核协调

| 维度 | 策略 |
|------|------|
| 切分轴 | ... |
| 核间依赖 | 无 / 有 |

## 9. Kernel 组织建议

目录结构树，标注各文件中的 VF 函数。
```
