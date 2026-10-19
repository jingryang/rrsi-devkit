# step-84 — codegen 收敛加速：全局化框架契约自检 + host-only 快编 + 参考算子隔离 — 方案分析（L3）

> 性质：**L3 方案分析**（选项 + 取舍 + 推荐，待用户拍板后冻结）。self-evolution 线，step 84。
> 上游 L1：`84-batch-205112-issues-summary.md` Q1（scatter 缺 InferShape + ASCENDC_TPL 试错）、Q10（moe_re_routing 带毒 + 编译层内耗）。
> 触发：用户主张「用全局化的、通用化的方案加速 codegen 的收敛」。与 `84-codegen-precision-boundary-analysis.md`（边界重划）**耦合**：本文加速"框架收敛"，边界文管"framework OK 后 runtime 崩下沉"——两文一起看避免决策打架。
> 纪律：§1.8——事实产权在 L1，本文只记根因（L3 产权）+ 选项决策；代码改动配方留 L4。§1.12——一切机制不得耦合具体算子名，判据基于客观结构信号。

---

## 0. 一句话

codegen 当前**唯一的框架契约执行者是编译器**——生成 C++ 到手后要先跑一整轮"build-all→install→真机 smoke"（deploy.py 全包编译，无 host-only 快编，无静态 C++ 契约门）才知道对不对，coder 只能靠"编译错误考古"逐级学契约（Q1 的 7 级阶梯、Q10 的 138 次命中）。加速方向：先**把脚手架参考从"cwd 隐式仓耦合浏览"解耦为"profile/CLI config 显式声明"**（机制 ⓪，用户点名 + 治 Q10 根 + §2.1；注意脚手架参考经 `reference_roots` 通路，与方案级 `reference_code` 是两回事），再把"编译器才拦得到"的**框架级确定性缺陷前移到 build 前的静态门 + host-only 快编**——四个已证缺口各补一个**通用**（结构信号驱动、非算子特判）机制：① 缺 InferShape 静态门；② ASCENDC_TPL 宏选择（DTYPE vs DATATYPE）静态门；③ 参考算子与 target-repo GLOB 的编译隔离（⓪ 的编译侧兜底）；④ host-only/分层快编探针，让廉价错误在秒级暴露而非整包 build。

---

## 1. 事实（L1 产权，本文只引用 + 补代码 map）

### 1.1 现象（Q1/Q10，L1 已录）
scatter 3600s 超时=7 级 distinct 编译错误阶梯（每级一整轮整包编译），两处自伤：(a) 6 路 `ASCENDC_TPL_DTYPE_DECL` vs `ASCENDC_TPL_DATATYPE_DECL` 宏震荡；(b) 缺 InferShape 注册 → host tiling 拿到坍缩 1-D storage shape（`key_cache must be 4D, got 1 dims` → EZ1008），末尾才诊断出。aggregate 138 次编译命中 + moe_re_routing 参考算子带毒经 CMake GLOB 污染整包 build。

