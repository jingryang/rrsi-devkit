# L1 — 设计阶段质量门 loopback 无效化问题记录

> 批次：`20260813-164600-f65f5b`（3 算子：resize_bilinear/8c3ae6、grid_sampler_3d/955f4a、unique/d345f0）
> 数据源：`output/20260813-164600-f65f5b/<run>/events.jsonl`、`run.log`、`artifacts/design/**/`（decision_log / anchor_report / gate_scope.json）
> 本文件只记录客观事实与证据，不提方案、不排顺序（§1.8 L1 边界）。
> 关联既有分析：`../batch-20260813-timing-analysis/`（P7/P13、R5/R6）——本批是 R5/R6 落地后的**再复现**，发现 R6 遗留缺陷 + 新的 loopback 无效化形态。

---

## 总览：本批 3 算子设计阶段 loopback 触发情况

| 算子 | 设计 loopback 次数 | 定性 | 证据 |
|---|---|---|---|
| resize_bilinear（8c3ae6） | 0 | 健康基线（review 就地修 1 处、anchor 0 blocker） | `anchor-consistency/anchor_report.json` status=passed |
| unique（d345f0） | 2 | general-design discover+regenerate；anchor 复验回路断裂 | loopback 事件 ×2 |
| grid_sampler_3d（955f4a） | 1 | anchor 7 真缺陷，重跑分支失败 → halt 弃跑 | `run.log` 末行 fail_strategy=halt |

---

## P1 — anchor「完全只读 + loopback」的复验回路断裂（R6 遗留 bug）

**代码事实**：`design_tree.py:157-165` 的 `_anchor_branch_factory`：

```python
for t in templates:
    name = _template_name(t)          # ← 死变量，未传入
    branches.append(AtomicStage(AnchorPerTemplateStage(template=t)))
```

`AtomicStage.__init__` 只收 `stage`，`self.name = stage.name` 恒为 `"anchor-per-template"`（`node.py:35`）。而 `_anchor_rerun_selector`（`design_tree.py:168-181`）返回的是模板名 `{"T1"}`。`_invalidate_subtree` 用 targets 匹配分支名时 `"anchor-per-template" != "T1"` → 清不掉 → anchor-per-template 永远保持 `completed` → loopback 后**被 resume-skip，永不重跑**。

对比 `tiling_branch_factory`（`design_tree.py:117`）显式 `SequentialGroup(name=name, …)`，tiling 的 template-precise 重跑是正常的。

**日志证据**（d345f0，UTC）：

- 18:48 anchor-consistency 报 2 条 AC2 blocker → loopback 回 tiling；
- 19:32–20:09 tiling 重跑 split/buffer-kernel/precision-perf（约 81min），**确实修复**：重生成的 `tiling_buffer_kernel.json` 已含 `int64SortPasses=3`、`bf16→float 分数（否决 fp16）`、`否决两趟`；
- 20:09–20:16 anchor-consistency 第二轮：`events.jsonl` 中**没有** anchor-per-template 的 stage_enter（`design/anchor/T1/anchor_template_report.json` mtime 停在 02:44，早于 03:53 的修复）；
- 结果：anchor-consistency 读**过期**的 per-template 报告，把已修好的 2 条 AC2 **原样再报**（decision_log 明写「2 条 AC2 与上轮逐字段一致……未观察到消解证据」）→ 命中 stagnation → fail-open 前逃，`anchor_report.json` 仍 status=blocked。

**事实**：修没修对，系统自己不知道；「loopback 复验」这一半从机制上就是断的。

---

## P2 — general-design-review 的 discover+regenerate loopback（确定性可修问题被报 blocking）

**配置事实**：`ascendc-op-general-design-review/schema/gate_scope.json` 把 `GD-G*`（「narrative 有素材但 generator 产物不全/自相矛盾」）路由到 `fix_owner=generator`（loopback）。

**日志证据**（d345f0）：

1. review 第一轮发现 GD-G1（NaN 支持域矛盾）、GD-G2（numel=0 空输入域遗漏）→ 报 blocking 回 generator（loopback 事件 count=1）；
2. generator corrective pass 声明「无设计变更」——其 workdir `requirement.json` 是**截断版**（缺 `nan_semantics`/`boundary_handling`/`test_cases`）→ loopback 无效；
3. review 第二轮复核时这 2 问题仍残留，于是 review **自己就地修**（`patched_nodes: [narrative, loop_framework]`）。

**事实**：review 自己在 decision_log 里写明「修复内容完全由需求指定、无设计自由度」，却仍走了 blocking→generator 这一圈。纯浪费 generator 重跑 335759ms + review 重跑 964106ms ≈ 22min。

---

## P3 — anchor→tiling loopback 重跑代价高 + 脆弱（重跑失败弃跑）

**日志证据**：

- d345f0：loopback 重跑 split 2670099ms + buffer-kernel 1342691ms + precision-perf 868822ms ≈ **81min**，其中 split 重跑 44min 根本不需要改（issue 只指向 buffer-kernel 段）。
- 955f4a：anchor 报 7 条 blocker → loopback 回 tiling 全量重跑，**T2/split 重跑失败** → `run.log` 末行 `Workflow halted: stage 'T2/split' failed with fail_strategy=halt: fork-join 分支 'T2' 失败` → 算子弃跑（未到 integrate/codegen）。

**事实**：把「纠正一个可修的 tiling 缺陷」退化成「整算子弃跑」；且全量重跑的分支失败无 fail-open 兜底。

---

## P4 — validate 的 redo_tiling 全量重跑（可自修范围配得太窄）

**配置事实**：`ascendc-op-design-validate/schema/gate_scope.json` 的 `self_fixable_scope` 只有「GV10-a(TilingData 旧宏→POD struct 机械重写) + GV5(格式就地 Edit)」，其余 GV1/2/3/4/6/8-A/9-a/9-c + AC0/1/2 全部路由 `fix_owner=tiling`（loopback）。

**事实**：其中「字段缺失」「格式」「GV7-B 公式↔伪代码不一致（公式权威已自检→伪代码错）」等是确定性可修的，却走了全量 tiling 重跑。

---

## P5 — 「独立对质」的只读设计，在本批无实证价值

**配置事实**：`ascendc-op-design-anchor-consistency/schema/gate_scope.json` 的 `self_fixable_scope` 写死「（无——anchor 完全只读，绝不编辑设计来修复）」。

**日志证据**：

- anchor 的**发现**价值为真（抓出 bf16 有损 Cast、int64 两趟排序、SyncGrid API 不存在等 9 条真正确性缺陷）；
- 但「只读 + 回 tiling 重跑」这一半价值为负：P1 证明修后无复验（「独立性」没兑现），P3 证明重跑贵且脆弱。

**事实**：所谓「独立对质」= 第二双眼睛在修复后复核。本批因 P1 的 branch 命名 bug，**修复后根本没有第二双眼睛**。独立性既没在修复前发挥作用，也没在修复后发挥作用。

---

## 共性（供 L3 引用，非独立问题）

三处门（review/anchor/validate）的共性：框架已有「就地修」的一等概念（`gate_scope.json` 的 `self_fixable_scope` + `stop_in_stage_retry`），但三个门把「就地修」范围配得太窄、把「loopback（fix_owner）」范围配得太宽——凡「确定性可修 / 无设计自由度」的缺陷，都该走 self_fixable_scope，却配成了 fix_owner loopback。这是 P1–P4 的共同配置根因。
