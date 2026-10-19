---
name: ascendc-op-dev-coding
description: |
  Pipeline 叶子 skill：根据设计产物（design_spec / tiling_strategy / kernel_architecture / meta.json）
  生成 AscendC 算子代码。覆盖 TilingData 归一化 → Host Tiling → Kernel → ACLNN API → Plugin
  分层编码，带编码自检 + 关键决策记录。跑一次返回，不派下级 subagent。
triggers:
  - ascendc-op-dev-coding
  - pipeline代码生成
  - pipeline coding
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Skill
skills:
  - ascendc-dev-knowledge
  - ascendc-tips
  - evolution-knowledge
  - ascendc-api-best-practices
---

# Pipeline 叶子 Skill：算子代码生成

## 职责

读取设计产物（design_spec.json / tiling_strategy.json / kernel_architecture.json / meta.json），
按编程模型分层生成 AscendC 算子代码到工作目录。

**叶子约束**：本 skill 跑一次返回，不派下级 subagent，不做循环。

---

## 零交互纪律

- **禁止 AskUserQuestion**
- 设计产物缺必要字段（IO spec / 计算公式 / Tiling 策略）或契约歧义导致无法落笔 → 报错退出，
  **不猜测补全**。**对设计路径的可行性怀疑不属此列**——按「设计蓝图缺陷处置」（Step 4）
  处置，不得以「无法确定」为由冻结不落笔。

## 参考来源纪律（算子无关红线）

- 算子代码从「**上游源中间产物**（见输入表）+ 知识库模板（`ascendc-dev-knowledge` / `references/`）」生成。
- **`reference_code`（`ref_*` 文件，若上游注入）是显式给定的参考算子，读它受控可追溯——该读**：用于学习
  API 用法、文件布局、命名约定、缩进风格。
- **禁止自行 grep/Glob/find 文件系统去搜罗参考实现**（含目标仓 `ops/` 下其他算子、其他仓库、
  `$ASCEND_TOOLKIT_HOME`、`/usr/local/Ascend/` SDK 头文件）。只操作输入表中的显式路径。
- **禁 `ls`/`cd` 目录侦查**：不遍历目录去「发现」文件，只操作输入表显式路径。
- **每个上游产物文件只读一次**：读后缓存，禁止重复 Read 同一路径（compaction 冲刷后=缺信息，允许按读纪律重读）；缺信息才重读，不反复扫同一文件。
- **Why**：自搜抄来的实现会产生「看似通过实则通路不符」的虚假信号（历史 20/20 通过却迁移崩溃即此根因）——
  按指示参考（`reference_code`）受控可追溯，自行搜索不可控。
- 知识库查阅（Step 3）查的是 **API 签名 / 约束 / 编程模型**，不是算子成品实现——不受本纪律限制。

---

## 输入（文件契约）

codegen 读**上游源中间产物**（State 字段物化进 staging），分步翻译为 AscendC 代码。需求分析/概设/详设/
tiling/section 声明/验收用例**上游已定，复用不重做**——codegen 只决定代码层落地（API 调用、TilingData
struct 形态、文件命名/布局、ACLNN/Plugin 注册细节）。

当前工作目录（staging）下的文件：

| 文件 | 必填 | 来源 stage | codegen 翻译为 |
|------|------|-----------|---------------|
| `design_spec.json` | 是 | integrate | IO spec / 公式 / attrs（紧凑契约；**TilingKey 路由不在此**，见下 `template_division.json`） |
| `tiling_strategy.json` | 是 | integrate | 跨模板整合：tile 因子 / buffer_model / UB 预算 / shared_tiling_data_fields |
| `kernel_architecture.json` | 是 | codegen_init | section 声明（产出 op_host/op_kernel/op_api/op_plugin 哪些目录） |
| `tiling_results/<模板名>.json` | 强烈推荐 | tiling(split/buffer-kernel/precision-perf)→integrate | **per-template 切片（实现蓝图主源：`buffer_kernel.kernel.pseudocode`）——按当前实现的模板读对应切片；跨模板一致性核对读相邻切片（相邻切片名从 `template_division.json` 派生，勿 ls 目录）**。同目录上级的 `tiling_results.json` 单体=全貌视图（整体对照用） |
| `general_design.json` | 可选 | general-design-generator | 算子分类 / sections 骨架 / precision 策略 |
| `template_division.json` | 多模板必需 | template-division | 模板结构 + 全局锁定决策（如 BUFFER_NUM）+ **TilingKey 路由唯一权威源**（`templates[].tiling_key` + `route_condition`；codegen 据此生成 tiling_key 选择/分发，勿从 design_spec 找路由） |
| `requirement.json` | 可选 | requirement | IO / 公式 / 约束（需求权威源） |
| `test_cases.json` | 可选 | test_design | 验收用例（TDD：codegen 须满足） |
| `meta.json` | 是 | codegen（物化） | programming_model / chip_code / soc_version（驱动编码路径） |
| `ref_*`（参考算子） | 可选 | context 注入 | 参考算子真实代码（API 用法 / 文件布局 / 命名） |
| `op_name` | 是 | 调用方注入 | 算子名（snake_case），上下文变量 |

> **实现蓝图优先级**（分步翻译源产物）：先 `tiling_results/<当前模板>.json → buffer_kernel.kernel.pseudocode`（按当前实现的模板读对应切片） → Kernel/Buffer →
> `general_design`+`template_division` → 骨架 → `design_spec`+`tiling_strategy` → Host Tiling/TilingData →
> `kernel_architecture` section → ACLNN/Plugin。
>
> **读纪律（上下文经济）**：重读大产物**先定位后读段**——grep 取键路径，Read 带
> limit/offset 定向读所需段；**定位失败（不确定要看哪段）时允许整文件读**——
> 禁止的只是跳过定位尝试的无差别整读（大文件整读即撑爆上下文）。

---

## 输出（文件契约）

1. **源代码文件**：按 `kernel_architecture.json` 各 section 的 `directory` 产出到对应子目录。**具体文件名由 codegen 参考目标仓现有算子确定**（与 CMakeLists.txt 同机制），不进契约约束。
2. **`decision_log.json`**：关键决策记录（schema 见 `schema/decision_log.json`），写入当前工作目录
3. **`codegen_manifest.json`**（**算子签名契约，禁止当会话报告/调试笔记用**）：记录 codegen 实际采纳的算子签名——"实际采纳" = 你在 `op_plugin` 的 `m.def("op(...)")` 里**真正注册**的签名（非 design_spec 拷贝；移除了不支持的 dtype 等改动必须反映在此）。**只填契约字段**（schema 见 `schema/codegen_manifest.json`）：

   - `op_name`：C++ OpType；`inputs`/`outputs`：`[{"name":..,"type":"Tensor"}]`，name 与你的 `m.def` tensor 参数一致；
   - `callable_target.symbol`：`torch.ops.<namespace>.<op>`，其中 `<namespace>`/`<op>` **必须与你写的 `TORCH_LIBRARY_FRAGMENT(<namespace>, m)+m.def("<op>...")` 完全一致**（`callable_target.kind` 由框架按 profile 注入，你只写 `symbol`）。

   **禁止**写 `compile_status`/`runtime_status`/`suspected_root_causes`/`next_steps`/`files`/`key_apis_used`/`template_routes` 等调试/报告内容进 manifest——它们归 `decision_log.json`。框架会校验 `required_keys`（`op_name`/`inputs`/`outputs`/`callable_target`，缺则定向重试而非放行），并从 plugin 注册自动派生漏填的 `callable_target.symbol`，但 `inputs`/`outputs`/`op_name` 必须由你声明。

代码完整性判据：`kernel_architecture` 声明的每个 section 目录存在且至少包含一个非空源文件。

---

## 执行流程

### Step 1：参数校验

- 校验所有必填输入文件存在
- 读取 `meta.json` 获取 `programming_model` / `chip_code` / `soc_version`
- meta.json 不存在或缺 `programming_model` → 报错退出

### Step 2：读取设计产物

从设计产物提取编码所需信息：
- `design_spec.json` → IO spec（输入输出 tensor 定义、dtype、shape 约束）、计算公式/算法描述
- `tiling_strategy.json` → 切分方案、TilingKey 路由
- `kernel_architecture.json` → 需要产出的文件清单（各 section 的 `directory` / `files[]`）

**缺失关键信息判定**：
- 无 IO spec → status=fail，提示"详设缺 IO 定义"
- 无计算公式 → status=fail，提示"详设缺计算逻辑"
- 无 Tiling 策略 → 使用保守默认（单核 + 最小 tile）+ warning
- 无 kernel_architecture → status=fail，提示"缺 kernel 架构文件清单"

**锁定项入口校验（fail-fast，③）**：以下字段若算子涉及、却在上游源中缺失 → **停下报告「上游缺 X」**，
status=fail，不 grep CANN、不自搜、不猜测补全（§1.3 入口期校验优于运行期暴露 + §3.7 诚实报缺）：
- 涉双缓冲算子 → `general_design`/`template_division` 须含 BUFFER_NUM 决策
- 涉 reduce/gather/scatter/sort/topk/broadcast 或任何用 GM workspace 的算子（跨核 reduce / UB 不够暂存 / SyncAll-as-GM 等）→ `tiling_strategy`/`tiling_results` 须含 workspace 预算；**且 tiling 函数 `ws[0]` 必须含 `GetLibApiWorkSpaceSize()`（见 Step 4② GM workspace 设置）**——只设用户 workspace 会越界（507015，历史实证）
- TilingData → `tiling_strategy` 须含字段清单（shared_tiling_data_fields）
- dtype → `design_spec` IO spec 须含 dtype 支持矩阵