### 1.2 代码 map（本文首次落入，L4 实施锚点；general-purpose agent 核实）
- **无脚手架模板下发**：coder 从零生成——`_build_codegen_prompt`（`codegen.py:868-1097`）只递设计 JSON + `ref_*` 参考算子源 + 规则；CMakeLists「非核心，自行参考目标仓」（`:998-1000`）、文件名「参考目标仓现有算子」（`:1022-1024`）、注册/命名空间「现场确定」（`:1001-1007`）。唯一结构契约=section 目录放置（`_expected_code_files` `:145-176`）。
- **缺 InferShape 无静态门（Q1b 核心）**：InferShape 仅作**条件** section（"若 kernel_architecture 声明"，SKILL.md:145）+ 散文质量注记（SKILL.md:194）+ regbase 清单标签 B1（无验证）。`src/` 非测试 grep `InferShape/GetStorageShape/GetDimNum` **只命中 prompt 字符串字面量**（codegen.py:433,993），零校验逻辑；Step 6 自检表（SKILL.md:257-282）**无 InferShape 行**。缺 InferShape 只在 NPU tiling build 才炸（EZ1008），无更早门。
- **ASCENDC_TPL 有引导 + 1 个自检，但宏名不 gated（Q1a 核心）**：`tilingkey-ascendc-tpl-unification`（commit d966c0a）已统一引导 + Step 6 "TilingKey 机制一致性(host↔kernel)" 门（SKILL.md:265，缺任一侧正特征则 fail）。**但该门只查"正特征存在"**（host 有 SEL_PARAM AND kernel 有 template+if constexpr），**不区分 `DTYPE_DECL` vs `DATATYPE_DECL`**——两宏在知识库合法共存（`算子工程编译.md:226-228`，语义不同：DATATYPE 取 `ASCENDC_TPL_INPUT(n)` 绑定、DTYPE 取具名 enum）。该 plan 明确把机械 grep 加固**延期为 "m2 follow-up 非必须"**（`tilingkey.../03-impl.md §后续`）——即 Q1a 是**已知延期缺口**，本批实证其代价。
- **参考算子无算子名硬编码（合 §1.12）但 GLOB 无隔离（Q10）**：参考算子经 `state.reference_code/reference_op_path`（codegen.py:785-787,925-927）上游注入，`src/` grep `moe_re_routing` 零命中。真代价=**CMake GLOB cache trap（P96）**：`deploy.py:621-629` clean_build 清 `clean_dirs`，target repo CMake `file(GLOB)` 无 `CONFIGURE_DEPENDS` 编译 `csrc/ops/` **全部**算子；`cannbench_adapt.py:119-127` 触发 clean rebuild 把新 op 进 `_C.abi3.so` → 任一带毒 sibling（moe_re_routing）挂掉整包 build。GLOB 在**外部 target repo 的 CMakeLists**，框架**无参考算子噪声隔离机制**。
- **静态门现状（两层，均结构/manifest 级）**：Skill Step 6 自检（agent 执行，多为 warning，SKILL.md:255-282）；框架 transition 门（`_transition_membase` codegen.py:1234-1348，确定性）：section 覆盖→`incomplete_output`、`callable_target` 存在性、`_warn_manifest_name_drift`（warn）、`_check_plugin_schema_consistency`（plugin m.def vs manifest，warn，抓 EZ1001 phantom-input）。**缺口：无一个门校验生成的 C++ 对框架契约**（无 InferShape 存在性、无 ASCENDC_TPL 宏正确性、无 tiling shape-dim 期望）——真契约执行=编译器，只在 build 到达。
- **编译粒度=整包，无 host-only 快编（Q1/Q10 放大器）**：prompt（codegen.py:1077-1095）指示写完所有代码+manifest 后跑 `ascendc-devkit redeploy` → `Deployer.deploy`（deploy.py:93-165）整条 build→install→smoke 一体；`_run_profile_chain`（:605-644）经 repo build stages（GLOB-all）。**无低于整包的粒度**——Q1 的 7 级错误、Q10 的 138 次命中**每次都一整轮（可能 clean、build-all）编译**。

---

## 2. 根因（L3 产权）

**codegen 把"框架契约"的执行完全外包给了编译器，且以最贵的粒度（整包 build-all + 真机 smoke）到达。** 三重结构问题：

1. **契约隐式、靠考古**：框架契约（InferShape 该不该有、ASCENDC_TPL 哪个宏、schema 参数名、tiling shape 维度）散在 prompt 散文 + 知识库 + 目标仓现例里，coder 靠"生成→编译→读 stderr→改"逐级发现。确定性可静态判的框架事实（缺 InferShape、宏选错）**没有前置门**，全推到编译器暴露（违反 §1.3 加载/早期校验优于运行期暴露）。
2. **暴露粒度最贵**：唯一反馈=整包 build-all + 真机 smoke（60s+ 且经 GLOB 编译所有 sibling）。host 侧就能判的错（tiling/InferShape/def 编译、schema）与 device 侧错共享同一昂贵回合，且被 sibling 噪声（Q10）拖累。
3. **已知缺口延期累积**：ASCENDC_TPL 宏加固（Q1a）被 tilingkey plan 明确延期 m2；InferShape 静态门从未有；GLOB 隔离从未有——三者本批同时爆，放大成 3600s 超时/138 次命中。

