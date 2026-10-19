# L4 — 「间接索引采样/插值」建模范式 skill 内容草案

> 性质：L4 实施方案草案，是 R3「新建 gather 建模范式最佳实践」的**内容设计**，供后续写 skill reference 直接取材。
> 定位：这是**知识/数据类 reference**（§2.8），不是 workflow；按**结构特征**组织（§1.12），不绑定任何具体算子名；正面讲「该怎么做」，负面约束归「约束」小节作边界，不做补丁式负面清单。
> 关联：L1 `01-problems.md` P13（gather 建模错）、L3 `02-analysis.md` Q15（方案层根因）。

## 0. 最终落地位置（组织归属，非本草案目录）

本文件是 **L4 阶段评审用的内容草案**，不长期停留 `docs/plan/`。草案内容**分两层落地**（不是全进 best-practices）：

**A. API 用法层 → `api-gather.md`（best-practices）**
- §3 原语选择、§5 关键约束（srcOffset 字节 / DataBlock 粒度 / 32B 对齐 / 越界钳制）→ `<repo>/.claude/skills/ascendc-api-best-practices/references/api-gather.md`
- 与 `api-datacopy.md` / `api-gathermask.md` / `api-transpose.md` 并列，**不改任何现有文件**。

**B. 概要设计模式层 → `G01_gather-vector.md`（补「采样/插值」变体）**
- §1 适用判据（间接寻址识别）、§2 分块范式（沿连续维分块 + 常数维退化）→ `ascendc-op-general-design/references/patterns/atomic/G01_gather-vector.md`，**补充「采样/插值」变体**。
- 理由：G01 是「索引间接搬运（LP2）」的概要设计模式**权威位置**；其现有语料（gather_v2/scatter/gather_nd…）**全是 index 张量驱动的 gather/scatter，缺「坐标变换生成 index + 角点相邻结构」的采样/插值类**。grid_sampler 走偏的根因正是「G01 缺采样/插值变体，设计没匹配到『沿连续维分块 + 常数维退化』，退化成逐元素搬移」。evolution-knowledge 定位是「进化优化」（double-buffering/pipeline 等性能模式），**不是**概要设计模式的归属（§2.7 skill 职责边界）。

**波及面（不止 api-gather.md 一个文件）**：

1. `ascendc-op-design-shared/references/knowledge_policy.md`（共享知识引用策略，被 10 个 `ascendc-op-*` skill 引用）
   - 三级知识源体系加 `ascendc-api-best-practices` 为「API 用法层」（插在 Tier 2 与 Tier 3 之间）。
   - **「骨架级 API 强制查证门」优先级调整**：从「无条件查 Tier 3 裸签名」改为「**先查 best-practices（用法 + 避坑）→ 再查 Tier 3（签名细节）**」。
2. `ascendc-dev-knowledge/SKILL.md`：检索优先级（evolution-knowledge → 本库 grep → WebSearch）加 best-practices 在最前。
3. `ascendc-api-best-practices/SKILL.md`（移植后）：API 类别索引 + 场景索引加 `Gather`/`BilinearInterpolation` → `api-gather.md`。

**查询优先级调整的根因**：现有「骨架级 API 强制查证门」要求 gather 选用前「查 Tier 3 裸签名」，但 gather 的坑（怎么分块、禁止逐元素 DataCopyPad）在「API 用法 / 建模范式层」，**不在裸签名里**——裸签名只讲「srcOffset 是字节」，不讲「该怎么分块、别逐元素搬」。故查证门查了签名、没查用法坑，是 grid_sampler AC2 的深层根因之一。调整后 gather 的强制查证会先命中 api-gather.md（用法 + 避坑），再补 Tier 3 签名细节。

依据：§2.8 知识归 `references/`、§4.2 skill 单一扁平树 `.claude/skills/<skill>/`、§2.7 skill 职责边界（API 用法 vs 建模范式分层）、R3「缺项新建 + 查证顺序改写」。草案审完、待查证项闭环后按此落地；落地后本草案归档删除，不在 `docs/plan/` 留副本。

