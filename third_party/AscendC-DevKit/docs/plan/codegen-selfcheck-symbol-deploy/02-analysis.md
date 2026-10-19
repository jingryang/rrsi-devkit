# codegen 契约/符号簇（P1/P2/P3/P4）— 方案分析（L3）

> 覆盖问题：P1（长会话末尾写契约失败）、P2（agent 自检缺产物符号验证）、P3（`_` 前缀
> 算子目录被 CMake GLOB 跳过）、P4（framework deploy 无符号存在性门）。
> 两条根：**契约/自检都发生在 agent 长会话末尾（P1）或静态层面（P2），未落到实际产物**。
> 本文档记选项与取舍；拍板后冻结，实施配方见 L4。

## 问题本质（L1 摘要）

`__interpolate` 的 `aclnn_interpolate.cpp` 定义了 `aclnnInterpolate`/`aclnnInterpolateGetWorkspaceSize`
（extern "C"），但 built `libcust_opapi.so` 缺这两个符号（nm 实测仅 Add/Sqrt）。agent round3
宣称「verified end-to-end」实为静态宏链推演，从未 `nm -D` 验证产物。框架 smoke 兜住但拖到
smoke×3 + precision 20/20 才暴露 → HALT。直接构建原因：cann-bench 的 `csrc/ops/CMakeLists.txt`
GLOB 排除 `_` 前缀目录（为跳内部目录如 `_common`），误伤 `__interpolate`。

## 设计目标（判据，供选型）

- 产物合法性在**构建期/加载期**校验（§1.3），不拖到 smoke/precision。
- **producer 自检闭环**（§2.9）：codegen agent 以实际产物为证据（§1.11），不认构建日志/静态推演。
- 覆盖同类新算子（§1.2 可扩展）：任何 op 的 aclnn 符号缺失都自动被拦，不靠已知算子打补丁。

---

## P1 — 长会话末尾写契约失败（框架侧优先，独立于符号簇）

**问题本质**：契约写盘位于 skill 流程末尾（框架规定的最终交付物），而 round 1 会话已
≈33 万 token，早期加载的维8 契约要求在长上下文里失效 → agent 末尾写 manifest 非契约。
round 2（框架反馈后）短会话即正确 → 证明「写盘时刻的上下文负载」是主因。

**设计目标（判据）**：把「契约正确性」从「长会话末尾的 agent 注意力」中解放出来——
构造性保证优先（§2.9），或把写盘移到上下文峰值之前。

**选项**：
- **A 前置契约骨架（skill 流程）**：读完设计产物后、写代码前，先落 `codegen_manifest.json`
  契约骨架（从 requirement.json/design_spec 派生 inputs/outputs/attrs/callable_target），
  代码写完末尾只做**同步更新**（漂移由框架机械校验兜）。
  - 优点：写盘从上下文峰值移到最轻时刻；契约源 = 设计产物（稳定上游）。
  - 缺点：末尾仍需同步（比新写省力）；改 skill 流程。
- **B 框架构造性派生定稿（§2.9，推荐）**：框架对可从产物确定性派生的契约字段直接定稿——
  `inputs/outputs` 从 plugin `m.def` 解析（WARN 已证框架能解析 m.def）、`callable_target`
  从 TORCH_LIBRARY（已有 `derived callable_target` 先例）、op_name 从 op_dir；agent manifest
  降级为补充**不可派生**字段（dtypes/shapes/param_type/chip_code/programming_model，且大部分
  也能从 requirement.json 取）。派生与 agent 声明不一致时以派生为准 + WARN。
  - 优点：彻底消除「末尾写契约出错」失败面；契约由产物+上游设计派生，一致性**构造性保证**
    （§2.9），不再依赖 agent 自检；可扩展（任何算子自动正确归位）。
  - 缺点：不可派生字段仍需来源（requirement.json 兜）；实现量中等。
- **C 短会话化**：codegen 拆多个短会话（<50 turn）。
  - 优点：根治上下文退化。
  - 缺点：大改造，与现有单会话设计冲突，成本高。非首选。

**拍板（最终采用，2026-08-20）**：**manifest 收敛**——不采用 A/B/C（框架派生 IO / 前置
骨架 / 短会话化），因为进一步实证发现 **manifest 的 IO 结构不被下游消费**：
- 下游（deploy/smoke/precision/adapt）只读 `callable_target` + `op_name`；harness 绑 golden
  用 op_spec；IO 只服务 codegen 内部校验门 → IO 是**三重冗余**（冗余于 m.def、op_spec、下游）。
