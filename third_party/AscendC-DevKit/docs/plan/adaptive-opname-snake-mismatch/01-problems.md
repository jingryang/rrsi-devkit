# adaptive_avg_pool_3d 算子注册名/文件名下划线错位 → runtime 静默落回内置 op（361001）— L1 问题记录

> 层级：**L1 / 问题记录**。只陈述客观事实（哪里坏了、凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：本会话**运行时实测坐实**（非静态推断）——2026-09-06 批 `c649db` 的 adaptive 算子
> 361001 失败，经 `ASCEND_GLOBAL_LOG_LEVEL=1` 抓 runtime 加载路径逐行证实。
> 与 `diagnose-model-convergence-gap/`（同批 34 轮空转，模型侧）同批但**独立根因、正交**。
> **状态（2026-09-08）**：根因归属修正（注册名为 coder 抄 proto 所致，可修点在 codegen）后，
> 修复已落地——见同目录 `02-analysis.md`（L3 D0-D3）与 `03-impl.md` §7 实施记录（skill 派生规则 +
> `domain/op_name.py` 单点判定 + codegen 机械校验 + UT，真实失败产物复验命中）。

---

## P1：custom kernel config 文件名与 runtime 推导查找名不一致 → runtime 永不选中 custom binary，静默落回内置同名 op

### 现象（361001 现场）

- fp16 case（`x:[2,32,64,64,64]`, `output_size:[8,8,8]`）调用 `torch.ops.cann_bench.adaptive_avg_pool_3d` → 抛错：
  `errno[361001] ... aclrtBinaryGetFunctionByEntry failed, kernel name: AdaptiveAvgPool3D, tiling key: 257`。
- debug 阶段 34 轮 corrective 未修复；本会话用最小脚本**稳定复现**（`/tmp/repro_adaptive.py`）。

### 运行时证据链（ASCEND_GLOBAL_LOG_LEVEL=1 实测，逐行）

runtime 找 kernel config json 的顺序（`kernel_mgr.cpp ParseDynamicKernelConfig`）：

```
[8705] json file path [.../custom_ops/.../config/ascend910b/adaptive_avg_pool_3_d.json] is invalid or does not exist
[8706] json file path [.../custom_ops/.../config/ascend910b/adaptive_avg_pool3d.json]     is invalid or does not exist
[8707] json file path [built-in/.../config/ascend910b//adaptive_avg_pool_3_d.json]        is invalid or does not exist
[8708] json file path [built-in/.../config/ascend910b//adaptive_avg_pool3d.json]          is invalid or does not exist
[8709] json file path [built-in/.../config/ascend910b/ops_nn/adaptive_avg_pool_3_d.json]  is invalid or does not exist
[8724] Parse dynamic kernel config of builtIn success, file path: built-in/.../ops_nn/adaptive_avg_pool3d.json   ← 命中内置
[8729] SelectBin: Available bin for op AdaptiveAvgPool3D is built-in/.../ops_nn/adaptive_avg_pool3d/AdaptiveAvgPool3d_a8d63cbe....o   ← 用内置 binary!
```

**custom opp 目录实际存在的文件名**（实测 `ls`）：
```
adaptive_avg_pool_3d.json     ← custom 唯一 adaptive config（task 目录名派生，pool_3d 间有下划线）
add.json / sqrt.json / binary_info_config.json
```

**对照矩阵**：

| | runtime 推导名（按 Pascal op 名 `AdaptiveAvgPool3D` 归一化） | custom 实际生成名 |
|---|---|---|
| 候选 1 | `adaptive_avg_pool_3_d.json`（首字母 + 每个大写后插 `_`）| — |
| 候选 2 | `adaptive_avg_pool3d.json`（camel→snake 无 3d 边界）| — |
| **实际** | — | **`adaptive_avg_pool_3d.json`** |

三个 runtime 候选 **都不等于** custom 实际文件名 `adaptive_avg_pool_3d.json`。custom 目录无命中 → fallthrough 到内置 `ops_nn/adaptive_avg_pool3d.json`（内置目录名恰好是 `adaptive_avg_pool3d`，无 pool/3d 边界）→ 选中内置 binary。

### 为什么内置 binary 报 funcEntry=257 invalid（次级但确证）

- custom host tiling（`adaptive_avg_pool_3d_tiling.cpp:200` `ASCENDC_TPL_SEL_PARAM(dTypeX, bufferMode)`）按 custom 模板算 funcEntry：fp16/bm1 = `1 | 1<<8` = **257**（Add 算子同机制、smoke 通过，机制本身正确）。
- 但 runtime 用的是**内置** binary `AdaptiveAvgPool3d_a8d63cbe...o`（单模板无 ASCENDC_TPL 动态键，functionEntry 稀疏）→ 无 257 → `BinaryGetFunctionByEntry failed, funcEntry=257` → 361001。
- custom 自己的 binary（`AdaptiveAvgPool3D_240b7d...o` fp16）经 `nm`/`.ascend.meta` section 证实**含 `_1` 和 `_257`**，meta json kernelList = `[_1,_257]`——**257 在 custom binary 里存在**，只是 runtime 从没加载它。

### 根因一句话

