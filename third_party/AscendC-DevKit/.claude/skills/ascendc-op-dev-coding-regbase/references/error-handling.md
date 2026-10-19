# 错误处理与重试策略

> 本文件定义 ascendc-dev skill 的错误分类体系、校正策略和问题隔离流程。
>
> **体系说明**：本文件定义错误分类体系——§1 细分代码（`C-SYM`、`CHK`、`ENV` 等）供 SubAgent 记录具体错误到 9.3 迭代记录。E(t) 加权累计已移除：重试预算收敛为 per-type 上限 + s4 per-substage / s2/s5 阶段级计数（见 §6），升级决策（retry→rollback→halt）的权威实现在编排层 `codegen.py` / `codegen_s4.py`（`check_retry_exceeded` / `bump_retry_counter` / `_handle_regbase_failure`）。

---

## 1. 错误分类表

| 错误类型 | 代码 | 常见原因 | 校正策略 | 重试上限 | 回退范围 |
|---|---|---|---|---|---|
| 环境错误 | ENV | CANN 未配置、路径不存在、硬件参数缺失 | 提示用户修复环境 | 1 | 不回退，阻塞当前 Stage |
| 歧义错误 | AMB | 需求不明确导致实现偏差 | 回退 Stage 3 重新澄清 | 2 | Stage 3 |
| 设计错误 | DES | 架构决策有误、数据流设计不合理 | 回退 Stage 2 重新分析 | 1 | Stage 2 |
| 编译-符号未定义 | C-SYM | Host/Device 字段名不一致、头文件未包含 | 检查 tiling.h 与 kernel 字段一致性 | 3 | Stage 5 内 |
| 编译-类型不匹配 | C-TYP | Cast 缺失、模板参数错误 | 检查数据类型转换链 | 3 | Stage 5 内 |
| 编译-重复定义 | C-DUP | include guard 缺失、多重包含 | 添加 `#pragma once` 或条件编译 | 3 | Stage 5 内 |
| 编译-链接错误 | C-LNK | CMakeLists.txt 未添加新源文件 | 更新 CMake 配置 | 3 | Stage 5 内 |
| 编译-API 不存在 | C-API | API 签名变更、文档与实际不符 | 查知识库确认正确 API 签名 | 3 | Stage 5 内 |
| 自检失败 | CHK | 对齐问题、TilingKey 机制不一致（host/kernel 新旧混用） | 定位具体检查项修复 | 2 | Stage 4 sub-stage 内 |

---

## 2. 问题隔离流

编译失败时，按以下层次逐步隔离问题根因：

```
编译失败
  │
  ├─ 1. 环境问题？
  │     检查: ASCEND_TOOLKIT_HOME 是否设置
  │     检查: 编译工具链是否可用（cmake, g++）
  │     检查: 依赖库路径是否正确
  │     → 如果是环境问题 → 错误类型: ENV → 提示用户修复
  │
  ├─ 2. Host 代码问题？
  │     检查: *_tiling.h 结构体定义
  │     检查: *_tiling.cpp 逻辑
  │     检查: *_def.cpp 声明
  │     → 如果是 Host 问题 → 定位具体文件和行号 → 修复
  │
  ├─ 3. Kernel 代码问题？
  │     检查: kernel .h 实现
  │     检查: kernel .cpp 入口
  │     检查: API 调用签名
  │     → 如果是 Kernel 问题 → 定位具体文件和行号 → 修复
  │
  └─ 4. 构建配置问题？
        检查: CMakeLists.txt 源文件列表
        检查: 头文件搜索路径
        检查: 链接库配置
        → 如果是配置问题 → 更新 CMake → 修复
```

---

## 3. 重试协议

### 3.1 梯度递进策略

> SubAgent 内部按"同策略→换策略→返回 FAILED"三级递进（详见 §8 重试预算的"SubAgent 行为"流程）。主 SKILL 收到 FAILED 后根据累计上限决定升级处理。

