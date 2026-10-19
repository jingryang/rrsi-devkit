# P44/P45 — 详设反馈通路收口 — 实施方案（第四层）

> 状态：动手前配方（拍板后即实施）
> 层级：**第四层 / 实施方案**。具体改哪个符号、什么顺序、怎么验证。
> 覆盖问题：P44（check 越界）、P45（loopback 消费端契约缺失）。
> 承接：`23-check-feedback-loop-analysis.md`（L3，已拍板 P44=B+C、P45=第一刀+(a)）。
> 范围：P44-B（能力约束）+ P44-C（schema 分层 verdict/remediation + 改造令告警）+ P45 第一刀（`_feedback_section` 共用）+ P45-(a)（issue 指纹激活停滞检测）。
> 约定：按符号定位（不写 file:line）；外部依赖（CANN / 知识库文档 / chip spec）只读；issue_id 工程派生不入 schema。

---

## 0. issue 结构统一设计（贯穿 P44-C 与 P45-(a)，避免两次改 schema）

issue 新结构（P44-C 新增 `verdict`/`remediation` 两字段；其余沿用）：

```
{
  "code": "AC2",                 # 现有：语义类型
  "severity": "blocker",         # 现有
  "verdict": "infeasible",       # P44-C 新增（推荐）：判定面 unverified | infeasible | verified
  "detail": "声称 Gather 不可用，但 Gather 指令明文可用",   # 现有：只写事实陈述，严禁含结构改造令
  "remediation": "改用 Gather 重写该 tiling 段",           # P44-C 新增（可选）：补救建议，非强制
  "target": "tiling",            # 现有
  "target_template": "T1"        # 现有
}
```

工程派生（P45-(a)，**不入 schema**、不需 agent 产出）：

```
issue_id = f"{code}@{target_template or target}"
```

- `verdict` 与顶层 `status`（completed|blocked）不同层级、不同语义，不冲突。
- `verdict` 推荐（非 required）：缺失时渲染按 `detail` 原样降级，不阻断；SKILL 强引导 agent 填。
- `issue_id` 纯工程层（停滞检测用），不进 schema → P44-C 改 schema 与 P45-(a) 改 `error_signature` **零交叉**。

---

## 1. 时序（承接 L3 §5，关键）

1. **Step1 P44-C**（schema 分层 + 渲染 + 告警）— 必须先于第一刀。
2. **Step2 P44-B**（consistency 能力约束）— 引用 `verdict=unverified` 概念，排 Step1 后。
3. **Step3 P45 第一刀**（`_feedback_section` 只读判定面）— 读反馈时 `remediation` 已是独立字段并标「非强制」，不会把改造令当判决执行。
4. **Step4 P45-(a)**（gate `error_signature` 激活停滞检测）— 独立，最后。

> 若先做第一刀而不做 P44-C：`detail` 里的改造令（fp32/Cast/tileLength）会真正灌进 tiling prompt，比现状（反馈没进 prompt、空转）更毒。故 Step1 不可后置。

---

## 2. Step1 — P44-C：schema 分层 + 渲染 + 改造令告警

### 2.1 schema（三个 example + description）

| schema 文件 | 改动 |
|---|---|
| `anchor_report.json`（consistency） | example issue 加 `verdict`/`remediation`；description 增「verdict=判定面(unverified/infeasible/verified)；remediation=可选补救建议(非强制)；detail 只写事实陈述，不得含结构改造令」 |
| `blocking_status.json`（validate / general-review 复用） | 同上 |
| `anchor_template_report.json`（per-template） | 同上 |

### 2.2 SKILL 引导（三处，软兜底 — §6.4 告警为主，SKILL 配合）

- `ascendc-op-design-anchor-consistency/SKILL.md`：已申明「只汇总不重查」，补「判定写 `verdict`、补救写 `remediation`、`detail` 严禁结构改造令；缺证据的 claim 标 `unverified` 转 human，勿判 `infeasible`」。
- `ascendc-op-design-validate/SKILL.md`、`ascendc-op-design-anchor-per-template/SKILL.md`：补判定/补救分离 + detail 禁改造令。

