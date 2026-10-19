# codegen skill A5 编码硬约束 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。
> 外部参考 `ascendskills/agents/ascendc-dev-s4-coding.md` §4.4a/4.5/4.6/4.7（只读，只取思路，不照搬实现）。
> 与上游复用（`../codegen-skill-upstream-reuse/`）正交：上游复用管「读什么源产物」，本工作管「A5 编码时什么能写/什么禁写」。

## 前置问题（P3）— 资源归属：DevKit 已有 A5 知识，缺口是「编码红线」不是「知识」

**查证结论**（grep DevKit `.claude/`）：

1. **DevKit 已有完整 A5/Regbase/VF 知识，且已被 codegen 链路加载**——`ascendc-dev-knowledge` skill（`shared` 插件，ascendc-coder agent 必载）内：
   - **VF 指令参考**（等价 Phase C `regbase-vf-test/references/vf-instructions/`）：`api_reference_docs/SIMD_API/基础API/Reg矢量计算/` —— Cast/Interleave/Move/Reg数据搬运(连续对齐搬入·搬出/连续非对齐搬入·搬出)/Reduce/Gather/类型转换/数据重排 等全量 VF 指令签名与参数。
   - **Regbase 编程模型与约束**（等价 Phase C `ascend_regbase_programing_guide.md` + `ascend950_hardware_and_pipeline_control.md`）：`910D_knowledge_extra/` —— RegTensor.md / MaskReg.md / AddrReg.md / GetPhyAddr.md / asc_vf_call.md / SIMD-BuiltIn关键字和API.md / SIMD与SIMT混合编程.md / AI-Core-SIMD编程.md / AIC和AIV独立运行机制.md / VF循环优化.md / VF融合优化.md。
   - 当前 SKILL.md Step3 已有「A5 场景查 910D_knowledge_extra」一句——**这是已建立、可工作的引用**。
2. **`evolution-knowledge`（`references/a5/` 也有 Regbase/VF 内容）未被 codegen agent 加载**——它在 `.claude/skills/` 下，不在 ascendc-coder 加载的三个插件（stage-codegen / codegen-coder-extra / shared）任一之内；`shared` 插件只含 ascend-hardware / ascendc-dev-knowledge / ascendc-op-code-analysis。且 ascendc-dev-knowledge SKILL.md 自述定位为「代码编写时的精确 API 查阅」（L2），evolution-knowledge 为「进化优化决策」——codegen 该用前者。
3. **缺口确认**：缺的不是 A5 知识（ascendc-dev-knowledge 已有），而是 **A5 编码时的可执行红线**——Phase C §4.5 九条强制约束 + §4.6 专属规则。当前 skill 对 A5 仅 Step4 路由表一句「VF 入口 + RegTensor + 910D 约束」，agent 不知道 Vector 执行域内什么禁写 → A5 kernel 极易编译失败。

## 决策 1 — A5 编码红线落 codegen skill，不落 ascendc-dev-knowledge

- **选项 A**：把九条红线 + 专属规则写进 `ascendc-dev-knowledge` 知识库（作为 A5 编程约束文档）。
- **选项 B**：把九条红线 + 专属规则内联进 codegen SKILL.md（编码时校验，同 Step6 自检性质）。
- **选 B**：
  1. **§2.7 职责边界**：红线是「核心计算红线 / 编码时针对性引导 / 跨算子跨仓通用」——正是 §2.7 判定该留在 skill 的核心内容（与 Step6 自检、TilingData 归一化铁律同性质）；知识库存 API 签名 / 编程模型文档（§1.5：算子知识在 resources/，不进 Python 代码——此处对称：API 文档在 ascendc-dev-knowledge，编码红线在 skill）。
  2. **§1.3 加载期优于运行期**：红线随 skill 投递（§4.3 slash）进 agent 会话即生效，无需 agent 运行时再去知识库 grep「约束在哪」——减少一次「找不到→grep CANN」的滑坡入口。
  3. **可诊断**：红线违例在 Step6 自检就地报（status=fail + 具体检查项），不推迟到 CANN 编译期才炸（Regbase 约束违反即编译报错，但报错信息晦涩、定位远）。
- **不选 A**：知识库是「按需查阅的文档库」，红线是「编码时强制校验」——职责不同；且知识库文档 agent 可能漏查（Step3 只在「进入编码前」查一次），红线随 skill 始终在场。

## 决策 2 — VF 指令参考复用 ascendc-dev-knowledge，不新建、不复制 ascendskills

