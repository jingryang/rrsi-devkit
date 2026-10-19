# L4 设计阶段数学声称验证 — 实施方案

> 前置：L1 `01-problems.md`（D1/D2/C1/B1/T1）、L3 `02-analysis.md`（决策汇总）。
> 按用户决策③：本次先落文档；实施待用户确认后启动。本 L4 给出具体改动点、TDD 测试、验证方式。
> 原则：主修在设计自检（构造性保证 §2.9），codegen 对质/ debug 兜底不越层（§1.2）。

---

## 1. 改动范围总览

| 层 | 文件/资源 | 改动 |
|---|---|---|
| 设计 | `ascendc-op-design-shared/references/design-math-claims/`（新建） | 验证清单 + Python 模板 + 已核验事实库 |
| 设计 | `ascendc-op-general-design/SKILL.md`、`ascendc-op-design-template-division/SKILL.md` | 自检表新增"化简声称验证"项 |
| 设计 | `design_spec` schema | 新增 `support_domain` / `known_limitations` 字段 |
| 设计 | ~~anchor claim_type 扩展~~（已撤，§2.9 门边界） | anchor 保持硬件可行性对质；域验证归设计自检 + codegen |
| codegen | `codegen` 生成前校验逻辑 | 域对质：requirement 域 ⊆ support_domain；缺口→**注入 coder prompt**（覆盖 golden 全域 + 记 decision_log）+ 信号落盘供观察（明确消费，20260810 落地；design 反馈通道待允许上游后启用） |
| debug | `ascendc-precision-fix` / `-printf` SKILL.md | host 兜底必须标 `fallback_masked=true` |
| debug | `ascendc-precision-scope-guard` 判定表 | 新增"host 兜底通过 → 上游设计缺口"行 |
| debug | 报告渲染（`precision-report-rendering` 工作，B8） | 区分 kernel 真通过 vs host 兜底通过 |
| 算子 | transpose design/kernel/tiling/plugin | 算法②通用 N-D 转置，删 host 兜底 |

## 2. 设计侧（第一层）

### 2.1 references 资源 `design-math-claims/`

- **`claim-verification-checklist.md`**：声称类型 → 验证方法 → 自检判据（L3 §D1 五档表落地）。核心判据：**支持域 ⊇ 需求(golden)域；未验证必须显式标 known_limitations，禁止裸描述**。
- **`verify_simplification_claim.py`**：通用验证模板，**骨架已知正确、LLM 只填算子特定声称逻辑**（缩小 LLM 错误表面积，L3 §D1 杠杆②）。三段式：
  1. **穷举段**：小参数空间全枚举（如 perm rank≤5），对照 golden；
  2. **随机段**：`np.random` 随机 shape/参数，对照 golden；
  3. **报告段**：输出"声称支持域 vs 实测可覆盖域"差异表，供 design agent 写 `support_domain`。
  骨架（输入生成 / golden 调用 / 对比 / 报告）本身由 UT 守护（V1），LLM 填写的声称逻辑段落是唯一易错面。
  模板以 `verify_transpose_perm.py`（本工作目录归档版）为基准泛化——归档版中"循环旋转分类 / 算法①②"即 LLM 需填写的声称逻辑样例。
- **`verified_facts.md`**：已核验事实库（首批 + 持续沉淀）：
  - 单个 2D 转置 ≡ 循环旋转 `[b..n-1,0..b-1]`；rank=n 时循环旋转 n 个。
  - 任意 perm 可分解为 ≤n-1 次两两换维（算法①）或通用 N-D index 映射（算法②），均对照 `np.transpose` 核验。
  - 后续算子设计时产生的验证脚本结果，验证后归档追加，供同类声称引用。

### 2.2 SKILL.md 自检项

`ascendc-op-general-design` / `ascendc-op-design-template-division` 自检表新增：