### 2.3 issue_render 渲染判定/补救

`render_issue`（issue_render.py，runner 日志 + graph_executor 路由摘要共用）：
- 有 `verdict` → 前缀 `判定=verdict`；无则按原样（降级）。
- 有 `remediation` → 后缀 `建议(非强制): remediation`，与 `detail` 分行，明确非判决。

### 2.4 detail 改造令告警（可诊断不阻断 — §6.4 先告警）

issue_render.py 新增 `lint_directives(issues) -> list[str]`：扫各 issue 的 `detail`，命中改造令关键词（初版：`fp32`/`Cast`/`tileLength`/`tile_length`/`分核`/`改写`/`换成`/`必须`）返回命中描述；纯事实陈述返回空。
- 调用点：三个 gate 的 `transition` 解析出 issues 后调一次，命中则 `Logger.warning`（产出端即告警，非消费端）。
- helper 放 issue_render.py（与 `render_issue` 同域）。

### 2.5 TDD

- UT `render_issue`：带 `verdict`+`remediation` → 输出含「判定=」「建议(非强制)」；仅老五字段 → 降级原样。
- UT `lint_directives`：detail 含 `Cast`/`tileLength` → 命中；纯「声称 X 不可用，但 Y 明文可用」→ 空。
- schema：加 example 字段，无逻辑测试；schema loader UT 验证新字段可选（不报缺失）。

---

## 3. Step2 — P44-B：consistency 证据源能力约束

### 3.1 落点（核实后，修正 L3 §6.2）

- `AnchorConsistencyStage._upstream_inputs` 本就**只传 `anchor_template_reports` + `tiling_shared_summary`，不传原始知识库文档** → B 的「inputs 不传文档」已成立，非落点。
- 真正越权通道：consistency 复用 `ascendc-design-anchor` agent（`allowed_tools` 含 `Read`/`Grep`）+ SKILL 引导「Grep ascendc-dev-knowledge 查证 API 能力」（该引导本是为 per-template 骨架级查证而设）→ consistency agent 在汇总关卡也去 Grep 重查。
- agent 工具层无法精确切路径（`Read`/`Grep` 通用），故硬落点是 **stage 层 prompt 注入**（每条消息都带，比 SKILL 软引导硬）。

### 3.2 改动

- 基类 `_DesignSubstage._build_prompt` 加扩展钩子 `_extra_prompt_sections(self, state) -> list[str]`（默认 `[]`），在 `output_boundary` 之后、`_loopback_feedback` 段之前插入。零侵入、复用 Stage 扩展模型。
- `AnchorConsistencyStage` override `_extra_prompt_sections` 返回证据源约束段：
  > 「**汇总关卡唯一证据源 = 各模板的 anchor_template_report**；禁止 Grep/Read ascendc-dev-knowledge 原文重新硬件查证（per-template 已查）；对 per-template 未覆盖的能力缺项，标 `verdict=unverified` 转 human，不得自行判 `infeasible` 并下结构改造令。」
- per-template **不动**（它该查骨架级 API，职责正确）。

### 3.3 TDD

- UT：`AnchorConsistencyStage._build_prompt` 输出含「唯一证据源」「禁止…重新硬件查证」；`AnchorPerTemplateStage._build_prompt` 不含该禁令。
- UT：基类默认 `_extra_prompt_sections` 返回 `[]`（不污染其它 stage）。

---

## 4. Step3 — P45 第一刀：`_feedback_section` helper + tiling 消费

### 4.1 改动

- 从基类 `_build_prompt` 内联的反馈渲染段（读 `_loopback_feedback`）抽成 `_feedback_section(self, state) -> str | None`。
- 渲染只取判定面：`verdict`/`detail` 为事实主体；`remediation` 标「建议(非强制)」前缀（复用 `render_issue(detail_limit=None)`，不截断——下游 LLM 须据此行动）。
- 基类 `_build_prompt` 调 `self._feedback_section(state)`。
- `_TilingSegmentStage._build_prompt`（当前重写覆盖基类、丢了反馈段）同样调 `self._feedback_section(state)` → **修复 run 的 3 轮零消费直接根因**。