**∴ 根因 = 框架契约缺"生成后、build 前"的确定性静态门 + 缺廉价（host-only）反馈层**，迫使 coder 用编译器当契约文档、以最贵粒度试错。这是**可诊断性/早期校验的结构缺口**（§1.3、§2.9 产出当下自检到位），非 coder 能力问题。

---

## 3. 选项（四把尺子；每项独立、可分步落）

**总原则（§1.12）**：所有门基于**客观结构信号**（design_spec 张量维度、tiling_strategy 模板参数、生成 C++ 的 AST/正则特征），**不认算子身份**、无白名单/特判表。删任一算子名不改代码路径。

### 机制 ① 缺 InferShape——**改为 codegen skill 自检项（用户订正：不做 Python 静态门）**
- **用户订正**：缺 InferShape 注册**是算子框架正确性问题**，正是 codegen 该自检的本职（§2.9 自检闭环优先于下游门 + 构造性保证优先于检查门）；且算子知识**归 skill/resources 不进 Python**（§1.5）。做成 Python 静态门反而是"下游 discover-only 门"，§2.9 明确不鼓励。**改定：机制① 从"Python transition 静态门"改为"codegen 编码 skill 的自检 checklist 项"。**
- **落法**：在编码 skill（`ascendc-op-dev-coding` / `ascendc-op-dev-coding-regbase`）的 Step 6 自检表（现无 InferShape 行）**加一条 checklist**：「若 output 张量维度/来源 ≠ input，或 host tiling 读 `GetStorageShape`/`GetDimNum` → **必须确认 InferShape 已注册**，否则 tiling 拿到坍缩的 1-D storage shape → EZ1008」。判据（结构信号）：output 维度/来源与 input 不同 OR tiling 读 storage shape。构造性自检，coder 产出当下即闭合，不外推给下游门。
- **四把尺子**：可诊断——缺 InferShape 在编码自检当下就报（带"多维张量需 InferShape 传播 storage shape"信号），不拖到 EZ1008；可扩展——任何多维张量新算子自动纳入 checklist，无算子特判（结构信号驱动）；架构合理——落**编码 skill 本阶段自检**（§2.9 本职），非下游 Python 门越界；可维护——判据是张量维度这一结构事实，且算子知识留在 skill（§1.5）。**边界情形**（纯 elementwise/shape 不变算子不需要）宁可 skill 提示 warn、让编译兜底，也不误判。
- **是否重复 tilingkey plan**：否——tilingkey 管 TilingKey 机制，InferShape 是独立契约维度。

### 机制 ② ASCENDC_TPL 宏选择（治 Q1a，补 tilingkey m2 延期缺口）——✅ 已实施为 skill 引导+warn（V3 降级）
- **V3 实证**：`ascendc-op-tiling-split/schema/tiling_split.json` **未声明**每参数来源（dtype 派生 vs enum 派生）字段——故**不能**做确定性静态门（无权威结构字段可交叉校验），按原 L3 风险条款**降级为 skill 引导层强化 + warn**（非确定性 fail）。
- **已实施（skill 引导，SKILL.md `ascendc-op-dev-coding` TilingKey 段）**：补两宏选择判据，**凭参数来源结构信号非算子名**——① `ASCENDC_TPL_DATATYPE_DECL`=原生 DataType，参数由某 IO 张量 dtype 派生（`ASCENDC_TPL_INPUT(x)`/`OUTPUT(x)` 绑定或列 `C_DT_*`），判据="参数语义=第 N 个 IO 的数据类型"；② `ASCENDC_TPL_DTYPE_DECL`=算子私有自定义枚举（与任何 IO dtype 无绑定）。**加维5b 自检（warn）**：核对每个 dtype 维度参数声明宏是否与来源匹配（绑 IO/原生 却用 DTYPE_DECL，或私有 enum 却用 DATATYPE_DECL → warn），设计产物未声明来源时从 kernel 签名+OpDef IO dtype 矩阵推断、拿不准 warn 让编译兜底。UT `test_codegen_selfcheck_dims.py::{test_tilingkey_datatype_vs_dtype_decl_guidance, test_macro_choice_no_operator_name_coupling}`。
- **四把尺子**：可扩展——结构信号驱动（IO 绑定 vs 私有枚举）零算子特判；可诊断——宏选错在编码自检当下 warn（带"参数来源是 IO dtype 派生，应改 DATATYPE_DECL"信号），缓解 6 路震荡；架构合理——落编码 skill 本职自检（§2.9）+ 知识留 skill（§1.5），非 Python 门；可维护——权威语义引知识库 `模板参数定义.md`。**因 V3 缺来源字段，止于 warn 不强 fail（§1.2 不误杀）。**