### Step 3：知识库查阅

**知识源优先级**：API 用法/避坑（精度边界、dtype 支持、对齐约束）优先查 `ascendc-api-best-practices`；裸签名/参数约束查 `ascendc-dev-knowledge`——查不到时用 `ascendc-tips`；仍查不到 = 知识库未覆盖（≠API 不存在）——停下报告「知识库未覆盖、存在性存疑」或走定向查证（已知路径定点读/窄域 grep），不猜测、不写死存在性结论。

进入编码前，通过 `ascendc-dev-knowledge` skill 查阅：
- 所需 API 的签名和约束
- **OpDef（`def.cpp`）渲染**：必读 `ascendc-op-design-shared/references/OpDef渲染规格映射.md`（+ 官方 `ascendc-dev-knowledge/references/basic_knowledge_docs/编程指南/附录/工程化算子开发/算子原型定义.md`）——按映射表从 `design_spec.json`（inputs/outputs/attrs/`param_type`）逐字段套 builder 链；chip 从 `meta.json.chip_code` 经 `to_soc_version()` 翻译成 `AddConfig` 的 soc 字面量。**禁** `desc.Mut*`/`OutputAttrMapping`/`ScalarValueType`/`<占位>` 等虚构 API
- 芯片特定编程约束：A5 Regbase 场景查 `ascendc-dev-knowledge` 两处（已加载，VF 指令 + Regbase 模型分指）：
  - **VF 指令签名/语义**：`api_reference_docs/SIMD_API/基础API/Reg矢量计算/`（Cast / Interleave / Move / Reg数据搬运 连续对齐搬入·搬出·连续非对齐搬入·搬出 / Reduce / Gather / 类型转换 / 数据重排 等，等价 VF 指令参考库）
  - **Regbase 编程模型与约束**：`910D_knowledge_extra/`（RegTensor / MaskReg / AddrReg / GetPhyAddr / asc_vf_call / SIMD-BuiltIn关键字和API / SIMD与SIMT混合编程 / AI-Core-SIMD编程 / AIC和AIV独立运行机制）
- **TilingKey 模板参数化机制**：编码 `tiling_key.h` / `*_tiling.cpp` / kernel 入口前，必读本 skill 参考文档 [`references/tilingkey-tpl-style.md`](references/tilingkey-tpl-style.md)（覆盖 `ASCENDC_TPL_ARGS_DECL` / `ASCENDC_TPL_SEL` / `GET_TPL_TILING_KEY` / `ASCENDC_TPL_SEL_PARAM` / `REGISTER_TILING_DEFAULT` / `REGISTER_NONE_TILING` / 多模板多 TilingStruct 等完整写法和一致性约束）
- 对齐要求、同步约束
- **同步选型（落码前必读）**：凡代码含跨流水数据依赖（DeQue 后 V 流水计算、SetValue/GetValue 与搬运交互等），必读 `ascendc-sync` skill §3 选型表；**`DataSyncBarrier` 是内存屏障而非流水间同步工具，禁止在跨流水依赖处使用**（见 `ascendc-sync/references/common-pitfalls.md` 陷阱 13）
- **strided DataCopyPad 行距一致性（落码前必读）**：编码凡遇到 strided `DataCopyPad`
  （`blockCount>1` 或含 `srcStride`/`dstStride`）且存在尾块/非 32B 对齐行，必读
  `ascendc-op-design-shared/references/datacopy-stride-consistency.md` 核对「搬运行距 ==
  寻址行距」不变式后再落码.
- **GM workspace 契约（host tiling 必读）**：`ascendc-dev-knowledge/references/basic_knowledge_docs/附录/常用操作/如何使用workspace.md` + `.../api_reference_docs/.../PlatformAscendC/GetLibApiWorkSpaceSize.md`——tiling 函数 `ws[0]` 须含 `GetLibApiWorkSpaceSize()`，见 Step 4②

### Step 4：分层编码

根据 `programming_model` 选择编码路径：

| 编程模型 | 路径 | 特点 |
|----------|------|------|
| A2 Membase | 路径二 | 传统 AscendC（Membase Vector，与 A3 一致） |
| A3 Membase | 路径二 | 传统 AscendC（Membase Vector） |
| A5 Regbase | 路径三 | VF 入口 + RegTensor + 910D 约束 |
| 纯 Cube | 路径一 | 不涉及 Vector Pipeline |

**编码顺序**（按 `kernel_architecture` 的 section 逐层产出）：

```
① TilingData 定义（设计驱动）
  → host_code section 中 tiling_data 相关文件
  → kernel_code section 中 tiling_data 相关文件（与 host 侧内容一致）
  → 约束：plain C struct（不使用 BEGIN_TILING_DATA_DEF 等 CANN 宏）

② Host 层（设计驱动）
  → tiling.cpp — Tiling 计算逻辑（主路由 + TilingKey 分支）
  → infershape.cpp — InferShape 实现（若 kernel_architecture 声明）
  → def.cpp — OpDef 注册（若 kernel_architecture 声明）：按《OpDef渲染规格映射.md》从 design_spec 渲染 builder 链 + `OpAICoreConfig`/`AddConfig`（chip 取 `meta.json.chip_code` 经 `to_soc_version()`）+ `OP_ADD`

③ Kernel 层（设计驱动）
  → kernel 入口 + 计算实现
  → tiling_data.h — TilingData 副本（与 host 侧一致）
  → tiling_key.h — ASCENDC_TPL 模板参数声明（ARGS_DECL/SEL）

④ ACLNN API 层（若 kernel_architecture 声明 api_code section）
  → L2 API（aclnn{Name}GetWorkspaceSize + aclnn{Name}）
  → L0 API（OP_TYPE_REGISTER + InferShape + AiCore dispatch）

> **注册名派生源（贯穿 ②/④ + plugin `m.def` + manifest，本 skill 所有产注册名处统一遵守）**：
> 注册名（Pascal：`OP_ADD`/`register_aclnn_op` 首参/`ADD_TO_LAUNCHER_LIST_AICORE` 首参/`m.def` op/class 名）
> **一律从落盘目录名（你的算子源码目录 `op_dir` 的末段；无前缀仓 = op_name/golden 入口 snake，带
> 前缀仓 = 前缀 + golden snake）经「逐 `_` 段 capitalize 后拼接」派生**
> （`adaptive_avg_pool_3d` → `AdaptiveAvgPool3d`，数字段 `3d` 保持小写 d）。**禁止直接抄
> proto/requirement 的 `operator.name`**——其 Pascal 可能把数字段大写（`AdaptiveAvgPool3D`），抄它使
> runtime 按注册名反推（`adaptive_avg_pool3_d`）≠ 落盘目录名（config 文件名基底，编译器从目录名
> 派生）→ runtime 找不到 custom config、静默落回内置 op → 361001（历史实证：adaptive_avg_pool_3d 批）。
> proto 名仅作参考。目录名以 `pwd`/上下文注入的 op_dir 为准，勿用 strip 后短名（带前缀仓短名≠目录名）。
> 自检（框架机械校验兜底）：注册名经 runtime camel→snake 反推须等于落盘目录名；不等即抄错了源。

⑤ Plugin 层（若 kernel_architecture 声明 plugin_code section）
  → TORCH_LIBRARY_FRAGMENT + meta/npu 实现
```

> **编码顺序保证正向依赖**：TilingData（①②必需）→ Host Tiling（②依赖①）→ Kernel（③依赖①）→ ACLNN API（④依赖②③）→ Plugin（⑤依赖④）。
> 每完成一个文件立即 Write/Edit 落盘，不攒到最后。
> **首稿纪律**：Step 4 的首动作，是按 `kernel_architecture` 的 section 文件清单 + 脚手架模板，**一次性落全套文件骨架**（允许有编译错误/占位），再针对编译错误逐文件迭代修正；**禁止先做大量 read/bash 调研而不落码**（历史反例：首轮只调研 0 Write，下一轮从零重探）。首稿允许错、不允许缺——有错的骨架能靠编译报错驱动迭代，零产出的调研什么也驱动不了。
>
> **构建归属（方案 2，勿整仓自建）**：**整仓 build / install / smoke 归框架**——codegen
> 完成后框架自动运行编译验证（compile → 错误注入 → 你修 → 再 compile，直到过 → install+smoke）。
> **禁止在会话内自行执行整仓构建**（`bash build.sh` / `cmake --build` / install / smoke / pip /
> 写系统 vendors）——那会污染共享环境且与框架 deploy 门重复；整仓构建的中间产物/日志由框架管理，
> 你不自行复刻构建链。**最终编译正确性由框架验证**，会话内不以整仓构建自检。
>
> **会话内职责边界（按「何时发生」组织，方案 2）**：
> - **写码阶段（无编译反馈）**：只读 + 知识搜索（Read/Grep/Glob/ls/cat/…），**不编译**——整仓
>   build 由框架跑，你不需要也不应该自行制造编译机会；不要预验证、不要逐 API 试编。
> - **某 API 用法存疑时**（写码中不确定签名/参数，或编译报错指认 no matching function）：先查
>   知识库/ascendc-tips 的正确签名；仍存疑可做**最小单文件编译验证**（方法见
>   `references/verify-api-signature.md`，是仅存疑时的定向动作，非常规流程，不装系统）。
> - **host 阶段错误（smoke host 反馈）**：修 op_host/op_api/op_plugin 脚手架（tiling/infershape/
>   attr 接线/注册/launch——CPU 侧可推理验证，生产者自闭环）。
> - **kernel 阶段错误（smoke kernel/运行期）**：vector core 异常如 507035、运行期数据错、
>   MTE/vector 同步竞态形态——**不在会话内吸收**：把已观察到的错误现象（签名/复现/已排除方向）
>   记入 `decision_log.json.known_issues`，然后**按原样交棒**——框架 smoke 门会按「kernel 是否
>   执行过」分类并把 kernel 类转交 precision 阶段（那里有 golden 对照与设计上下文，同步竞态的
>   解法查同步选型表：SetFlag/WaitFlag/PipeBarrier）。
>   **「代码写完 + host 自检过 + kernel 阶段错误已记录交棒」= 合格完成**——kernel 阶段 smoke 红是
>   合法交接，不是你的失败；用标量化/单核化消灭流水来让 kernel 错误消失是结构偏离（见维4 AR-1，
>   框架会定向打回）。
>
> **验证脚本的环境契约错误归环境，不归代码**：验证/冒烟脚本若以**环境契约专用错误**失败（stderr 含环境契约标记、指明运行环境变量在传输途中被改写），这是**部署环境问题而非算子代码问题**——按 ownership 判 `not_codegen` 交棒即可，**不要**在会话内诊断环境、也**不要**以写系统目录/改共享环境（安装到默认路径、拷贝算子包到系统位置、改共享包）的方式自建通路绕过——那会污染其他算子的运行环境。