**落地格式对齐（硬约束）**：`api-gather.md` 正文必须与并列 API 文档（以 `api-gathermask.md` 为主模板，`api-datacopy.md`/`api-transpose.md` 为参照）保持**章节模板一致**：`# <API> 使用指南` → 顶部 `> **适用场景**` 引用块 → `## 目录` → `## 概述`（用法模式表）→ `## 平台适用性`（表）→ 各 API 详解（代码示例 + 约束表）→ `## 常见错误`（错误/原因/解决方案表）→ `## 检查清单`（checkbox）→ `## 适用性检测`（grep）→ `## 参考资料`（CANN 链接）。**注意分层**：只有「API 用法层」映射进 api-gather.md——§3 原语选择→「Gather 详解」+「BilinearInterpolation 详解」、§5 约束→「约束表」+「检查清单」、§6 反例→「常见错误」表、§6.1 正例→「使用场景示例」；§1 判据、§2 分块范式属「概要设计模式层」，归 `G01_gather-vector.md`（补采样/插值变体），**不进 api-gather.md**。落地时剥离分析元信息：§0、§6.1 算子名追溯、§7。

**知识点 → 精确落位**（分层后，落地时逐条核对）：

| 知识点 | 归属 | 落地章节/小节 |
|---|---|---|
| 适用判据（间接寻址/非固定间隔/相邻结构） | `G01_gather-vector.md`（补「采样/插值」变体） | 变体条目 |
| 分块洞察（沿连续维分块 + 常数维退化） | `G01_gather-vector.md`（补「采样/插值」变体） | 变体条目 + 切分策略 |
| 搬入（向量化 DataCopy 整块）/ 加权累加（向量 Mul/Add） | `G01_gather-vector.md`（补「采样/插值」变体） | 变体条目 |
| 用法模式总表（Gather / BilinearInterpolation / GatherMask） | `api-gather.md` | `## 概述` → 模式对比表 |
| 偏移提取（Gather 的 srcOffset 字节偏移向量） | `api-gather.md` | `## Gather 详解` |
| **offset 越界钳制**（`min(floor, W-1)` + padding_mode 权重侧） | `api-gather.md` | `## Gather 详解` → `### offset 越界钳制` |
| **BilinearInterpolation 覆盖 3D 结论**（DataBlock 粒度 vs 元素粒度） | `api-gather.md` | `## BilinearInterpolation 详解` → `### 粒度与 3D 覆盖` |
| BilinearInterpolation dtype 仅 half、offset DataBlock 粒度 | `api-gather.md` | `## BilinearInterpolation 详解` → 约束表 |
| 平台差异（A2/A3 分块搬入 + Gather；A5 Reg 为源） | `api-gather.md` | `## 平台适用性` |
| 逐元素 DataCopyPad 单元素事务反例 | `api-gather.md` | `## 常见错误` 表首行 |
| 分块沿连续维 / offset 钳制 / 禁逐元素 | `api-gather.md` | `## 检查清单` |
| 逐元素 SetValue/GetValue 检测 | `api-gather.md` | `## 适用性检测` |
| CANN 文档链接（Gather / BilinearInterpolation） | `api-gather.md` | `## 参考资料` |

---

## 1. 适用判据（结构特征，满足任一即适用）

- **间接寻址**：输出每个元素在输入里的取值位置，由「运行时索引/坐标张量」决定，而非编译期常量或固定偏移。
- **非固定间隔**：取值位置不是「等间隔/掩码模式」（排除 GatherMask 的固定间隔场景，那属另一主题）。
- **相邻结构（采样/插值语义）**：取值位置是「各维 floor/ceil 的笛卡尔积」——d 维采样 = 2^d 个角点，相邻角点沿某一维差 1 个元素。

判据方法：看输出元素与输入元素的对应关系是否由**运行时索引**决定、且索引可能指向非连续位置。是 → 本范式；否 → 普通连续算子，走常规 tiling。

## 2. 核心范式（四步）

