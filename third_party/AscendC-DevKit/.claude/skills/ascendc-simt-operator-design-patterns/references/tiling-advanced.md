# 分核策略进阶

> 基础切分（`ceil(总量/每核最少元素)` + `SetBlockDim`）参考 `ascendc-tiling-strategy` skill。本节补充实际算子中反复出现的**进阶分核决策**。

## 1. blockDim 必须封顶物理核数（防 vector core exception）

SIMT kernel 核内用 grid-stride 循环覆盖全部元素，blockDim 不需要随元素数增长。旧实现 `SetBlockDim(CeilDiv(total, coreNum))` 会让 blockDim 随元素数线性膨胀，大 shape 下远超可用核数，**触发 507035 vector core exception**。

```cpp
// ✅ 推荐：封顶物理核数，核内 grid-stride 兜底
int64_t usedCoreNum = Ops::Base::CeilDiv(totalNum, coreNum);
if (usedCoreNum > coreNum) { usedCoreNum = coreNum; }
if (usedCoreNum == 0) { usedCoreNum = 1; }
context->SetBlockDim(usedCoreNum);
```

- 出处：`math/atanh/op_host/arch35/atanh_tiling_arch35.cpp`（源码注释明确记录 507035 事故）

## 2. 每核最小工作量钳制（防小 shape 空转核）

核数估算普遍采用"每核最少元素数"钳制：`perCore = max(CeilDiv(total, coreNum), PER_CORE_MIN)`，再反推 needCoreNum。常见下限：**1024 元素**（foreach/optim/pooling）、**128B 字节**（cdist）、warp(32) 对齐。

```cpp
// ✅ 推荐：每核下限 + 32 对齐 + 反推核数
int64_t perCore = (totalElements + maxCoreNum - 1) / maxCoreNum;
perCore = std::max(perCore, PER_CORE_MIN /*1024*/);
perCore = ((perCore + ALIGNMENT /*32*/ - 1) / ALIGNMENT) * ALIGNMENT;
params.needCoreNum = (totalElements + perCore - 1) / perCore;
```

- 出处：`pooling/dilation2_d/op_host/arch35/dilation2_d_tiling.cpp`、`foreach/foreach_add_list`

## 3. 双任务分核取 max（两阶段并行度需求不同）

很多算子有两个阶段的并行度需求（如"输出清零"+"数据累加"、"argmax 前向"+"梯度回传"、"默认值填充"+"稀疏写"），tiling 分别计算各阶段核数后取最大值作为 blockDim：

```cpp
formerLength_ = CeilDiv(totalLength_, coreNum_);          // 阶段1: 输入侧均分
needXCoreNum_ = CeilDiv(totalLength_, formerLength_);
clearYFactor_ = CeilDiv(bins_, coreNum_);                 // 阶段2: 清零侧独立分核
clearYCoreNum_ = CeilDiv(bins_, clearYFactor_);
needCoreNum_ = std::max(needXCoreNum_, clearYCoreNum_);   // 取 max
```

- 出处：`math/histogram_v2/op_host/histogram_v2_simt_tiling.cpp`、`conv/deformable_offsets_grad`、`index/sparse_to_dense`

## 4. 线程数自适应收缩（防"核多用不满"）

SIMT 每核线程数不是固定的。当 `CeilDiv(workSize, threadNum) < aivNum/2`（核数利用不足一半）时逐次减半线程数，保证每个线程分到足够元素：

```cpp
uint32_t threadNum = MAX_THREAD_NUM /*2048*/;
while (threadNum >= 2 * MIN_THREAD && CeilDiv(ySize, threadNum) < aivNum / 2) {
    threadNum /= 2;                       // 每线程分不到足够元素就折半
}
perCoreElements = AlignUp(CeilDiv(ySize, needCoreNum), threadNum);   // 对齐到线程数整数倍
```

- 出处：`index/gather_v2/op_host/arch35/gather_v2_tiling.cpp`（SimtTwoDimTiling）、`math/select`

## 5. 按"最大工作量子循环"估算核数

单线程内包含多个工作量悬殊的阶段（如帧内清零/中心力/邻居力），取三者最大值作为工作量基准，防止按单一阶段估核导致负载高估或低估：

```cpp
int64_t maxWorkload = max({initTotal, centerTotal, neighborTotal});
int64_t perCoreElements = std::max(CeilDiv(maxWorkload, aivCoreNum), PER_CORE_MIN);
int32_t needCoreNum = CeilDiv(maxWorkload, perCoreElements);
```

- 出处：`math/prod_force_se_a/op_host/arch35/prod_force_se_a_tiling.cpp`

## 6. 按最大单 tensor 元素数定核

Foreach 等 tensor-list 算子中，若所有核共同遍历全部 tensor，核数由**最大单 tensor 元素数**（而非总量）决定，保证最大 tensor 内部有足够并行度：

```cpp
for (i < tensorNum) { maxTensorElements = std::max(maxTensorElements, numel[i]); }
int64_t needCoreNum = std::min(coreNum, CeilDiv(maxTensorElements, 1024));
```

- 出处：`foreach/foreach_addcdiv_scalar_list/op_host/arch35/foreach_addcdiv_scalar_list_tiling.cpp`

## 选择指南

| 场景 | 策略 |
|------|------|
| 通用逐元素 | `min(CeilDiv(total, coreNum), coreNum)` 封顶 |
| 小 shape | 每核下限 1024 元素 + 32 对齐 + 反推 |
| 两阶段算子（清零+累加） | 两套分核取 max |
| 核数利用不足 | 线程数自适应减半 |
| 单线程多阶段工作量悬殊 | 按最大工作量基准估核 |
| tensor-list 全局遍历 | 按最大单 tensor 定核 |
