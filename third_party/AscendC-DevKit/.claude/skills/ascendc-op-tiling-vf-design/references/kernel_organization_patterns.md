# Kernel 内部组织模式

抽象自 14 类算子的**kernel 内部代码组织共性**。不暴露具体算子信息。

---

## 模式 1：基类继承（Base Class Inheritance）

**描述**：定义统一的 kernel 基类，所有变体算子继承基类并 override Compute。

### 结构

```
class BaseKernel {
public:
  void Init();           // 统一初始化
  void Process();        // 主流程
  void CopyIn();         // 默认实现
  void CopyOut();        // 默认实现
protected:
  virtual void Compute() = 0;   // 子类 override
};

class OpV3Impl : public BaseKernel {
protected:
  void Compute() override;   // 子类特有计算
};
```

### 适用类别

- **典型**：C3 random（PRNG 业务逻辑差异大，公共框架统一）
- **次典型**：C10 foreach（Init/Process/CopyIn/CopyOut 统一）

### 优势

- Init/Process/CopyIn/CopyOut 统一管理
- 子类只需关注 Compute 差异

### 劣势

- 灵活性受限（公共流程不易改动）
- 继承层级深时难以调试

---

## 模式 2：common header（共享基础设施）

**描述**：通过 `*_common.h` 集中跨算子共享的 helper VF、index 表生成、数据搬运辅助。

### 结构

```
{op}_common.h      # 共享 helper VF、index 表、数据搬运
  ├─ {op}_v2.cpp        # include common
  ├─ {op}_grad.cpp      # include common
  ├─ {op}_v3.cpp        # include common
  └─ ...
```

### 适用类别

- **典型**：C5 conv（喂料重排 helper）、C6 pooling（pool_3d_common 跨 15 个算子）
- **次典型**：C14 posembedding（跨算子共用 header）

### 优势

- 模块化清晰（公共代码集中）
- 易于维护（修改一次，全员生效）

### 劣势

- common header 改动影响所有 include 算子
- 编译依赖复杂（修改 common 触发大量重编译）

---

## 模式 3：Helper VF / Helper Struct（跨算子复用）

**描述**：将复杂 DAG 或计算封装为 helper（VF 或 struct），跨多个算子复用。

### VF 形式

```
namespace OpHelper {
  template<typename T>
  __aicore__ inline void ComputeXSquare(LocalTensor<T> ...) {
    // 跨算子复用的平方和计算
  }
}
```

### Struct 形式

```
namespace MishDag1 {
  struct MishCustom {
    template<typename T>
    __aicore__ inline void operator()(RegTensor<T>& dst, ...) {
      // 跨算子复用的 Mish 计算
    }
  };
}
```

### 适用类别

- **典型**：C4 activation（mish_grad 持有 MishCustom）
- **次典型**：C9 norm（NormCommon 跨算子 helper）

### 优势

- 复杂逻辑复用，避免重复实现
- 单元测试友好（helper 独立测试）

### 劣势

- 跨算子耦合（helper 修改影响所有调用方）
- helper 接口稳定性要求高

---

## 模式 4：dtype × 属性模板特化

**描述**：通过 `template<typename T, bool ...>` + `if constexpr` 在编译期生成多个 VF/DAG。

### 结构

```cpp
template<typename T, bool HAS_WEIGHT, bool IS_TRAINING, typename IndexT>
class OpImpl {
public:
  __aicore__ void Compute() {
    if constexpr (HAS_WEIGHT) {
      // weight 分支
    }
    if constexpr (IS_TRAINING) {
      // 训练分支
    }
  }
};

// 调用
OpImpl<float, true, false, uint32_t> impl;
impl.Compute();  // 编译期选择分支
```

### 适用类别

- **几乎所有**：C2、C4、C8、C9、C11 等

### 优势

- 编译期优化（死代码消除）
- 单文件管理多个变体

### 劣势

- 编译时间长（每个特化实例都编译）
- 调试困难（错误信息指向模板实例）

---

## 模式 5：mode × path 笛卡尔积多文件

**描述**：mode（计算模式）× path（实现路径）的笛卡尔积生成多个 VF 文件。

### 结构

```
{op}_v3_mode_a_path_1.cpp
{op}_v3_mode_a_path_2.cpp
{op}_v3_mode_a_path_3.cpp
{op}_v3_mode_b_path_1.cpp
{op}_v3_mode_b_path_2.cpp
...
```

### 典型规模

- C1 layout 的 pad_v3：13 文件 = 4 mode × 3-4 path
- C11 quant 的 ascend_anti_quant_v2：10 文件 = per_tensor × {sqrt, !sqrt} × {nddma, !nddma}
- C1 layout 的 matrix_diag：3 文件 = 3 dtype 切分

### 适用类别

- **典型**：C1 layout、C9 norm（含 quant 扩展）、C11 quant

### 优势

- 每个文件职责单一
- 编译粒度可控（修改一个不影响其他）

### 劣势

- 文件数量爆炸
- 公共代码需要通过 header 共享

---

## 模式 6：跨核 workspace 累加

**描述**：reduction 类算子需要跨核汇总，通过标准 5 步流水线实现。

### 5 步标准流水线

```cpp
// 步骤 1：清零 workspace
ClearUB(workspaceUb);

// 步骤 2：每个核写入自己的 partial result 到 workspace
DataCopyWorkspace(workspaceUb, localResult);

// 步骤 3：跨核 AddPartialResult 累加
AddPartialResult(workspaceUb, partialResults);

// 步骤 4：DivAndCast（如果是 mean）
DivAndCast(outputUb, workspaceUb, totalCoreCount);

// 步骤 5：写出
DataCopy(outputGm, outputUb);
```

### 适用类别