### 3.2 重试计数规则

- 同一错误位置（同文件同行号）的重复失败共享重试计数
- 不同位置的错误独立计数
- 跨 session 恢复时，重试计数从开发记录中读取（不重置）
- 用户明确指示"重新尝试"时，可重置特定错误的计数

---

## 4. Issue 管理

### 4.1 Issue 创建条件

以下情况必须创建独立 Issue 文件：
- 同一错误重试 ≥ 2 次仍未解决
- API 行为与文档描述不符
- 需要用户提供额外信息才能继续
- 涉及多个 Stage 的交叉问题

### 4.2 Issue 文件规范

**位置**：开发记录同目录下 `issues/` 子目录
**命名**：`issue_{YYYYMMDD}_{关键词}.md`

**模板**：

```markdown
# Issue: {标题}

> **创建时间**: {YYYY-MM-DD HH:mm:ss}
> **错误类型**: {错误代码}
> **关联 Stage**: Stage {N}
> **状态**: 待解决 / 已解决 / 已关闭

## 问题描述

{具体错误现象，包含错误日志片段}

## 已尝试的修复

| # | 修复方案 | 结果 |
|---|---------|------|
| 1 | {方案描述} | 失败: {原因} |
| 2 | {方案描述} | 失败: {原因} |

## 根因分析

{对问题根因的分析，可能的原因列表}

## 建议方向

{下一步建议的修复方向}

## 解决方案

{最终解决方案，解决后填写}
```

### 4.3 Issue 生命周期

```
创建 → 记录到开发记录 Issue 注册表 → 用户/agent 解决 → 标记已解决 → 关闭
```

简单问题（重试 1 次即解决）不创建 Issue，直接记录在开发记录的"迭代记录"表中。

---

## 5. 错误模式识别

### 5.1 常见错误模式与快速修复

| 错误模式 | 识别特征 | 快速修复 |
|---|---|---|
| Host/Device 字段不同步 | `undefined reference to` + TilingData 字段名 | 对比 tiling.h 和 kernel 中的字段声明 |
| 头文件循环包含 | `multiple definition of` | 检查 include 链，添加 pragma once |
| API 参数数量错误 | `too many/few arguments` | 查知识库确认 API 签名 |
| 模板实例化失败 | `no matching function` + 模板相关 | 检查数据类型是否支持该 API |
| CMake 源文件遗漏 | `undefined reference` + 链接阶段 | 在 CMakeLists.txt 中添加源文件 |
| 对齐违规 | 运行时错误或编译警告 | 检查 DataCopy 基地址 32B 对齐 |

### 5.2 错误关联分析

当多个编译错误同时出现时，优先修复根因错误：
1. 头文件包含错误 → 可能导致大量"未定义"错误
2. 结构体定义错误 → 可能导致所有使用该结构体的地方报错
3. CMake 配置错误 → 可能导致整个模块链接失败

**原则**：先修复最上游的错误，再重新编译观察下游错误是否消失。

### 5.3 已实证的高频编译陷阱（A5 Regbase 编译期）

> 以下均为真实 run 中验证过的结构性陷阱。s5-compile 编译失败时优先对照本条，避免反复试错。

