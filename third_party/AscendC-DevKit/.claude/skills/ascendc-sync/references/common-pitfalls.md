# 同步机制常见陷阱与调试

## 陷阱 1: eventID 手动指定导致死锁

**错误**:
```cpp
AscendC::SetFlag<AscendC::HardEvent::MTE2_V>(0);  // 手动指定 ID = 0
```

**正确**: 必须通过 `FetchEventID` 或 `AllocEventID` 获取:
```cpp
int32_t eid = static_cast<int32_t>(
    GetTPipePtr()->FetchEventID(AscendC::HardEvent::MTE2_V));
AscendC::SetFlag<AscendC::HardEvent::MTE2_V>(eid);
AscendC::WaitFlag<AscendC::HardEvent::MTE2_V>(eid);
```

## 陷阱 2: SetFlag/WaitFlag 不成对导致死锁

每个 `SetFlag` 必须有对应的 `WaitFlag`，反之亦然。遗漏任何一个都会导致后续指令永久阻塞。

## 陷阱 3: SyncAll workspace 未初始化为 0

`gmWorkspace` 的值**必须初始化为 0**，否则核之间的状态判断会出错。初始化方式：
- Host 侧初始化后传入
- Kernel 侧：每个核都必须初始化**全部** gmWorkspace 空间

## 陷阱 4: blockDim 超过实际核数导致卡死

使用 IBSet/IBWait、SyncAll、WaitPreBlock/NotifyNextBlock 时，逻辑 `blockDim` **不能超过**实际 AI 处理器核数。否则框架多轮调度时会插入异常同步，导致 Kernel 卡死。

## 陷阱 5: WaitPreBlock/NotifyNextBlock 调用次数不一致

每个核调用 WaitPreBlock 和 NotifyNextBlock 的次数**必须相同**。如果某个核少调用一次，其他核会永久等待。

## 陷阱 6: CrossCore flagId 计数器溢出

同一 `flagId` 的计数器**最多设置 15 次**。超过后行为未定义。如需更多同步点，使用不同的 flagId。

## 陷阱 7: 分离模式使用软 SyncAll

分离模式下不建议使用软同步 `SyncAll`（仅适用于纯 Vector，性能低）。应使用硬同步接口，并设置 Kernel 类型为 `KERNEL_TYPE_MIX_AIV_1_0` 或 `KERNEL_TYPE_MIX_AIC_1_0`。

## 陷阱 8: SuperKernel TilingKey 分支不一致

如果子 Kernel 某个 TilingKey 分支调用了 `SetNextTaskStart`/`WaitPreTaskEnd`，则**所有可能运行的 TilingKey 分支都必须调用**。否则同步指令数量不匹配会导致卡死。

## 陷阱 9: CrossCore 接口与 Matmul 高阶 API 冲突

Matmul 高阶 API 内部使用了 CrossCoreSetFlag/CrossCoreWaitFlag。如果开发者同时使用，会有 flagID 冲突风险，导致不可预期的行为。

## 陷阱 10: scalar SetValue 写 UB,后续 MTE3 出 GM 缺 S→MTE3 同步(沉默错误,典型于 reduce-style 算子)

**症状**: 算子小 case 全对(T=1/T=2),大 case 部分 t 输出错乱,且 **跨多次调用结果不同**(nondeterministic)。错点位置随机,但集中在某些 t(往往是某种循环边界)。

**根因**: scalar `SetValue` 走 S 流水写 UB,后续 `DataCopyPad(GM, ub_buf)` 走 MTE3 读同一块 UB。如果只发了 `V→MTE3` flag,MTE3 不会等 S。低 T 时 S 流水有时间自己跑完;高 T 时硬件 scheduling 让 S 滞后到 MTE3 已经 copy 过 stale 值 → 输出错。

**错误**:
```cpp
// In ProcessOneT loop:
for (int k = 0; k < dTileNum; ++k) {
    // ProcessOneDTile 内部反复用 SetValue 写 acc[i]
    ProcessOneDTile(t, k);
}
SetFlag<HardEvent::V_MTE3>(eVMTE3);   // 只发了 V→MTE3
WaitFlag<HardEvent::V_MTE3>(eVMTE3);
DataCopyPad(accGm[t], acc, p);        // ❌ MTE3 读 acc,但 acc 最后是 S 写的
```

**正确**:
```cpp
SetFlag<HardEvent::V_MTE3>(eVMTE3);
WaitFlag<HardEvent::V_MTE3>(eVMTE3);
SetFlag<HardEvent::S_MTE3>(eSMTE3);   // 同时让 MTE3 等 S 流水
WaitFlag<HardEvent::S_MTE3>(eSMTE3);
DataCopyPad(accGm[t], acc, p);
```