> **化简/降维/等价声称验证（主动验证）**：若设计含"化简/降维/等价/复用/覆盖"声称，**优先写并运行 Python 验证（对照 golden）**：把声称操作化为可运行代码（用 `verify_simplification_claim.py` 骨架），对 golden 穷举/随机核验，得到"声称支持域 vs 实测可覆盖域"。必须给出①`support_domain`（形式化支持域）+ ②验证方式与证据（穷举范围 / 随机 N / 引用 verified_facts）+ ③与 golden 域对比结论 + ④残余风险进 `known_limitations`。仅在声称不可运行化（纯估计/启发式）时用引用事实或显式标域限制。**禁止裸描述；禁止把"跑过 Python"冒充"已证明"——验证方式与残余风险必须随产物记录（§1.3 可诊断）**。

（注：LLM 写的验证 Python 可能本身有错——概率性提升，非保证；可靠性由 golden 锚定 + 骨架已知正确 + 记录验证方法与残余风险兜底，L3 §D1 五杠杆。）

**不 halt 规则（L3 §D1，含自修语义）**：验证脚本跑不通 / 无法运行 / 声称被证伪 → 一律**不 halt**。**先 agent 内部多轮自修**（改脚本→重跑→再改，§2.9 自检闭环）——"跑不通" = 多次内部尝试后仍跑不通，不是一次机会。自修不动 → 标 `known_limitations`（reason=验证不可运行/未验证）+ `support_domain`（声明域）→ 继续进入 codegen/debug（下游自有兜底）。仅不可解且需上游裁决才走 `resolve_ambiguity` / `blocking_issues target=human`。

### 2.3 anchor claim_type 扩展

`ascendc-op-design-anchor-per-template` 新增 claim_type：
- `domain_coverage`：对 design 的 `support_domain` 声称，对照需求/golden 域做集合包含对质；
- `math_feasibility`：对"降维/化简"类声称做数学可行性对质（如 transpose：任意 perm ≠ 单个 2D 转置）。
与现有 `hardware_api_capability` 并列（§1.2 可扩展，同一对质机制）。

### 2.4 design_spec schema

新增结构化字段（§2.10）：
```json
"support_domain": { "desc": "声称支持的输入域，集合形式；machine-readable" },
"known_limitations": { "desc": "未覆盖/未验证部分；非空即须 codegen 对质裁决", "default": [] }
```

## 3. codegen 侧（第二层）—— 已实施（结构化域词汇表 + 引擎 + 非 halt 信号）

**结构化域词汇表**（需求/设计共享，§2.10/§1.12）：
- `requirement.json.domain`（req-analysis 产出，schema 已加）：`rank{min,max}` / `inputs[].dtypes` / `attrs[].domain{kind,constraint}`。
- `design_spec.support_domain`（设计产出，schema 已加）：同词汇表。
- attr domain kind 用 canonical 集（`permutation: any|cyclic_rotation`），经 `ATTR_DOMAIN_COVERAGE` 可扩展。

**引擎**：`src/ascendc_devkit/domain/support_domain.py`
- `domain_covers(req_domain, design_domain) -> list[str]`：rank/dtype/attr 三轴 ⊆ 判定，缺口列表，空=覆盖；缺声明轴跳过（不假阳性）。
- `requirement_domain(req)`：优先新 `domain` 字段，容错回退到既有字段（rank 解析 symbolic_rules、dtypes 展平 input_combinations）。
- `design_support_domain(ds)`：读 `support_domain`。
- transpose 端到端：需求 `perm:any` + 设计 `perm:cyclic_rotation` → gap `attr[perm] ... ⊄`；设计 `any` → 通过。

**接入（非 halt，no-halt 哲学）**：`codegen.py::_emit_domain_gap_signal`（`_materialize_inputs` 之后调用）
1. 读 on-disk `requirement.json`（权威源）+ `state.design_spec.support_domain`；
2. `domain_covers` 判定；
3. 缺口 → `Logger.warn` + 写 `staging/domain_gap_signal.json`（结构化信号，下游 codegen agent / debug / eval 可读）→ **不 halt、不 feedback loopback**（安全网不阻断；缺口由 debug/eval 兜底）；
4. 无缺口/缺声明/任何异常 → 静默跳过（安全网绝不崩 codegen）。