#### 设计蓝图缺陷处置（明显先改、疑点送测）

- **明显缺陷**（判据 = 可证明性：约束条款出处 + 可复算的违反推导）：先做**等价变形**再落盘
  （优先最小、只改违约点、保持蓝图语义与性能意图），decision_log 登记出处 + 推导 + 变形理由，
  写 `known_issues` 交棒设计侧；变形后的代码照常过全部构建/测试。无最小变形时允许更大的
  **等价重实现**（同样登记 + 交棒）——能解决的不报错；标量化/单核化等降级规避不属等价变形
  （维4 AR-1 红线）。
- **非明显怀疑**（写不出完整证明的一切疑点：API 形态 / 性能 / 语义拿不准）：第一版**按设计
  蓝图直译**，疑点记 decision_log 不预改；**构建与测试**（编译/冒烟/精度对照）是设计与实现
  分歧的唯一裁判。实测失败按首错修，归因由**修复层级**派生：就地可修 = 编码错误；
  须动算法路径 = 设计路径，按上条处置（证据 = 实测失败输出）。
- **报错退出仅限**：输入缺失/契约歧义（零交互纪律）；或设计缺陷处置后仍完全无法确定正确
  路径（结构化报错记真实根因与已排除方向，交棒设计侧）。

#### GM workspace 设置（tiling 函数末尾，强制契约）

**铁律**：tiling 函数末尾设 `ws[0]` 时**一律加 `GetLibApiWorkSpaceSize()`**，禁只设用户 workspace、禁写死常量（如 `0` / `16*1024*1024`）。

**机理（必知）**：工程（OpDef）模式下框架在 workspace 总分配前端预留系统区、并把 kernel 入口的 workspace 指针**偏移过系统区**后交给 kernel（知识库「kernel 入口 workspace 为用户的 workspace 指针」）。`ws[0]` 必须含 `usrSize + sysWorkspaceSize`；只设用户量 → 总分配 < 偏移量 → kernel 写入落在分配之外 → **GM 越界 → aicore exception(507015)**。**此规则对纯低阶 API 算子同样成立**（历史实证：某纯 DataCopyPad/Add/Cast 算子无 Matmul，`ws[0]` 只设用户量致 9/20 例 507015；加 `GetLibApiWorkSpaceSize()` 后转绿）——比知识库字面「使用 Matmul 等高阶 API 时才需加」的条件性措辞**更强**（工程模式框架无条件偏移系统区）。

**唯一正确 pattern**：

```cpp
// 在 tiling.cpp 的 TilingFunc 末尾、SetBlockDim 之后：
auto ascendcPlatform = platform_ascendc::PlatformAscendC(context->GetPlatformInfo());
uint32_t sysWorkspaceSize = ascendcPlatform.GetLibApiWorkSpaceSize();  // 系统 workspace，平台相关，禁硬编码
size_t* ws = context->GetWorkspaceSizes(1);
ws[0] = userWorkspaceSize + sysWorkspaceSize;   // 一律加，禁 ws[0] = userWorkspaceSize
```

- `userWorkspaceSize`（用户 workspace）优先取设计产物 `tiling_results.buffer_kernel.workspace.user_workspace_bytes`；缺失则按 tiling 推导（如 `sCoreNum × W × dAlignF32 × sizeof(float)`）+ decision_log 记「设计未声明 user_workspace_bytes，codegen 按 tiling 推导」。
- **GM workspace 布局契约消费（layout_contract）**：设计产物 `tiling_results.buffer_kernel.workspace.layout_contract` 在位时，kernel 侧跨核 GM 布局（平面划分/偏移/stride/地址恒等式）与 host tiling 公式**按契约直译**，禁止现场重推布局——布局推导属设计期产权，编码期重推既烧深推理又引入 host/kernel 公式漂移风险。契约与实现需求冲突、或 kernel 需要 GM 布局而契约缺位时：做最小推导 + decision_log 记「layout_contract 缺失/冲突，codegen 现场推导（应在设计期交付）」+ 写入 `known_issues` 交棒设计侧——不得自推后静默吸收。
- **`sysWorkspaceSize` 恒取 `GetLibApiWorkSpaceSize()`**——平台/CANN 版本相关，**禁写死 16M 或任何常量**（无权威源）。
- 注意区分：本节是 **tiling 函数的 `ws[0]`**（GM workspace，kernel 用）。下文 ACLNN API 层的 `aclnn{Name}GetWorkspaceSize`（executor workspace，Step 4④）是另一回事，由 executor 图构建获取、不手动估算，与本节无关。

#### dtype 策略（Kernel 层，强制）

**默认在 IO 张量 native dtype 上运算**。升精度仅对**浮点算术累加**且设计声明 `compute_dtype` 时引入；**整数不升精度**（运算精确，仅溢出风险；**int→FP 必丢精度 >2²⁴，禁止**）。**非计算算子**（compare/sort/dedup/gather/scatter/mask）**不得引入 intermediate dtype 中转**——升精度无累加可保。dtype 转换一律 vector `Cast()`，**禁**元素循环内标量 `ToFloat`/`ToBfloat16`/`ScalarCast` 漏斗（自检维4 AR-4）。判据按"算子是否对值做算术"，不认算子名。

#### TilingKey 路由（ASCENDC_TPL 模板参数化）

TilingKey 一律用 **ASCENDC_TPL 模板参数化**机制，host/kernel 同侧同机制：

| 侧 | 写法 |
|---|---|
| Host Tiling | `ASCENDC_TPL_SEL_PARAM(context, dTypeX, ...)`；模板参数声明放 `tiling_key.h`，用 `ASCENDC_TPL_ARGS_DECL`（声明参数维度：dtype/format/buffer 等）+ `ASCENDC_TPL_SEL`/`ASCENDC_TPL_ARGS_SEL`（穷举参数组合） |
| Kernel 入口 | `template <typename D_T_X, ...> __global__ __aicore__ void op(GM_ADDR..., GM_ADDR workspace, GM_ADDR tiling)`，用 `if constexpr` 编译期路由到各模板实现 |
| TilingData | 所有分支共用一份 plain C struct |

**适用范围**：分支由 dtype / format / buffer 模式等正交模板参数区分即用此机制；多模板算子（不同算法路径/数据结构，如 softmax 的 T1/T2、block/mx/hifp8）通过 `ASCENDC_TPL_UINT_DECL` 声明多组参数组合，仍走编译期路由。参考 `add` 范例（`template <typename D_T_X, int BUFFER_MODE> __global__ __aicore__`）、知识库 `ascendc-dev-knowledge/.../Utils_API/Tiling模板编程/` 以及本 skill 参考文档 [`references/tilingkey-tpl-style.md`](references/tilingkey-tpl-style.md)。

**多 TilingStruct 注意**：当模板参数会改变 TilingData 大小/数组维度时（如 RANK 分 4/8 导致结构体不同），必须按 `tilingkey-tpl-style.md` §10.2/§11 使用 `REGISTER_NONE_TILING` + 各分支显式 `GET_TILING_DATA_WITH_STRUCT`；host 下发给某 TilingKey 的 TilingData 大小必须与 kernel 分支解析的 struct 严格匹配。