| # | 症状 | 根因 | 修复 |
|---|------|------|------|
| 1 | `deduced conflicting types for parameter 'T' ('long int' and 'int')` | `Ops::Base::CeilAlign` 等模板要求两参数同类型；`int64_t` 变量与 `int` 字面量混用（如 `CeilAlign(numExperts, 32)`） | 显式模板参数 `CeilAlign<int64_t>(...)` 或 `static_cast<int64_t>(32)`。**必须 grep 全文件所有同类调用一次性修复**（编译常只报首个），注意 `32/xDtypeSize`（xDtypeSize 为 int64_t 时）可不用改 |
| 2 | kernel binary 编译期 `gen_input_json` 越界 / `input_dtype[idx]` index out of range | OpDef 各输入/输出的 dtype/format 数组长度不一致（如 x 3 个 dtype、optional `finished` 只有 1 个 dtype）；`count` 取首个输入 dtype 数展开后越界 | 让所有输入/输出的 dtype/format 列表长度一致（OD-3 规则），单 dtype 输入重复自身补齐到与首个输入相同长度 |
| 3 | kernel 编译报 `no template named 'LocalTensor'`（VF 头文件） | 主 kernel 头的 `using namespace AscendC;` 在 VF include 之后——C++ using 不回溯先前的 include，且 VF 可能被 ccec 独立翻译单元编译 | 在每个 VF 头文件自身 include 之后、使用位置之前补 `using namespace AscendC;` |
| 4 | kernel 编译报 `expected unqualified-id`（入口处） | `extern "C"` 修饰模板函数（`extern "C" __global__ __aicore__` + `template<...>`）——C++ 禁止模板函数 C 链接 | 移除入口的 `extern "C"`（参考同仓已编译通过的 kernel 入口写法） |
| 5 | build exit 0 / install 成功，但 OPP 缺 `<OpName>_<hash>.o/.json`，smoke 才报 `BinaryGetFunctionByEntry failed` | `build_run.sh` 中 `cmake --build --target binary || { echo WARNING }` 把 kernel binary 编译失败吞掉（只告警不退出） | install 后先验 kernel binary 存在；缺失则手动重跑 `--target binary` 看真实错误，修复后**重跑完整 build**（勿信增量产物） |
| 6 | smoke 报 `BinaryGetFunctionByEntry failed, funcEntry=N, tiling key: M` 但 binary 已安装 | CANN runtime 按 opInterface 名（含下划线 snake_case）查 `kernel/config/ascend950/<op_interface>.json`，编译工具只按 `opFile.value`（不含下划线的紧凑名）生成，缺别名 | `def.cpp` 中 `ExtendCfgInfo("opFile.value", "<opInterface 名含下划线>")`，重编译生成两个 config json（原名+别名）。可对比同 OPP 可运行算子的 config 目录确认别名结构。**命名转换规则见 [`references/op-name-conversion.md`](op-name-conversion.md)** |
| 7 | 分类脚本把模板类型推导错误判为 C-API | `classify_compile_error.sh` 基于关键词匹配，易误判 | 分类结果仅供参考，对照原始日志根因（`deduced conflicting types` → C-TYP） |
| 8 | kernel 入口漏声明任务类型，编译报 `the type of kernel function ... auto derivate failed, please manually add the function type attribute`（C-SYM，A5 ld.lld） | **`GET_TILING_DATA_WITH_STRUCT` 关闭 ld.lld 对 kernel 函数类型的自动推导**；A5 部分体模板 kernel（入口只调类方法、计算全在 VF 内）无法被推导。曾有 ref_op 侥幸通过（sqrt 体系被 DataCopyPad + 向量 API 全路径覆盖），**不可依赖** | 纯矢量（elementwise，无 Cube）算子 kernel 入口**必须**显式声明 `KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_AIV_ONLY);`（位置：`REGISTER_TILING_DEFAULT(...)` 之后、`GET_TILING_DATA_WITH_STRUCT(...)` 之前）。CANN 官方同款模式见 `pkg_inc/atvoss/broadcast/broadcast_sch.h:42`；语义：纯 AIV 计算无 Cube → AIV_ONLY |

> **定位方法论**：编译/部署卡壳时，**优先对比同批次/同 OPP 中可正常工作的参照算子产物**（config 目录、kernel 目录、state_snapshot 结构、npu_id 设置）——差异点往往就是根因；比深挖 runtime 源码高效得多。

---

## 6. 重试预算（per-type 上限 + per-substage 计数，E(t) 已移除）

每次 SubAgent 返回 `status=FAILED` 时，编排层按错误类型递增对应计数，未超限则重试；
计数器耗尽后按类别确定性升级（权威实现 `codegen.py:_handle_regbase_failure` 与
`codegen_s4.py:check_retry_exceeded` / `bump_retry_counter`）：

