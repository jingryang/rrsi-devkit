# 可配置轴算子设计/编码缺口 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发：复盘 foreign run `20260721-032228-2e7f58`（swi_glu，cann-bench 评测三轴全 0）。

---

## P1 — 算子的计算/拆分轴为**运行时属性**（dim/axis）时，设计→编码通路只覆盖「轴=末维」，dim≠末维一律算错

### 现象（run 客观事实）

- run `20260721-032228-2e7f58` 生成 swi_glu（A5 / ascend950 / RegBase SIMT），cann-bench 评测：
  `kernel_eval exited 20`（退出码=失败用例数），`overall=0.00 compile=0.00 func=0.00 perf=0.00 pass_rate=0.00%`，20/20 用例全 fail。
- 评测用例 20 个，其中 **9 个 `dim≠-1`**（dim=0 五个、dim=1 三个、dim=2 一个）；多个为 3D/4D/5D。
- adapt 冒烟跑的正是 `dim=0` 用例（[8192,16384] fp16）：`max_diff=173.5625`、`mismatch_count=67108807/67108864`（≈99.99%）、`mare≈128287`——输出与 golden 量级/符号都不对，属**正确性错误**非精度抖动。
- kernel 能跑（无 crash）、对 `dim=-1` 的 2D 基础用例也 fail（说明另有独立缺陷，见 P2/P3）。

### 凭什么说是「dim 被丢」（传递链断点定位）

dim 的合法传递链应为：`OpAPI(aclnn) → OpDef 注册 attr → TilingFunc 读 attr 填 TilingData → TilingData struct → kernel`。本次 run 在 **host TilingFunc → kernel 的数据布局边界**断链：

- OpDef 侧：注册了 `dim` 属性 ✓。
- host InferShape：**正确**按 dim 折半对应输出轴（故用例未在 shape 校验阶段挂）。
- host TilingFunc（`GetShapeAttrsInfo`）：**正确**读 dim、规范化、取 `D=GetDim(dim)`、算 X/Y（"shape 展平到 X/Y/D 三轴"是**逻辑乘积展平**，非物理搬运）。
- **断点 1（TilingData 结构）**：struct 只有 `D`/`halfD`/`ubFactorY`…，**无 dim 字段、无"需 transpose"标志**——dim 无从传给 kernel。
- **断点 2（无物理重排）**：host 全程**无 transpose/moveaxis/reshape** 把 dim 轴变成连续末轴；REQ-03 写的「需 reshape/moveaxis」从未落地成任何步骤。
- **断点 3（kernel 写死末轴）**：kernel GM 寻址写死 `[Y, D]` 行主序、x0=列`[0,halfD)`/x1=列`[halfD,D)`——仅在 dim=末轴时正确；dim≠末轴时读错数据 → 正是 `dim=0` 用例 diff=173 的直接原因。

### 缺口所在层（非 codegen 单方责任）

- requirement / general-design **正确**提出需求：`dim` 可配置、默认 -1；REQ-03 明确「dim≠-1 需 reshape/moveaxis」。
- **详设（tiling 设计）只给出了 dim=末维情形**：Split 伪代码写死末维切片、tiling 策略把输入当 `[X,Y,D]` 且 D 即末轴、TilingData 无 dim/axis 字段。REQ-03 要求的 reshape/moveaxis 在详设**悬空**——既没设计 host transpose 步骤、也没设计 kernel 按参数化轴切分、也没给 TilingData 加 dim/axis 字段。
- codegen **忠实实现了这个只覆盖 dim=-1 的设计**：host 两处都正确读了 dim，但因设计未给定落地机制，无处把 dim 传进 kernel 的数据访问。

→ 一句话：**dim 不是 codegen 「丢」的，是在详设 tiling 阶段被悬空的**——设计只画了 dim=末维的通路，REQ-03 的 reshape 要求从未被设计成可实现的机制。

---

## P2 — 详设多核分发设计与 kernel 实现不一致（X/Y 双轴分解缺失）

- 详设 `inter_core_split` 要求 `block_dim = blockNumX × blockNumY`、`xBlockIdx = blockIdx / blockNumY; yBlockIdx = blockIdx % blockNumY`，D（dim）维不参与多核切分。
- 生成的 kernel `Process()` **未做 X/Y 分解**，把 blockIdx 当一维 Y 索引：`yBlockOffset = blockIdx * (totalY / blockNumX)`；当 `totalY < blockNumX` 时**所有核 offset=0** → 多核处理同样的行 → 越界。
- run 表现：16/20 用例 device error 507035 崩溃（非"精度错"而是 OOB/崩溃）；pipeline-sync-debug 识别到此 bug、尝试修反而触发 `VECTOR_CORE_EXCEPTION`，回退未解决。
- 这解释了「为何 0/20 通过」而非「至少 dim=-1 的几个过」。

