# codegen skill A5 编码硬约束缺口 — 问题记录（L1）

> 纯事实快照（哪里不够 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发：审查 codegen skill 上游复用（见 ../codegen-skill-upstream-reuse/）时，对照 Phase C 编码 skill
> 发现 A5 编码约束是当前 skill 最大内容缺口，但与「源产物复用」正交 → 单独立项。

## P1 — 当前 codegen skill 对 A5 只有一句，无可执行编码红线
`.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/SKILL.md` Step4 编程模型路由表对 A5 仅：
「A5 Regbase | 路径三 | VF 入口 + RegTensor + 910D 约束」——**无任何可执行的 A5 编码红线/约束清单**。
agent 拿到 A5 任务时不知道 Vector 执行域内什么能写、什么禁写，只能靠 LLM 自由发挥 → A5 kernel 极易
编译失败（Regbase 编程模型约束强，违反即编译报错）。

## P2（对照，外部只读参考）— Phase C s4-coding 有完整 A5 红线
`ascendskills/agents/ascendc-dev-s4-coding.md`（只读参考，只取思路不照搬）：
- §4.5「A5 Regbase 强制约束」九条（Vector 执行域内：禁 A3 DataCopy / 禁 TILING_KEY_IS /
  禁 LocalTensor 直接计算 / 禁 A3 内存对象 / 禁 A3 高阶 API / 禁 callee 交叉调用 / VF 必须 inline void /
  禁 pass-by-reference；外加 SIMD/SIMT 隔离）。
- §4.6「A5 Regbase 专属编码规则」：VF 函数参数类型检查（仅 `__ubuf__ T*` 和 PoD）、修饰符检查
  （inline + void）、RegTensor≤32、MaskReg≤8、地址转换（GetPhyAddr）、UB DCache 预留（SIMD+SIMT 混合
  预留 8KB、SIMT DCache≥32KB）。
- §4.4a VF 指令参考预查询（`regbase-vf-test/references/vf-instructions/`：Cast/Interleave/LoadAlign/
  StoreAlign 等 VF 指令语义、组合模式、陷阱）。

## P3 — DevKit 是否有等价 A5 资源待查
Phase C 的 A5 红线 + VF 指令参考位于 `ascendskills/skills/regbase-vf-test/references/`（含
`ascend_regbase_programing_guide.md`、`ascend950_hardware_and_pipeline_control.md`、`vf-instructions/`）。
DevKit 当前 `.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/` 下**只有 SKILL.md + schema/**，
无 A5 专属参考文档。落地前须确认：DevKit `resources/` 或 skill 目录是否已有等价 A5/Regbase/VF 参考资源，
还是需新建/引入（属资源归属 §1.5/§2.2 决策，不在本 L1 范围）。

## 状态

已实现（2026-07-11）。L3 见 `02-analysis.md`、L4 见 `03-impl.md`。

- **资源归属结论（P3）**：DevKit 已有完整 A5/VF 知识于 `ascendc-dev-knowledge`（`shared` 插件，coder 必载）——
  `api_reference_docs/SIMD_API/基础API/Reg矢量计算/`（VF 指令签名，等价 vf-instructions/）+ `910D_knowledge_extra/`
  （Regbase 编程模型）。缺口是「编码红线」非「知识」。`evolution-knowledge` 虽在 skill `skills:` 过滤器内，
  但未被 ascendc-coder 加载（不在 stage-codegen/codegen-coder-extra/shared 任一插件），故不依赖。
- **改动**：SKILL.md Step3 A5 指针精确化（指 SIMD_API/Reg矢量计算 + 910D_knowledge_extra 两处）；
  Step4 新增「A5 Regbase 编码红线」subsection（Vector 执行域定义 + 九条强制约束表 + 专属规则）；
  Step6 新增 A5 专属自检 6 行（VF 签名/RegTensor≤32/MaskReg≤8/Membase API 入侵/SIMD-SIMT 隔离/GetPhyAddr）。
- **守护**：`tests/ut/orchestration/test_codegen_a5_constraints.py`（6 测试，grep 断言）。
- **验证**：UT 1799 全绿 / ST 105 passed、3 skipped（external_repo env）、7 deselected（heavy_llm）、0 fail。
- **未覆盖**：heavy_llm E2E（真跑 A5 算子 codegen 验红线不违例）待用户确认后跑（§3.11，见 L4 后续段）。