**`ASCENDC_TPL_DATATYPE_DECL` vs `ASCENDC_TPL_DTYPE_DECL` 选择（关键，防 6 路震荡）**：两宏都声明 dtype 维度参数、易混用错致编译期反复试错。判据**凭参数来源结构信号**，不凭记忆：
- **`ASCENDC_TPL_DATATYPE_DECL`（原生 DataType）**：参数**由某个 IO 张量的 dtype 派生**——即该模板参数取值就是输入/输出张量的实际 dtype（fp16/fp32/bf16 等原生类型）。此时用 `ASCENDC_TPL_INPUT(x)`/`ASCENDC_TPL_OUTPUT(x)` 绑定到第 x 个输入/输出（编译器从 IO dtype 自动穷举），或直接列 `C_DT_FLOAT/C_DT_FLOAT16` 等原生枚举。**判据：参数语义 = "第 N 个 IO 的数据类型"→ 必用 DATATYPE_DECL**（如 `add` 的 `D_T_X ← ASCENDC_TPL_INPUT(0)`、`D_T_Z ← ASCENDC_TPL_OUTPUT(0)`）。
- **`ASCENDC_TPL_DTYPE_DECL`（自定义枚举）**：参数**是算子自定义的、与任何 IO 张量 dtype 无绑定关系的枚举维度**（如算法模式选择、自定义精度档 `ADD_TPL_FP16/ADD_TPL_FP32` 这类算子私有 enum）。**判据：参数语义 = "算子私有的一个离散选项档"、其取值不等同于某 IO 的 dtype → 用 DTYPE_DECL**。
- **自检（维5b，warn）**：对每个 dtype 维度模板参数，核对其**声明宏是否与来源匹配**——参数绑定到 `ASCENDC_TPL_INPUT/OUTPUT(x)` 或取原生 `C_DT_*` 却用了 `DTYPE_DECL`（或反之：私有 enum 却用 `DATATYPE_DECL` 硬塞 IO 绑定）即**不匹配 → warn**「模板参数 {name} 来源是 {IO dtype 派生|私有枚举}，应改用 {DATATYPE_DECL|DTYPE_DECL}」。**判据凭来源结构（是否绑定 IO / 是否原生 C_DT_*），非算子名**。设计产物未显式声明参数来源时，从 kernel 模板签名 + OpDef IO dtype 矩阵推断；拿不准不强判 fail，warn 让编译兜底。参见知识库 `ascendc-dev-knowledge/.../Utils_API/Tiling模板编程/模板参数定义.md`（DATATYPE=原生/可 INPUT(x) 绑定，DTYPE=自定义枚举）。

⑥ **算子导出检查**（best-effort，非阻塞）

> **导出检查定位**：CannbenchAdaptStage 是算子导出的权威适配步骤——它在 deploy 和 eval
> 之间运行，专门负责仓胶水文件的适配。codegen 的导出检查降为 best-effort：尽力而为但不阻塞。
> 如果 codegen 漏掉了 wrapper，CannbenchAdaptStage 会兜底补上。两者都读 codegen_manifest，
> 签名一致，不会互相覆盖。

参考目标仓内现有算子（调用方注入的参考实现路径）的导出/注册模式——如评测仓的
Python 包入口（`cann_bench/__init__.py` 类）追加 `def {op}(...)` wrapper，具体文件/
机制以目标仓现有算子为准（§2.7 仓特定内容由 LLM 现场参考目标仓学习）。

不写死具体文件路径；LLM 从参考实现学习，自行决定是否需要更新、更新哪个文件。
与 CMakeLists.txt 同属非核心脚手架，不进 kernel_architecture 契约。codegen 完成此检查为
加分项，失败不影响 pipeline 继续——收尾适配层会兜底。

**ACLNN API 层 / Plugin 层 核心质量要求**（跨算子通用，与仓无关）：
- 参数校验：必填 input/output 做 null check + dtype support check
- Workspace 计算：通过 executor 图构建获取，不手动估算
- InferShape 逻辑：必须与 kernel 期 tiling 的 shape 推导一致
- Dtype dispatch：所有声明的 dtype 必须在 IsAiCoreSupport 中检查
- Attrs 传递：attr 类型（int64_t/float/bool）必须与 OpDef 注册一致
- **In-place 算子（`design_spec.mutation_mode == in_place`）plugin 交付契约**：读 design_spec 的 `mutation_mode`。
  - **交付契约（由目标仓决定，默认 out-of-place 返回）**：多数评测仓（如 cann-bench——golden/AI run 共享输入，真 in-place 会污染对方输入）要求 out-of-place 返回交付 → in-place 算子 clone+return。若目标仓用真 in-place torch 接口（如 `op_(...)` 原地算子），按仓约定。判别：参考目标仓现有算子的接口形态，**不假定所有仓一律**。
  - `in_place` 算子：对每个**同名 input-output 状态张量**（per-tensor 读写由 inputs/outputs 同名关系隐式定义：同名=read_write）**强制 `.clone()`** 作 output（**禁用 `.contiguous()` 充当 clone**——已连续时返回 view 非副本）；clone 同时作 aclnn 的 input 与 output（维持 aclnn 内部 in-place alias 语义，kernel 零改动）；`m.def` 返回值 == 所有 output（非 `-> ()`）；**禁止 `copy_()` 写回调用方传入的原张量本体**。
  - `out_of_place` 算子：output 与 input 不同名（独立），直接 return output，无需 clone。

**仓特定布局（如 register_aclnn_op 宏、CMakeLists 模板、include 路径）不在本 skill 范围内**——
参考目标仓内现有算子的实现模式，由 LLM 现场学习生成。

#### 轴参算子 axis-aware 发射（条件：`general_design.json` 含 `axis_param_design`）

当 `general_design.json` 含 `axis_param_design`（`is_axis_param_op=true`，即拆分/计算轴为运行时 `dim` 属性的算子，如 SwiGLU/GLU/concat-dim/gather 等）时，发射 dim==末轴 与 dim≠末轴 两路径代码；**不含则跳过本节（休眠 no-op），维持当前 dim=末轴行为**（非轴参算子只有末轴路径；纯加性，commit-1 未合则 `axis_param_design` 不存在 → 休眠，零回归）。**蓝图源**：两路径的 Kernel 伪代码（CopyInContiguous / CopyInStrided 等）直接取自上游 `tiling_results.<tpl>.buffer_kernel.kernel_pseudo_code` 的 fast_path / generalized 段（设计阶段已产出，经 Buffer 对齐 / TilingData 字段 / 循环不变量校验），**按其翻译，不再凭 `axis_param_design` 文字规格自由推导 strided 参数**——自由推导是历史降级路径，会导致 host tiling 与设计蓝图脱节、执行失败（EZ1008）。

- **① TilingData**：在 plain C struct 中追加 `axis_param_design.generalization.tiling_data_fields` 列出的轴描述符字段（如 `x0GmOffset` / `x1GmOffset` / `axisBlockLen` / `axisBlockCount` / `axisSrcStride`），供 host 填、kernel 读；host/kernel 两侧 tiling_data 一致（Step 5）。
- **② Host TilingFunc（tiling.cpp）**：读 `dim` 属性（design_spec attrs），按实际 dim 推导 x0/x1 的 GM 描述符并填入轴描述符字段：
  - `dim==末轴`（fast path）：x0/x1 为同连续区间两半 → 描述符取连续值（基址差 halfD、跨距=行宽）。
  - `dim≠末轴`：按 dim 轴在内存中的实际布局推导 x0、x1 两段的基址（offset）与跨距（stride）/ blockLen / blockCount。
- **③ Kernel CopyIn**：generalized 路径按 `buffer_kernel.kernel_pseudo_code` 的 CopyInStrided 伪代码翻译——用 `DataCopyPad`（strided：`DataCopyExtParams` 的 blockCount/blockLen/srcStride 取自轴描述符字段）搬 x0/x1 进 UB；fast_path 路径按 CopyInContiguous 伪代码翻译（连续 DataCopy）。**VF 计算（轴无关）与 CopyOut（按输出布局）两路径共享**。两路径伪代码必须都落地翻译，不得只翻末轴。
- **Step 6 自检增项**：轴参算子须校验「轴描述符字段 host 已填 + kernel CopyIn 已用 + dim==末轴与 dim≠末轴**两路径伪代码均已翻译**（不得只翻末轴）+ 两路描述符推导自洽」。

> 设计侧规格见上游 `general_design.json:axis_param_design`；**两路径 Kernel 伪代码见 `tiling_results.<tpl>.buffer_kernel.kernel_pseudo_code`（fast_path / generalized 段）**。chip-agnostic：A5 下 strided `DataCopyPad` 属 MTE2 CopyIn（Vector 执行域外），不违 A5 红线 #1（#1 仅禁 Vector 域内 DataCopy）。

#### A5 Regbase 编码红线（programming_model == A5 Regbase 时强制，违反即编译失败）

> **Vector 执行域定义**：A5 中 Vector 计算发生在 `__simd_vf__` / `__simt_vf__` 函数体或
> `__VEC_SCOPE__` 代码块内。域内受 Regbase 约束；域外（同函数内）允许普通 scalar 计算。
> 以下九条约束限定范围均为「Vector 执行域内」。VF 指令语义/组合模式/陷阱编码前查 Step3 两处
> `ascendc-dev-knowledge` 参考库（不 grep CANN）。

**九条强制约束**（任一违反 → A5 编译失败）：