- 故 `required_keys` 收敛为 `(op_name, callable_target)`，IO 降为可选**不触发 retry**，
  P1 的 retry 门从源头消除；`_check_plugin_schema_consistency` 仅在 manifest 主动声明非空
  inputs 时校验（plugin m.def 为运行时绑定唯一权威）；schema/skill/prompt/feedback 同步。
- resume 亦不用于 P1（浅修 respawn 已便宜，round 2/3 只读 ~15K）。

**验证（Part 1 已落地）**：UT——required_keys 变更后缺 inputs/outputs 不再 retry（
`test_manifest_missing_inputs_outputs_no_retry`）、一致性检查对「不声明 IO」不误报
（`test_no_warn_when_manifest_omits_inputs`）、callable_target 派生不变；全量 UT 3616 通过。

### P1 配套：上下文成本削减（脚手架契约减负）— 缓解长上下文根因的另一面

**背景（round 1 token 拆解）**：会话 ≈19 万 token，其中 **~40% 可减**，大头：
- 脚手架参考整读 ~90K 字符（agent 整读 `add` 参考算子全套；其中 `aclnn_common.h`/`interpolate.h`
  各**重复读 2 遍** = 66K，违反 skill「每文件只读一次」）。
- in-session build ×15 次 ~56K 输出（与框架 deploy/smoke 构建冗余；砍的是全量日志抓取，
  不是构建自检本身）。
- 知识库整读 ~18K（`OpDef渲染规格映射.md`/`Gather.md` 整文件读，可用 INDEX 定向）。

权威输入不可减：设计产物 49K + skill 32K + write 调用 82K（代码本体）。

**设计（脚手架契约减负）——解耦 + 兜底**：
- **归属（解耦，用户拍板）**：脚手架契约 = per-repo 知识，落 repo profile——**扩展既有
  `default_reference_root` 机制**（现 profile 已把脚手架参考收窄到单个干净样例算子 add），
  加 `scaffold_contract:` 字段（提取规格 + 锚定标记）。framework/skill 保持 repo 无关
  （§2.6/§1.5/§1.7）；接新仓 = 加 profile，零框架改动。
- **派生（防陈旧）**：codegen 开始从**活仓**读参考算子 CMakeLists/注册宏/文件布局 → 生成
  ~2-5K 紧凑契约摘要注入 coder prompt（替代整读 ~90K）。派生按结构信号（§1.12），不认算子名。
- **兜底（仓脚手架变更）**：派生前校验锚定标记（宏签名 / GLOB 规则文本）与活仓一致；失配或
  派生空 → **跳过注入**，agent 退回会话内读仓学习（现状）+ WARN「profile scaffold 规格失配，
  请更新」（§1.3 诚实信号）。终极防线 = P4 deploy 符号门 + precision_debug scope_guard。
- **原则**：profile = 加速器/提示，**活仓 = 权威真值**（§1.13 同构）；契约从活仓派生故永不陈旧。
- **收益**：省 ~85K 字符/会话（~28K token），并缓解 P1「长上下文末尾退化」根因（上下文越短，
  末尾自检越可靠）。

---

## P4 — deploy 符号存在性门（框架侧，最先做）

**现状**：`deploy.py` Deployer 流程 = `_run_build_install`（跑仓 build.sh，产出 install 包）→
`_run_smoke_phase`（smoke 验证 callable）。符号缺失只在 smoke 暴露。

**选项**：
- **A（推荐）**：`_run_build_install` 后、smoke 前，对 built 产物做 `nm -D` 断言预期
  `aclnn<Op>` 与 `aclnn<Op>GetWorkspaceSize` 存在；缺 → 归类 deploy 缺陷（复用
  `classify_build_error` 的分类与 retry 状态机），报错含「预期符号 vs 实际符号」清单。
  - 预期符号从 `codegen_manifest.callable_target.symbol` 的 `<op>` 段派生（PascalCase + aclnn 前缀）。
  - libcust_opapi.so 定位：install 产物 `find`（per-op opp/vendors/custom_ops/op_api/lib/）。
  - 优点：§1.3 直接落地；可诊断（报预期/实际清单）；可扩展（符号名规则统一，新算子自动覆盖）。
  - 风险：符号命名规则若有例外（namespace / 别名）→ 误报。缓解：仅对 `programming_model` 含
    ACLNN/plugin 的算子启用；误报则按 deploy 缺陷走 retry（不会空烧 precision）。