### 机制 ⓪ 脚手架参考解耦——接通已存在但未接线的 profile 通路（治 Q10 根，用户主张）

> **本机制是用户复核两份 L3 后追加的核心决策**，且是 ③（GLOB 隔离）的**上游根因修复**——先解决"脚手架参考从哪来"，③ 只是"编译时别被没解耦的 sibling 拖累"的兜底。
> **关键澄清（用户订正）——两条参考通路职责不同，不可混谈**（`repository.py:83-85` docstring 明说 default_reference_root 与 reference_code 是 "intentionally distinct concerns and never merged"）：
> - **`reference_code`/`reference_op_path`（方案级参考）**：注入某个相似算子的**全量源码**指导算法/解法，消费方 `requirement.py:80,149,188`（从 golden/参考推 op spec）+ codegen `codegen.py:785,925`。**不是脚手架参考。**
> - **profile `default_reference_root` → `state.reference_roots`（脚手架级参考）**：指向该仓 op 组织/注册/CMakeLists 的约定参考根，是 coder 学"这个仓的脚手架怎么写"的通路。**Q10 病根在这条。**
> 本机制只处理**脚手架级通路**；方案级 `reference_code` 未填是独立问题（不在 Q10 范围）。

- **实证根因（本文首次落入，已核实）——脚手架参考经 cwd 隐式仓耦合浏览，非 config 驱动**：
  - coder 需学目标仓脚手架约定（注册宏/build.sh/CMakeLists/DataCopyPad 用法），但**脚手架通路 `state.reference_roots`（profile `default_reference_root` 已填）codegen 根本不读**——grep 证实全仓只有 `verify_repo.py:124` 读 `reference_roots`，codegen 零消费。
  - coder cwd=`.../csrc/ops/<op>/`，sibling `add/sqrt/moe_re_routing` **可被 Bash/Read 浏览**；脚手架通路没接进 codegen → coder 回退**隐式浏览 sibling** 当脚手架参考：aggregate/manifold coder 各引用 `moe_re_routing` **87–88 次**（学它的注册/DataCopyPad/CMakeLists），scatter 0 次（浏览 add/sqrt，故错误阶梯不同）。**这既是 §2.1 仓耦合，又是 Q10 带毒源。**
  - 讽刺：codegen prompt（`codegen.py:922`）**明令禁止** coder 自搜目标仓 `ops/`——但脚手架通路没接线 + cwd 在 ops/ 内，coder 照样浏览 sibling 学脚手架，prompt 禁令形同虚设（禁了却没给替代的 config 通路）。
  - **且 profile 现在指"整个 ops 目录"而非"指定的干净脚手架样例"**：`default_reference_root: examples/aclnn_launch_example/csrc/ops`（bare dir）——coder 被指向目录下**所有** op，包括新加的、带毒的 `moe_re_routing`。用"整目录"而非"声明几个干净参考算子"，本身就是让带毒 sibling 混进脚手架参考的结构原因。
- **关键发现——脚手架解耦通路已存在，只是没接进 codegen**：
  - **repo_profile 通路已有**：`default_reference_root`（`cann-bench.yaml` build_variants）→ `repository.reference_roots()`（`repository.py:258-268`）→ `state.reference_roots`（`context.py:194,240`）。
  - **外部参数追加已有**：`--reference`（`run.py:30`，repeatable，"appended after profile's default reference root"）→ 经 `entry.py:112`/`dispatcher.py:771` 进 `reference_roots`。
  - **断点**：`reference_roots`（脚手架、config 驱动、已填）与 codegen **没接线**——codegen 不读它，coder 才回退隐式浏览 sibling。