## P3 — codegen 对 A5 RegBase SIMT 的 API 知识缺失，产出的 kernel 原始编译不过

- codegen 原始产出含 7+ 处 A5 API 签名错误（`DataCopyPad` 参数不匹配、`Reg::Cast` 的 `MaskMergeMode`/`RoundMode`/`RegLayout` 填 `UNKNOWN` 致 static assertion、`UpdateMask` 签名、前向声明不可见、include 路径 `ascendc/common/tiling_data.h` not found 等）。
- s5-compile 阶段 `status=FAILED`（重试用尽）；后由 precision-debug 链路的 pipeline-sync-debug agent 逐个手改修掉才让 kernel 能编能跑——即落盘 kernel 是 debug agent 缝合产物，非 codegen 原生。
- **归属**：A5 codegen 属他人责任域，本仓只诚实记录、不负责修复；疑似已在 `codegen-skill-a5-constraints/` 跟踪（该条 2026-07-11 已实施：Step3 SIMD/Regbase 知识指针 + Step4 九条 A5 红线 + Step6 A5 自检，纯 skill 文本、未动 codegen.py）。
- **诚实不确定性**：run 基于 2026-07-20 `5ea52869`（在 07-11 修复之后）仍编译不过，**但** run 的 codegen skill 是 dirty 本地改版（skill 指纹 `38273c49` 不在本仓提交历史），**无法确认 run 用的 codegen skill 里是否包含该修复**；且该修复的 heavy_llm 端到端验证一直未跑（§3.11）。故"现有修复够不够"目前**未知**，待 A5 codegen 责任人核实（两条路：静态审计 skill 对失败 API 的覆盖 / heavy_llm 端到端跑）。

## P4 — vf_test 质量门是假阳性：测的是干净参考实现，非部署 kernel

- run 中 vf_test（`regbase-vf-test`）10/10 pass、max_diff≈5.9e-8，但它测的是 codegen 另写的**独立干净 VF 参考实现**（`compute_swi_glu_vf_custom.cpp`，SingleOperatorLaunch 编译运行），**不是部署进 kernel 的那个有 bug 的 `ComputeSwiGluVFRegImpl`**。
- 后续 vf-debug-01/02 试图对部署 kernel 的 VF 做隔离测试，均中途停止（未跑出结果）；vf-debug-03 仅 prompt 未执行。
- 后果：vf_test「通过」未守护真实 kernel，给了假信心；与 P1/P2 叠加使 precision-debug 链路空转约 90 分钟未救回。

## P5 — docgen 文档模板混用 TilingData 编程范式（`// BEGIN_TILING_DATA_DEF` 标记）

- docgen skill 的文档模板在「TilingData 设计」节让详设输出 `// BEGIN_TILING_DATA_DEF … // END_TILING_DATA_DEF` 注释 + 裸 `struct`。
- `BEGIN/END_TILING_DATA_DEF` 是**传统 AICore** 的 TilingDef 宏注册 idiom；A5 RegBase 的正确机制是裸 `struct` + `REGISTER_TILING_DEFAULT` + `GET_TILING_DATA_WITH_STRUCT`。模板给 A5 设计套传统宏外衣（哪怕是注释），语义上指向错误注册范式。
- 本次 run codegen 把注释原样照抄、保留了 `//` 使其惰性、用了 struct——**未实际误用宏**（部署代码全程无真宏，编译错误也无关 TilingData 宏）。但这是**真实隐患**：codegen 是 LLM，同时被设计文档的注释宏标记 + 知识库的真宏范本双重暴露，靠模型自觉保留注释惰性很脆弱；且已误导人审以为「struct 与宏混用」。

---

## 版本与核验

### foreign run 对应的工程代码版本（执行时间 ≠ 版本时间）