| # | 约束 | 禁止行为（Vector 执行域内） | 正确做法 |
|---|------|----------------------------|---------|
| 1 | 禁 A3 DataCopy | `AscendC::DataCopy` / `DataCopyPad` / `DataCopyExtParams` | SIMD 用 `LoadAlign`/`StoreAlign`，SIMT 直接用 `__gm__` 指针 |
| 2 | TilingKey 模板参数化 | 运行时 TilingKey 分支路由（host 手动拼 TilingKey 数值 / kernel 运行时分支选实现） | ASCENDC_TPL_SEL_PARAM(host) + kernel template + if constexpr 编译期分发；`VF_CALL`/`asc_vf_call` 仅管 Vector 计算调度（与 TilingKey 路由正交） |
| 3 | 禁 LocalTensor 直接计算 | `LocalTensor<T>` 直接做 Vector 计算 | 先 `(__ubuf__ T*)tensor.GetPhyAddr()` 提取地址传入 VF |
| 4 | 禁 A3 内存对象 | `pipe` / `inQueue`/`outQueue` / `TBuf` / `AllocTensor` / `FreeTensor` | 域内仅用 `RegTensor` / `MaskReg` / `__ubuf__*` |
| 5 | 禁 A3 高阶 API | `AscendC::Add`/`Mul` 等（无 MicroAPI 命名空间） | 用 `AscendC::MicroAPI::Add` 等 Regbase API |
| 6 | 禁 callee 交叉调用 | `__simd_vf__` 调 `__simt_callee__`，或 `__simt_vf__` 调 `__simd_callee__` | SIMD 只调 `__simd_callee__`，SIMT 只调 `__simt_callee__` |
| 7 | 禁非 inline VF | `__simd_vf__`/`__simt_vf__` 未标 `inline` | 必须 `inline` |
| 8 | 禁 VF 返回值 | `__simd_vf__`/`__simt_vf__` 返回非 `void` | 必须返回 `void` |
| 9 | 禁 pass-by-reference | 参数用 `T&` / `const T&` | 仅 `__ubuf__ T*` 或 PoD |

**专属规则**：
- VF 函数参数仅 `__ubuf__ T*` 或 PoD（禁 pass-by-reference，同约束 9）；修饰符必须 `inline` + 返回 `void`。
- 单个 VF 内 `RegTensor` 声明不超过 32 个；`MaskReg` 声明不超过 8 个。
- 所有传入 `VF_CALL`/`asc_vf_call` 的 `LocalTensor` 须经 `GetPhyAddr()` 转为 `__ubuf__*`。
- UB Data Cache 预留：SIMD+SIMT 混合场景编译器预留 8KB，SIMT DCache 至少 32KB（UB 静态+动态内存 ≤ UB 总大小 − 8KB − 32KB）。

### Step 5：TilingData 归一化校验

**铁律**：TilingData 使用 plain C struct，不使用 CANN 宏。

校验所有 tiling_data 文件：
- 不含 `TILING_DATA_FIELD_DEF` / `BEGIN_TILING_DATA_DEF` / `END_TILING_DATA_DEF`
- struct 可被 `sizeof()` 正确计算
- 违规 → 自动修正为 plain C struct
- kernel 侧与 host 侧的 tiling_data 内容一致（不一致 → 以 host 侧为准覆盖）

### Step 6：编码自检

