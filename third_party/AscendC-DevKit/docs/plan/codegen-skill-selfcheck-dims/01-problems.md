# codegen skill 多维自检缺口 — 问题记录（L1）

> 纯事实快照（哪里不够 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发：审查 codegen skill 上游复用（见 ../codegen-skill-upstream-reuse/）时，对照 Phase C 编码 skill
> 发现自检维度缺口，但与「源产物复用」正交 → 单独立项。

## P1 — 当前 codegen skill Step6 自检只有 6 项泛化检查
`.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/SKILL.md` Step6 自检表仅：32 字节对齐 /
TilingData 一致性（host↔kernel）/ API 签名合规 / 文件完整性 / ACLNN 符号一致性 / TILING_KEY_IS 分支覆盖。
**缺**：禁硬编码硬件参数的机械检查、buffer-pipeline 红线（主循环数据搬运/嵌套循环 GM 单点/非对齐
DataCopyPad）、dtype 一致性（OpDef dtype ⊇ IO spec / Tiling 分支 ⊆ OpDef / Plugin cast 兜底）等维度。

## P2（对照，外部只读参考）— Phase C 编码 skill 自检分维2/维3/维4/维5
`ascendskills/skills/ascendc-op-dev-coding/SKILL.md`（只读参考，只取思路不照搬）Step6：
- 维3：禁硬编码硬件参数（op_host/*_tiling.cpp、op_kernel/* 含裸 `=32`/`=262144`/`=14336` 等 CORE_NUM/
  BLOCK_NUM/UB_SIZE/对齐常数 → 改运行时查询 GetBlockNum/GetUBSize 或 sizeof(T)/GetSizeByDataType）。
- 维4：AR-1 主循环禁 GetValue/SetValue 数据搬运（过滤注释+TilingData 元数据+纯索引）/ AR-2 嵌套循环 GM
  单点访问 / AR-3 非对齐场景用 DataCopyPad 而非单点。
- 维5：OpDef dtype ⊇ 详设 IO spec dtype / Tiling dtype 分支 ⊆ OpDef / Plugin cast 兜底检测。
- 维3「禁硬编码硬件参数」与本项目 `.claude/rules/ascendc-dev.md`「No hardcoded hardware params」一致。

## P3 — 维4/维5 依赖 DevKit 暂缺的 redline/registry 资源
Phase C 维4 引用 `ascendc-op-design-shared/references/buffer_pipeline_redline.md`（E1/E2/E3 判定）、
维2/维5 引用 `high_risk_api_registry.md`（C1-C4 准入）。DevKit 当前：
- `find` 仅命中 `.claude/plugins/stage-testdesign/.../redline_rules.md`（测试设计用，非 codegen 编码自检）与
  `evolution-strategies/.../P82_manual_multi_buffer_pipeline_policy.md`（进化策略卡，非编码红线）。
- **无 codegen 编码自检可用的 buffer_pipeline_redline / high_risk_api_registry**。
故 ⑤ 落地有前置：要么先补这两份资源（§1.5 资源归属决策），要么把维4/维5 的判定规则直接内联进 skill
（不依赖外部 registry，但 skill 会增厚，须权衡 §2.7）。

## 状态

已实现（2026-07-11）。L3 见 `02-analysis.md`、L4 见 `03-impl.md`。

- **资源前置结论（P3）**：`buffer_pipeline_redline` / `high_risk_api_registry` 在 DevKit 确认不存在
  （grep 0 命中，仅 testdesign redline_rules）。决策**内联判定规则进 SKILL.md Step6**，不补 registry——
  维3/维4/维5 规则机械简洁（grep 模式 + 字段比对）、跨算子跨仓通用（§2.7 核心）、保 §2.1 即插即用、
  仅增 7 行表项不触发膨胀；不照搬 Phase C E1/E2/E3·C1-C4 标签组织。
- **改动**：SKILL.md Step6 新增 维3（禁硬编码硬件参数 → GetBlockNum/GetUBSize/sizeof/GetSizeByDataType）+
  维4（AR-1 主循环禁 GetValue/SetValue 搬送 / AR-2 嵌套 GM 单点 / AR-3 非对齐 DataCopyPad）+
  维5（OpDef dtype ⊇ IO spec / Tiling dtype ⊆ OpDef / Plugin cast 兜底）共 7 行。
- **不重复**：BUFFER_NUM↔详设 / workspace 分配 / TilingData 字段↔源 已由上游复用 ②（字段↔源）+ ③（锁定项入口 fail-fast）覆盖，本工作不造同维自检。
- **守护**：`tests/ut/orchestration/test_codegen_selfcheck_dims.py`（4 测试，grep 断言）。
- **验证**：UT 1799 全绿 / ST 105 passed、3 skipped（external_repo env）、7 deselected（heavy_llm）、0 fail。
- **未覆盖**：heavy_llm E2E（真跑 codegen 验维3/4/5 自检 catch 典型违例）待用户确认后跑（§3.11，见 L4 后续段）。