1. **分块**：沿「坐标连续变化的维」（相邻输出对应相邻输入的维，通常是最内维）切块；其余维的 floor/ceil 在块内**近似常数**。效果：采样窗口从「散布全平面的 2^d 个角点」退化为「沿连续维展开的局部条带」（常数维各 2 个 × 连续维一段），条带大小可进 UB。
2. **搬入**：向量化 `DataCopy` 把「采样窗口条带」整块搬进 UB。**不是**逐元素 `DataCopyPad` 单元素事务，**不是**整输入平面。
3. **偏移提取**：在 UB 内用指令自带能力取「角点在条带内的相对位置」的值（见 §3 原语选择）。
4. **加权累加**：向量化乘加完成插值权重累加（权重张量同 tile 广播或逐元素）。

## 3. 偏移提取的原语选择（按粒度/dtype 分支）

| 场景 | 原语 | 关键点 |
|---|---|---|
| 运行时任意偏移（每元素独立，元素粒度） | `Gather`（ISASI） | `srcOffset` 为运行时字节偏移数组，src 在 UB；支持 fp16/fp32/bfloat16 |
| DataBlock 粒度采样 + 双线性（half） | `BilinearInterpolation`（ISASI） | 偏移取 DataBlock + 加权累加一条指令；**A2/A3 仅 half**，`src0Offset` 为 **DataBlock（32B）粒度** → **不适用「元素粒度相邻角点」的 8 邻域插值**（w0/w1 同 DataBlock 无法区分），仅适用「采样点是 32B 对齐块」的场景 |
| 固定间隔提取 | `GatherMask` | **本范式不适用**（属解交织主题），勿误用于运行时任意索引 |

**禁用**：逐元素 `DataCopyPad` 单元素事务——每元素独立搬 1 个元素时，A2/A3 只有 Normal 模式（逐事务补 32B），dst 又有 32B 对齐约束，导致「每元素占 32B 槽位」的 UB 预算爆炸 + 全标量（PIPE_S）路径。这是本范式要消灭的头号反模式。

## 4. 平台差异（§1.9，按芯片代际分层，不写死单一原语）

- **A2/A3（Vector 模型）**：数据经 UB 做矢量计算是通用前置（非特例）。间接索引 = 分块搬入 + UB 内 `Gather` / `BilinearInterpolation`。
- **A5（Regbase/SIMT 模型）**：有 `Gather`（srcReg 寄存器为源），寄存器间接寻址对随机访问更友好。

## 5. 关键约束

- **32B 对齐**：src / dst / offset 的 LocalTensor 起始地址均须 32B 对齐。
- **offset 单位**：`Gather` 的 `srcOffset` 单位为**字节**（须 dtype 位宽对齐）；`BilinearInterpolation` 的 `src0Offset` 单位为 **DataBlock（32B）**。
- **dtype**：`BilinearInterpolation` 仅 half；`Gather` 支持 fp16/fp32/bfloat16；fp32 采样走 `Gather` + 手动向量插值。
- **offset 越界钳制**：`Gather` 的 offset 须落在 src（条带）内；越界位置**先坐标变换再钳制**（`min(floor, W-1)`），配合 padding_mode 在权重侧实现 zeros（权重置 0）/ border（钳读边界值）；reflection 是坐标反射后再钳制。这是「分块条带 + 越界采样」的标准处理，非逐元素搬移（正例实证：偏移向量一次性 `min(w0, WIn-1)` 钳制，见 §6.1）。

## 6. 反例（历史实证，通用语义描述）

把「d 维采样的 2^d 邻域间接 gather」建模成「逐元素 DataCopyPad 单元素事务」，导致每元素 32B 补全 → UB 预算超限、全标量路径、最终精度失败。该错误在 API 层表现为「DataCopyPad 约束没算对」，但根因是方案层「gather 被退化成逐元素搬运」——本范式第 2/3 步正是从根上堵住这条岔路。

### 6.1 正例对照（本批第二个采样算子，验证分块洞察通用性）

同为「采样 + 双线性插值」的算子（2D，4 角点），其通过实现**正是本范式的正确落地**，与上反例形成正反对照：