> 相比初版 L3 的"缺口→反馈 design loopback"：实施期收敛为**非 halt 结构化信号**（§2.9 不引入无界 loopback；问题显式携带，debug 侧 scope_guard 对实际域外失败识别为设计缺口再反馈）。域对质是**声明级安全网**（防"声称任意 perm 实为循环旋转"类），实际域外失败仍由 debug/eval 兜底——三层防线职责清晰。

## 4. debug 侧（第三层）—— skill 部分已实施，框架消费归 B8

### 4.1 fallback_masked 标注（fix/printf skill）✅ 已实施

- `ascendc-precision-fix` SKILL.md **已有**（`:141-148`）：「低性能回退方案拒绝」（plugin/host 用 golden 同源参考替代 kernel → refuted）+「host fallback 检测」（必须走时标 `fallback_masked=true`，不记 kernel 验证通过）。
- `ascendc-precision-printf` SKILL.md **本次补**（transpose 605af87 即 printf 路径，此前无检测）：新增「host fallback 检测（commit 前必做）」——kernel 不支持某输入域时优先扩展 kernel/设计域；必须走 host 兜底时标 `_summary.fallback_masked=true` + 注明「host fallback 通过，kernel 未真实现该输入域」。

### 4.2 scope_guard 判定表新增行 ✅ 已实施

判定表新增：
> `fallback_masked=true`（或结果经 host CPU 兜底绕过 kernel）→ 属**设计/kernel 覆盖缺口**（需求域 ⊄ 实现域）→ **upstream** | `design`。首轮不出现（fallback 是 fix/printf 后产生）；触发场景=scope-guard 因 `observed_issues(blocking=true)` 重判或结果携带 fallback_masked。

### 4.3 框架消费（并入 `precision-report-rendering` 工作，B8，❌待实施）

报告区分"kernel 验证通过"vs"host 兜底通过"（B8）：通过 case 若 `fallback_masked=true`，状态列标注 `host_fallback`，成功态不写成纯 `✅`。框架 Python 消费该字段（当前零命中）——归 `precision-report-rendering` 工作（报告渲染 + debug_result 携带 `host_fallback` 标志供下游 eval 感知）。

## 5. transpose 算子落地（T1，验证用例）

1. **设计**：`support_domain = {perm: 1<=len(perm)<=8, perm 为排列}`（= golden 全域），`known_limitations=[]`。
2. **kernel/tiling**：实现算法②通用 N-D index 映射转置（单 pass，已核验）。tiling 负责把任意 perm 映射为输出 tile → strided 输入读。算法①（两两换维）作实现风险过大时的 fallback 备选。
3. **plugin**：删 `IsKernelSupportedPerm` host 兜底分支（`transpose_plugin.cpp:63-81`），全 perm 走 `ACLNN_CMD(aclnnTranspose, ...)` 真 kernel。
4. **回归**：20 case precision 全过 + 评测 8 case 真跑 NPU、反作弊不触发。

## 6. TDD 测试（先写测试，再改代码）

| # | 测试 | 断言 |
|---|---|---|
| V1 | `verify_simplification_claim.py` 自测 | 穷举 rank 2-5：循环旋转数 = n；算法①②对照 `np.transpose` 随机 100 组全一致 |
| V1b | 验证失败不 halt | 设计 agent 报告"脚本跑不通/未验证" → 产物含 `known_limitations` + `support_domain` 声明，**流水线继续**（不 halt、不 loopback） |
| V2 | 域包含判定 | `golden 域(全部 perm) ⊆ support_domain(循环旋转)` = False；`⊆ support_domain(全部 perm)` = True |
| V3 | codegen 域对质路由 | 域缺口 → 产出 feedback 条目 target=design，不 halt |
| V4 | fallback_masked 检测 | fix 产物含 host 兜底证据而无 `fallback_masked=true` → 契约错误 |
| V5 | scope_guard 判定 | `fallback_masked=true` → verdict=upstream(design) |
| V6 | 报告渲染（并入 precision-report-rendering） | fallback_masked case 状态列非纯 `✅` |
| V7 | transpose 全 perm 回归（UT/ST） | 20 case 含 8 个非循环旋转 perm 全过，无 host 兜底信号 |

