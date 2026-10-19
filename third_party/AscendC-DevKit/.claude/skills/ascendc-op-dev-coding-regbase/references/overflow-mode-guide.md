# Float Overflow Mode 使用指南（A5 Regbase 专属）

> **文档定位**：给 S4 编码阶段提供 A5 Regbase 场景下 **浮点溢出模式（Float Overflow Mode）** 的完整实操指南——覆盖触发条件、API 用法、4 种调用位置模式、代码模板、社区惯用 helper、常见陷阱。由 S2 在 `coding_index.md` 通过 `overflow_mode:XXX` 前缀引用。
>
> **⚠️ 平台约束**：本文档**仅**适用于 **A5 Regbase**（`__NPU_ARCH__ == 3510`，Ascend 950PR/950DT/Atlas 350）。**A3 Membase 场景不适用**——A3 无对应的 CTRL SPR 位设置需求，也不涉及 FP8/FP4/HiFP8 家族 dtype。
>
> **不覆盖**：CTRL 寄存器其他位（CTRL[45] Mmad 语义、CTRL[53] 整数饱和、CTRL[8:6] 原子操作等）→ 见 `ascendc-dev-knowledge` 的 `SetCtrlSpr（ISASI）.md` 官方文档。

---

## §1 快速定位

| 场景 | 直接读本文档哪一节 |
|---|---|
| 判断算子是否需要设置溢出模式 | §2 触发决策树 |
| 理解为什么需要设置（不设置会怎样） | §3 背景与后果 |
| API 用法（`SetCtrlSpr<60, 60>(0)` 参数含义） | §4 API 详解 |
| 4 种调用位置选哪个（Init / kernel 入口 / Compute 局部包裹） | §5 调用位置模式 |
| 直接抄代码模板 | §6 代码模板 |
| 是否使用社区 helper 函数 `SetFloatOverflowModeForRegbase` | §7 社区惯用 helper |
| 陷阱清单（原子操作、SuperKernel、恢复缺失等） | §8 常见陷阱 |

---

## §2 触发决策树

```
是否 A5 Regbase 场景？（__NPU_ARCH__ == 3510）
├─ 否 → 本指南不适用（本文档以下所有规则均无效）
└─ 是 → 继续判断输出/量化后 dtype
    ├─ dtype ∈ { hifloat8_t, fp8_e5m2_t, fp8_e4m3fn_t, fp4x2_e2m1_t, fp4x2_e1m2_t }
    │   → **必须设置** 浮点溢出模式（本指南主场景）
    ├─ dtype ∈ { int8, int4, int32, uint* } 等整数类型
    │   → 无需设置（整数饱和由 CTRL[53] 控制，本指南不覆盖）
    ├─ dtype ∈ { float, bfloat16_t, half } 等常规浮点
    │   → 无需设置（常规浮点计算走默认路径即可）
    └─ Compute 内部经过 FP8/FP4 中间转换（如 MxQuant 场景）
        → **必须设置**（即使输入输出都不是 FP8，只要中间态涉及 FP8/FP4）
```

**判断依据**（重要）：判断依据是 **"目标/输出 dtype 或中间态 dtype"**，不是"输入 dtype"。代码模板：

```cpp
// 常见模板：以输出类型 U 为触发条件
// ⚠️ MxQuant 类算子中间态涉及 FP8/FP4，即使输入输出都不是 FP8 也需触发——
// 此类算子建议无条件设置（不判 dtype），见 §7 陷阱 8
if constexpr (
    IsSameType<U, hifloat8_t>::value ||
    IsSameType<U, fp8_e5m2_t>::value ||
    IsSameType<U, fp8_e4m3fn_t>::value ||
    IsSameType<U, fp4x2_e2m1_t>::value ||
    IsSameType<U, fp4x2_e1m2_t>::value) {
    AscendC::SetCtrlSpr<FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>(0);
}
```

---

## §3 背景与后果

### §3.1 CTRL[60] 位的语义

`FLOAT_OVERFLOW_MODE_CTRL == 60`——CTRL 系统寄存器的第 60 位，控制**浮点溢出饱和模式的生效方式**：

| CTRL[60] 值 | 语义 | 效果 |
|---|---|---|
| **0** | **单指令生效模式** | 让每条 Cast 指令按自己的 `SatMode` trait 决定（`SatMode::SAT` 生效，饱和到 ±MAX，NaN→0）|
| **1**（默认） | **全局生效模式** | 由 CTRL[48]/CTRL[59] 全局控制饱和/非饱和（默认路径会产生 Inf/NaN）|

### §3.2 不设置的后果（有实证）

来源：`skills/regbase-vf-test/references/vf_experiences/dequant-quant/experience-fp8-data-dequant.md`（实证来源含原 lesson）：