- **直接先例（同源决策，强支撑）**：golden/cases 曾**刻意从 profile 预置迁到 CLI 显式**（`cann-bench.yaml` 末注释 "13 E1/B9a"）。脚手架参考该走**同一 config 显式范式**。
- **两方案（用户点名的二选一 + 组合）**：
  - **⓪a 外部参数（CLI `--reference`）为主**：接通 `state.reference_roots` → codegen 读它、物化声明的脚手架参考算子为只读注入。**每次运行显式指定**，与仓完全解耦。契合 13 E1 先例。
  - **⓪b repo_profile 为主**：profile `default_reference_root` 从**目录级**收窄为**声明具体干净脚手架样例算子**（如 `add`/`sqrt`，排除带毒 `moe_re_routing`），codegen 只物化 profile 声明的那几个。
  - **组合（原推荐，已弃）**：~~profile 声明缺省干净脚手架样例 + CLI `--reference` 精确覆盖/追加~~。**用户订正弃用**——脚手架参考职责已明确归 profile，加 CLI = 同一职责两条通路（违 §2.5）。**改定纯 profile（⓪b）**：只做①把 `reference_roots` 接进 codegen、②profile 从整目录收窄为指定样例、③**关掉 coder 的隐式 sibling 浏览**（prompt 禁令升级为 cwd 隔离/只读注入 ref）。CLI `--reference` 入口不启用。
- **四把尺子**：
  - **可维护**：接通已存在的通路 + 复用 golden/cases 已验证的解耦范式，不新造机制。
  - **可扩展**：任何仓/任何脚手架参考经 profile/CLI 声明即用，coder 不再靠"cwd 里恰好有什么 sibling"碰运气——换仓、换参考零改代码。
  - **可诊断**：脚手架参考来源显式可追溯（§1.11 受控注入 vs 自搜虚假信号）；带毒 sibling 不再被隐式当参考。
  - **架构合理**：解耦落 config（profile/CLI）+ DevKit 物化层，**不耦合具体仓**（§2.1）、脚手架样例属"实例数据"不进代码（§1.5/§1.12/§2.7 仓特定内容外移）。
- **与 ③ 的关系**：⓪ 修"脚手架参考从哪来"（根），③ 修"编译时 GLOB 仍会扫到未声明 sibling"（兜底）——⓪ 让 coder 不再**学**带毒 sibling，③ 让编译不再被带毒 sibling **挂掉**。二者互补，⓪ 优先。
- **待核实（用户提出，不臆断）**：cann-bench 的脚手架约定（注册宏/build.sh/目录结构/`csrc/ops` 布局）近期是否有变——若变，profile 声明的脚手架样例算子清单需同步刷新（需对比 cann-bench 仓历史或用户一手信息，代码层无法单独断定）。见 §5 V4。

### 机制 ③ 参考算子与 GLOB 编译隔离（治 Q10 编译侧兜底）
- **判据（结构信号）**：codegen/deploy 编译**目标 op** 时，隔离 `csrc/ops/` 下**非目标、非注入参考**的 sibling 算子，使带毒 sibling 不挂整包 build。选项：
  - **③a**：deploy 编译前，把目标 op + 注入的 `ref_*` 之外的 sibling 目录临时移出 GLOB 范围（或生成一个只含目标+ref 的临时 ops 树编译）。
  - **③b**：给 target repo 的 GLOB 编译加"跳过已知不可编译 sibling"——但这需改外部仓 CMake（§2.1 不耦合外部仓，否决）。
  - **③c**（现状 memory 记法）：删/改名带毒 sibling 源目录（`cann-bench-deploy-builds-all-ops` 记法）——手工、非通用、每次批跑重来。
- **四把尺子**：③a 架构合理（隔离在 DevKit deploy 层，不碰外部仓 CMake）、可扩展（任何带毒 sibling 自动不干扰，非 moe_re_routing 特判）、可维护（编译范围=目标+显式 ref，符合最小依赖）；③c 违反 §1.12（手工特判具体算子）。**推荐 ③a**。**风险**：需确认 target repo 编译是否支持"子集 ops 树"（cann-bench 的 `_C.abi3.so` 是否要求全量 ops 注册）——若 `_C` 需全量注册，③a 需保证隔离的 sibling 仍以 stub/预编译形式在，或确认 precision/eval 阶段不依赖被隔离 sibling。**先核实 cann-bench `_C` 注册粒度再定 ③a 可行性。**