**codegen 的 kernel config json 文件名 / binary 目录名由 task 目录名派生（`adaptive_avg_pool_3d`），而 runtime 按 Pascal op 注册名（`AdaptiveAvgPool3D`）做归一化推导查找名（`adaptive_avg_pool_3_d` / `adaptive_avg_pool3d`）。task 目录名与 op 注册名对 `3d`（含数字的子串）的下划线切分不一致** → 文件名永不匹配 → runtime 永不选中 custom binary，**静默**落回内置同名 op → 361001。老版 task 名 `adaptive_avg_pool3d` 无 pool/3d 边界，往返归一化闭合 → 匹配 → 成功（20/20）。

### 根因归属修正（2026-09-08 实测，关键——可修点在 codegen 而非上游）

**注册名（`ADD_TO_LAUNCHER_LIST_AICORE` + `OP_ADD` 里的 `AdaptiveAvgPool3D`）是 coder 生成的代码，
不是上游锁死**。实测证明：注册名若从**落盘目录名**（`state.op_name` = golden snake `adaptive_avg_pool_3d`）
经 `snake_to_pascal` 派生为 `AdaptiveAvgPool3d`（小写 d），则 runtime 反推正好命中落盘 config
`adaptive_avg_pool_3d.json`，361001 不发生：

| 注册名写法 | runtime 反推 | 落盘 config | 结果 |
|---|---|---|---|
| `AdaptiveAvgPool3D`（大写 D，抄 proto `operator.name`）| `adaptive_avg_pool_3_d` | `adaptive_avg_pool_3d` | ❌ 361001 |
| `AdaptiveAvgPool3d`（小写 d，从落盘名派生）| `adaptive_avg_pool_3d` | `adaptive_avg_pool_3d` | ✅ 命中 |

`snake_to_pascal`（每 `_` 段 capitalize）+ runtime camelsnake 对「落盘名 → Pascal → 落盘名」**往返闭合**
（含 `_3d`/`_2d` 数字段，见 L3 §1 验证表）。故**病根是 coder 派生注册名时抄了 proto 的 Pascal
（`AdaptiveAvgPool3D`），而非从落盘目录名派生**——修复点在 codegen 的注册名派生源（skill/渲染规格
指令 + 机械校验），不是上游 task 命名，也无需 deploy 补发。老版成功 = 其落盘名 `adaptive_avg_pool3d`
恰好与 proto `AdaptiveAvgPool3d`(小写d) 的 Pascal 一致，coder 抄 proto 也碰巧命中；新版 proto 为
`AdaptiveAvgPool3D`(大写D)，抄它就错位。

### 反证排除（本会话逐一实测排除的干扰项）

- 非 tiling-key 编码错：Add 用同 key 机制（dtype 低 8 + bufferMode 高 8，fp16/bm1=257）smoke 通过。
- 非符号遮蔽/dlopen 竞态：`ACLNN_CMD` 宏只从 `libcust_opapi.so` dlsym，不落回内置（unique D22 类问题不适用）。
- 非缓存/幽灵 binary：当前部署 custom .o 为最新（04:30:29），config 指向哈希与实际 .o 文件名一致。
- 非大小写 D/d 表面问题：内置 `AdaptiveAvgPool3d`(小写 d) 与 custom `AdaptiveAvgPool3D`(大写 D) 确实不同名，但 runtime 归一化后都找 `adaptive_avg_pool3d` 类名——错位的是**下划线位置**，不是大小写本身。
- 隔离实验佐证：`ASCEND_OPP_PATH` 指向仅含 custom 的合成目录后，错误从 361001 变为 EZ9999（Parse dynamic kernel config fail）——证实 runtime 行为受内置目录存在与否影响，与"选中了内置"判断一致。

## 关联

- 老版成功任务命名 `adaptive_avg_pool3d` vs 新版 `adaptive_avg_pool_3d`（`scripts/batch_self_evolve.sh:62` 明文）+ golden 目录名派生——**task 目录名是错位的起点**。
- CLAUDE.md §1.9：soc_version 之类命名单一权威源已确立；本问题暴露「task 目录名 / op Pascal 名 / 运行时归一化查找名」三者间缺一个统一的下划线切分权威——是否属同一类命名治理待 L3 讨论，本文只记事实。
- 记忆 `codegen-a5-ownership-boundary`：本问题在 A3 codegen 侧生成物，用户职责内。

---

## P1 复验闭环（改名坐实，2026-09-07 本会话实测）

- **验证操作**：在部署的 custom opp 目录 `.../kernel/config/ascend910b/` 下建软链
  `adaptive_avg_pool3d.json → adaptive_avg_pool_3d.json`（覆盖 runtime 候选名之一），
  其余不动。
- **结果**：此前稳定复现 361001 的 fp16 case（`x:[2,32,64,64,64]`, `output_size:[8,8,8]`）
  变为 `CALL OK torch.Size([2,32,8,8,8])`。6 个 case（fp16/fp32/bf16 × 多 shape）全部 CALL OK。
- **结论**：P1 根因闭环坐实——config 文件名匹配后 runtime 选中 custom binary，361001 消失。
  验证后软链已撤，恢复原文件名。
- **附带观测（不属本文范畴）**：改名加载到 custom binary 后，该算子另有自身数值错（全 1 输入
  输出 0.375/0.0781 而非 1，kernel 归约漏加）——属算子实现缺陷的正常调试职责，非 agent 引入的
  生成/加载 bug，与 P1 正交，本文不记录、不解决。
