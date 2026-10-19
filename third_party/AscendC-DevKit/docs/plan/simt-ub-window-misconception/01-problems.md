# SIMT UB 共享内存窗口误解（8KB 绝对上限）— 问题记录（L1）

> 观测事实与证据，不提方案、不排顺序、不写决策。方案见 `02-analysis.md`，实施见 `03-impl.md`。

## P1 vf_experiences 把 SingleOperatorLaunch 默认 SIMT 共享内存窗口误记为"绝对 8KB 硬约束"

- **事实**：`regbase-vf-test/references/vf_experiences/gather-scatter/experience-simt-async-infra.md` 及受其传播的 4+ 份文档声称"SIMT VF 的 UB 读写窗口 = 绝对 [0, 8192B)，与分配方式无关（TPipe/TBuf、LocalMemAllocator、手工 LocalTensor、静态 `__ubuf__` 池均实测受限）"，并给出手工 `LocalTensor<uint8_t>(VECCALC, 0, 8192)` 的规避写法。
- **证据（官方文档反证）**：
  - CANN AI-Core-SIMT编程《内存层级》/《SIMD与SIMT混合编程》：SIMT 共享内存 = Unified Buffer（256KB），UB 从低到高分 静态内存 → 动态内存 → 预留 8KB → Data Cache(≥32KB)；SIMT 场景算子只须预留 8KB + ≥32KB DCache，即可用共享内存 ≈ 216KB。
  - 文档中的"8KB"是**预留空间（禁止使用的固定保留区）**，不是"可用窗口只有 8KB"。
- **证据（生产路径反证）**：真实 gather 算子（run `20260823-071337-c1d232`）生产 kernel（`gather.h`）用 TPipe/TQue/InitBuffer 正常分配 index/y 双缓冲，SIMT VF 经 `LocalTensor.GetPhyAddr()` 在任意 UB 地址读写并通过 run-cases——并非把 buffer 排进 offset-0 的 8KB 窗口。
- **证据（轨迹内 self-check 已自疑）**：该 run 的 `vf_lesson.md` 写道"若生产 TQue 分配的 buffer 起点不在 UB offset 0，需确认 8KB 窗口约束的正式配置"——作者自己意识到生产路径非 offset 0，但未查证即按经验照抄。

## P2 错误经验已传播至多份文档与决策

- **事实**：以下文档/决策被 P1 的"绝对 8KB"污染，存在"buffer 必须排 offset 0 单 8KB 窗口 / 单批 n≤480~496 压批"等推导：
  1. `experience-simt-async-infra.md`（源头，标题 + §8KB 窗口 + 坑表 + 实证来源均含错）
  2. `gather-scatter/INDEX.md` 常见陷阱 #1 + 条目索引
  3. `experience-simt-gather.md`（stride 表"搬入 8KB 窗口头部" + 坑表"8KB 窗口越界 → n≤480~496"）
  4. `stateful-accumulator/experience-rmw-accumulate.md` 实证来源（"SIMT rmw + 8KB 窗口"）
  5. `regbase-vf-test/SKILL.md` 层次 A 检索说明（"横切关注（SIMT 异步 8KB 窗口 …）"）
  6. gather 轨迹 vf-test kernel（`SIMT_UB_WINDOW=8192` + 手工 pool）——run 产物，非 skill 本体
- **证据**：`grep "绝对 8KB|8KB 窗口|8192"` 命中以上各文件（见 P1/P2 引文）。`docs/plan/vf-experience-categorization/01-problems.md` P1 早已记录"adaptive_avg_pool_3d 直接'复用 gather 8KB 窗口'"的母本链传播。

## P3 skill 未写清 SIMT 共享内存的申请与使用方式

- **事实**：vf_experiences 只给了"8KB 手工 pool"一种规避，未按官方模型说明 SIMT 共享内存（UB）应当如何申请（TPipe/TQue 常规分配、GetPhyAddr 转 `__ubuf__*`）与 launch 期动态共享内存大小如何配置（`<<<grid,block,dynUBufSize>>>` / RTS `dynamic_share_mem_size`）。
- **证据**：官方《内存层级》明示共享内存申请 = 静态 `__ubuf__` 数组 / 动态 `extern __ubuf__` + `dynUBufSize`；vf_experiences 无此内容。