### 机制 ④ host-only / 分层快编探针（治 Q1/Q10 放大器：暴露粒度）
- **判据**：在整包 build-all 前，插一层**廉价、host-only** 编译探针——只编 `op_host`（def/tiling/infershape）+ plugin 的 host 编译单元（不进 device kernel 编译、不 install、不真机 smoke），秒级返回。coder 每轮先过 host-only 快编，host 编译错（Q1 大半：GetData 模板、DataCopyPad 配对、tiling def、schema）在秒级暴露，通过后才进整包。
- **四把尺子**：可诊断——廉价层先滤掉 host 编译错（Q1 的 7 级里多数是 host/plugin 层）；可扩展——所有算子受益；架构合理——分层反馈是编译工程标准做法；可维护——探针复用 deploy 的 host 编译 stage 子集。**与边界文协同**：④让 codegen 廉价拦住框架/host 编译错，边界文让 device runtime 崩下沉——两者合起来 codegen 只在"廉价 host-only 框架层"花预算。**风险**：host-only 编译能否独立于 device kernel 编译（AscendC 工程 host/kernel 耦合度）——需确认 CANN 工程支持只编 host 侧（`opbuild`/tiling 编译可能已是独立 stage，deploy.py `_run_profile_chain` 的 build stages 或可拆）。**先核实 build stage 可拆性。**

---

## 4. 推荐 + 优先级

**落地结论（实施后更新）**：⓪/① 已做；③/④ 经 V2 实证弃做（违点 3 + moot）；② 视 V3 决定。

0. **机制 ⓪（参考算子显式解耦）——✅ 已实施**（纯 profile：reference_roots 接进 codegen prompt + profile 收窄 add 单样例 + prompt 禁 sibling 浏览；UT `test_prompt_wires_scaffolding_reference_roots` 等）。用户点名的根因修复，解 Q10 根 + §2.1 仓耦合。
1. **机制 ①（缺 InferShape）——✅ 已实施为编码 skill 自检项**（SKILL.md Step6 维6，结构信号驱动、EZ1008 后果、边界 warn；UT `test_step6_has_dim6_infershape_registration`）。非 Python 门（§2.9 本职自检 + §1.5 知识留 skill）。
2. ~~机制 ④（host-only 快编）~~ **弃做（纯性能，无未解 bug）**——见下 B1 澄清。
3. ~~机制 ③a（GLOB 隔离）~~ **弃做（正确性已闭环）**——见下 B1 澄清。

**B1 澄清（2026-07-31，纠正先前误导表述）**：先前把 ③a/④ 包装成"cann-bench 能力缺口 / 理想终局=per-op 编译目标"，给了"还有未解 bug"的错误印象。**订正：没有未解决的 bug。**
- **正确性已完全闭环**：Q10（带毒 sibling 经 GLOB 污染 build）根因 = 我们往 worktree HEAD 塞了本地毒算子（moe_re_routing），**非 GLOB 本身缺陷**。已由 (a) 批跑早已有的 **git worktree per-op 隔离**（`cann-bench-batch/<ts>/<op>/` 各一份独立检出）+ (b) cann-bench `reset --hard origin/master`（纯远端、不塞毒）双重根治。GLOB 全量编译对 cann-bench（评测仓）是**合理设计**，不是 bug。
- **剩余"全量编译慢"纯是性能**，且是单体 `_C` 设计的正常代价，非缺陷。**不给 cann-bench 提任何需求**（它无 bug）。
- **批量评测方案（批跑完统一编译评测一次，摊薄 GLOB 全量成本）= 纯性能优化，用户决定暂缓不做**。当前 per-op 隔离编译"慢但正确"可接受。删除先前"能力缺口/理想终局"表述。
4. **机制 ②（ASCENDC_TPL 宏门）**——补 tilingkey plan 延期缺口，纯 DevKit-内部（skill 引导，不耦合外部仓）。依赖 V3"tiling_strategy 是否声明模板参数来源"：字段缺则降级 skill 引导+warn。**唯一待做机制，先核实 V3。**

