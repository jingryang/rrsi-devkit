# L4 实施方案 — 三腿落地（TDD）

> 对应 L3 冻结方案。**本文件为待实施计划**（2026-08-26 立项冻结；实施逐项 TDD）。

## 改动 1（腿 1·设计侧）：tiling_strategy 声明标量点

- `.claude/skills/ascendc-op-design-integrate/schema/tiling_strategy.json` 增可选字段
  `scalar_access_points[]`（item: `name` / `location_semantic` / `reason`）；
- `.claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md` 增声明义务：凡 buffer/kernel
  设计决定采用标量数据通路的点，必须给出 name+语义位置+理由（进入产物）；
- `.claude/skills/ascendc-op-design-integrate/SKILL.md` 汇总说明：integrate 把各模板
  声明汇总进 tiling_strategy.scalar_access_points[]；
- 加载期校验：present 时校验 item 三键非空（§1.3，与既有 staging 校验同点）。

## 改动 2（腿 1·coder 侧）：AR-1 收口为可校验引用

- `.claude/skills/ascendc-op-dev-coding/SKILL.md` 维4 AR-1 行与 L382 自检节：
  `reference` 必须命中 `tiling_strategy.scalar_access_points[].name`；无声明可引 →
  该条目改携 `deviation_evidence`（`failure_signature` / `repro_or_log` /
  `why_no_vector_equivalent`），语义上等同 design deviation（与 step-88 precision 侧
  字段同名同义，跨阶段对齐）；
- `.claude/skills/ascendc-op-dev-coding/schema/decision_log.json`：scalar_access_points
  item 增 `deviation_evidence`（object，上述三键），并加描述说明二选一约束；
- 「DataCopy 等价物 → 理由不成立」条款原样保留。

## 改动 3（腿 1·框架侧）：codegen transition 机械校验 + 定向 retry

- `codegen.py` 新增模块级 `_validate_scalar_contract(declared, decision_log, kernel_dir)
  -> list[str]`（纯函数，便于 UT）：
  - `declared`：tiling_strategy.scalar_access_points[] 名集（从 staging 产物读）；
  - 逐点：decision_log.scalar_access_points[] 每条 → `reference ∈ declared` 或
    `deviation_evidence` 三键齐备，否则违约（条目指名）；
  - 簿记覆盖：op_kernel 源码扫描 `SetValue(` / `GetValue(` 计数 > 0 而清单空 →
    「有标量访问未声明」违约；**从磁盘读源码**（state.generated_sources 供 prompt 有
    5000 字截断，不可作判据源）；
- 接入点：与 manifest 机械校验同一调用点（§1.15 单点），违约汇总进既有定向 retry
  反馈（逐条：向量化（若 DataCopy 等价物命中）/ 补引用 / 补证据），不 halt、不新增
  重试循环；
- 违约反馈文案含修复三选一，模型可就地闭环。

## 改动 4（腿 3）：归属边界镜像进 coder skill

- `.claude/skills/ascendc-op-dev-coding/SKILL.md` 会话内构建自检节（L178 附近）增边界
  声明（L3 原文）：会话内自检范围 = 编译 + host 阶段；kernel 阶段错误（vector core
  异常 / 运行期数据错 / 同步竞态形态）不吸收，按原样交棒（框架门
  `_classify_smoke_phase` 会 kernel → D4 precision），kernel 阶段 smoke 红是合法交接；
- `.claude/agents/ascendc-coder.md` 同步一句（若该节存在）。

## 改动 5（腿 2）：交棒证据格式

- `.claude/skills/ascendc-op-dev-coding/SKILL.md` + decision_log schema：增可选字段
  `handoff_evidence[]`（`error_signature` / `repro_or_log` / `excluded_directions[]`）；
  会话内遇 kernel 阶段错误按此落盘后交棒；同步类形态注明疑似类别并指向
  ascendc-sync 选型表（指针非枚举）；
- precision diagnose 侧不新加门（step-88 上下文注入已存在；handoff_evidence 随
  decision_logs/产物文件自然可达——diagnose 读 op 工程产物）。

## 验证

1. UT（先红后绿）：
   - `_validate_scalar_contract`：引用命中/未命中、deviation 三键缺一、清单空+源码有
     标量、清单空+源码纯净、反馈文案含三选一；
   - schema 加载期校验：tiling_strategy 字段形态、decision_log deviation_evidence；
   - 定向 retry 通路上违约汇总可进反馈（复用既有 manifest 校验测试形态）；
2. 全量 `tests/ut --quick`；skill 文本无 UT（结构化 schema 有）；
3. heavy_llm：端到端 codegen 真实链路（含一次 kernel 阶段错误的吸收/交棒行为观察）
   §3.11 待用户决策；