- B：仅加强 smoke 错误分类（把「符号缺失」从 generic 拆出）→ 仍是运行期暴露，治标。
- C：不动，靠 smoke（现状）→ 已证不足（3× 同签名 stop-loss 才暴露）。

**拍板**：A。

## P2 — skill 自检补「产物符号验证」（producer 侧，根治）

**现状**：`ascendc-op-dev-coding/SKILL.md` Step 6 自检表维1–维8 全静态代码级，无产物验证项；
维7 注释「编译器 in-session 兜底」被 agent 滥用成「build 日志 grep 算验证」。

**选项**：
- **A（推荐）**：Step 6 自检表新增 **维9「产物符号验证」**（codegen 产权）：
  「写码 + in-session 构建后，必须 `nm -D <built libcust_opapi.so> | grep -E 'aclnn<Op>($|GetWorkspaceSize)'`
  确认符号在产物；缺 → 自检 fail，就地修 CMake 注册/plugin 后重构建回验，不得以构建日志 grep /
  静态宏链推演冒充验证（§1.11 看实际产物）。」
  - 同时把维7「编译器 in-session 兜底」措辞收紧为「构建须以产物符号/可调用为证据」。
  - 优点：producer 自检闭环（§2.9），问题在 codegen 内闭合；与 P4 双层。
  - 风险：agent 是否真正执行 `nm` 仍不可强制——但维9 把「证据形式」写死，配合 P4 门兜底。
- B：不动 skill，纯靠 P4 门 → 仍让 agent 自检假阳性蔓延，违背 §2.9。

**拍板**：A。

## P3 — `_` 前缀算子目录被 CMake GLOB 跳过（构建层）

**现状**：cann-bench 的 `csrc/ops/CMakeLists.txt` GLOB 排除 `_` 前缀目录（为跳 `_common` 等内部
目录），误伤 `__interpolate`。CMakeLists 属仓特定脚手架（§2.7 外移给 LLM 生成）。

**选项**：
- **A（推荐）**：在 P2 的维9 自检中显式覆盖此场景——维9 判据含「op 目录名以 `_` 开头时，核对
  CMake GLOB 未误排除」（结构信号：glob 排除规则只应匹配内部目录名白名单，如 `_common`/`op_kernel`，
  不按 `_` 前缀一刀切）。由 agent 在自检/修复中落正确的 glob。
- B：在 cann-bench 仓库侧修 GLOB 模板（只排除白名单内部目录）→ 治本次，但脚手架在 LLM 手中，
  模板改了 agent 仍可能照旧生成。
- C：改 `__interpolate` 算子目录名 → 改数据/命名，不可取（算子名是数据事实）。

**拍板**：A（由维9 自检驱动 agent 修正 glob；P4 门兜底确保缺失必现）。若后续同类反复，再考虑
B（仓侧模板）。

---

## Part 3 落地（2026-08-20，resume 保险机制）

**机制已实施**：`SpawnAgent.resume_prompt`（action.py）+ `AgentBackend.spawn(resume_prompt)` +
runner 透传 + SDK/OpenCode 后端 resume 首条消息改用 `resume_prompt or _RESUME_PROMPT`（深修反馈
替代硬编码「继续」）。测试桩签名全量补 `resume_prompt=None`。UT 覆盖 resume 首条消息携带反馈。
**采纳（下一步）**：precision_debug diagnose→fix 的 session_id 捕获 + resume 传递（深修密集），
需在 precision_debug phase spawn 处接线——机制已就绪，接线是独立工作项。

---

## 实施顺序（本簇内部）

1. **P4** deploy 符号门（框架代码，独立可验）→ UT。
2. **P2** skill 维9 自检（skill 文档）→ 无代码，靠 P4 + 后续批跑实证。
3. **P3** 由维9 判据覆盖（agent 行为），不做独立代码改动。

## 待确认（拍板前）

- **skill 编辑**：`ascendc-op-dev-coding/SKILL.md` 是 A3 codegen skill（用户域），但属共享
  `.claude/skills/` 文件；并发期「暂缓共享文件编辑」的记忆是否仍适用 → 需确认。
- **P4 符号命名规则**：预期符号 = `aclnn` + `PascalCase(callable_target.symbol 的 op 段)`；对
  有 namespace/别名的算子是否误报 → 实施时先查既有 op 的符号命名规律再定启用范围。
