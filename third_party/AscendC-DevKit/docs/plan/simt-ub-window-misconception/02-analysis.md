# SIMT UB 共享内存窗口误解 — 方案分析（L3）

> 候选方案与取舍，调研中演进，拍板后冻结。问题证据见 `01-problems.md`，实施见 `03-impl.md`。

## 设备实测证据（本问题的决定性反证，2026-09-02，Ascend950DT/CANN 9.1.0）

用真实 gather 同款 SingleOperatorLaunch 工具链写了 SIMT 探针 kernel（`LocalTensor<uint8_t>(VECCALC, 0, 65536)` 大 pool，SIMT 256 threads 全窗口读写），控制 launch 期 SIMT 共享内存大小做边界扫描：

| 数据量 | simt_share_memory_size | 结果 |
|--------|------------------------|------|
| 9216B (>8KB) | 0（SingleOperatorLaunch 默认） | **VEC_ERROR**（仅 ~8KB 内正确） |
| 8192B | 0（默认） | PASS（默认窗口恰 = 8KB） |
| 64KB | 65536 | **PASS（64KB 全窗口通过）** |
| 64KB | 8192/12288/16384/32768 | VEC_ERROR（数据越出配置窗口） |
| 12KB | 12288 | PASS |

**结论**：SIMT VF 能访问的 UB 上限不是固定 8KB，而是 launch 配置的 SIMT 共享内存窗口（RTS `RtTaskCfgInfo.dynamic_share_mem_size`，对应官方 `<<<grid,block,dynUBufSize>>>` 的 dynamic shared memory；SingleOperatorLaunch 默认传 0 → RTS 落 8KB 默认）。

## 方案对比

| 方案 | 做法 | 结论 |
|------|------|------|
| A. 静默删除全部 8KB 表述 | 不留痕迹 | 否决——历史观察有真实成因（默认窗口=8KB），直接删会让后人重踩 |
| B. 全仓机械替换"绝对 8KB"为"默认 8KB" | 逐文件替换措辞 | 否决——各文件角色不同，需按"源头/衍生"区分修正深度 |
| **C. 源头纠正 + 衍生文档同步 + 补正确共享内存用法** | infra 源头文件改为「共享内存窗口 = launch 配置（默认 8KB，可放大到 ~216KB）」，坑表与"压批"建议改为"单批须 ≤ 配置窗口"；衍生 INDEX/gather/rmw/SKILL 同步；补 TPipe/TQue + dynUBufSize 的正确申请方式 | **采纳** |

## 选定方案 C 的构成

1. **源头文件**（`experience-simt-async-infra.md`）：标题改掉"8KB 窗口"绝对化；§8KB 窗口改述为"SIMT 共享内存窗口 = launch 配置，默认 8KB（SingleOperatorLaunch 不传 dynUBufSize 时）"，附设备实测表 + 官方 UB 分区模型（static/dynamic/预留8KB/DCache≥32KB）；坑表对应行改"数据超配置窗口"。生产集成预警改为"单批 UB 占用须 ≤ launch 配置的 SIMT 共享内存；生产经 kernel json localMemorySize/RTS 配置，TQue 正常分配"。
2. **衍生文档**（INDEX.md / experience-simt-gather.md / experience-rmw-accumulate.md / regbase-vf-test SKILL.md）：去掉"绝对/硬约束 8KB"措辞，改为"≤ SIMT 共享内存窗口（默认 8KB，可配置）"。
3. **补充正确用法**：索引/共享内存小节补 "SIMT 共享内存 = UB，经 TPipe/TQue 分配 + `GetPhyAddr()` 转 `__ubuf__*`；launch 期用 dynUBufSize/`simt_share_memory_size` 放大窗口（上限受 UB − 预留8KB − DCache≥32KB ≈ 216KB 约束）"。
4. **文档记录**：本 L1/L3/L4 + 更新 `00-status-summary.md`。