**关键设计约束（四把尺子导出）**：
- **全部结构信号驱动、零算子特判**（§1.12）：InferShape 判据=张量维度、宏判据=参数来源、GLOB 隔离=目标+显式 ref 集合、快编=编译单元分层——删任一算子名不改路径。
- **确定性门 fail vs warn 分层**（§1.2 组合）：判据可靠的上确定性 fail（① InferShape 存在性、③ 隔离）；判据依赖未证字段的上 warn + 编译兜底（② 宏门字段缺时、① 的"是否需要"边界情形），不静默、不误杀。
- **静态门只前移"确定性可静态判"的框架事实**，不越界替编译器/precision 做 runtime 判断（与边界文一致：框架层@codegen 静态门，device runtime@precision）。
- **不进 codegen skill 的仓特定内容**（§2.7）：GLOB 隔离、build stage 拆分属 DevKit deploy 层桥接逻辑，不写进 skill；skill 只承载跨算子通用的核心引导（宏语义、InferShape 必要性判据）。

**scope**：本 L3 只覆盖 codegen 收敛加速（Q1+Q10）。与 `84-codegen-precision-boundary-analysis.md`（Q2/Q3 边界）**耦合但正交**：边界文管"framework OK 后 runtime 崩去哪"，本文管"framework 层怎么更快收敛"。Q11（硬超时业务语义）独立但受益（收敛快+崩溃下沉后，codegen 不再逼近超时）。

---

## 5. 待用户拍板 + 待核实（冻结前）

**决策点：**
- **E0（用户点名，追加）——已定：纯 profile（⓪b），不加 CLI**。用户订正：脚手架参考的职责已明确归 profile；再加一条 CLI `--reference` 通路 = **同一职责两条通路**，违反 §2.5（唯一通路、不留旧债），CLI 那点覆盖灵活性不值得引入第二入口。**取 ⓪b 纯 profile**，三件事：① 把 `state.reference_roots` 接进 codegen（当前 codegen 不读——Q10 病根）；② profile `default_reference_root` 从整目录收窄为**声明的干净脚手架样例**（排除带毒 sibling）；③ **关掉 coder 隐式 sibling 浏览**（prompt 禁令升级为只注入声明的 ref + cwd 不放开 sibling）。（注意：`--reference` CLI 入口本机制**不启用/移除**，不作为长期并存通路；方案级 `reference_code` 未填是独立问题，不在本机制范围。）
- **E1（订正）**：原顺序 ⓪→①→④→③a→②。**④/③a 经 V2 弃做**（见 E3）。**实际落地 = ⓪✅→①✅→②✅**（② 经 V3 降级为 skill 引导+warn，非确定性门：schema 无参数来源字段）。全部 DevKit-内部机制已实施。
- **E2（用户订正，已定）**：机制 ① **改为 codegen 编码 skill 的自检 checklist 项**（不做 Python 静态门）——缺 InferShape 是算子框架正确性问题、归 codegen 本职自检（§2.9）+ 算子知识留 skill（§1.5）。判据仍用"output 维度/来源 ≠ input OR tiling 读 storage shape"，边界情形宁 skill-warn 不误判。
- **E3（订正——V2 实证否决，机制③/④ 弃做）**：原计划 ③a（DevKit deploy 层隔离）+ ④（host-only 快编）。**V2 实证推翻可行性**：`examples/aclnn_launch_example/CMakeLists.txt:200-214` — `_C.abi3.so` = `add_library(_C SHARED extension.cpp $<TARGET_OBJECTS:cann_bench_plugin_obj>)`，而 `cann_bench_plugin_obj` 的 `ALL_PLUGIN_SRCS` 由 `csrc/ops/CMakeLists.txt:9 file(GLOB)` + `add_subdirectory` 对**每个** op 聚合。即 `_C`（整个 eval harness import 的模块）**对全部 op 的 plugin 源单体链接**——任一 op 的 plugin 坏 → `_C` 编不出 → 全算子 eval 挂。**后果**：
  - **③a 不可行**：`_C` 单体，DevKit 无法在不动 cann-bench CMake（= 为其 GLOB-without-CONFIGURE_DEPENDS bug 做耦合修改，违用户点 3）或不裁剪 ops 树（裁剪 = 从 `_C` 丢 op → 破坏其他算子）的前提下隔离单 op 编译。
  - **④ 不可行**：cann-bench `build.sh`/CMake 未暴露 host-only target，做 host-only 快编须改其 build 脚本（同样耦合外部仓）。
  - **且 ③/④ 的防护目标已被覆盖**：原威胁（带毒 sibling 破坏 build-all）现已由 (a) cann-bench reset 纯远端（毒源已除）+ (b) 机制⓪（codegen 只读声明的干净样例、绝不浏览/写 sibling）双重消除。故 ③/④ **弃做**（moot + 违点 3），非遗留技术债。cann-bench GLOB-without-CONFIGURE_DEPENDS 若要根治属**其上游职责**（加 `CONFIGURE_DEPENDS` 或拆 `_C` 为 per-op 模块），DevKit 不耦合兜底。
  - **已有的合规缓解保留**：profile `clean_dirs`（清 GLOB cache 强制 reconfigure，P96）是 DevKit 侧调用外部 build 的正当参数化，非改外部 CMake，保留。