**对称地**:加载 UB 后若用 scalar `GetValue` 读,要发 `MTE2_S`(光发 `MTE2_V` 不够)。

**判别口诀**:
> 看一段 UB 最后是哪条流水写的(V?MTE2?S?),后续哪条流水读它(V?MTE3?S?),就发 `<src>_<dst>` 那条 flag。把所有可能的 src/dst 组合都列一遍,缺哪条补哪条。

## 陷阱 11: FetchEventID 池只有 0-7,在长 inner loop 里 fetch 会回绕(沉默错误)

**症状**: 同上(nondeterministic),但 SetFlag/WaitFlag **看起来都成对**。

**根因**: A2 上 `FetchEventID` 返回 0-7 的循环 ID。如果在 inner loop 里反复 `auto e = pipe.FetchEventID(...); SetFlag(e); WaitFlag(e);`,百次后 ID 会回到 0,但**前一对 SetFlag(0)/WaitFlag(0) 可能还没真正同步完成**——硬件 flag 寄存器的状态被新一对覆盖,导致 set/wait 配对失效。

**错误**:
```cpp
for (int i = 0; i < n; ++i) {
    for (int j = 0; j < n; ++j) {            // 内层循环 100+ 次
        ReduceSum(...);
        auto e = pipe.FetchEventID(HardEvent::V_S);
        SetFlag<HardEvent::V_S>(e);
        WaitFlag<HardEvent::V_S>(e);
        float v = tmp.GetValue(0);
        // ... SetValue / FetchEventID / SetFlag / WaitFlag 又一对 ...
    }
}
// 跑 1000+ 个 t * 100 个 inner pair = 10万对 fetch ⇒ 必然回绕
```

**正确**:
- **首选**:把 inner loop 内部的同步抽到外层(每个 dtile 一对而非每个 (i,j) 一对)
- **次选**:用 `PipeBarrier<PIPE_ALL>()` 替代细粒度 SetFlag/WaitFlag
- **下策**:用 `AllocEventID` 在 Init 阶段固定分配,内部循环复用同一 ID(但要确认每对 set/wait 之间没有别的 fetch 抢 ID)

## 陷阱 12: V-pipe 向量指令最小长度 ≥ 32B(8x fp32 / 16x fp16)

**症状**: 编译通过,运行时报 `vector core exception` (errno 507035)。

**错误**: 想用 V-pipe `Add(acc[i], acc[i], partial, 1)` 替代 scalar SetValue,以避开陷阱 10/11。但 V-pipe 不支持 len=1。

**对策**:
- 累加器仍用 scalar SetValue,但严格按陷阱 10 加 S→MTE3 / S→V 同步
- 或者把 partial 收集成长度 ≥ 8 的 vector,再一次性 Add 进 acc


## 陷阱 13: 把 DataSyncBarrier（内存屏障）当流水间同步工具用

**症状**: 编译通过,运行期出现难复现的竞态——读到旧值/垃圾、输出透传等,且换 shape/换编译优化级别后表现不定。

**根因**: `DataSyncBarrier` 是内存屏障,语义是"等待之前的内存访问指令执行完",**没有 `源流水_目标流水` 的方向概念**,不能替代流水间同步。在跨流水数据依赖处(如 MTE2 搬入后 V 流水读、V 写后 MTE3 搬出)用它,不会建立 MTE2→V / V→MTE3 的定向依赖 → 竞态。

**判别口诀**:
> 看一段 UB 最后是哪条流水写的(V?MTE2?S?),后续哪条流水读它(V?MTE3?S?),就发 `<src>_<dst>` 那条 flag;单流水内用 `PipeBarrier`。`DataSyncBarrier` 只用于"等所有内存访问完成"的内存屏障场景,不做流水间同步。

## 调试方法

1. **死锁排查**: 如果 Kernel 卡死，优先检查：
   - SetFlag/WaitFlag 是否成对
   - eventID 是否通过 API 获取而非手动指定
   - blockDim 是否超过实际核数
   - WaitPreBlock/NotifyNextBlock 调用次数是否每个核一致
   - CrossCore flagId 计数是否超过 15

2. **数据竞争排查**: 如果多核结果不正确：
   - 确认所有核间 GM 访问都有同步保护
   - 确认 gmWorkspace 已初始化为 0
   - 确认使用了正确的同步粒度（全核 vs 点对点）

3. **使用 DumpTensor**: 在同步点前后插入 DumpTensor，对比各核数据是否符合预期（参考 `ascendc-dumptensor` skill）