- **典型**：C8 loss（nll_loss ReduceSumInCore）、C10 foreach（cross-tensor norm）
- **次典型**：C2 math（含 reduce 的算子）

### 关键约束

- 仅 `reduction != none` 时启用
- 需要 `SyncAll` 跨核同步
- workspace 通常分配在 GM（容量大）

---

## 模式 7：Helper + main 双文件

**描述**：helper 文件负责生成 index 表等"一次生成多次使用"的数据，main 文件包含主 VF。

### 结构

```
{op}_helper.cpp   // SetIndex/CreateIndex（仅 firstIterate 跑）
{op}_main.cpp     // 主 VF（gather/scatter/compute）
```

### 适用类别

- **典型**：C5 conv（喂料重排 helper 配对）
- **次典型**：C1 layout（gather helper）

### 关键约束

- helper 仅 `isFirstIterate` 跑一次
- helper 输出（idx_table）常驻 UB 跨主循环复用

---

## 模式 8：分发器 VF（Dispatcher VF）

**描述**：dispatcher VF 仅做"清零 + 按 dtype/属性调子 VF"，不包含实际计算。

### 结构

```cpp
template<typename T>
__aicore__ void DispatchVF() {
  ClearSpr<AR>(outputReg);
  if constexpr (is_fp16<T>) {
    ComputeFP16();   // 子 VF
  } else if constexpr (is_fp32<T>) {
    ComputeFP32();   // 子 VF
  }
}
```

### 适用类别

- **典型**：C7 index（unsorted_segment_sum 的 ComputeUniqueIdNum）
- **次典型**：C8 loss（按 dtype 分发到具体 DAG）

---

## 模式 9：同构算子复用（Isomorphic Operator Reuse）

**描述**：姊妹算子（如正向/反向、add/update）100% 同构，直接复用对方的 VF。

### 典型场景

- C7：scatter_nd_update 复用 scatter_nd_add::ComputeOutOfset
- C9：rms_norm_grad 复用 rms_norm 部分 helper
- C8：cross_entropy_loss_grad 复用 cross_entropy_loss 部分 DAG

### 适用类别

- 多个类别都有此模式

### 优势

- 减少代码量
- 行为一致性（姊妹算子保证同步）

---

## 模式 10：闭式 VF 内联（Closed-form Inlining）

**描述**：当算子最终表达式可在单 VF 内完成时，避免不必要的 VF 拆分。

### 判定条件

- 无跨阶段依赖
- 无中间结果需要跨 VF 共享
- 寄存器压力在限内

### 适用类别

- **典型**：C9 norm（rms_norm 闭式单 VF）
- **次典型**：C4 activation（简单一元函数）
- **典型反例**：C9 batch_norm（必须拆 reduce → normalize → cast）

### 优势

- 性能最优（无 VF 间同步）
- 代码简洁

### 关键约束

- 寄存器压力不可超限（A5: 32 RegTensor / 8 MaskReg）

---

## 模式选择决策

```
选择模式时考虑：
  ├─ 是否跨算子共享？
  │   ├─ 是 → 基类继承 (A) 或 common header (B)
  │   └─ 否
  │       ├─ 是否多 dtype × 属性组合？
  │       │   ├─ 是且 < 20 → 模板特化 (D)
  │       │   └─ 是且 ≥ 20 → 多文件 (E)
  │       └─ 否
  │           ├─ 是否有 gather/scatter？
  │           │   ├─ 是 → Helper + main (G)
  │           │   └─ 否
  │           │       ├─ 是否需跨核累加？
  │           │       │   ├─ 是 → Workspace 累加 (F)
  │           │       │   └─ 否
  │           │       │       ├─ 算子是否单闭式？
  │           │       │       │   ├─ 是 → 闭式内联 (J)
  │           │       │       │   └─ 否 → 按阶段分 VF（基类继承 A）
```

---

## 模式间的相互关系

```
┌──────────────────────────────────────────┐
│           模式 A：基类继承                │
│  ┌───────────────────────────────────┐   │
│  │   模式 B：common header           │   │
│  │  ┌─────────────────────────────┐  │   │
│  │  │  模式 C：Helper struct      │  │   │
│  │  │  ┌───────────────────────┐  │  │   │
│  │  │  │ 模式 D：模板特化       │  │  │   │
│  │  │  │  ┌─────────────────┐  │  │  │   │
│  │  │  │  │ 模式 E：多文件  │  │  │  │   │
│  │  │  │  │  ┌───────────┐  │  │  │  │   │
│  │  │  │  │  │ 模式 F-G  │  │  │  │  │   │
│  │  │  │  │  │ Workspace │  │  │  │  │   │
│  │  │  │  │  │ Helper+   │  │  │  │  │   │
│  │  │  │  │  │ main      │  │  │  │  │   │
│  │  │  │  │  └───────────┘  │  │  │  │   │
│  │  │  │  └─────────────────┘  │  │  │   │
│  │  │  └───────────────────────┘  │  │   │
│  │  └─────────────────────────────┘  │   │
│  └───────────────────────────────────┘   │
└──────────────────────────────────────────┘
```

**实际工程中，多个模式嵌套使用**：

- 顶层：基类继承（A）
- 第二层：common header（B）
- 第三层：Helper struct（C）+ 模板特化（D）
- 文件组织：多文件（E）
- 运行时：Workspace 累加（F）+ Helper+main（G）

---

## 总结：选择组织模式的 5 个关键问题

1. **跨算子复用度？** —— 高 → A/B，低 → D/E
2. **dtype × 属性组合数？** —— < 20 → D，≥ 20 → E
3. **是否有 gather/scatter？** —— 是 → G
4. **是否需跨核累加？** —— 是 → F
5. **是否单闭式？** —— 是 → J（闭式内联）