> "FP32 Mul 溢出为 inf …… scale × max_fp8 > FP32_MAX → FP32 inf → BF16 inf …… max_diff=inf"

**症状**：量化算子在大 scale 场景下**全部输出 Inf/NaN**，精度完全失控，且不会崩溃只是结果错误——非常隐蔽。

### §3.3 为什么"设置 = SPR 位设为 0"

- CTRL[60] 默认值 = 1（全局模式），此时即使 Cast 声明了 `SatMode::SAT` trait 也会被忽略
- 设为 0 后，Cast 指令按自己的 SatMode trait 生效，饱和逻辑正常工作
- 代码里常用命名常量 `FLOAT_OVERFLOW_MODE_SATURATE = 0` 表明这一含义

---

## §4 API 详解

### §4.1 API 原型

```cpp
template <int8_t startBit, int8_t endBit>
__aicore__ static inline void SetCtrlSpr(int64_t value);

template <int8_t startBit, int8_t endBit>
__aicore__ static inline int64_t GetCtrlSpr();
```

**权威来源**：`ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/系统变量访问/SetCtrlSpr（ISASI）.md`（完整版含 CTRL 全 bit 表）。

### §4.2 常用调用格式

```cpp
// 设置：CTRL[60] = 0，即启用单指令 SatMode 生效
// 两个 template 参数分别是 startBit / endBit，操作单 bit 时两者相同（约定写法）
AscendC::SetCtrlSpr<FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>(0);

// 读取当前值（用于 save/restore）
int64_t ori = AscendC::GetCtrlSpr<FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>();

// 恢复
AscendC::SetCtrlSpr<FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>(ori);
```

### §4.3 相关 CTRL 位（速查）

以下位属于同一 CTRL SPR 寄存器但**本指南不覆盖**，如需深入查官方 `SetCtrlSpr（ISASI）.md` 表 4：CTRL[48] 全局浮点饱和、CTRL[50] FP→FP8 NaN 策略、CTRL[59] FP→INT 饱和、CTRL[53] 整数计算饱和、CTRL[45] Mmad E4M3FN→HiFP8。**本指南场景只需操作 CTRL[60]**。

---

## §5 调用位置模式（3 种，附选择建议）

从代码规律总结，A5 量化/归一化算子有 3 种典型调用位置：

| # | 模式 | 使用场景 | 是否 restore | 代表算子 |
|---|---|---|---|---|
| A | **Init 中一次性 Set(0)，不 restore** | 单算子简单场景，kernel 生命周期内全程需要 | ❌ | `quantize.h` L88-97；`quant_update_scatter_base.h` L61-70 |
| B | **Kernel 入口 apt 层 save+restore** | 严谨、生产级；避免污染下游算子 | ✅ | `quantize_apt.cpp` L131/L165 |
| C | **Init 保存 + Compute 局部包裹 + 恢复** | 只在算子内某段（如 MxQuant Compute）需要 | ✅（局部）| `rms_norm_dynamic_mx_quant_full_load.h` L43/L211/L221 |

> **编码风格差异（非独立模式）**：模式 A/B/C 均可搭配命名常量 `FLOAT_OVERFLOW_MODE_SATURATE = 0` 代替字面量 `0`，提高可读性（见 §6 代码模板）。

### §5.1 选择建议

| 场景 | 推荐模式 |
|---|---|
| **默认（推荐）** | **模式 B**：Kernel 入口 apt 层 save+restore。最严谨，未来即使集成到 SuperKernel 场景也不会污染下游 |
| 单算子独立部署，无 SuperKernel 顾虑 | 模式 A（最简单）|
| Compute 中只有某段涉及 FP8/FP4（其他段是 BF16/FP16）| 模式 C（局部包裹，最小影响面）|

**社区惯用 helper**：`SetFloatOverflowModeForRegbase<U>()`，8+ 算子共用。**详见 §7**。

---

## §6 代码模板

三种模式的模板骨架。**推荐用命名常量 `FLOAT_OVERFLOW_MODE_SATURATE = 0`** 提高可读性。类框架内如需集成为 helper 见 §7.1。

### §6.1 模板 A：Init 一次性 Set（最简，无 restore）

```cpp
constexpr int64_t FLOAT_OVERFLOW_MODE_SATURATE = 0;  // 单指令 SatMode 生效

#if (__NPU_ARCH__ == 3510)
    if constexpr (
        IsSameType<U, hifloat8_t>::value ||
        IsSameType<U, fp8_e5m2_t>::value ||
        IsSameType<U, fp8_e4m3fn_t>::value ||
        IsSameType<U, fp4x2_e2m1_t>::value ||
        IsSameType<U, fp4x2_e1m2_t>::value) {
        AscendC::SetCtrlSpr<
            FLOAT_OVERFLOW_MODE_CTRL,
            FLOAT_OVERFLOW_MODE_CTRL>(FLOAT_OVERFLOW_MODE_SATURATE);
    }
#endif
```