| 检查项 | 方法 | 失败处理 |
|--------|------|----------|
| 32 字节对齐 | 检查 DataCopy/Vector 操作的 offset 表达式 | warning |
| TilingData 一致性 | host 和 kernel 两侧 tiling_data 内容一致 | 自动修正 |
| 字段↔源逐一对应（②） | 生成的 TilingData struct 字段（名/类型/数量）须与 `tiling_strategy`/`tiling_results` 源字段清单逐一对应；权威源是 State 源字段，非派生文档 | status=fail |
| API 签名合规 | 参数数量/类型与知识库匹配 | warning |
| 文件完整性 | kernel_architecture 声明的每个 section 目录存在且至少有一个非空源文件 | status=fail |
| ACLNN 符号一致性 | 声明 ↔ 实现函数名一致（若产出 api_code） | 自动修正 |
| TilingKey 机制一致性（host↔kernel） | host 用 ASCENDC_TPL_SEL_PARAM 且 kernel 入口为 template 模板函数 + if constexpr 编译期路由；两侧同走 ASCENDC_TPL（任一侧缺正向特征即 fail） | status=fail |
| 【维3】禁硬编码硬件参数 | `op_host/*_tiling.cpp`、`op_kernel/*` 含裸 CORE_NUM/BLOCK_NUM/UB_SIZE/对齐常数（`=32`/`=262144`/`=14336` 等）；过滤 `sizeof`/`GetSizeByDataType`/`GetBlockNum`/`GetUBSize` 等运行时查询与 TilingData 字段 | warning，改运行时查询 GetBlockNum/GetUBSize 或 sizeof(T)/GetSizeByDataType(dtype)/TilingData 字段 |
| 【维3b】block_dim 运行时派生 | `op_host/*_tiling.cpp` 中 `TilingData.blockDim`/`blockNum` 的赋值**源头**是字面核数（来自 `hw_params` 的 `ai_core_cnt`/`cube_core_cnt`/`vector_core_cnt` 或裸数字），而非 `GetBlockNum()`/`GetCoreNumAiv()` 运行时派生。注：维3「过滤 TilingData 字段」不豁免本条——经 TilingData 字段传递但源头是字面核数仍违规 | warning，改 host tiling 用 `GetBlockNum()`/`GetCoreNumAiv()` 派生 block_dim（代际内 SKU 跨档 A5:8/28/32/36，静态核数换 SKU 必失效） |
| 【维4】AR-1 主循环禁 GetValue/SetValue 数据搬送（默认禁 + 逐点授权落盘，框架契约校验） | 主循环内 GetValue/SetValue 做 GM↔scalar 搬送。**默认禁止**；仅限①设计声明点（tiling_strategy.scalar_access_points[]）②TilingData 元数据读取 ③纯索引计算。凡出现 SetValue/GetValue **逐点全量登记** `decision_log.json.scalar_access_points[]`（location / usage[data-move/metadata/index] / reason / reference）；data-move 类**二选一授权**：reference 命中设计声明 name，或 deviation_evidence 三键齐备（failure_signature / repro_or_log 真实存在路径 / why_no_vector_equivalent）。命中「主循环数据搬送有 DataCopy/DataCopyPad 等价物 / 排序有 Sort API（fp16/fp32）+ CompareSwap bitonic（int/bf16）/ 归并有向量化实现」→ 理由不成立，须改向量化；不得以「正确性优先」「单核简化」等主观理由豁免（历史反例：把可修索引 bug 误诊为硬件一致性）。判据凭结构信号，不认算子名。**框架在出口对清单做机械校验**（逐点授权 + 源码-清单簿记一致性），违约定向打回 | warning + 授权必须落盘且合法；清单空而源码有标量访问 / reference 未命中且无完整 deviation_evidence / repro_or_log 不存在 → status=fail「scalar_access_points 未授权：{具体}」 |
| 【维4】AR-2 嵌套循环 GM 单点访问 | 嵌套 for 内对 GM GetValue/SetValue 单点（非 LocalTensor 批量） | warning |
| 【维4】AR-3 非对齐用 DataCopyPad | tail/pad/copyLen%ALIGN≠0 场景用单点 GetValue/SetValue 而非 DataCopyPad | warning |
| 【维4】AR-4 禁 UB 侧标量 cast 漏斗 | 元素循环内对 LocalTensor `GetValue→标量 ToFloat/ToBfloat16/ScalarCast→SetValue` 做 tensor 级 dtype 转换（AR-1/2 覆盖 GM↔scalar；此条覆盖 UB 侧） | warning，改 vector `Cast()` 批量转换 |
| 【维5】OpDef dtype ⊇ IO spec | `{op}_def.cpp` 的 `DataType::X` 枚举 vs `design_spec` IO spec dtype 矩阵逐一比对（权威源：State 源字段，同②字段↔源纪律） | 缺失 → status=fail「OpDef 缺 dtype：{X}，详设有定义」 |
| 【维5】OpDef param_type 一致 | `{op}_def.cpp` 每个 `.ParamType(X)` ∈ `design_spec` 对应项 `param_type`（REQUIRED/OPTIONAL/DYNAMIC）；OPTIONAL 输入的 aclnn/plugin 侧可选入参对齐 | 不一致 → status=fail「OpDef param_type 与 design_spec 不一致：{name}」 |
| 【维5b】OpDef 输出 param_type 禁 OPTIONAL（argsize 膨胀隐患） | **codegen 产权**：`{op}_def.cpp` 的**输出** `.ParamType(OPTIONAL)` 会令 AscendC 编译器在 kernel 参数区多发射 8 字节槽（presence 标志，`__CCE_KernelArgSize` 48 vs host 40）→ kernel 入口读垃圾 tiling 指针 → **507057 向量核异常**（历史实证：可选输出算子声明 OPTIONAL → 507057，改 REQUIRED 后迁移）。**规则**：OpDef 输出一律 `ParamType(REQUIRED)`（kernel 恒收全输出句柄，plugin 侧恒提供合法句柄）；「可选性」只表达在 torch schema `-> Tensor[]` + plugin 返回层（条件 push，见维11），**不表达在 OpDef param_type**（**禁止修改 golden/参考实现**——golden 是权威真值 §1.13，可选输出语义按 golden 在 plugin 返回层对齐，见维11）。判据凭结构信号（`{op}_def.cpp` 输出 `.ParamType(OPTIONAL)`），不认算子名 | 命中「输出 ParamType(OPTIONAL)」→ status=fail「OpDef 输出声明 OPTIONAL → __CCE_KernelArgSize 膨胀（48 vs 40）→ 507057，改 REQUIRED；可选性归 schema `Tensor[]` + plugin 条件 push（维11）」，就地改 REQUIRED |
| 【维5】OpDef canonical 形态 | `{op}_def.cpp` 含 `register/op_def_registry.h`/builder 链/`OpAICoreConfig`+真 soc 字面量/`OP_ADD`；**禁现** `desc.Mut*`/`MutatableInputDesc`/`OutputAttrMapping`/`ScalarValueType`/`<SOC_VERSION` 占位（虚构 API） | 命中虚构 token → status=fail「OpDef 用了不存在的 API：{token}，按《OpDef渲染规格映射.md》重写」 |
| 【维5】Tiling dtype 分支 ⊆ OpDef | `{op}_tiling.cpp` 的 `DT_X` 运行时分支 ∈ OpDef 枚举 | OpDef 缺 → status=fail「OpDef/Tiling dtype 不一致」 |
| 【维5】Plugin cast 兜底检测 | op_plugin 对非 OpDef dtype 做 cast（过滤注释，查实际 torch API） | warning，记回报 `plugin_cast_dtypes[]` |
| 【维5】Plugin 交付契约 | `mutation_mode==in_place` 算子：plugin `m.def` 返回所有 output（非 `-> ()`）、用 `.clone()` 非 `.contiguous()` 作 output、无 `copy_` 写回调用方原张量本体 | status=fail「plugin 违背 out-of-place 返回交付契约（mutation_mode=in_place）」 |
| 【维6】InferShape 注册（结构信号驱动） | **判据（不认算子名，凭结构）**：满足任一即"需要 InferShape"——① output 张量 shape/来源 ≠ 任一 input（新造维度/规约/重排/拼接，非 elementwise 逐元素同形）；② `op_host/*_tiling.cpp` 读 `GetStorageShape()`/`GetOriginShape()`/`GetDimNum()` 派生 tiling。需要时 `op_host/` 必须有 InferShape 实现且 `{op}_def.cpp` 经 `.SetInferShape(...)` 注册。缺失后果：入图时 tiling 拿到**坍缩的 1-D storage shape** → tiling 计算错 → 运行期 EZ1008/shape 不匹配（编译期不报，最贵粒度才暴露）。 | 需要却缺 → status=fail「输出与输入不同形/tiling 读 storage shape，须注册 InferShape，否则 tiling 拿坍缩 1-D shape → EZ1008」；纯 elementwise 同形算子不需要，边界拿不准 → warning（宁提示不误杀，交编译兜底） |
| 【维7】Kernel API 字面量正确性（codegen 本职自检） | **本项是 codegen 产权，非上游设计门职责**（anchor 只判硬件能力/范式抽象层，不查 C++ API 字面量）：逐条核对生成的 kernel/host C++ 里**具体 AscendC API 的枚举名 / 调用形式 / 参数**是否与知识库签名一致——典型：`Cast(dst, src, RoundMode::X, count)` 的 `RoundMode` 枚举必须 ∈ 真实枚举集 `{CAST_NONE,CAST_RINT,CAST_FLOOR,CAST_CEIL,CAST_ROUND,CAST_TRUNC,CAST_ODD,CAST_HYBRID}`（**禁造** `CAST_FP16_TO_FP32` 这类"按 dtype 方向"的虚构枚举——dtype 方向由模板参数 `Cast<Tdst,Tsrc>` 决定，非 RoundMode）；标量写 GM 用 `Duplicate`+`DataCopy` 通路而非虚构的 `SetScalarValue`。查知识库 `ascendc-dev-knowledge`（API 签名）核对，**不靠记忆**。 | 命中虚构/错拼 API 字面量 → 就地修正为知识库确认的正确形式（codegen 有编译器 in-session 兜底，此处先静态自检提前拦）；拿不准的 API → 查知识库确认后再落，查不到停下报告 |
| 【维7b】strided DataCopyPad 行距一致性 + 批量优先（codegen 本职自检） | **codegen 产权**：kernel 内凡 strided `DataCopyPad`（`blockCount>1` 或含 `srcStride`/`dstStride`）且存在尾块/非 32B 对齐行，核对「**搬运行距 == 寻址行距**」——strided CopyIn 尾块（逐行 `blockCount=1` 写 `tile[j*rowStrideElems_]`）与 CopyOut 尾块须**共用同一 `rowStrideElems_`**（方案一，默认）或各自对称寻址（方案二）；禁止搬运按各自对齐长度（`dstStride=0` 自动 32B 补位）而寻址按主块固定步长的混搭 → 尾块错位/越界。**批量优先（同为本维产权）**：行距均匀的行块（主块、**行分块尾块**、整 tile）必须**单条批量**（`blockCount=rows`，行尾块传 `blockCount=curRows`——行分块尾块 GM 布局与主块同构、仅数值变小，仍恒单条指令；GM 行连续 `srcStride=0` 字节、UB `dstStride=(行距−AlignUp32(块宽))/32` dataBlock，`rightPadding` Normal 模式逐块生效等价逐行，`blockCount≤4095`）；逐行 `for`+`blockCount=1` 形态**仅限列分块尾块**（同一行切多个列块、块间 GM 不连续且块宽互异），禁止推广到行分块尾块/整 tile 搬运。判据（结构信号，不认算子名）：grep `DataCopyPad` → ① 含 `dstStride` 或 `blockCount>1` 的 strided 搬运核对行距对称一致；② `for` 循环包 `blockCount=1` 的 DataCopyPad（非列分块尾块场景）→ 命中「行块逐行搬运」→ fail。规则见 `ascendc-op-design-shared/references/datacopy-stride-consistency.md`。 | 命中「搬运与寻址行距不一致 / CopyIn/CopyOut 不对称」→ status=fail「strided DataCopyPad 行距与 kernel 寻址不一致（尾块错位/越界风险），按 datacopy-stride-consistency.md 修正」；命中「行块逐行搬运（非列分块尾块）」→ status=fail「行距均匀行块须单条批量 DataCopyPad（blockCount=rows/行尾块 curRows），逐行 MTE 微事务是性能红线，按 datacopy-stride-consistency.md §3 修正」 |
| 【A5】VF 函数签名合规 | `__simd_vf__`/`__simt_vf__` 必须 `inline void`，参数仅 `__ubuf__ T*`/PoD（仅 A5 Regbase） | status=fail |
| 【A5】RegTensor 数量合规 | 单个 VF 内 `RegTensor` 声明 ≤32（仅 A5 Regbase） | status=fail |
| 【A5】MaskReg 数量合规 | 单个 VF 内 `MaskReg` 声明 ≤8（仅 A5 Regbase） | status=fail |
| 【A5】Membase API 入侵 | VF 函数体内仅用 MicroAPI 命名空间（禁 A3 DataCopy / A3 高阶 API）；Cube 部分搬运不限（仅 A5 Regbase） | status=fail |
| 【A5】SIMD/SIMT 隔离 | `__simd_vf__` 不调 `__simt_callee__`，`__simt_vf__` 不调 `__simd_callee__`（仅 A5 Regbase） | status=fail |
| 【A5】GetPhyAddr 地址转换完整 | 传入 `VF_CALL`/`asc_vf_call` 的 `LocalTensor` 均经 `GetPhyAddr` 转 `__ubuf__*`（仅 A5 Regbase） | status=fail |
| 【维8】Manifest 签名契约（codegen 本职自检） | **codegen 产权**：产出 `codegen_manifest.json` 前自检——(a) **必填 `required_keys` 仅 `op_name`/`callable_target`**（P1 收敛 2026-08-19：`inputs`/`outputs`/`attrs` 降为**可选**——下游只消费 `callable_target`+`op_name`，harness 绑 golden 用 op_spec，IO 属三重冗余，**不要求回声，缺了也不触发重试**）；若你**选择**声明 `inputs`/`outputs`/`attrs`，则其 name 必须与你的 plugin `m.def` **逐字一致**（框架检测到「声明了却不一致」才 warn）。且**不含调试笔记字段**（`compile_status`/`runtime_status`/`suspected_root_causes`/`next_steps`/`files`/`key_apis_used`/`template_routes` 等——它们归 `decision_log.json`）；(b) `callable_target.symbol` 的 `<namespace>`/`<op>` 与你生成的 `TORCH_LIBRARY_FRAGMENT(<namespace>, m)+m.def("<op>...")` **逐字一致**。对齐 regbase skill 已有规则（`ascendc-op-dev-coding-regbase/SKILL.md:350`）。 | 缺 `op_name`/`callable_target` / 含调试笔记 / 声明了 IO 却与 m.def 不一致 / symbol 与注册不一致 → status=fail「manifest 非契约：{具体}」，就地重写 manifest 为纯契约字段再返回（框架兜底：缺 `callable_target.symbol` 从 plugin 注册派生；IO 不再触发定向重试） |
| 【维9】GM workspace 契约（codegen 本职自检） | **codegen 产权**：`op_host/*_tiling.cpp` 中 `GetWorkspaceSizes(...)` 的赋值（`ws[0]`/`currentWorkspace[0]`）**必须含 `GetLibApiWorkSpaceSize()`**——只设用户量、或写死常量（`=0`/`=16*1024*1024` 等）即违规。判据（结构信号，不认算子名）：grep `GetWorkspaceSizes` → 其赋值表达式中须出现 `GetLibApiWorkSpaceSize`（或经 `auto ascendcPlatform = ...PlatformAscendC(...)` + 变量传递，终值含 sysWorkspaceSize）。 | 命中「只用户量/写死常量」→ status=fail「ws[0] 漏 sysWorkspaceSize → 工程模式框架偏移系统区致 GM 越界（507015，历史实证），按 Step4② GM workspace 设置改 `userWs + GetLibApiWorkSpaceSize()`」 |
| 【维10】plugin 脚手架边界（codegen 本职自检） | **codegen 产权**：op_plugin 是脚手架层，只做「接口适配 + 调 aclnn kernel」。自检 plugin 文件——**命中任一即违规**：①调用 golden 同源参考实现替代 kernel（`at::_unique2`/`torch::unique`/`torch::sort`/`at::unique` 等 torch CPU 算子）②host 实现算子逻辑（重算算子结果如 `max(inverse)+1` 归约定 numUnique、变长输出 slice 决策、去重/排序逻辑）③含 CPU 兜底路径（`.cpu()` 往返 + torch 算子 + `.npu()` 绕过 aclnn）。**允许**：Tensor 转换（contiguous/reshape 展平输入）、调 aclnn kernel、dtype/device 检查、输出封装（含按 torch 语义还原 shape，如 inverse reshape 回 x.sizes()——接口适配 ≠ 算子逻辑）。**变长输出判界（与维12 调和）**：plugin 把输出 **narrow/slice 到 kernel 写回的真实长度** 属接口适配（合法，见维12 读回定型）；违禁的是 plugin **自行决定/重算**长度（如 `max(inverse)+1` 归约、host 去重排序）。判据凭结构信号（文件内容模式），不认算子名、不耦合具体 plugin | 命中①/②/③ → status=fail「plugin 越界：{具体}」，就地改回脚手架形态（只保留接口适配 + aclnn kernel 调用）；算子逻辑回归 kernel/tiling 实现（如 numUnique 应由 kernel 写回 workspace，由 host tiling 决定 y 长度）。**框架机械门（③ 的确定性兜底）**：`op_plugin/*.cpp` 出现 `.cpu()`/`kCPU`（注释除外）即 `plugin_host_offload` 硬门 + 定向 retry codegen——不靠 LLM 自觉，写进代码就拦 |
| 【维11】条件输出契约（由参数控制的可选输出） | **codegen 产权**：当算子有「可选输出——由某输入参数控制是否返回，golden 语义下参数为假时不返回该输出」时，**raw op（plugin）schema 用 `-> Tensor[]`，C++ 实现返回 `std::vector<Tensor>`，按控制参数条件 push**（参数为假 → 只 push 主输出；为真 → push 全输出），返回数量随参数变、与 golden 一致。**禁止**「固定元组 schema + 空占位张量」冒充省略（固定元组在 Python 层恒返回定长，与 golden 条件单/多返回数量错位 = 契约 bug，历史实证：golden 单张量 vs 绑定层二元组 → 评测层输出数量不匹配）。同时**plugin 层不得实现算子内部逻辑**（结果长度计算/去重/排序等归 kernel/host tiling，不在 plugin 层重算）。判据凭结构信号（proto OPTIONAL 输出 + 控制参数），不认算子名、不认具体仓 | 命中「固定元组 + 空占位冒充省略 / plugin 实现算子内部逻辑 / schema 未用 `-> Tensor[]`」→ status=fail「条件输出契约不符：{具体}」，改 `-> Tensor[]` + vector 条件 push 对齐 golden 语义 |
| 【维12】动态长度输出定型（运行时定长输出的 workspace readback） | **codegen 产权**：当算子有「输出长度运行时才确定（数据相关，如去重/排序/检索类）」时，必须有可靠的「kernel 写有效长度 → host 读回 → 定型输出」回路，且 **plugin 读 workspace 的偏移必须与 kernel 写入位置一致**——kernel 入口 `workspace` 参数=用户 workspace 指针（知识库）；plugin 若持完整总缓冲（含系统区，`aclnn{Op}GetWorkspaceSize` 返回总大小 = 用户 + `GetLibApiWorkSpaceSize()`），readback 偏移必须在用户区偏移基础上加系统区偏移，否则读错位 → 0/垃圾 → **输出恒空而 golden 非空**（框架 comparator 对该形态置 `shape_mismatch`+`empty_output_suspect`，scope_guard 判归 plugin/harness 层）。判据凭结构信号（proto 输出长度运行时定 + plugin 出现 workspace readback），不认算子名 | 命中「readback 偏移与 kernel 写入不一致 / 输出恒空无信号 / 无有效长度回传回路」→ status=fail「动态长度输出定型缺陷：{具体}」，按上文「动态长度输出定型」修正（偏移对齐 + 读回值合理性核对 + 空输出必须留信号） |
| 【维13】host tiling block_dim≥1 守卫（codegen 本职自检） | **codegen 产权**：`op_host/*_tiling.cpp` 产出的 `TilingData.blockDim`/`blockNum` 计算**必须保证 ≥1**——核数分配/工作量分片后若归一得 0（某些 shape 组合下 `totalRows`/工作量 = 0）须 `max(1, …)` 兜底或显式 halt 报错，**禁止把 0 写进 TilingData**（kernel 收 `block_dim=0` → `Invalid block_dim` 崩溃，历史实证：索引取数算子多维/非对齐 shape 组合）。判据（结构信号，不认算子名）：grep host tiling 中 `blockDim`/`blockNum` 赋值 → 核对存在 `≥1` 守卫（`max(1,·)` 或显式 `if (0) halt`）；多模板共用时每个模板分支都须守卫 | 命中「无守卫 / 可能得 0 直接下发」→ status=fail「host tiling 产出 blockDim 可能为 0 → Invalid block_dim 崩溃，加 ≥1 守卫（max(1,·) 或显式 halt）」 |
| 【维14】间接寻址 source 行映射（codegen 本职自检） | **codegen 产权**：适用于**索引取数（间接寻址）**算子——kernel 存在「按输出行号 `outRow` 求 x 源行」的取数路径时。此时必须满足**二选一**：**① 非 dim 轴 shape 已约束相等**——host tiling 对 index 非 dim 轴 shape == x 非 dim 轴 shape 做显式校验/约束（assert 或 if 报错拒绝不等输入），设计域只覆盖相等情形，`srcRow = outRow` 合法；**② 行映射描述符**——host tiling 下发 `idxRowDims`/`xRowStrides` 等行映射描述符，kernel 按 index 网格行主序扁平化 + 混合基展开（`outRow` 只作 index 侧下标，x 源行由映射派生）。**仅当两者皆无**才违规：tiling 既不约束相等、也不下发映射，kernel 却 `srcRow = outRow` 直代——index 非 dim 轴收缩（shape < x 对应轴）时行号错位（历史实证：非 dim 轴 index.shape=127 vs x.shape=255 全错）。**不触发的情形**：kernel 用除法链/stride 链按坐标直接求源址（无 `outRow` 直代模式）；非索引取数算子。判据（结构信号，不认算子名）：grep 索引取数路径中 `srcRow`/源行计算 → 核对命中 ① 的相等校验或 ② 的映射描述符，二者缺一即 fail | 命中「`srcRow = outRow` 直代 且 无相等校验 且 无行映射描述符」→ status=fail「间接寻址行映射缺陷：tiling 未约束非 dim 轴相等也未下发行映射，index 轴收缩时输出行直代 x 源行错位；按 ② 下发 idxRowDims/xRowStrides 混合基映射，或按 ① 显式约束非 dim 轴 shape 相等」 |
| 【维15】嵌套列表属性直传（schema 原生支持） | **codegen 产权**：当算子属性（attr）的契约类型是**嵌套列表**（`list[list[int]]` 等任意深度）时，**直接按嵌套形态注册与实现，禁止压平**——plugin 的 `m.def` schema 用嵌套形（`int[][]`），C++ 参数 `std::vector<std::vector<int64_t>>`，OpDef 侧 `ListListInt`（深度>2 逐层套 `std::vector`）。torch.library 的 schema 注册**原生支持嵌套列表**（实测），嵌套值原样进出实现层；**禁止**把嵌套压平成扁平列表+自创配对约定（"长度必须为偶数、相邻两项为一对"类散文规则）——那会使 plugin 接口与用例/golden 的嵌套值形态脱钩（历史实证：契约压平 + 用例嵌套 → 属性校验在 smoke 期确定性拦截、整链返工）。边角：无张量参数的纯属性算子，实现注册需 CompositeExplicitAutograd fallback key。判据凭结构信号（契约类型为嵌套列表），不认算子名 | 命中「嵌套属性被压平为扁平+配对约定」→ status=fail「嵌套属性须直传：schema 用 `int[][]` 形态、C++ 用 `std::vector<std::vector<int64_t>>`、OpDef 用 `ListListInt`，删掉压平编码与配对校验逻辑，改为逐层向量直传」 |

