# rmw 累加测试编排 + 跨调用持久验证

## 适用判据

被测 VF 是 read-modify-write（`out ← out + term`，load 初值 + store 终值同一 UB buffer），且输出状态**跨调用/跨批持久**。测试 kernel 必须正确喂入初值并模拟链式调用，否则 rmw 语义无法被验证。

## 关键实现要点

1. **rmw 测试 kernel 同步设计**：初值来自 GM（MTE2 搬入）、输出要 MTE3 搬出——跨引擎同步不能靠同一 queue 双向承载：
   - 初值走 VECIN queue 搬入 + EnQue/DeQue（MTE2→V 同步 ✓）
   - V 引擎内 `CopyFp32RegImpl`（LoadAlign+StoreAlign）把初值 seed 到 VECOUT queue 的 outLocal——**同引擎程序序，无同步需求**
   - 被测 VF 在 outLocal 上 rmw（V 引擎）
   - outQueue EnQue/DeQue（V→MTE3 同步 ✓）+ DataCopyOut
   
   （工具链 CANN 9.1.0 aarch64 头文件无 `GetTPipePtr`/`FetchEventID`，显式 SetFlag/WaitFlag 不可用；上述 queue 方案是等效标准做法。SIMT rmw 场景反之——必须显式 HardEvent flag，见 `gather-scatter/experience-simt-async-infra.md`。）
2. **非 rmw 输出型 VF 更简单**：输入 VECIN → 被测 VF → VECOUT，**不需要** Copy seed 步骤。
3. **golden 与 kernel 运算顺序对齐**（位级一致）：`golden = out_init + scale * s`（先加后乘，与 kernel 指令序一致）；SIMT 逐 ow 用 `np.float32(0.0)` 顺序 `+=` 段内元素再一次性加到 acc——与 kernel 标量累加顺序完全一致。
4. **跨调用持久验证**：tiling 加 batchCnt/segNum 字段，kernel 入口 `__aicore__` 层循环 batchCnt 次调 VF（同一 UB out/acc）——模拟集成侧批循环契约；batchCnt=2/segNum=3 case 验证 rmw 持久性位级正确。
5. **rmw 初值可观察性**：y GM 预填随机非零初值（host `rng.uniform(-1,1)`）→ kernel 搬入 → VF 读改写 → 搬回；未写区（空段/区间外）保持初值本身就是验证点（区分"未写"与"写 0"）。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| 输出=纯哨兵/prefill，累加项全灭 | `UpdateMask` 直接消费函数参数（传入传出自动递减）→ 同函数后续 `UpdateMask` 拿污染值（Gather 场景尤其） | **所有 UpdateMask 调用先拷贝到局部变量**（`uint32_t cnt = winElems;`）；callee 内单次消费也拷贝；probe 必须复刻生产 mask 形态 |
| `no member named 'RoundMode' in namespace 'AscendC::Reg'` | 枚举在全局 AscendC | `AscendC::RoundMode::UNKNOWN` |
| 未写区被写 / 初值被覆盖 | rmw 语义破坏 | 未写区保持初值断言 + golden 保留初值 |
| `[OVERFLOW]` 警告刷屏 | 设备不支持 float overflow mode 检查 | 环境噪声，不影响精度，无需处理 |

## 可复用模式（最小骨架）

```cpp
// 1) 初值/输入全走 VECIN (MTE2->V by EnQue/DeQue)
outInitLocal = outInitQueue.AllocTensor<float>();
DataCopyInTensor1D<float>(outInitLocal, outGm, tileLen);
outInitQueue.EnQue(outInitLocal);  outInitLocal = outInitQueue.DeQue<float>();
// 2) V 引擎内 seed 到输出 tensor（同引擎程序序）
outLocal = outQueue.AllocTensor<float>();
CopyFp32RegImpl((__ubuf__ float*)outLocal.GetPhyAddr(),
                (__ubuf__ float*)outInitLocal.GetPhyAddr(), tileLen);
// 3) 被测 VF rmw
AccumulateImpl(outLocal, termLocal, biasLocal, scale, useBias, tileLen);
// 4) V->MTE3 by VECOUT EnQue/DeQue
outQueue.EnQue<float>(outLocal);  outLocal = outQueue.DeQue<float>();
DataCopyOutTensor1D<float>(outGm, outLocal, tileLen);
```

## 横切标签

`reduce`、`simt-async`（SIMT rmw 见 infra 条目）、`multi-dtype`。

## 实证来源

- `moe_finalize_routing` `accumulate_term`（48/48 max_diff=0.0；rmw queue 骨架 + 位级 golden）
- `adaptive_avg_pool_3d` `accumulate_window_sum`（36/36 max_diff=0.0；SIMT rmw + 共享内存窗口（默认 8KB，可放大）+ 同步结构）
- `adaptive_avg_pool_3d` `merge_partial_sum`（跨批持久 batchCnt=2 验证）