- **分块**：沿 H 分行窗口（h0/h1 两行）+ W 全宽——「采样窗口 = 2 行 × 全宽 W 的局部条带」。
- **搬入**：`DataCopyPad` 二维整块搬源行窗口（blockLen = WIn×sizeof(T)，整行搬，非逐元素）。
- **偏移提取**：`Gather(gA_, src, w0OffU32_, rowBase0, n)` —— `w0Off/w1Off` 是**字节偏移向量**（`int32` 槽位 `ReinterpretCast<uint32_t>`）。
- **累加**：`y = h0λ·(w0λ·x00 + w1λ·x01) + h1λ·(w0λ·x10 + w1λ·x11)`，向量 Mul/Add。
- **分支（范式内的重要维度）**：该算子索引是「规则 scale」→ 偏移向量一次性预生成；「任意坐标」采样则运行时逐元素算偏移向量。两者分块策略相同，仅偏移向量来源不同。

**结论**：分块洞察在「规则 scale 采样」与「任意坐标采样」两类都成立，验证其为「采样/插值类算子」的通用范式，非单算子补丁。（验证实例追溯：规则 scale = `resize_bilinear`、任意坐标 = `grid_sampler_3d`；仅作 L4 验证记录，落地 `api-gather.md` 时剥离算子名，§1.12。）

## 7. 待查证项（诚实标注，未确证前不写进 skill）

- [x] `BilinearInterpolation` 覆盖「三线性（3D）」——**已闭环：不覆盖**。其 `src0Offset` 是 **DataBlock 粒度（32B）**，而 3D 三线性的 8 角点中 w0/w1 是元素粒度相邻（差 2B/4B，同 DataBlock），DataBlock 粒度 offset 无法区分相邻角点 → 元素粒度 8 角点三线性走 `Gather`（元素粒度 offset）+ 手动向量插值（正例 resize_bilinear 已证）。BilinearInterpolation 仅适用于「采样点是 32B 对齐 DataBlock」的场景，属另一主题，不并入本范式正文。
- [x] `Gather` 分块后「offset 跨块边界」的精确处理——**已解答**（坐标钳制 `min(floor, W-1)` + padding_mode 权重侧处理，见 §5 与 §6.1 正例实证）。
- [x] 「常数维 floor/ceil 在块内近似常数」的分块洞察通用性——**已验证**（见 §6.1 正例对照，规则 scale 与任意坐标两类采样均成立）。

## 8. 附录 — BilinearInterpolation 语义探针实现（上板实测待排）

> 目的：`BilinearInterpolation` 全仓（知识库 + cann-bench）**无现成用法示例**，其文档语义（水平 8 DataBlock + 垂直 vRepeat 累加）较抽象。本探针用于上板反推精确语义，为 `api-gather.md` 的「BilinearInterpolation 详解」提供实证用法。**注意**：本探针是「语义探针」，非「正确用法示例」——它验证的是文档未明说的累加布局，结果未上板前不作落地依据。

### 8.1 待验证的不确定点

| # | 不确定点 | 探针如何验证 |
|---|---|---|
| P1 | `src0Offset` 是否确为 DataBlock(32B) 粒度字节偏移 | 设 8 个 offset = 0/32/64/…，观察是否每 32B 取一块 |
| P2 | `repeatMode=true` 时 8 DataBlock × 8 权重的**累加顺序**（dst 每个元素 = Σ_k src0[off_k]·w_k？） | 用全 1 权重 + 递增数据，反推累加公式 |
| P3 | 水平迭代 hRepeat 与「8 DataBlock」的关系（hRepeat=2 是否处理 16 块） | hRepeat=1 vs 2 对比 |
| P4 | 垂直迭代 vRepeat 的 dst 布局（vROffset 单位=元素，范围 [128,65535)） | vRepeat=2 观察 dst 分段 |
| P5 | dtype 仅 half 之外的约束（sharedTmpBuffer 大小、地址不重叠） | 编译期 + 运行期观察 |

### 8.2 探针 kernel 骨架（half，最小验证 P1/P2）

