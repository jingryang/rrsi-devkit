# SIMT UB 共享内存窗口误解 — 实施方案（L4）

> 具体改哪些文件、什么顺序、怎么验证。问题见 `01-problems.md`，决策见 `02-analysis.md`。

## 改动文件与顺序

### 1. 源头文件（核心修正）

**`.claude/skills/regbase-vf-test/references/vf_experiences/gather-scatter/experience-simt-async-infra.md`**
- 标题 `（asc_vf_call / 8KB 窗口 / 同步结构）` → `（asc_vf_call / 共享内存窗口 / 同步结构）`
- §"### 8KB UB 窗口（工具链硬约束，实验证据）" → "### SIMT 共享内存窗口（launch 配置；SingleOperatorLaunch 默认 8KB，可放大）"，内容重写：
  - 保留历史观察（默认窗口=8KB，数据>8KB → VEC_ERROR），标注这是 SingleOperatorLaunch 默认 `simt_share_memory_size=0` → RTS 默认 8KB 所致，**非固定硬件上限**。
  - 附设备实测边界表（见 02-analysis.md）。
  - 附官方模型：SIMT 共享内存 = UB（256KB），UB 分区 static/dynamic/预留8KB/DCache≥32KB，动态共享内存可配（`<<<grid,block,dynUBufSize>>>` / RTS `dynamic_share_mem_size`），上限 ≈ UB−8KB−32KB ≈ 216KB。
  - 对策改为：单批 VF 输入输出 buffer 占用 ≤ launch 配置的 SIMT 共享内存；生产路径用 TPipe/TQue 正常分配 + `GetPhyAddr()` 转 `__ubuf__*`，不要求 offset 0 单窗口。
  - 坑表行改：`| 大 case 数据错位/丢失/VEC_ERROR | 数据超 SIMT 共享内存窗口（默认 8KB，可配置） | 单批 ≤ 配置窗口；放大窗口经 dynUBufSize/simt_share_memory_size |`

### 2. 衍生文档同步

- `gather-scatter/INDEX.md`：常见陷阱 #1 改"SIMT 共享内存窗口默认 8KB（SingleOperatorLaunch 未配 dynUBufSize 时）；单批 ≤ 窗口；可经 launch 配置放大"，条目索引行去掉"绝对"表述。
- `gather-scatter/experience-simt-gather.md`：stride 表"搬入 8KB 窗口头部"保留（128B 仍在窗口内，无害）但措辞改"窗口内"；坑表"8KB 窗口越界 / 窗口绝对 8KB / n≤480~496"改"数据超配置窗口 → 压批到 ≤ 配置窗口（默认 8KB）"。
- `stateful-accumulator/experience-rmw-accumulate.md`：实证来源行"SIMT rmw + 8KB 窗口" → "SIMT rmw + 共享内存窗口（默认 8KB）"。
- `regbase-vf-test/SKILL.md` §层次 A："横切关注（SIMT 异步 8KB 窗口 …）" → "（SIMT 异步共享内存窗口 …）"。

### 3. 验证

1. `grep -rn "绝对 8KB|绝对\[0, 8192|SIMT VF 的 UB 读写窗口" .claude/` → 无残留（除指向 02-analysis 的实测记录外）。
2. grep 确认 4+1 个文件均已更新措辞。
3. 无 Python 改动；若 regbase-vf-test skill 有 UT/契约测试引用这些措辞则运行（预期无——纯 markdown 知识文档）。
4. 探针脚本保留于 `/tmp/opencode/simt_ub_probe/`（`ub_probe_custom.cpp` + `run_ub_probe.py` + `run_boundary.py`）作为可复现证据；如需入库可再议（默认不入仓，§1.7 仓外临时物）。
