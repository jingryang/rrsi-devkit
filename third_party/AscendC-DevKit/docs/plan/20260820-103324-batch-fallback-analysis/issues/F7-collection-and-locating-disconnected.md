# F7: 契约检查与产物收集是两套逻辑，彼此不共享证据

## 现象

框架的**产物收集**（`_scan_working_dir`）和**错误定位**（`_harvest_relocation_evidence`）各扫各的，信息不共享：

- 收集方只扫注入的 `working_dir`，看不到孤儿产物（F1）。
- 定位方能从 transcript 找到孤儿 `actual_path`（F2），但只用于生成反馈文本，不喂给收集方。

**已经定位到的东西无法被消费**——这是 F1/F2 的结构性根源。

## 凭什么这么说（证据）

- `_scan_working_dir`（`_shared.py:274`）：入参只有 `working_dir`，无 transcript、无 evidence 参数。
- `_harvest_relocation_evidence`（`design_substages.py:140`）：独立函数，返回值只流向 `_missing_artifact_error`（构造反馈）和 `_sweep_located_strays`（删孤儿）。
- 两者在代码里没有任何共享的数据结构或调用链。

## 影响

每次孤儿产物都要经历"检测→反馈→重试→再检测"的完整循环，而定位证据明明可以让它"检测→直接消费"。信息孤岛放大了重试成本。

## 根因定位

职责划分（收集 vs 校验 vs 定位）正确，但**边界间的数据流断了**。定位证据应反哺收集，形成闭环，而不是各自为政。

## 收口记录（2026-08-21）

**主体已被 F3（commit 19f377f3）结构性解决**——本 L1 的三条证据引用均写于 F3
之前，现状对照：

| L1 引用（20260820 时点） | F3 后现状 |
|---|---|
| `_harvest_relocation_evidence` 独立在 design_substages | 已迁 `_shared.py` 单点权威 |
| `pending_relocation` 状态机、证据只进反馈文本 | 状态机已删；证据经 `recover_orphan_artifact` 直接驱动消费（搬回→同迭代重定位） |
| "检测→反馈→重试→再检测" 循环 | 已变 "检测→搬回→消费"，零额外迭代 |

backend 侧 `_scan_working_dir` 仍只扫 working_dir 属刻意设计：收集报工作区真
相，孤儿由 stage 层搬回后消费（经文件系统闭环）。

**残留（本 issue 唯一待办）已闭合**：code-tree 生产者类内不一致——codegen 有孤
儿路径反馈、perf 没有（smoke 已死代码无暴露）。修复：孤儿判定+反馈文本提为
单点 `artifact_recovery.orphan_path_feedback`（§1.15），codegen 删内联块改消
费 helper、perf 接入（transition 注入 + tuning prompt 消费 + 成功清反馈）。
方案与实施见 `../09-impl-code-tree-orphan-feedback.md`。

**演进路径（触发条件）**：若出现第 3、4 个代码型 stage，升级为显式
`orphan_policy` 声明 + 加载期校验（§1.3），消除"记得调 helper"的纪律残留。

**移交提示（所有权）**：A5 侧 codegen（regbase 路径）大概率存在同样缺口，归
同事所有，本次不动；建议移交时附本 issue 与 09-impl。