- **s4（子阶段级计数）**：计数落在 `orchestration_plan.json` 每个 sub_stage 条目的
  `retry_count`，**按子阶段隔离**——一个子阶段的失败只消耗自己的预算，不消耗其他
  子阶段的预算（并行 VF 批内各 VF 步骤、多个编码子阶段互不影响）。limit 按错误类型
  从下表取；子阶段标记 done 时 `retry_count` 清零（按尝试窗口计）。
- **s2/s5（阶段级计数）**：`_handle_regbase_failure` 递增 `meta.json retries.<type>.used`，
  s2/s5 各是一次性阶段，等价 per-unit 语义。

| 计数器（limit 按类型） | 上限 | 耗尽后升级 |
|----------------|------|-----------|
| `stage5_compile`（编译错误） | 24 | 回退 s4（代码需修），受 `s5_rollback` 预算（2）约束防 s4↔s5 乒乓 |
| `stage4_selfcheck`（自检/编码） | 8 | s4 阶段回退 s2；s2 阶段 PAUSED |
| `vf_test`（VF 精度） | 4 | 标 exhausted（⚠️ 继续，不阻塞流水线） |
| `stage3_ambiguity`（歧义） | 3 | PAUSED |
| 环境错误（`ENV` 类） | — | 恒 PAUSED（人工修复环境，不回退） |
| 设计错误（`DSG`/`DS-ALG`/`KBD`） | — | 恒回退 s2 |

> **环境错误特别说明**：环境错误（`ENV` / `ENV-CANN` / `ENV-DRV` / `ENV-CC`）**不触发 Stage 回退**——无论在 Stage 1~5 的哪个阶段发现，均阻塞当前 Stage 并返回 PAUSED，等待用户在父 shell 中修复环境后重试。这与 §1 错误分类表的"回退范围 = 不回退，阻塞当前 Stage"以及 workflow-spec.md §4.2"禁止从 Stage 4 回退到 Stage 1"保持一致。

---

## 7. SubAgent 错误代码注册表

SubAgent 返回 FAILED 时必须在 `## RETURN:` 行输出 `error_type`。**所有 5 个 SubAgent 写入 9.3 的错误代码必须按本表注册，不允许 SubAgent 自定义未列出的代码。**

| 类别 | SubAgent 错误代码（来源） | 说明 |
|------|-------------------------|------|
| 编译错误 | `C-SYM` / `C-TYP` / `C-DUP` / `C-LNK` / `C-API`（s5-compile）、`MEM`（s4-coding，Membase API 入侵） | 编译产物层错误 + 机械性规范违反 |
| 自检失败 | `CK` / `CK-FLD` / `CK-ALIGN` / `CK-VF` / `CK-REG`（s4/s5） | 代码层逻辑违例，发生在 s4 编码自检阶段 |
| 环境错误 | `ENV`（s1-env）、`ENV-CANN` / `ENV-DRV` / `ENV-CC`（s5-compile） | 驱动/CANN/工具链缺失，需用户修复环境后重启 session |
| 歧义错误 | `AMB`（s2/s3）、`CMD`（s1-env，编译指令不明）、`AM-CMD` / `AM-PATH`（s5-compile）、`USR`（s4-coding，用户拒绝确认 = 需求澄清不到位） | 关键信息缺失需用户澄清 |
| 设计错误 | `DSG`（s2-analysis）、`DS-ALG`（s5-compile）、`KBD`（s4-coding，知识库缺项 = 需要重新审视设计决策） | 数学公式/边界条件/算法层错误 |
| 输入/兜底 | `INP`（s1/s2/s3）、`OTH`（所有 SubAgent 兜底） | 输入文件/路径不可读；其他需人工介入 |