- **选项 A**：在 codegen skill 目录下新建 `references/vf-instructions/`（复制 ascendskills `regbase-vf-test/references/`）。
- **选项 B**：复用 ascendc-dev-knowledge 已有的 `api_reference_docs/SIMD_API/基础API/Reg矢量计算/` + `910D_knowledge_extra/`。
- **选 B**：
  1. **§2.5 唯一通路**：DevKit 已有等价 VF 指令参考（SIMD_API/Reg矢量计算 即 VF 指令签名库），复制 ascendskills 即开第二份会漂移的知识源——违反「同一职责一条实现通路」。
  2. **§1.5 资源单源**：ascendc-dev-knowledge 是 DevKit 的 A5/VF 知识权威源（已加载、已索引于 api_reference_docs/INDEX.md）；codegen skill 只需**指向**它，不需持有副本。
  3. **§2.1 即插即用不受损**：skill 指向「同被加载的 ascendc-dev-knowledge」是仓内相对引用（agent 会话内两 skill 同在），不指向仓外路径；skill 取出至他仓时，ascendc-dev-knowledge 作为通用知识库同随（与当前 Step3 既有的「查 ascendc-dev-knowledge」引用同机制，非新增耦合）。
  4. **查证**：SIMD_API/Reg矢量计算 下 Reg数据搬运(连续对齐搬入/搬出/连续非对齐搬入/搬出) 即 Phase C vf-instructions 的 LoadAlign/StoreAlign 等价物；Cast/Interleave/Reduce/Gather 等指令签名齐备。
- **落法**：Step3 把「A5 场景查 910D_knowledge_extra」一句**精确化为两处指向**——VF 指令签名查 `SIMD_API/基础API/Reg矢量计算/`，Regbase 编程模型/约束查 `910D_knowledge_extra/`（列具体文档名：RegTensor/MaskReg/AddrReg/GetPhyAddr/asc_vf_call/SIMD-BuiltIn关键字和API/SIMD与SIMT混合编程）。

## 决策 3 — 不依赖 evolution-knowledge

- codegen agent 不加载 evolution-knowledge（查证见前置问题 2），故**不**在 codegen skill 里指向 `evolution-knowledge/references/a5/`——指向了 agent 也读不到，是断链引用。
- ascendc-dev-knowledge 已覆盖 A5 编码所需的全部（VF 指令 + Regbase 模型 + 约束），无需 evolution-knowledge 补充。
- evolution-knowledge 的 A5 内容是「进化优化决策」视角（策略选择/优化模式），与 codegen「编码校验」视角正交——属进化链路，不进 codegen。

## 决策 4 — 吸收边界：九条红线 + 专属规则 + A5 自检；不吸收 driver 机制

**吸收（编码校验性质，符合当前框架）**：
- §4.5 九条强制约束（Vector 执行域内：禁 A3 DataCopy / 禁 TILING_KEY_IS / 禁 LocalTensor 直接计算 / 禁 A3 内存对象 / 禁 A3 高阶 API / 禁 callee 交叉调用 / VF 必须 inline void / 禁 pass-by-reference；SIMD/SIMT 隔离）——落 Step4 A5 红线 subsection。
- §4.6 专属规则（VF 参数仅 `__ubuf__ T*`/PoD、修饰符 inline+void、RegTensor≤32、MaskReg≤8、GetPhyAddr 地址转换、UB DCache 预留 SIMD+SIMT 混合 8KB / SIMT DCache≥32KB）——落 Step4 红线 subsection + Step6 自检。
- §4.4a VF 指令预查询的**思路**（A5 编码前先查 VF 指令语义/组合模式/陷阱）——吸收为 Step3 A5 知识查阅指引（指向 ascendc-dev-knowledge SIMD_API），不吸收其「vf-instructions: 引用协议 + coding_index_kb_cache.md 跨组缓存」driver 机制。

**不吸收（full-pipeline driver 机制，§2.6 第三类耦合 / §2.5 开第二套 driver）**：
- §4.7 VF 函数集成（从 `$RECORD_DIR/vf_verified/kernel_test/{vf_func}_test/` 读已验证 VF 函数）——依赖 vf_verified 目录 + .VT.{M} 子步骤 + coding_index.md 检查点组，是 full-pipeline driver 产物；当前框架等价物 = staging 物化源产物（已含 tiling_results.kernel.pseudocode 实现蓝图）+ skill 投递 + Event Sourcing，照搬即开第二套 driver。
- RECORD_DIR / coding_index.md / dev_record.sh / progress.md / CTX_DRIFT / RETURN error_type 编码——同上游复用决策 5「不吸收」段，已是定论。

## 四把尺子自检

- **可维护**：A5 红线单源在 codegen SKILL.md（编码校验层），VF 知识单源在 ascendc-dev-knowledge（知识库层），两层职责清晰不重叠；新增 A5 约束只改 skill，无需同步两处。
- **可扩展**：未来 A5 新增约束（如新 VF 指令禁区）只需在 Step4 红线表加一行 + Step6 自检加一行；新 VF 指令签名 ascendc-dev-knowledge 自会收录，skill 指向不变。
- **可诊断**：红线违例在 Step6 自检就地报（具体检查项 + 文件定位），不推迟到 CANN 编译期晦涩报错；A5 知识查阅有明确两处指向，agent 不再「找不到→grep CANN」滑坡。
- **架构合理**：改动落在 skill 内容层（编码红线 + 知识查阅指引 + 自检），不引入 driver 编排、不新增资源文件、不复制外部知识库；与上游复用 ①②③（同 skill 的输入契约/锁定项/字段↔源）同层、不冲突。