## 7. 验证

1. **TDD**：V1-V7 先红后绿，既有 UT 不回归（设计/编码 skill 相关 UT + orchestration UT 全量）。
2. **数学**：V1 的穷举 + 随机即设计侧验证方法的可执行证明。
3. **重跑 transpose**：precision 20/20 + 评测非 0 分（8 case 真跑 NPU）——端到端验证三层防线。
4. **通用性抽查**：选 1-2 个含"化简/降维"声称的存量设计，核对是否满足新自检项（§1.2 覆盖面）。

## 8. 边界与风险

- **不牺牲正确性的兜底**：`known_limitations` 非空即触发 codegen 域对质裁决，宁可拦下也不放行"声称覆盖实为子集"。
- **通用性 ≠ 全自动**：五档验证方法中穷举/原型/引用是确定性，形式化依赖 LLM 推导但以集合包含判据硬校验，标限制是兜底——机制不因"LLM 推导可能不严谨"而放宽。
- **实施范围**：本 L4 分三块（设计 skill / codegen / debug），可独立落地、独立验证；transpose 算子侧落地依赖设计/kernel，作为验证用例串行推进。
- **性能取舍**：算法②单 pass 已是最优方向；性能优化 stage 未实现，算法②不依赖它（正确性内最优即达标，§用户决策②）。

## 9. Phase 4 执行记录（2026-08-09）

> 用户决策（Phase 4 会话）：**改源头而非产物**——不手工改 batch 工作区里 codegen 生成的算子代码，改修 DevKit 的设计/codegen 机制 + 源头设计，让重生成自动产出正确代码；**只修源头、先不重跑**（重跑留后续批次）。

**已落地（源头侧）**：
1. **机制已落库**（commit `8d72745f`）：design-math-claims 三层防线（设计自检 + codegen 域对质 + debug fallback_masked），UT `test_support_domain.py`(9) + `test_design_math_claims.py`(3) 全过。
2. **域对质演示通过**：`domain_covers(requirement perm:any, design perm:cyclic)` → 抓出缺口 `attr[perm] ... ⊄`；design `perm:any` → 覆盖。旧设计（循环旋转）会触发 `domain_gap_signal`，新设计不触发。
3. **transpose 设计源头已修正 + Python 验证**：
   - `output/20260808-162146-ae8b74/.../artifacts/staging/design_spec.json`：`support_domain` = 全 perm（`len(perm)∈[1,8]` 且为排列）+ `known_limitations=[]` + `algorithm_choice=algorithm_2_nd_index_mapping`（fallback=algorithm_1）；删除错误声称"任意 perm 降维为二元 (M,N)"。
   - `tiling_strategy.json`：算法②通用 N-D index 映射 tiling（逐输出行 gather，fastStride==1 连续读 / >1 strided 读 + UB gather + MTE3 写）。
   - 验证脚本 `verify_transpose_algo2.py`：算法②逐输出行地址映射对照 `np.transpose` 穷举 rank 1-5 全 perm + 随机 200 + 真实 20 case = **365/365 一致**。
4. **算法② kernel 已实证正确**（为源头重生成提供可信设计依据）：Phase 4 会话曾按此设计在 batch 工作区手工实现 kernel/tiling（算法②），precision **20/20 全过（diff=0，kernel 真跑）**，含 8 个非循环旋转 perm；已回退该产物改动（用户决策：改源头）。

**未落地（按用户决策搁置）**：
- 重生成 transpose 流程（design→codegen→deploy→precision→eval）——留后续批次，从正确源头自动产出算子代码。
- 算法② kernel 的 per-row TQue sync 开销优化（transpose_1 实测 ~13.6s/134M 元素）——属性能 stage 范畴，未实现（§用户决策② 不越级做性能 stage）。

**经验**：手工改生成产物（batch 工作区算子代码）即便能跑通 precision，也被判定为"改产物无意义"——正确路径是源头（设计/机制）修正 + 流水线重生成。产物改动仅供会话内验证设计正确性，不提交、不视为交付。
