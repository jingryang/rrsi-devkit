# L3 — 跨模板一致性判定是「越界查上游」：完整论证

> 目的：论证 anchor-consistency 的「跨模板一致性判定」（AC3 跨模板部分）违反 §2.9「门不越界查上游」，应删除。供决策「删不删这个门」。
> 关联：L3 `02-analysis.md` Q16（系统根因）、L1 `01-problems.md` P13（AC3 证据缺失）。
> 本论证须经得起反问：每条结论给出事实证据 + §2.9 判据对照。

---

## 一、结论（先行）

anchor-consistency 的「跨模板一致性判定」（`SKILL.md` §3，查 TilingKey / workspace / dtype 路由）是**越界查上游**（§2.9 违反），其「字段名白名单漂移」是越界查的**必然结果**，不是「字段没对齐」的偶发失误。彻底解决 = **删除该判定**，让一致性由「单一作者 + 下游忠实消费」构造性保证。

## 二、三个检查项各有「单一作者」（事实证据）

| 检查项 | 单一作者 | 事实证据 |
|---|---|---|
| TilingKey 定义一致性 | `template_division` | `template_division.json` 的 `templates[].tiling_key`（本批 =1/2）；tiling 三段（split/buffer_kernel/precision_perf）**从不写 tiling_key**（P135 坐实，本批复核 False×3） |
| Dtype 路由表一致性 | `template_division` | `templates[].route_condition`（本批 `interpolation_mode=='bilinear'/'nearest'`）决定 dtype→模板映射 |
| Workspace 分配不重叠 | `buffer_kernel`（可选字段）+ 模板互斥 | `route_condition` 决定「同一时刻用哪个模板」；模板互斥 → workspace 天然不重叠 |

**关键**：这三个检查项要查的「一致性」，其**全部事实都已在单一作者处定义**——不需要「下游汇总多个模板的产物」才能知道。

## 三、为什么「单一作者 + 下游忠实消费」能构造性保证（§2.9 依据）

§2.9：「若一致性可由『下游消费上游既定前提』构造性保证（下游产物由上游派生），就不该再加跨段门查它」。

- **TilingKey**：`template_division` 单一作者定义 `tiling_key`，tiling 三段**忠实消费**（它们不写、不重定义，只按 template 生成各自段）→ TilingKey 天然一致，**不存在可查的冲突**。若某模板「不忠实消费」（自己改了 tiling_key），那是「下游违反契约」，归下游产出校验（见 §六），非跨模板门。
- **dtype 路由**：`route_condition` 单一作者自洽（同 dtype 映射唯一模板）→ 天然一致。若不自洽，是 `template_division` 自己的问题，归它自检。
- **workspace**：模板互斥（route_condition）→ 不同模板 workspace 天然不重叠。若重叠，是 route_condition 不互斥，归 `template_division`。

## 四、为什么「跨模板门查它们」是越界查（§2.9 判据对照）

§2.9 判据：「一项检查若不需本 stage 上下文、纯凭上游产物 + 权威源即可做，就属上游自检，不归下游门」。

- 「TilingKey 一致性」= 纯凭 `template_division`（上游权威源）即可判定，不需 anchor-consistency 的任何上下文 → **属上游自检**。
- 「dtype 路由一致性」= 纯凭 `route_condition` → **属上游自检**。
- 「workspace 不重叠」= 纯凭「模板互斥」（route_condition）→ **属上游自检**。

三项都落入 §2.9 的「门越界查上游」：查了又报 `target=tiling`（回退上游），而问题本应在上游自检闭合。这正是 §2.9 明令禁止的「查了又报 target=上游 让控制流兜底」。

## 五、字段漂移是越界查的必然结果（证据链）

1. 越界查「TilingKey/workspace/dtype」需要「从 tiling 段提取这些字段」→ 于是 `_extract_shared_summary` 手工维护一个「字段名白名单」。
2. 上游 schema 演进（字段名改：axis/tile/key_parameters/verifiable_claims/compute_dtype…）→ 白名单没跟上 → **漂移**。
3. P135 修了「tiling_key 一个死字段」（移出白名单），但**「越界查」这个设计本身还在** → 其他字段继续漂移。
4. 本批坐实：白名单 5 字段（tiling_data_fields/workspace/compute_dtype/dtype/buffer_allocation）仅 compute_dtype 命中，**其余 4 个是死字段**。

