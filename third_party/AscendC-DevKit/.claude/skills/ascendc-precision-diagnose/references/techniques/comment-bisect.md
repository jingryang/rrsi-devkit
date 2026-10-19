# 技巧：注释降级定位 runtime crash（就地诊断用）

> 这是 diagnose 就地定位时的一个**可用技巧**，不是独立 phase——**可选参考**，按需取用，
> 不产生 phase 协议（无实验预算 / located_roots / RESULT 行）。**是否使用由你基于对问题的
> 理解判断**（runtime crash 且 printf 无输出 → 用）。

## 何时用

runtime crash（SIGSEGV / 507035 / vector core exception）时——kernel 死在 flush 前、无 printf 输出可用。判定信号纯 **crash/no-crash**：对 kernel 做针对性注释/参数降级实验，观察 crash 是否消失，定位触发 crash 的代码区域/行。

## 怎么做（分层消融）

1. **Layer 0：DataCopy/TQue 定向消融**（先验快筛，默认起始层）：
   - 枚举所有 DataCopy/DataCopyPad 调用 + TQue 使用点，逐个**参数降级消融**（blockLen/element → 安全常量）→ build → 单用例 → crash 消失即定位到该调用点。
   - **消融纪律**：DataCopy 用参数降级（**禁止裸注释**——裸注释让下游读未初始化 buffer → 引入无关假 crash 带偏二分）；TQue 用最小安全配对（保留 Alloc/Free 配对，不破坏 pipe 不变式）。
2. **Layer 1：区域二分**（fallback）：DataCopy/TQue 全不命中才进入——注释 CopyIn/Compute/CopyOut 整段 → 段内二分收缩到区块。
3. **Layer 2：行级确认**：区块内逐行注释锁定触发行。
4. **多根因（增量）**：定位一处 → 就地修 → commit → 单用例验证；同 case 再入跳过已定位区域，从剩余继续。

## 消融纪律

- **参数降级优先于裸注释**：DataCopy 用 blockLen/element 改安全常量，不删调用（裸注释引入未初始化读 → 假 crash）。
- **只跑当前失败用例**（`test_command --case <id>`），不跑全量。
- **commit 前删所有注释实验痕迹**——commit 只含逻辑修复。

## crash-only 失败升级（布局风险怀疑）

当出现"编译通过 + 多次 crash + errcode/mte pattern 在实验间变化"时，**禁止直接放弃**——这是 TBuf-alias / 编译器布局风险信号（非纯容量问题）。先怀疑跨 buffer 别名（TBuf 复用重叠），检查 buffer 分配/复用是否安全；无法用 crash 信号定位时，把"slab-aliasing / layout hazard suspected"作为已知局限记录，转其他手段（受控实验 / ground-truth 查证 / 上报）。

## 与 printf 二分的分工

- **数值发散**（有输出、有中间值可比）→ printf 二分。
- **runtime crash**（无输出、纯 crash/no-crash）→ 注释降级。
- 二者都是就地定位技巧，共用纪律：只跑当前用例、commit 前清探针/注释、连续 3 次无好转换手段。
