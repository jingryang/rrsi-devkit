# precision-debug harness 拒绝 Optional/可空 attr — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`（P1–P5）。
> 同源议题：[[precision-debug-harness-env-pollution]] / [[precision-debug-dtype-coverage-gap]]
>（harness 契约层缺陷族）；本篇聚焦「Optional/可空 attr + 类型名漂移 + 误判族」。

## 决策 1（P1）— None 接受机制：运行期无差别跳过 / `default is None` 判定 / 新增 nullable 字段 → **选「`default is None` 判定」**

利用既有事实：`AttrSpec` **已带 `default` 字段**（`domain/operator.py:48`），requirement 已忠实从
golden `=None` 产出 `default:null`（P1 证据）。故「该 attr 的声明缺省就是 None」是权威既成事实，
无需新增字段、无需改 requirement 管线。

- **选项 A 运行期无差别跳过**（`if v is None: continue`）：改动最小，但把**所有** attr 的 None 都
  放过（含真正必填 attr 误传 None 的用例缺陷），丢了校验意义；判据缺失（§1.12）。
- **选项 B `default is None` 判定**：`if v is None and attr_spec.default is None: 跳过类型校验`。
  判据客观（既有 `default` 字段，权威源于 golden `=None`）。**关键**：该规则对 `default` 为 `0/False/[]`
  的 attr **拒绝** None（default 非 None）——只在「声明缺省即 None」时接受 None，恰是「None 是该 attr
  的合法缺省」的忠实判定，不是「用 default 代理 nullable」的有损代理（早先草案误用 §1.10 否决此项，
  属推理错误，此条更正）。
- **选项 C 新增 `AttrSpec.nullable` 字段**（从 golden `Optional[...]` 注解经 requirement-analyst 显式产出）：
  语义最纯（nullable 一等属性）。但要改 requirement skill + requirement.json schema + AttrSpec，触动
  requirement 共享管线；且只为覆盖「`Optional[X]=5`（Optional 但非 None 缺省）」这一罕见边角——
  违背「不为罕见小型号钻牛角尖」精神，YAGNI。
- **选 B 的理由**（四把尺子）：
  - 可维护：复用既有 `default` 字段，零 schema/管线改动；守住「None 是声明缺省即合法」不变式（§1.13）。
  - 可扩展：任何 golden `Optional[X]=None` → requirement `default:null` 的 attr 自动归位（§1.12 结构信号）。
  - 可诊断：必填 attr（default 非 None）误传 None 仍被拒，保留校验意义。
  - 架构合理：最小正确改动（§1.2）；无需为罕见 `Optional[X]=5` 预建 nullable 字段（真出现再按 §1.12 结构化补）。
- **已知边界（接受）**：`Optional[X]=非None缺省`（如 `Optional[int]=5`）的 attr 传 None 会被拒。极罕见；
  golden 此类签名若需接受 None，届时再上选项 C（结构化 nullable），不为预防它现在加字段。

## 决策 2（P2）— 类型名统一落点：运行期 `.lower()` 容忍 / 加载期单一规范化 → **选加载期单一规范化**

- **选项 A 运行期容忍双形态**：校验器 `expected = attr_spec.type.lower()` 并加 `list[float]` 分支。能让本次跑通，但 `ListInt` 与 `list[int]` **双形态长期并存** = 兼容层（§1.4 禁过渡层 / §2.5 唯一通路），且未知类型名仍静默落兜底（§1.3 推迟到运行期）。
- **选项 B 加载期单一规范化**：在 `AttrSpec` 构造（`domain/operator.py`，单一翻译点）把 `type` 规范化到 canonical（`ListInt→list[int]`、`ListFloat→list[float]`、补全 `list[float]`），**加载期对未知类型名告警/拒绝**（§1.3）；校验器只面对 canonical 形态。
- **选 B 的理由**：消除双形态债（§1.4/§2.5）；未知类型名加载期即暴露（§1.3，正是本次「`ListFloat` 连分支都没有却静默落兜底」的反例）；翻译点单一可维护（类比 §1.9 `to_soc_version` 单一翻译点）。

## 决策 3（P3）— scope_guard 归属判据：错误形态 / 抛错代码 ownership → **选 ownership**