- **执行时间（与版本无关）**：`built_at=2026-07-21T03:22:53Z`，`agent_backend=opencode`，model `deepseek-v4-pro`。批量跑今天也能跑去年的版本，故 `built_at` **不作版本判据**。
- PROVENANCE `git=null`（批量工作区 `…/AscendC-DevKit-BatchRun/workdir_02/AscendC-DevKit` 非 git 仓）。
- **版本定位靠内容指纹（跨全量 git 历史搜，不按执行时间圈窗口）**：
  - `agent_manifest_fingerprint=b0e03eed…` 在**全量历史**中精确命中提交 `5ea52869`（2026-07-20 22:43 +0800），该 agent 内容自此 commit 起至下一次 agent 改动前不变 → **DevKit 快照 agent 侧 = 基于 2026-07-20 `5ea52869`**。
  - `skill_manifest_fingerprint=38273c49…` 在**全量历史中零命中**——该 skill 内容**从未作为任何 commit 提交进本仓**。
- → 结论：run 用的是**基于 `5ea52869`（2026-07-20）+ 未提交的本地 skill 改动**的 dirty 快照。agent 侧可定位到 `5ea52869`；skill 侧因带本地改动（内容 `38273c49`）无法从本仓历史复现，无法干净 pin 到单一 commit。

### 当前最新代码（main `e62f441`，2026-07-22）核验：**P1 缺口仍然存在**

- 当前 `skill_fingerprint=335bdf68…`、`agent_fingerprint=0c166e5c…`，均与 run 不同（run 之后 skill/agent 有变更）。
- 静态核验（grep + schema 检查）：
  - 无任何设计/编码 skill 或 schema 建立「运行时可选轴」概念——schema 只有设计期静态的 `split_axis_priority`（如 `["N","C"]`，多核切分轴优先级），无 dim/axis 运行时参数字段；
  - `ascendc-op-design-template-division` SKILL 对 axis/dim/attr/transpose 零提及，不识别「轴是运行时属性」；
  - 概设模式 `A01_generic-elementwise` / `D01_data-move-reorder` 均为概设级、明确不含 TilingData/Kernel 细节，且不覆盖可配置轴；
  - 最近 15 个触及设计/codegen skill 的提交（R7/R8 清理、vf-design 移植、schema 拍平、claims 收口…）无一触碰 configurable-axis/dim。
- → **P1 是结构性缺口，run 版本与当前最新版本均存在**；run→now 的变更与之正交，未修复。
- P2/P3/P4/P5 未逐一在最新代码静态复核，待方案阶段一并确认是否仍存。
- **运行时确认（可选）**：用当前 main 对 swi_glu 重跑一遍可 100% 确认 P1，但属 heavy_llm（分钟级 + token 成本），须用户确认后方可跑（CLAUDE.md §3.11）。

---

## 状态

- P1：已定位根因 + 已核验当前最新代码仍存。**两笔 skill 修改均已实施并验证**：
  - **commit 1（设计层，加性，我们）**：general-design 识别轴参算子 + 可选 `axis_param_design` 字段（主路径仍 dim=末轴）+ schema 文档化、tiling-buffer-kernel 主伪代码边界、docgen 渲染轴参泛化小节。UT `test_design_axis_param.py` 4 项绿。
  - **commit 2（codegen，可独立撤下）**：`ascendc-op-dev-coding` 读 `axis_param_design` 发射 axis-aware（host TilingFunc 填轴描述符 + kernel strided DataCopyPad + VF 不变），gate 在该字段存在→commit 1 未合休眠。UT `test_codegen_axis_param_emission.py` 4 项绿。
  - design/codegen 契约回归（含 a5-constraints/upstream-reuse/selfcheck-dims/skill-delivery/output-paths/regbase-phases）全绿、零回归。
  - L3 `02-analysis.md`、L4 `03-impl-axis-aware-design.md`。**待办**：heavy_llm e2e（两笔合一起真跑 swi_glu，验 dim=0 用例 diff 173→pass）作 commit 2 合入证据——需用户 §3.11 确认（全流水线重跑，耗时长/token 高）；commit 2 合入由 codegen 责任人定。
- P3：**A5 codegen 属他人责任域，本仓只诚实记录、不修**；疑似已在 `codegen-skill-a5-constraints/` 跟踪且 2026-07-11 实施，但"现有修复够不够"未知（run skill dirty 无法确认是否含修复 + heavy_llm 未跑），待 A5 codegen 责任人核实。本仓优先级低。
- P4：**precision-debug 内容（vf_test 假阳性门）暂时只记录，不展开分析/修改**。
- P2/P5：已记录事实，待排期。（本仓修复范围；P2 归属待澄清——X/Y 分解是否落进 kernel 伪代码）