### 4.2 TDD

- UT `_feedback_section`：`_loopback_feedback` 非空 → 返回含「## 上次反馈」+ 判定 + 建议(非强制)；空 → `None`。
- UT `_TilingSegmentStage._build_prompt`：`_loopback_feedback` 非空 → prompt 含「## 上次反馈」（回归 run bug）；空 → 不含。
- UT：基类其它子类（如 `ValidateStage` 的上游生成者）prompt 仍含反馈段（无回归）。

---

## 5. Step4 — P45-(a)：gate `error_signature` + `issue_fingerprint` 激活停滞检测

### 5.1 机制（已核实）

- 停滞检测：`graph_executor` 对 corrective 路由按 `(from, to, sig)` 在 `scope["history"]` 去重计数，`same>=2` 则 halt corrective（`stagnation` event）。
- `sig = child.stage.error_signature(state)`；默认实现 = `state.last_error.message[:200]`。
- gate stage（`fail_strategy="continue"`，走 blocking_issues 路径）**不设 `last_error`** → 默认 `error_signature` 返 `""` → `if effective_type=="corrective" and sig:` 因空跳过 → **gate corrective 永不触发停滞检测**（run 的「配额内 3 轮空转 + 逐字重报」根因之一）。

### 5.2 改动

- issue_render.py 新增 `issue_fingerprint(issues) -> str`：对 outstanding issues 派生 `issue_id = f"{code}@{target_template or target}"`，**排序**后 join（稳定）；空集 → `""`。
- 三个 corrective-capable gate override `error_signature`：`return issue_fingerprint(self.blocking_issues(state))`：
  - `AnchorConsistencyStage`
  - `ValidateStage`
  - `GeneralDesignReviewStage`
- `AnchorPerTemplateStage`（`max_iter=1`、无 corrective）**不加**，注明理由；避免无意义扩散（[[avoid-overdesign-prefer-reuse]]）。
- 效果：gate 连续两轮 outstanding issue_id 集合相同 → `same>=2` → halt corrective。复用既有停滞检测，**零新出口/状态机**。issue 集合变化（问题换了）→ 指纹变 → 计数重置，不误判停滞。

### 5.3 TDD

- UT `issue_fingerprint`：两 issues → 稳定排序串；打乱顺序 → 同串；空 → `""`。
- UT 三个 gate `error_signature`：blocking_issues 非空 → 返回指纹；空 → `""`（不误触停滞）。
- 集成：gate 两轮同指纹触发 `stagnation` event + halt — 由既有 `test_graph_executor` 覆盖路径，gate `error_signature` 非空即激活，无需新增集成用例。

---

## 6. Step5 — 回归 + 收口

- `pytest` UT 全量（无 heavy_llm，§3.6/§3.11）；前台执行（§3.3）。
- L1 `06-problems.md`：P44/P45 状态 → ✅；变更记录指向本文 + 23-analysis。
- L3 `23-...-analysis.md` §6 待确认点：写定论（①B+C ②inputs 已不传文档+stage prompt 硬约束 ③仅(a) ④告警）。
- L2 索引：P44/P45 进度同步。
- **诚实记录**：heavy_llm e2e（重跑 run 验证 P44/P45 修复）本次**未覆盖**（§3.11，用户决策）；待用户在关键节点确认后跑。

---

## 7. 不做范围（后置，按真实残余滚动）

- P45-(b) `must_hold` 谓词（机判「是否已修」）：第一刀+(a) 上线后，若仍频发「问题解决但框架没识别」再立。
- P45-(c) 配额耗尽 + 仍有 outstanding → 自动 escalation：同上，依赖 (a) 的 outstanding 追踪实据。
- P44 detail 改造令从「告警」升级「schema 拒绝」：告警运行一段无副作用后视情升级。
- consistency agent 工具层路径级限制：工具层无法精确切，不追求。