### 条件输出 / 可选输出建模（维11）

**场景**：算子有「可选输出」——由某输入参数控制是否返回，golden 语义下该参数为假时不返回该输出（例：布尔参数 `return_opt` 控制可选输出 `out_opt`，`return_opt=false` 时 golden 仅返回主输出单张量，`true` 时返回 `(主输出, out_opt)`）。

**产出契约**（对齐 golden，禁止固定元组 + 空占位冒充省略）：

1. **内核 / 宿主层**：恒计算并产出全输出（内核 + host tiling 负责全部计算，包括结果长度、去重、排序等算子内部逻辑）。

2. **plugin 层（raw op）**：schema 用 `-> Tensor[]`，C++ 实现返回 `std::vector<Tensor>`，按控制参数**条件 push**，返回数量随参数变、与 golden 一致：
   ```cpp
   m.def("op(...) -> Tensor[]");
   std::vector<at::Tensor> op_npu(...) {
       std::vector<at::Tensor> r{main};
       if (return_opt) r.push_back(out_opt);
       return r;   // return_opt=false → [main]；true → [main, out_opt]
   }
   ```
   **禁止**「固定元组 schema `-> (Tensor, Tensor?)` + 空占位张量」冒充省略——固定元组在 Python 层恒返回定长（optional 缺席时对应位为 None），与 golden 的条件单/多返回**数量错位**（历史实证：golden 单张量 vs 绑定层二元组 → 评测层输出数量不匹配）。`-> Tensor[]` 是 raw op 返回数量随参数变的构造性前提。**plugin 层只做接口适配**（参数传递、条件 push、按 torch 语义还原形状），**不得实现算子内部逻辑**（结果长度计算/去重/排序归 kernel/host tiling，不在 plugin 层重算）。

   **对齐必须落在 raw op 返回结构本身（非裁剪 wrapper）**：评测层按 raw op（`torch.ops.<ns>.<op>`）调用（cann-bench `cann_matcher` 优先 `torch.ops` 而非 Python 模块 wrapper），「入口层裁剪 wrapper」在评测下不会被调用、是死代码——对齐 golden 只能靠 raw op 的返回结构（`-> Tensor[]` + 条件 push），构造性对齐而非依赖消费路径。precision_debug harness 经同一 raw op（`callable_target.symbol`）调用，按 proto 输出数右补 None 对齐（`_normalize_outputs` 对 `[main]`/`[main, out_opt]` 与 golden 的 `main`/`(main, out_opt)` 均右补到 proto 输出数后对齐）。