### §6.2 模板 B：Kernel 入口 save+restore（推荐）

```cpp
extern "C" __global__ __aicore__ void quantize_custom(
    GM_ADDR x, GM_ADDR scale, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    // === 入口：保存 SPR 原值并设置 ===
    int64_t oriOverflowMode = 0;
#if (__NPU_ARCH__ == 3510)
    oriOverflowMode = AscendC::GetCtrlSpr<
        FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>();
    AscendC::SetCtrlSpr<
        FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>(FLOAT_OVERFLOW_MODE_SATURATE);
#endif

    // === 主体：正常算子逻辑 ===
    KernelQuantize op;
    op.Init(x, scale, y, tiling);
    op.Process();

    // === 退出：恢复 SPR 原值 ===
#if (__NPU_ARCH__ == 3510)
    AscendC::SetCtrlSpr<
        FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>(oriOverflowMode);
#endif
}
```

### §6.3 模板 C：Compute 内局部包裹

```cpp
class KernelRmsNormQuant {
    int64_t oriOverflowMode_ = 0;  // 类成员

    __aicore__ inline void Init(...) {
        // ... 常规 Init 逻辑 ...
    #if (__NPU_ARCH__ == 3510)
        oriOverflowMode_ = AscendC::GetCtrlSpr<
            FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>();
    #endif
    }

    __aicore__ inline void Compute() {
        // ... BF16/FP32 段计算（不影响溢出模式）...

    #if (__NPU_ARCH__ == 3510)
        AscendC::SetCtrlSpr<
            FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>(FLOAT_OVERFLOW_MODE_SATURATE);
    #endif

        ComputeMxQuant();  // 涉及 FP8/FP4 转换

    #if (__NPU_ARCH__ == 3510)
        AscendC::SetCtrlSpr<
            FLOAT_OVERFLOW_MODE_CTRL, FLOAT_OVERFLOW_MODE_CTRL>(oriOverflowMode_);
    #endif

        // ... 后续常规段 ...
    }
};
```

---

## §7 社区惯用 helper：`SetFloatOverflowModeForRegbase`

现有 8+ 个算子（quantize / dequantize / dynamic_quant / gelu_quant / quant_update_scatter / dequant_swiglu_quant / ascend_quant 等）都采用同一 helper 命名。**新写算子建议沿用**，保持仓库一致性。将 §6 模板 A 的 dtype 判断 + Set 逻辑抽为 Base 类方法，好处：

- 触发条件（dtype 判断）集中在一处
- 架构宏 `#if (__NPU_ARCH__ == 3510)` 只写一次
- 未来若增加新触发 dtype，只改 Base 类

### §7.1 Base 类中定义 helper

```cpp
template <typename T, typename U>  // T: 输入 dtype；U: 输出/量化后 dtype
class QuantizeBase {
public:
    __aicore__ inline void SetFloatOverflowModeForRegbase()
    {
#if (__NPU_ARCH__ == 3510)
        if constexpr (
            IsSameType<U, hifloat8_t>::value ||
            IsSameType<U, fp8_e5m2_t>::value ||
            IsSameType<U, fp8_e4m3fn_t>::value ||
            IsSameType<U, fp4x2_e2m1_t>::value ||
            IsSameType<U, fp4x2_e1m2_t>::value) {
            AscendC::SetCtrlSpr<
                FLOAT_OVERFLOW_MODE_CTRL,
                FLOAT_OVERFLOW_MODE_CTRL>(FLOAT_OVERFLOW_MODE_SATURATE);
        }
#endif
    }
};
```

### §7.2 子类中调用

```cpp
class QuantizePerHead : public QuantizeBase<T, U> {
public:
    __aicore__ inline void Init(...) {
        // ... 常规 Init ...
        this->SetFloatOverflowModeForRegbase();  // ← 一行调用
    }
};
```

### §7.3 泛型 Get/Set 工具（norm 类推荐）

`rms_norm/op_kernel/arch35/rms_norm_regbase_common.h` L47-68 提供了配对的 `GetOverflowMode<T_Y>()` / `SetOverflowMode<T_Y>(mode)`，适用于需要 save/restore 的场景（模式 C）。norm 类新算子推荐参考。

---

## §8 常见陷阱

