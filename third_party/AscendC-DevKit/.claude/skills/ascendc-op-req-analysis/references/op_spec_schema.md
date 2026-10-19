# requirement.json 算子规格（op_spec）字段语义

本规范定义 requirement.json 中算子规格（op_spec）相关字段的语义（inputs/outputs/data_type_support/shape_constraints 等）。机器校验契约在 `schema/requirement.json`（required_keys: op_name/aclnn_name/mutation_mode/inputs/outputs/golden_alignment），本文件是字段语义详解（人读）。

> **权威源约定（§1.13）**：本 op_spec 各事实（shape / dtype / 公式 / mutation 语义 / IO 关系 / 排布 / 边界）的**唯一权威源是 golden.py**；需求描述、需求规格、测试用例均为**辅助印证**（cross-check），不是与 golden 并列的第二权威。缺失/不明/与 golden 冲突时经 `resolve_ambiguity` 询问用户，**默认选项永远以 golden 为准**。目标代际（design_target_chip）是唯一例外——由需求文档顶层 YAML 字段确定性声明，不从 golden 派生。

> 注：下方「op_spec.md 章节结构」段是历史的双产物（md+json）遗留描述，当前 agent 只产 requirement.json（JSON），md 章节结构仅作字段语义参考，不再产出独立的 op_spec.md。

## 一、op_spec.md 章节结构（历史参考）

### 1. 基本信息
- 算子名
- 算子类型（计算类 / 搬运类 / 混合类）
- 目标代际（A2/A3/A5，可选；由需求文档顶层 YAML `design_target_chip` 字段声明，requirement stage 确定性解析，权威源 domain/chip.py；不在 op_spec.json constraints 里——agent 产的 constraint 不作为 chip 来源，P81 step-58 防照搬示例污染）
- 开发场景（新算子 / 增量开发）
- 硬件参数：UB 大小、核数、内存带宽（可选）

### 2. 数学公式 / 地址映射逻辑
**计算类**：数学公式，所有变体及条件分支  
**搬运类**：地址映射规则（例如 `output[i] = input[indices[i]]`），含边界处理策略

### 3. 输入输出规格表
| 参数名 | dtype | shape 约束 | 语义描述 | 访问模式 |
|--------|-------|-----------|---------|---------|
| x      | fp16  | [N, C, H, W] | 输入特征图 | 只读 |

### 4. 数据类型支持矩阵
| 输入组合 | 是否支持 | 输出类型推导规则 | 备注 |
|---------|---------|----------------|------|
| fp16 + fp16 | 是 | fp16 | AI Core 原生支持 |
| fp16 + fp32 | 否 | - | 需要显式转换 |

### 5. 形状约束与广播规则
- 符号化约束：例如 `batch_size == N`，`H = ceil(H_in / stride)`
- 动态形状标记：哪些维度可变（如 `N`）
- 输出形状公式：`output_shape = ...`
- 广播规则：无 / Numpy 风格 / 单侧广播

### 6. 数据排布支持列表
| 排布格式 | 是否默认 | 说明 |
|---------|---------|------|
| NHWC    | 是 | 推荐 |
| FRACTAL_NZ | 可选 | 矩阵乘场景性能最优 |

### 7. 边界与异常行为
- 零维支持：是 / 否
- 空张量行为：跳过 / 报错
- 溢出处理：饱和 / 截断 / 未定义

### 8. 计算阶段划分（可选）
| 阶段 | 操作 | 输入 | 输出 |
|------|------|------|------|

### 9. 不支持功能列表
- 明确列出当前版本不支持的组合或边界条件

### 10. Golden 代码对齐结论
- 公式-代码一致性：通过 / 存在差异（列出差异点）
- 发现的笔误/错误：（若有）

---

## 二、op_spec.json Schema