**待核实（L4 前置，影响可行性）：**
- ~~V1（机制 ④）、V2（机制 ③a）~~ — **已实证，机制③/④ 弃做（见 E3 订正）**。
- **V2 结论**：`_C.abi3.so` 单体链接全 op plugin（`CMakeLists.txt:200-214` + `csrc/ops/CMakeLists.txt:9 GLOB`），**要求 csrc/ops 全量可编**，无法编译子集树。
- **V3（机制 ②）**：tiling_strategy 设计产物是否显式声明模板参数来源（dtype 派生 vs enum 派生）——决定宏门能否确定性化还是降级引导。
- **V4（机制 ⓪，用户提出）**：cann-bench 脚手架约定（注册宏/build.sh/`csrc/ops` 目录布局）近期是否有变——若变，profile 声明的干净脚手架样例算子清单需同步刷新。需对比 cann-bench 仓历史或用户一手信息，代码层无法单独断定。

---

## 6. 句柄（取证 + 代码锚点）

- L1：`84-batch-205112-issues-summary.md` Q1/Q10
- 关联 plan：`tilingkey-ascendc-tpl-unification/{01-problems,02-analysis,03-impl}.md`（ASCENDC_TPL 统一 + P3 host/kernel 机制交叉自检 + m2 延期缺口）、`84-codegen-precision-boundary-analysis.md`（耦合边界文）
- codegen 契约/prompt：`orchestration/stages/codegen.py:{868-1097 prompt,145-176 expected_files,1234-1348 transition 门,1099-1180 name-drift/schema 门,433/993 InferShape 字面量,972/1897 ASCENDC_TPL 引导,785/925/405/1849 reference_code/op_path 读点,922 禁自搜 ops/ 禁令}`
- **参考算子解耦（机制 ⓪）**：`orchestration/kernel/state.py:{80 reference_roots,134-135 reference_code/op_path}`、`cli/commands/run.py:{30-32 --reference,55-61 --golden/--cann-bench-cases 先例}`、`orchestration/stages/entry.py:112`（tr.references→reference_roots）、`orchestration/stages/context.py:191-192`、`domain/repository.py:{89 default_reference_root,258-268 reference_roots()}`、`resources/repository-profiles/cann-bench.yaml`（default_reference_root + 末注释 13 E1 golden/cases CLI 显式先例）；实证：本批 5 算子 state_snapshot `reference_code/op_path` 全空、aggregate/manifold coder 各 87–88 次浏览 `moe_re_routing` sibling
- deploy/编译：`adapters/npu/deploy.py:{93-165 deploy,605-644 profile chain,621-629 GLOB cache trap,384-416 smoke}`、`orchestration/stages/cannbench_adapt.py:119-127 clean rebuild`
- skill：`.claude/skills/ascendc-op-dev-coding/SKILL.md:{145 InferShape 条件,194 InferShape 注记,164-174 TilingKey,255-282 Step6 自检表,265 机制一致性门}`、`ascendc-op-dev-coding-regbase` coding-plan-template.md:36 / todo-template.md:107
- 知识库：`.../算子工程编译.md:226-228`（DTYPE_DECL vs DATATYPE_DECL 共存语义）
- 记忆：`cann-bench-deploy-builds-all-ops`（GLOB build-all + 手工删 sibling 记法 = ③c）