**实施规则**：
1. SubAgent 写入 9.3 的 ERROR 事件必须使用 3 列表格格式：`| {YYYY-MM-DD HH:mm} | ERROR | {错误代码}: {原因} |`。错误代码必须从本表左侧"SubAgent 错误代码"列中选用
2. SubAgent 内部不允许新增未列出的错误代码（需要新增时同步更新本表 + 各 SubAgent 文档）
3. 错误代码→类别/升级决策的映射由编排层（`codegen_s4.py:check_retry_exceeded`）消费，agent 只负责返回语义正确的代码，不感知权重

---

## 8. 重试预算（SubAgent 内部）

SubAgent 内部按错误类别在单次调度内自行管理重试（梯度递进策略）；跨调度的 per-type 计数器
与升级决策由编排层统一维护（见 §6）。

| 错误场景 | 单次调度内上限 | 超限行为 |
|---------|---------|---------|
| 编译错误 | 3 | 返回 FAILED |
| 自检失败 | 2 | 返回 FAILED |
| 环境错误 | 1 | 阻塞 + 提示修复步骤 |
| 歧义错误 | 2 | 返回 FAILED |
| 设计错误 | 1 | 返回 FAILED |

### 重试计数器持久化（dev record header 方案）

重试计数器作为 dev record header 字段持久化，由 SubAgent 自行读取和更新：

```
> **重试计数器**:
>   - Stage5 编译重试已用: N / 累计上限 24
>   - Stage4 自检重试已用: M / 累计上限 4
```

**SubAgent 行为**：
1. 进入重试逻辑前，从 dev record header 读取当前 `已用: N`
2. 计算本次可用次数 = min(单次上限, 累计上限 - N)
3. 如 ≤ 0 → 直接返回 FAILED，不重试
4. 每次重试前，用 Edit 将 N 值 +1（原子更新，确保跨 compact 不丢失）
5. 达到本次可用上限仍失败 → 返回 FAILED

**梯度递进策略**（SubAgent 内部每轮重试的递进逻辑）：
- 第 1 次：同策略修复——根据错误分类应用对应校正策略，修改代码后重试，记录 `{错误类型, 错误信息, 修复方案}`
- 第 2 次：换策略修复——重新审视设计决策，可能回退到上一 sub-stage 重做，记录 `{原策略失败原因, 新策略描述}`
- 第 3 次：返回 FAILED——将错误代码和诊断信息写入 9.3，由主 SKILL 决定升级处理

**主 SKILL 行为**：
1. 收到 FAILED 后，从 dev record header 读取计数器当前值
2. 对比累计上限，决定：重调 SubAgent / 创建 Issue / 流程暂停
3. 重调 SubAgent 时**不传预算数字**（SubAgent 自行从 dev record 读取）

**跨 session 恢复**：计数器已持久化在 dev record 中，新 session 直接读取，无需重新统计 9.2/9.3 行数。

### 职责划分

- **主 SKILL / 编排层**：维护 per-type 计数器与升级决策（retry→rollback→halt），创建 Issue、回退 Stage、最终决定"是否继续 / 暂停"
- **SubAgent 层**：自行读取计数器 → 计算本次可用次数 → 执行重试 → 自更新计数器 → 达限返回 FAILED

实施链：
1. SubAgent 读取 dev record 计数器，在单次上限内重试
2. SubAgent 每次重试前自更新计数器（+1）
3. SubAgent 达限后返回 FAILED（**不**自己创建 Issue）
4. 主 SKILL 收到 FAILED → 读取 dev record 计数器 → 对比累计上限 → 决定下一步
5. 主 SKILL 决定继续时重调 SubAgent（不传预算数字，SubAgent 自读）

> **设计意图**：避免两层在"升级处理"动作上重复——SubAgent 不应越权创建 Issue，主 SKILL 不应下放到 SubAgent 维护全局预算。per-type 计数器读写权在 SubAgent/编排层，升级决策的权威在编排层（`codegen.py`），职责清晰不交叉。