使用 JSON Schema 2020-12 语法描述。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AscendC Operator Specification",
  "type": "object",
  "required": ["op_name", "aclnn_name", "op_type", "mutation_mode", "inputs", "outputs", "data_type_support", "shape_constraints", "data_format", "boundary_handling"],
  "properties": {
    "op_name": { "type": "string", "description": "算子名称（snake_case，以 golden.py 入口函数名为权威源，§1.13；需求描述/ proto 的 operator.name 作辅助印证——proto 的 Pascal 可能含数字段大写如 AdaptiveAvgPool3D，与 golden snake 的 Pascal（AdaptiveAvgPool3d）不一致，op_name 一律取 golden 入口 snake）" },
    "aclnn_name": { "type": "string", "description": "算子的 ACLNN 接口名（必填，如 aclnnGridSampler2DBackward）。唯一来源 = 用户输入资料照抄（接口名是用户/算子产权方知道的事实）——不生成、不推断、不从 op_name 拼接（历史缺陷：拼接产出 aclnncross_entropy_... 这类错误名并污染下游 CSV 的 stc_op_name 列）；用户材料缺失时向用户确认。下游测试设计阶段写入用例 CSV 的 stc_op_name 列（供 cann-bench 侧按接口名调度）" },
    "op_type": { "type": "string", "enum": ["compute", "movement", "hybrid"] },
    "dev_scenario": { "type": "string", "enum": ["new", "incremental"] },
    "mutation_mode": {
      "type": "string",
      "enum": ["in_place", "out_of_place"],
      "description": "算子写法特性（必填）。in_place: 存在与 input 同名的 output（状态张量原地更新）；out_of_place: output 与 input 不同名（独立输出）。决定 plugin 交付契约——in_place 算子的同名状态张量须 clone 后 return，禁 copy_ 写回原张量本体。per-tensor 读写与之正交：由 inputs/outputs 同名关系隐式定义（同名=read_write、仅 input=read_only、仅 output=write_only），不单列 access_mode。自洽约束：mutation_mode=in_place ⇔ 存在 output.name 出现在 inputs 中；不符则加载期报错（§1.3）。"
    },
    "constraints": {
      "type": "array",
      "description": "精度/性能约束。design_target_chip 不在此——目标代际由需求文档顶层 YAML design_target_chip 字段声明（canonical A2/A3/A5，权威源 domain/chip.py），requirement stage 确定性解析；agent 产的 constraint 不作为 chip 来源（P81 step-58，防照搬示例污染）",
      "items": {
        "type": "object",
        "properties": {
          "kind": { "type": "string", "enum": ["precision", "performance", "hardware"] },
          "threshold": { "type": "number", "description": "精度阈值（precision）" },
          "baseline_ms": { "type": "number", "description": "性能基线（performance）" }
        }
      }
    },
    "hardware_params": {
      "type": "object",
      "properties": {
        "ub_size_kb": { "type": "number" },
        "num_cores": { "type": "integer" },
        "bandwidth_gb_s": { "type": "number" }
      }
    },
    "math_formula": { "type": "string", "description": "数学公式（计算/混合类必填）" },
    "address_mapping": { "type": "string", "description": "地址映射逻辑（搬运类必填）" },
    "inputs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "dtype", "shape_constraints"],
        "properties": {
          "name": { "type": "string" },
          "dtype": { "type": "array", "items": { "type": "string" }, "description": "支持的 dtype 列表" },
          "shape_constraints": { "type": "string", "description": "自然语言或符号表达式" },
          "semantic": { "type": "string" },
          "is_list": { "type": "boolean", "description": "结构信号：该输入是 TensorList（变长张量列表，CANN Tensor[]）。为 true 时 param_type 必须标 DYNAMIC（框架会确定性校验，误标 REQUIRED/OPTIONAL 会被拒）。proto.yaml 的 operator.inputs[].is_list 或 operator.schema 签名 Tensor[] 是权威信号，requirement 阶段会自动派生；此处按结构信号如实声明（不必臆造）" },
          "param_type": { "type": "string", "enum": ["REQUIRED", "OPTIONAL", "DYNAMIC"], "description": "OpDef ParamType（对齐 CANN OpParamDef::ParamType）。默认 REQUIRED；可选输入标 OPTIONAL；动态长度输入标 DYNAMIC。TensorList 输入（is_list=true）必须 DYNAMIC。未声明按 REQUIRED" },
          "value_range": { "type": "array", "description": "可选，仅用户声明才有：该输入数据的取值范围 [[min,max], ...]（可含 [\\\"inf\\\",\\\"inf\\\"]、[\\\"nan\\\",\\\"nan\\\"] 等特殊值条目）。用户输入资料中明确声明了 → 照抄（不推理、不改写）；没写 → 不写该字段（缺失 = 无算子特定值域，下游测试设计用通用类型值域兜底——非漏写）。禁止自行生成/推理补齐（推理=猜测，会引入无依据约束）。注意与 param_type 正交：param_type 描述输入本身可否缺省，value_range 描述输入数据的取值" }
        }
      }
    },
    "outputs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "dtype_derivation", "shape_formula"],
        "properties": {
          "name": { "type": "string" },
          "dtype_derivation": { "type": "string", "enum": ["same_as_input", "promote", "fixed"], "description": "类型推导规则" },
          "fixed_dtype": { "type": "string", "description": "若 derivation 为 fixed，则指定具体 dtype" },
          "shape_formula": { "type": "string", "description": "输出形状计算公式，如 'input_shape' 或 '[N, H_out, W_out]'" },
          "param_type": { "type": "string", "enum": ["REQUIRED", "OPTIONAL", "DYNAMIC"], "description": "OpDef ParamType，默认 REQUIRED；几乎全部输出为 REQUIRED，动态输出才标 DYNAMIC" }
        }
      }
    },
    "data_type_support": {
      "type": "object",
      "required": ["input_combinations", "output_derivation"],
      "properties": {
        "input_combinations": {
          "type": "array",
          "items": {
            "type": "array",
            "items": { "type": "string" },
            "minItems": 1
          },
          "description": "合法的输入 dtype 组合列表"
        },
        "output_derivation": { "type": "string" },
        "unsupported_combinations": { "type": "array", "items": { "type": "array", "items": { "type": "string" } } }
      }
    },
    "shape_constraints": {
      "type": "object",
      "required": ["symbolic_rules", "broadcast_rule"],
      "properties": {
        "symbolic_rules": { "type": "array", "items": { "type": "string" }, "description": "符号化等式/不等式列表" },
        "dynamic_dims": { "type": "array", "items": { "type": "string" }, "description": "可变维度名称列表" },
        "output_shape_formula": { "type": "string" },
        "broadcast_rule": { "type": "string", "enum": ["none", "numpy", "left_only", "right_only", "custom"] },
        "broadcast_custom_desc": { "type": "string" }
      }
    },
    "data_format": {
      "type": "object",
      "required": ["supported"],
      "properties": {
        "supported": { "type": "array", "items": { "type": "string", "enum": ["NHWC", "NCHW", "HWCN", "FRACTAL_NZ", "NC1HWC0", "ND"] } },
        "default": { "type": "string" },
        "requires_conversion": { "type": "boolean", "description": "是否需要在算子内部处理格式转换" },
        "conversion_overhead": { "type": "string", "enum": ["low", "medium", "high"] }
      }
    },
    "boundary_handling": {
      "type": "object",
      "required": ["zero_dim_support", "empty_tensor_behavior", "overflow_handling"],
      "properties": {
        "zero_dim_support": { "type": "boolean" },
        "empty_tensor_behavior": { "type": "string", "enum": ["skip", "error", "undefined"] },
        "overflow_handling": { "type": "string", "enum": ["saturate", "truncate", "undefined"] }
      }
    },
    "phase_breakdown": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "phase": { "type": "string" },
          "operations": { "type": "string" },
          "inputs": { "type": "array", "items": { "type": "string" } },
          "outputs": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "unsupported_features": { "type": "array", "items": { "type": "string" } },
    "golden_alignment": {
      "type": "object",
      "properties": {
        "status": { "type": "string", "enum": ["pass", "diff"] },
        "differences": { "type": "array", "items": { "type": "string" } },
        "notes": { "type": "string" }
      }
    }
  }
}
```

### 示例：Add 算子的 op_spec.json 片段

> 注：下方 `op_name: "Add"` 为示意（算子的名字标签）。机器消费端（落盘目录名 / runtime config
> 反推）以 **golden 入口 snake** 为基（无前缀仓目录名 = golden snake；带前缀仓目录名 = 前缀 +
> golden snake，`full_op_name = prefix + op_name`）：Add 的 golden 入口为 `add`，对应落盘目录
> `add`、注册名 `Add`——注册名 Pascal 由「逐 `_` 段 capitalize」从**落盘目录名**派生，不从本
> example 的 Pascal 字面抄（含数字段算子尤须如此：`adaptive_avg_pool_3d` 落盘 → 注册名
> `AdaptiveAvgPool3d` 小写 d，非 proto 的 `AdaptiveAvgPool3D`）。

```json
{
  "op_name": "Add",
  "aclnn_name": "aclnnAdd",
  "op_type": "compute",
  "mutation_mode": "out_of_place",
  "constraints": [
    { "kind": "precision", "threshold": 1e-05 }
  ],
  "inputs": [
    { "name": "x", "dtype": ["float16", "float32"], "shape_constraints": "same as y" },
    { "name": "y", "dtype": ["float16", "float32"], "shape_constraints": "broadcastable to x" }
  ],
  "outputs": [
    { "name": "z", "dtype_derivation": "same_as_input", "shape_formula": "broadcast(x, y)" }
  ],
  "data_type_support": {
    "input_combinations": [["float16","float16"], ["float32","float32"]],
    "output_derivation": "same_as_first_input"
  },
  "shape_constraints": {
    "symbolic_rules": [],
    "broadcast_rule": "numpy"
  },
  "data_format": {
    "supported": ["ND"],
    "default": "ND",
    "requires_conversion": false
  },
  "boundary_handling": {
    "zero_dim_support": true,
    "empty_tensor_behavior": "skip",
    "overflow_handling": "saturate"
  }
}
```