| # | 陷阱 | 症状 | 正确做法 |
|---|------|------|---------|
| 1 | 忘记 Set(0)，或依据输入 dtype 而非输出 dtype 判断触发 | 大 scale 场景全部输出 Inf/NaN，max_diff = inf | 按 §2 决策树，**只看输出/量化目标 dtype**（不是输入 dtype）；触发时必设 |
| 2 | Set 后不 restore，污染下游算子 | 后续算子 SPR 状态被污染，结果错乱（SuperKernel 场景高发）| 用模式 B（kernel 入口 save+restore），或模式 C（局部包裹）|
| 3 | 原子操作场景改 CTRL[60] 前未 `DataCacheCleanAndInvalid` | 原子操作跨模式混算，隐蔽数据竞争 | 有原子操作时，Set 前先调 `DataCacheCleanAndInvalid`；见 `DataCacheCleanAndInvalid.md` L37 |
| 4 | 在 SIMT 代码中调用 SetCtrlSpr | SIMT 不支持 SPR 操作 | SIMT 场景通过 SIMT 的 cvt 接口（如 `asc_cvt_float2_to_fp8x2`）内部处理 |
| 5 | 使用 `SetCtrlSpr<60, 60>` 字面量或 `(0)` 立即数 | 可读性差，不利维护 | 用 `FLOAT_OVERFLOW_MODE_CTRL` 常量 + `FLOAT_OVERFLOW_MODE_SATURATE` 命名常量 |
| 6 | 忘记 `#if (__NPU_ARCH__ == 3510)` 保护 | A3/A2 场景编译失败或运行时报错 | 所有 SetCtrlSpr 调用必须用 `#if (__NPU_ARCH__ == 3510)` 包裹 |
| 7 | 触发 dtype 判断遗漏 FP4 变体（`fp4x2_e2m1_t` / `fp4x2_e1m2_t`）；或 MxQuant 类算子只按输出 dtype 判断 | MxQuant/FP4 场景漏设（输入输出可能都不是 FP8/FP4，但中间态涉及）| MxQuant 类算子建议**无条件设置**（不看 dtype），因中间态一定涉及 FP8/FP4 |

---

## §9 与其他知识源的关系

| 知识层 | 关系 |
|---|---|
| `ascendc-dev-knowledge` 官方文档 | 本文档提炼自 `api_reference_docs/SIMD_API/基础API/系统变量访问/SetCtrlSpr（ISASI）.md`（CTRL 全 bit 表、饱和模式配置）、`GetCtrlSpr（ISASI）.md`、`ResetCtrlSpr（ISASI）.md`、`DataCacheCleanAndInvalid.md`（L37 原子操作场景约束）、`Cast.md`（SatMode trait）；深入 API 语义请查官方文档 |
| `regbase-vf-test/references/vf_experiences/dequant-quant/experience-fp8-data-dequant.md` | 提供 FP8/FP4 转换前后 save/set(0)/restore 三行代码模式；本文档 §6 已扩写为完整模板 |
| `regbase-vf-test/references/vf_experiences/dequant-quant/experience-fp8-data-dequant.md`（实证来源） | 提供不设置的实证反例（max_diff=inf），本文档 §3.2 已引用 |
| `ascendc-op-design-shared/references/a5_regbase_design.md` §8.3 RB-EXC-R1/R2/R3 | 方法论规则要求"溢出/clip 优先用 SetCtrlSpr 类溢出模式而非 Max+Min 夹逼"；本文档提供具体实操 |
| `evolution-knowledge/a5/regbase_api/` | 未覆盖 CTRL SPR，本文档补齐该维度 |
| `tpipe-usage-guide.md`（本目录）| 不重叠。tpipe 讲 UB 内存管理（TQue/TBuf）；本文档讲 SPR 系统寄存器控制 |
| `ascendc-sync` skill | 不重叠。CTRL SPR 是控制寄存器，不属于流水同步范畴（虽然写入会持续影响后续指令，但语义不同）|

---

## §10 引用协议（S2 使用）

S2 在生成 `coding_index.md` 时，通过 `overflow_mode:XXX` 前缀引用本文档。**仅在 A5 Regbase 路径下使用**——A3 Membase 场景禁止填入。

| 前缀 | 指向章节 | 使用场景 |
|---|---|---|
| `overflow_mode:总入口` | §1 + §2 + §5 + §6 | **A5 Regbase + FP8/FP4 输出 dtype 场景 C.1 类框架默认强制填入**（唯一入口，涵盖决策/位置/模板）|
| `overflow_mode:代码模板` | §6 | Compute 编码时想快速定位模板 |
| `overflow_mode:helper` | §7 | 需要使用 `SetFloatOverflowModeForRegbase` 惯用写法 |
| `overflow_mode:陷阱清单` | §8 | 自检关注点（**尤其陷阱 1/2/3/6 是高频错误**；有原子操作时必查陷阱 3）|

**S4 解析** `overflow_mode:XXX` **时**：Read `${SKILL_ROOT}/references/overflow-mode-guide.md`，定位到对应章节。**如果算子不满足触发条件**（非 A5 Regbase / 输出非 FP8/FP4 家族 dtype 且中间态不涉及），S4 应忽略此引用并在 `history.log` 记录"跳过 overflow_mode 引用（非触发场景）"。
