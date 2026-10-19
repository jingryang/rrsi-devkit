# AtomicAdd 不支持 dtype 时的跨核汇总 fallback

> 本文件描述当算子需要跨核写同一 GM 地址（规约轴跨核切分或 segment scatter-add），
> 但输出 dtype 不在硬件 `SetAtomicAdd` 的支持列表内时，必须采用的 fallback 方案。
>
> **适用阶段**：详设 buffer-kernel 步骤（agent 在此步骤查证 `SetAtomicAdd.md` 并发现 dtype 缺口）。
>
> **相关模式**：B02_reduce-nonD（segment 分组规约）、G01_gather-vector（scatter-add）。

---

## 触发条件

算子存在"多核写同一输出地址"的累加需求（如沿规约轴跨核切分、segment_ids scatter-add），
且输出 dtype 不在 `SetAtomicAdd` 产品 dtype 列表内。

典型场景：A2/A3/A5 全产品线 `SetAtomicAdd` 均不支持 **int64**。

当 AtomicAdd 不可用时，"多核直接写同一 GM 地址"会产生丢更新，必须改走下方两阶段方案。

> **关键纪律**：fallback 不是一句注释。详设须为两阶段各产出完整的伪代码、buffer 设计、
> workspace 预算。
---

## 方案结构（两阶段）

### 阶段一：per-core 写出

| 项目 | 说明 |
|------|------|
| 执行者 | 每个核各自独立 |
| 动作 | 每核把本核的规约/累加结果写到 GM workspace 中**本核独占的区域**，而非直接写到输出 yGm |
| 关键点 | 各核区域互不重叠，无写冲突；搬出后syncall()确保所有核的搬出都结束 |


### 阶段二：reduce 汇总（reduce kernel）

| 项目 | 说明 |
|------|------|
| 执行者 | 阶段一所有kernel 完成后，选择其中一个核执行规约操作 |
| 动作 | reduce kernel 读 workspace 中 blockDim 个核对同一段的部分和，累加后写出最终结果到输出 yGm |
| 关键点 | 只能有一个核执行最终的规约操作 |