**自检**：生成后核对（a）条件 push 逻辑与 golden 的控制参数语义一致；（b）无「固定元组 + 空占位」冒充省略；（c）plugin 层无算子内部逻辑；（d）**可选输出算子 schema 用 `-> Tensor[]`**（非固定元组）；（e）**`m.def` 声明返回 ↔ C++ 实现返回类型 arity/形态一致**——可选输出算子 `-> Tensor[]` 对应 `std::vector<Tensor>`（条件 push，数量随参数变）；非可选输出的 `-> (A, B, ...)` 定长元组（N≥2）对应 `std::tuple<...>`（**禁止**用 `std::vector<Tensor>` 表达元组返回——vector 被 PyTorch 推断为 `Tensor[]` 1 个变长返回 → 与声明 N 个定长返回矛盾，checkSchema 注册时拒）；`-> Tensor` 单返回对应 `torch::Tensor`/`at::Tensor`。框架 codegen 契约门会在 deploy 前静态对质（高置信类）并在 smoke 时用运行期 checkSchema 信号兜底，命中 → 定向 retry 回 codegen 重修。命中违反 → 维11 fail。

### 动态长度输出定型（运行时定长输出，与维11 正交）

**场景**：输出张量的长度（元素数）**运行时才确定**（数据相关，如去重/排序/检索类算子的结果长度），编译期/InferShape 只能声明上界或未知维。此时必须有一条「kernel 写有效长度 → host 读回 → 定型输出」的可靠回路。

**两条硬不变式（生成后逐条核对）**：

1. **有效长度必须可靠回传 + 正确消费**：kernel 把真实长度写进 workspace（或经其它确定性机制），plugin/host 读回后把输出 narrow/slice 到精确长度。**禁止**「先按上界分配、永远不裁」或「读到 0/垃圾 → 输出恒空」静默通过——输出恒空而 golden 非空 = 定型缺陷的确定性特征（框架 comparator 会对该形态置 `shape_mismatch` + `empty_output_suspect` 信号，scope_guard 据此判归 plugin/harness 层）。
2. **plugin 读 workspace 的偏移必须与 kernel 写入偏移一致**：kernel 入口的 `workspace` 参数**就是用户 workspace 指针**（知识库「核函数内删除 Workspace 相关冗余操作」：传入的 workspace 已直接赋值为用户 workspace，系统区由框架预留并从总分配前端偏移）。而 `aclnn{Op}GetWorkspaceSize` 返回的是**总 workspace**（用户 + 系统，tiling 里 `ws[0] = userWs + GetLibApiWorkSpaceSize()`）。**若 plugin 持有的是完整总缓冲（含系统区），readback 偏移必须在用户区偏移基础上加 `GetLibApiWorkSpaceSize()`**——直接用用户区偏移读完整缓冲，会读错位（读到排序/中间数据区）→ 返回 0/垃圾 → 输出恒空（历史实证：去重算子 readback 读错位 → 输出 Size([0]) vs golden 非空，一路静默到 precision 对比才暴露）。

**推荐做法（避免 plugin 端重新推导偏移的脆弱性）**：
- 优先让 host/plugin **不依赖手工复算 workspace 布局**——若框架/上层能提供「有效长度」的确定性回传通道，用那套；必须用 workspace readback 时，把「用户区偏移 + 系统区偏移」的计算收敛到一处、并**用实测核对**（读回的值必须是合理长度，而非 0/超大垃圾）。
- 生成后自检：动态输出算子的 plugin 里若出现 workspace readback，逐条核对（a）读回值合理性（非恒 0/垃圾）；（b）偏移与 kernel 写入位置一致（含系统区偏移，若 plugin 持完整缓冲）；（c）输出空而 golden 非空时必须有明确报错/信号，不得静默。

**读回 API 的确定写法（合法/禁用的硬边界）**：
- **合法**：标量元数据回读用 `aclrtSynchronizeStream` + `aclrtMemcpy(D2H)`（`ACL_MEMCPY_DEVICE_TO_HOST`）读一块固定小字节（如 8B count）到 host 局部变量——这是 device→host 元数据回传的标准形式，不触发 host 往返红线。
  ```cpp
  // 读回有效长度：先同步（等 kernel 写完 count 槽），再 D2H 拷 8B 标量
  aclrtStream stream = c10_npu::getCurrentNPUStream().stream(false);
  TORCH_CHECK(aclrtSynchronizeStream(stream) == ACL_SUCCESS, "...: sync failed");
  int64_t count = 0;
  aclrtMemcpy(&count, sizeof(int64_t), /*device count 槽指针*/ptr, sizeof(int64_t),
              ACL_MEMCPY_DEVICE_TO_HOST);
  auto y = yUpper.narrow(0, 0, count).clone();   // 上界分配 → narrow 到真实长度
  ```
- **禁用**：`.to(kCPU)` / `.cpu()` / `.to(torch::kCPU)` 整张搬回 host——被框架 `plugin_host_offload` 机械门拦截（维10③）。即使「只读 count 也要搬回整个上界张量」仍是 host 往返，不是元数据回读的正解。
- 区别判据（结构信号，不认算子名）：读回**固定小字节标量**（count/长度等元数据）用 `aclrtMemcpy(D2H)` 合法；把**数据张量本体**搬 host 计算 = host 往返禁用。

### Step 7：输出

从 `kernel_architecture` 各 section 的 `directory` 统计已落盘的源文件（每个 section 目录下的非空文件），
写入 `decision_log.json`（按 `schema/decision_log.json` 的格式），
并写入 `codegen_manifest.json`——**算子签名契约**（格式/约束见上方产物清单第 3 项 + `schema/codegen_manifest.json`：只含契约字段 `op_name`/`inputs`/`outputs`/`callable_target`，调试/运行时笔记归 `decision_log.json`；`callable_target.symbol` 须与你 `TORCH_LIBRARY_FRAGMENT` 注册一致）。

**decision_log 强制补充项（维4 AR-1 / 维10 落盘）**：
1. kernel 中凡出现 GetValue/SetValue **逐使用点全量登记**到 `decision_log.json.scalar_access_points[]`（location / usage / reason / reference），usage 分三类：`data-move`（数据搬送，**必须授权**）/ `metadata`（TilingData 元数据读取，免 reference）/ `index`（纯索引计算，免 reference）——三类都要登记，框架按清单与源码做簿记一致性检查（清单空而源码有标量访问会被定向打回）。**data-move 类二选一授权**：① `reference` 命中设计产物 `tiling_strategy.scalar_access_points[].name`（设计声明的标量点）；② `deviation_evidence` 三键齐备（`failure_signature` / `repro_or_log` 指向真实存在的产物路径，框架校验存在性 / `why_no_vector_equivalent` 结构论证）。仅写「正确性优先/单核简化」类主观理由视为缺失，返回重写。
2. plugin 脚手架边界自检结论（维10 命中/修正记录）写入 `decision_log.json.key_decisions`（decision="plugin 脚手架边界自检"，reason 注明越界项与修正）。

**返回摘要**：
```
status=pass|fail
files_written=<各子目录文件数>
warnings=<自检 warning 数>
summary=代码生成完成，编程模型=<programming_model>
```

---

## 精度修复模式

当调用方注入 `task_mode=precision_fix` + `error_info`（失败用例 shape/dtype/误差）时：

1. 读取 `error_info`（失败用例的输入 shape、期望输出、实际输出、误差）
2. 读取现有代码（kernel + tiling + tiling_data）
3. 对照设计产物分析失败原因（常见：Tiling 边界、dtype cast 精度、对齐偏移）
4. 修改对应代码文件（Edit，不重写所有文件；精度问题通常只涉及 kernel/tiling 层）
5. 若修改了 TilingData struct → 同步更新 kernel 侧副本
6. 执行 Step 5-6 自检
7. 返回 status + 修改文件列表 + 修改摘要

---

## 错误处理

| 错误场景 | 处理 |
|----------|------|
| meta.json 不存在 | status=fail，提示环境检查未执行 |
| 设计产物不可读 | status=fail，提示路径错误 |
| 设计产物缺关键字段 | status=fail，列出缺失字段 |
| 编程模型不识别 | status=fail，输出 meta.json 内容 |
| 文件完整性自检失败 | status=fail，列出缺失文件 |
| 自检 warning | status=pass + warnings 计数 |