4. 下批跑自然观测：decision_log.scalar_access_points 非空率、kernel 错误交棒率。

## 不做清单

1. 不硬禁 SetValue/GetValue、不限循环数、不做 C++ 深度语义解析（L3 否决项）；
2. 不动 `_classify_smoke_phase` 与 D4 通路（边界已正确，缺的是会话内镜像）；
3. 不做并行度塌缩的机械判据（无结构信号，L3 范围边界）；
4. 不改 precision diagnose 主干（step-88 已覆盖设计上下文；交棒证据是增量输入）；
5. 不做性能门（产权 step-92 选项①，独立立项）。

## as-built（2026-08-26 实施完成）

- **改动 3 修正**：L4 原文「从磁盘读源码」不必要——`agent_result.artifacts` 是完整内存
  dict（5000 字截断只作用于 prompt 注入），`_validate_scalar_contract` 直接扫
  `artifacts` 中 `op_kernel/` 前缀条目即可，无需磁盘读。函数签名实为
  `_validate_scalar_contract(declared, decision_log, sources, op_dir=None)`（op_dir 用于
  deviation_evidence.repro_or_log 相对路径存在性解析）。
- **malformed 清单 = 2 条违约**（非 1 条）：形态违约（非 list）+ 簿记覆盖（源码有访问而
  清单不可用）都是真信号，UT 按此断言。
- **改动 1 超出原文**：除 tiling_strategy.json（optional_fields + example，doc 层约束）外，
  `ascendc-op-tiling-buffer-kernel/schema/tiling_buffer_kernel.json` 的 description + example
  同步增 `buffer_kernel.scalar_access_points[]`（内层可选字段，name/location_semantic/
  reason/derivation/verification）——声明源头在模板产物，integrate 汇总不改写。
- **改动 4 落点**：coder SKILL.md 边界段插在「构建经济性」段后（非 L178 原定位）；
  `.claude/agents/ascendc-coder.md` Coding Rules 末尾同步一句（该节存在，已加）。
- **改动 5 按修订版落地**：无 handoff_evidence schema；kernel 错误交棒走 decision_log
  既有 `known_issues`（边界段内一句指引），同步知识路标不新增。
- **optional_fields 属 doc 层**：tiling_strategy.json 的 optional_fields 描述约束模型产出
  形态，example 是 prompt 可见性载体（既有 schema 惯例一致）；框架侧不校验声明形态
  （空/缺省合法——设计无标量点时省略）。
- UT：`tests/ut/orchestration/test_codegen_scalar_contract.py` 13 用例（引用命中/未命中、
  deviation 三键缺一、repro 相对/绝对解析、簿记空/纯净/非 kernel 源、malformed×2、
  非 dict 条目、transition 定向 retry 路由）；全量 `tests/ut --quick` 3658 passed
  （基线 3645 + 13，零回归）。
- heavy_llm 端到端与下批跑自然观测未做（§3.11 用户决策 / 等真实批次数据）。

## 修订（2026-08-26，随 L3 修订同步；以此版为准）

- **改动 1 重写**：`scalar_access_points[]` 声明锚定 buffer-kernel **R6 举证制**——每条
  挂排除论证（derivation/verification，对齐 tiling_results 既有 `verifiable_claims`
  形态）；buffer-kernel SKILL.md 在 R6 自检项后补一句「排除成立的点进入产物
  scalar_access_points[]」；integrate 汇总不变；precision-perf 性能分析把标量路径列为
  风险项交叉印证。**不再**是自由填表。
- **改动 5 重写（腿 2 降级）**：删除 `handoff_evidence` 新 schema；coder 交棒前把已观察
  kernel 错误现象记入 decision_log 既有 `known_issues` 字段（SKILL.md 一句 + example
  更新）。同步选型路标不新增（diagnose 侧 rules 触发词表已有）。
- **改动 4 补全**：腿 3 以**合格完成路径**形态写入（编译过+host 自检过+kernel 错误已
  记录交棒=合格完成），非禁令。
- **改动 3 补全**：`deviation_evidence.repro_or_log` 增存在性校验（引用的产物路径必须
  真实存在——簿记检查）；UT 补存在性校验用例。
- 验证追加：下批跑观测「设计声明与 coder deviation 的错配率」（任一侧错配=改进信号）。
- **实施注意（§2.11）**：落进 skill/schema 的文案一律用通用语义（如「与 precision
  阶段设计偏离字段同名同义」），不得出现 step-88 等仓内编号——编号只留在 docs/plan。
