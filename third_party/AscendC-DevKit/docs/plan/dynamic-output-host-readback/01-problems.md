# unique 数据相关输出长度——设计机制缺口 + 红线死路指令 — L1 问题记录（2026-09-07）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 方案分析见同目录 `02-analysis.md`（L3）。
> 来源：两次批次对照——成功 `20260827-132819-41aea1/95e52f`（unique 出分）vs
> 失败 `20260906-102728-cdb27e/f9ad14`（unique codegen halt）轨迹 + 框架源码。
> **scope 界定**：本记录只针对「输出长度数据相关（变长输出）」这一算子类的设计机制
> 缺口与红线反馈死路；adaptive 的诊断不收敛问题（模型侧）已独立记于
> `docs/plan/diagnose-model-convergence-gap/01-problems.md`，不在本文。
> **状态（2026-09-08）**：P1 机制缺口 + P2 红线死路指令均已落地修复——见
> `02-analysis.md` §4/§5.1（H01 变长输出闭环 + 维12 读回 API 确定写法 + 维10 判界调和 +
> 红线反馈文案分两类处置 + UT 守护）。

---

## P1：设计产物未给出「数据相关输出长度」的合法实现机制，失败版设计把 codegen 导向死路

### 现象：两次批次同一算子，设计差异决定成败

- **成功版设计显式给了机制**（`staging/general_design.json` + `tiling_strategy.json`）：
  - tiling_data 字段 `wsNumUniqueOffset`：语义 = "workspace：num_unique 结果标量偏移
    （host 回读以设置 y 真实长度）"。
  - 概设风险 R1："kernel 写 GM 标量 + host 回读设置 y 真实长度（y 存储按 N 上限规划）"。
  - 设计文档明确 `InferShape 输出 y 形状设 N 上界`，数据依赖裁剪放 plugin 层 narrow。
- **失败版设计没给机制，且导向反模式**（`state_snapshot.json` codegen decision_log）：
  - `design_spec.json` 只写 `y shape=["M"]`，全文零处"回读/读回/host 收窄"字样。
  - design 概设决策 = "两段式 prescan→launch"（先扫值域判 bitmap/radix 路径，再二次 launch），
    但 codegen 转写时自己标注这条违反 aclnn 模型："aclnn tiling 模型不支持跨 launch 的
    数据相关 tiling（tiling 在 op 加入 executor 时计算，无法 prescan 后重算）"→ 被迫改
    单 kernel + 运行时分支 + 骨架级实现 → M（唯一数）仍需 host 回读 → 死路。

### 根因分层

1. **设计链的知识库本身没这个机制的完整表达**：`H01_select-sort.md`（design_patterns 变长输出
   行）只覆盖到"workspace 暂存计数 + 前缀和算写出位置（ES3）"，**未覆盖"host 回读 count →
   plugin narrow 收窄输出 shape"这一必需的下游收尾**，也未写"aclnn 不支持跨 launch 数据相关
   tiling"这一约束 → 设计 agent 无从知道「输出张量真实长度必须 host 侧定、且只能经回读
   count 这一个合法渠道」。
2. 上游机制缺口传导：设计没给机制 → codegen 临场发明，自由度大 → 大概率踩红线或死路。

## P2：维10③ 红线门对数据相关输出算子的反馈是死路指令，比不给更糟

### 现象

- 失败版 codegen 触红线被拦（`state_snapshot.json last_error`）：
  `plugin_host_offload` / line 113 / pattern `kCPU`，message = "op_plugin host CPU 往返
  （'kCPU'）违反维10③…**把 host 算值逻辑迁回 kernel/tiling**，plugin 只保留接口适配 +
  aclnn kernel 调用"。
- 触发代码（`unique_plugin.cpp:113`）是**读回 M 这一个标量元数据**：
  ```cpp
  auto m_cpu = workspace_tensor.narrow(0, mOffset, 8).to(at::kCPU);
  M = *reinterpret_cast<const int64_t*>(m_cpu.data_ptr());
  auto y_result = y.narrow(0, 0, M);
  ```
- **反馈指令"迁回 kernel/tiling"对该类算子语义上不可能**：M 是 kernel 跑完后才知道的
  count，host 侧定输出长度是唯一出路，kernel/tiling 无 M 的合法归宿 → 最强模型照做也
  做不到 → codegen 反复 retry 无路可走 → halt（`codegen_iterations=11`、consecutive 清零、
  fail_strategy=halt）。

### 对照：合法写法存在且能过规则（9 天前同算子跑通）

- 成功版 codegen 用的是 **C 级 ACL API 回读，不经 `.to(kCPU)`**（`unique_plugin.cpp`）：
  ```cpp
  aclrtSynchronizeStream(stream);
  aclrtMemcpy(&count, sizeof(int64_t), slotPtr, sizeof(int64_t), ACL_MEMCPY_DEVICE_TO_HOST);
  auto y = yUp.narrow(0, 0, count).clone();
  ```
  正则 `_HOST_ROUNDTRIP_RE = r"\.cpu\(\)|kCPU"` 不命中 `aclrtMemcpy`/`aclrtSynchronizeStream`。
- 成功版 decision_log D16 自检明写"无 .cpu()/kCPU 路径依赖"——coder 主动避红线。
- 结论：**规则本身不拦正确路径**（合法写法已存在且通过），缺的不是"例外放行"，是
  「红线触发时告知合法替代」与「设计阶段前置机制」——两件事，不是一件事。

## P3（同源，独立问题）：规则只扫字面量，无法区分「读回标量元数据定 size」与「host 算值 copy 回输出」

- 正则 `\.cpu\(\)|kCPU` 一刀切命中两种性质不同的代码：
  - 合法：读回 8B count 元数据收窄输出 shape（unique 动态输出）。
  - 作弊：host 算完整结果再 copy 回（moe_re_routing，维10③ 原始实证）。
- 框架当前**无法从字面量区分二者**，故反馈只能给统一文案；但统一文案对前者是死路。

## 关联

- CLAUDE.md §1.12（不耦合具体算子，判据用结构信号）+ §1.13（golden 权威）：
  本类知识以「输出长度数据相关」这一**结构特征**为类边界，不以 unique/NonZero 点名分类。
- `docs/plan/codegen-host-offload-guard/`：维10③ 规则本体的历史记录（moe_re_routing 实证）。
- 记忆 `codegen-faithfulness-step93`、`scatter-pa-kv-cache-507035-not-workspace`：动态/变长输出
  是反复出现的高难类。