```cpp
// bilinear_interp_probe.cpp — 语义探针（非生产实现）
#include "kernel_operator.h"

// 目标：验证 BilinearInterpolation(ISASI) 的 src0Offset 粒度与 8-DataBlock 累加语义。
// 输入布局（half，1 DataBlock = 16 half = 32B）：
//   src0    : 8 个 DataBlock 连续排列（128 个 half），块 k 内容 = [k, k, ..., k]（16 个 k）
//   src0Off : uint32[8] = {0, 32, 64, 96, 128, 160, 192, 224}（每块字节偏移）
//   src1    : half[8] 权重 w_k（repeatMode=true 时 8 个权重）
// 预期（若语义 = Σ_k src0[off_k]·w_k 逐元素）：dst[j] = Σ_k k·w_k，与 j 无关。
template <typename T>
class BilinearProbe {
public:
    __aicore__ inline void Init(GM_ADDR src0Gm, GM_ADDR offGm, GM_ADDR wGm, GM_ADDR dstGm, uint32_t blkCnt) {
        src0_.SetGlobalBuffer(reinterpret_cast<__gm__ T*>(src0Gm));
        off_.SetGlobalBuffer(reinterpret_cast<__gm__ uint32_t*>(offGm));
        w_.SetGlobalBuffer(reinterpret_cast<__gm__ T*>(wGm));
        dst_.SetGlobalBuffer(reinterpret_cast<__gm__ T*>(dstGm));
        blkCnt_ = blkCnt;
    }
    __aicore__ inline void Process() {
        // 简化：单层搬运，不接 queue（探针，非性能）
        AscendC::LocalTensor<T> src0 = src0UB_;   // 8*16 half
        AscendC::LocalTensor<uint32_t> off = offUB_;   // 8 uint32
        AscendC::LocalTensor<T> w = wUB_;         // 8 half
        AscendC::LocalTensor<T> dst = dstUB_;     // 16 half（一个 DataBlock）
        AscendC::LocalTensor<uint8_t> tmp = tmpUB_;

        AscendC::DataCopy(src0, src0_[0], 8 * 16);
        AscendC::DataCopy(off, off_[0], 8);
        AscendC::DataCopy(w, w_[0], 8);

        // 关键待验证：mask / hRepeat / repeatMode / dstBlkStride / vROffset / vRepeat
        uint64_t mask = 128;          // 连续模式，16 位 → mask∈[1,128]
        uint8_t hRepeat = 1;
        bool repeatMode = true;       // P2：8 权重
        uint16_t dstBlkStride = 1;
        uint16_t vROffset = 128;      // P4：垂直迭代偏移（元素）
        uint8_t vRepeat = 1;
        AscendC::BilinearInterpolation(dst, src0, off, w, mask, hRepeat, repeatMode,
                                       dstBlkStride, vROffset, vRepeat, tmp);
        AscendC::DataCopy(dst_[0], dst, 16);
    }
private:
    AscendC::GlobalTensor<T> src0_, w_, dst_;
    AscendC::GlobalTensor<uint32_t> off_;
    uint32_t blkCnt_;
    // UB 分配省略（探针：直接声明固定偏移，实际需 TQue/TBuf）
    AscendC::LocalTensor<T> src0UB_, wUB_, dstUB_;
    AscendC::LocalTensor<uint32_t> offUB_;
    AscendC::LocalTensor<uint8_t> tmpUB_;
};
```

### 8.3 上板成本与前提

- **前提**：`source /usr/local/Ascend/ascend-toolkit/cann-9.1.0-beta.3/set_env.sh`；NPU driver 可用（本机有 `hdcdrv` 偶发 hang 风险，见框架已知问题）。
- **成本**：写 host 侧（tiling + launch，或借 cann-bench 脚手架注册临时探针算子）+ 编译 + 上板，约 30–60 min，且结果仅服务「BilinearInterpolation 详解」章节的实证，**不影响本范式正文与结论**（§3 已明确「DataBlock 粒度 → 不适用元素粒度 8 角点」，§7 已闭环）。
- **建议**：作为独立验证任务排期，与 `api-gather.md` 落地解耦——落地不依赖探针结果；探针结果到位后回填「BilinearInterpolation 详解」的示例代码。