**根因链**：越界查 → 手工字段名白名单 → 上游演进漂移 → 提取恒空 → AC3 `unverified` 噪音。**只要「越界查」还在，就永远有下一个死字段要修**——这是用户「做过多次分析还是反复出现」的根本原因。

## 六、删除后，一致性如何保证（含「下游违反契约」的检测归属）

删除「跨模板一致性判定」后：

- **一致性本身**：由「单一作者（template_division/buffer_kernel）+ 下游忠实消费」构造性保证（§2.9）。
- **下游违反契约的检测**（tiling 段不忠实消费 template_division 定义）：由「**tiling 段产出校验**」承担——tiling 段产出时校验「消费的 tiling_key/route_condition 与 template_division 一致」，缺失/不一致即时报错（§1.3 加载期校验）。这是「下游自检」，不是「跨模板门」。

## 七、AC3 的「integrate 类」与 AC0 的归属（完整覆盖，不留死角）

- **AC3 integrate 类**（跨模板字段命名/接口不一致）：这是「整合层统一」的职责。integrate 消费各模板产物做整合，字段命名不一致由 **integrate 消费时构造性消解**（§2.9 下游忠实消费上游既定前提），不需要 anchor-consistency 跨模板查。故 AC3 integrate 类也越界。
- **AC0 骨架级 API 全局判定**：SKILL.md §1 当前「从 tiling_shared_summary 判定算子是否含骨架级 API」，这是**第二个判定来源漂移**——「骨架级 API」是算子语义事实（归 general_design 的 LP 分类 / golden），不从 tiling 段产物摘要判定。删除「跨模板一致性判定」后，AC0 的判定来源也需一并改到算子语义源头。

**推论**：删除「跨模板一致性判定」+ AC0 改语义源头后，`tiling_shared_summary` 这个中间产物**整体不需要**了——`_extract_shared_summary` 连同「字段名白名单」这个漂移根源一起消失。

## 八、风险与边界（诚实标注，经得起反问）

**反问题：有没有「真的需要跨模板查、单一 producer 看不到全貌」的东西？**

候选：无。「TilingKey / workspace / dtype 路由」三者的全貌都在 `template_division`（单一作者）处可见——它不是「分散在多个 producer、单一 producer 看不到」的跨 agent 信息。它满足 §2.9 的「构造性保证」，不满足「跨 agent 信息对齐」的例外。

**反问题：删了门，上游（template_division）自己写错 tiling_key/route_condition 谁兜？**

由「上游自检」兜：`template_division` 产出时校验「route_condition 互斥 + tiling_key 唯一」，这是它本职自检（§2.9 自检闭环），不是下游门越界兜。若担心「上游自检缺失」，正确做法是**补上游自检**，而非「下游门越界查」（§2.9 禁止「查了又报 target=上游」）。

**反问题：会不会删了门反而丢掉了「真实存在的跨模板 bug」？**

不会。若某模板 tiling 段「不忠实消费」template_division（如改错了 tiling_key），这会体现在「该模板的 tiling 产物」里，由「tiling 段产出校验」兜住（§六）。这是「下游自检」，比「跨模板门汇总后才查」更早、更精确。

## 九、决策点（待拍板）

1. 删除 `anchor-consistency/SKILL.md` §3「跨模板一致性判定」+ 相关 prompt/输入（`tiling_shared_summary`）。
2. AC0 骨架级 API 判定改从 general_design LP 分类（或 golden）。
3. 删除 `design_substages.py` `_extract_shared_summary` + `_upstream_inputs` 的 `tiling_shared_summary`。
4. 补「tiling 段产出校验」（消费 tiling_key/route_condition 与 template_division 一致）+ 「template_division 自检」（route_condition 互斥 + tiling_key 唯一）——这是删除门的「上游兜底」。