- **选项 A 按错误形态判**（「是 schema 类错 → 归 harness；像 compilation → 归 codegen」）：机制特征代理（§1.10）。语义相反单元共享形态（真正的上游 schema 缺陷 vs harness 自家 schema 闸门），必有一类静默误判——本次正是把 harness 自家 `_validate_attrs` 错误误判成「上游 test_design」。
- **选项 B 按 ownership 判**：归属 = 抛错代码的产权方。`_validate_attrs` ∈ `adapters/npu/runner.py`（框架/harness 自有）→ in-scope（至少不是 test_design 的 cases.yaml）；cases.yaml/kernel 源码错误才算 upstream。
- **选 B 的理由**：业务语义判据（§1.10），语义相反单元 ownership 不同，不会共享误判；与 §2.9「门不越界查上游 / 按 ownership 定 scope」一致。
- **边界**：决策 1+2 落地后，harness 不再 abort，scope_guard 碰不到本 case——决策 3 是**二级硬化**（防同类误判再发），非主修复。

## 决策 4（P4）— 「passed」计数：保持 `total−failed` / 仅在真跑过时计通过 → **选后者**

- **选项 A 维持现状**（`passed = total − failed`）：hard_error/schema-abort 期也产出「19 passed」，把「未测」伪饰成「通过」（§3.4 掩盖）。
- **选项 B 按真实执行计**：`last_result_json=null` / hard_error-at-schema（0 条上板）时，`passed_count=0`（或显式 N/A），report 不渲染「最优/收敛」假信号。
- **选 B 的理由**：§1.2 可诊断 + §3.4 禁止掩盖；与 §1.13「golden 是权威」精神一致——没跑就不能声称通过。

## 决策 5（P5）— failure_type 分类：关键词 / 结构性信号 → **选结构性**

- **选项 A 关键词**（`Error:` 前缀 → compilation）：机制特征代理（§1.10），schema 错误错路由到 compilation 处置。
- **选项 B 结构性信号**：按抛错点/阶段判（C++ 编译器阶段失败 = compilation；Python schema/契约校验抛错 = schema/contract；kernel runtime 错误码 = runtime）。
- **选 B 的理由**：§1.10；分类决定路由（compilation → codegen 重试；schema/contract → 契约修复；runtime → precision_debug），误判致错误路径。

## 决策 6 — 分层与优先级：主修复 vs 二级硬化/可观测性

- **主修复（根治本次 halt）**：决策 1（nullable）+ 决策 2（类型名加载期规范化 + 补 `list[float]`）。
  二者落地后 harness 不再对合法 None abort，用例真正上板，本次 halt 消失。
- **二级硬化 / 可观测性（独立于本次根因，对任何 halt 都该修）**：决策 3（scope_guard ownership 判据）、
  决策 4（passed 计数诚实）、决策 5（failure_type 结构性分类）。
- 按 §1.2「单一方案无法同时满足时优先组合」：主修复承担根治（正确改动），二级项承担可诊断/防误判
  （可观测 + 宽容兜底）。两者**分层实施、分别验证**，不混为同一改动。

## 决策 7 — 不采纳「在 cases.yaml/loader 里把 output_size 兜底填值」

- 把 `output_size` 从 `scale_factor*input_shape` 在 loader 侧物化，能让本次跑通，但**反向修正了正确的上游**
  （cases.yaml 忠实 golden Optional 语义，P1 已证），违反 §1.13（框架应忠实消费 golden 事实，不得用工程
  逻辑「修正」合法的 None）。且耦合「scale_factor↔output_size 互斥」这一具体语义到 loader（§1.12）。
  本决策**否决**该方向，留此条防止后续重提。

## 决策 8 — 构造性保证优先（§2.9）：基于既有 spec 字段 > 新增检查门

- 决策 1+2 合起来是**构造性保证**而非「加检查门」：`default` 是 AttrSpec 既有权威字段（加载期定型，
  源于 golden `=None`），canonical type 在加载期单一规范化定型。校验器路径上「声明缺省为 None 的 attr
  取 None」恒为合法、canonical type 恒走对 typed 分支——「None 被误拒 / list 型落兜底」在构造上不再可能。
  优于「校验器里加 if 分支硬编码类型名」（后者是检查门，仍可被新类型名绕过）。与 §2.9「构造性保证优先
  于检查门」一致；且不新增字段（§1.4 不留过渡层）。
