# VF 并行派发按模板组分批 — 方案分析（L3）

> 对应 L1 `01-problems.md`。状态：已拍板冻结（用户决策，2026-09-01）。

## 问题本质

`_actions_regbase_vf` 的批量选取是 `batch = pending[start:start+max_concurrent_vf]`，
`pending` 来自 `pending_vf_ids()` = **全部**仍 pending 的 VF 步骤（plan 序）。因此：

- 一旦首批 VF（T1）done，下一批取"前 2 个 pending VF"会**跨模板**混入 4.C.6.VT.0；
- 剩余 T2 VF（VT.1/VT.2）排在任何普通步骤之后 → 等到 4.C.3~4.C.5 做完才轮得到。

这使 plan 中"T1 VF → 4.C.3 → 4.C.4/5 → T2 VF → 4.C.6"的归属关系被打散：T2 的 VF
要么提前混进 T1 批次，要么被普通步骤压后。

## 选项

| 选项 | 描述 | 取舍 |
|------|------|------|
| A（现状） | 批 = 前 max_concurrent_vf 个 pending VF（跨模板） | 并行度最高，但跨模板混批 + T2 VF 被普通步骤压后，与 plan 序归属错位 |
| **B（选）** | 批 = **与当前 frontier 同模板组**（`.VT.` 基名相同）的 pending VF，取前 max_concurrent_vf 个；保留全局首个 VF 串行 canary | T1 组内并行、T2 组内并行；组不混、且各组等各自普通步骤顺序推进；代价=同一时刻并行上限从"全 plan 任意 VF"降为"当前组内"（组间串行） |
| C | 去掉串行 canary，整组一次全并行 + 提高 max_concurrent_vf | 并行度最高，但丢失首个 VF 的脚手架/工具链 canary，LLM 并发占用上升 |

## 决策（用户拍板，2026-09-01）

- 选 **B**：按模板组并行 + **保留全局首个 VF 串行 canary**。
- 理由：既满足"4.C.3.VT.X 一组、4.C.6.VT.X 一组各自并行"的诉求，又保留首个 VF
  先建 `vf_verified` 脚手架/验证工具链的安全网；`max_concurrent_vf=2` 上限不动。

## 组定义（结构信号，不认算子名，§1.12）

- 组基名 = 子阶段 id 去掉 `.VT.{M}` 后缀：`4.C.3.VT.0 → 4.C.3`，`4.C.6.VT.2 → 4.C.6`。
- 新辅助函数 `codegen_s4.vf_group_base(sid)`（与 `pending_vf_ids`/`all_vf_ids` 同层）。

## 冻结后的行为示例

```
4.C.3.VT.0              （串行 canary）
[4.C.3.VT.1]             （组内仅剩 1 个 → 单派发）
4.C.3 → 4.C.4 + 4.C.5    （普通步骤按序推进）
[4.C.6.VT.0, 4.C.6.VT.1] （T2 组内并行 2）
4.C.6.VT.2               （T2 组内再 1）
4.C.6
```

T1 组两 VF 因 canary 实际上 VT.0 先单独跑、VT.1 随后（该组只有 2 个）；T2 组三 VF
分批 2+1。各组之间不混批。
