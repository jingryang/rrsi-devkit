# codegen skill A5 编码硬约束 — 实施（L4）

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`，事实见 `01-problems.md`。
> 目标文件：`.claude/plugins/stage-codegen/skills/ascendc-op-dev-coding/SKILL.md`
> 纯 skill 内容改动（编码校验性质），**不改 codegen.py**——programming_model 已物化进 meta.json（上游复用 ② + delivery 测试已守护），skill 读 meta.json 走 A5 路径，无需 Python 改动。
> 与上游复用 ①②③（输入契约表 / Step2 锁定项 / Step6 字段↔源）同 skill，改动落 Step3 / Step4 / Step6，不冲突。

## 改动 1 — Step3 知识库查阅：A5 指针精确化（决策 2）

把 Step3 现有一句「芯片特定编程约束（A5 场景查 910D_knowledge_extra）」**精确化为两处指向**（ascendc-dev-knowledge 已加载，VF 指令 + Regbase 模型分指）：

```
- 芯片特定编程约束：A5 Regbase 场景查 `ascendc-dev-knowledge` 两处——
  - VF 指令签名/语义：`api_reference_docs/SIMD_API/基础API/Reg矢量计算/`（Cast/Interleave/Move/
    Reg数据搬运 连续对齐搬入·搬出·连续非对齐搬入·搬出/Reduce/Gather/类型转换/数据重排 等，等价 VF 指令参考库）
  - Regbase 编程模型与约束：`910D_knowledge_extra/`（RegTensor/MaskReg/AddrReg/GetPhyAddr/
    asc_vf_call/SIMD-BuiltIn关键字和API/SIMD与SIMT混合编程/AI-Core-SIMD编程/AIC和AIV独立运行机制）
```

## 改动 2 — Step4 分层编码：新增「A5 Regbase 编码红线」subsection（决策 1/4）

在 Step4 编码顺序之后、Step5 之前，新增 subsection（仅 `programming_model == A5 Regbase` 时强制）：

- **Vector 执行域定义**：A5 中 Vector 计算发生在 `__simd_vf__` / `__simt_vf__` 函数体或 `__VEC_SCOPE__` 代码块内；域内受 Regbase 约束，域外（同函数内）允许普通 scalar。
- **九条强制约束表**（违反即编译失败）：禁 A3 DataCopy（域内禁 DataCopy/DataCopyPad，SIMD 用 LoadAlign/StoreAlign）/ 禁 TILING_KEY_IS（用 VF_CALL/asc_vf_call 调度）/ 禁 LocalTensor 直接计算（先 GetPhyAddr 转 `__ubuf__ T*`）/ 禁 A3 内存对象（域内禁 pipe/inQueue/outQueue/TBuf/AllocTensor/FreeTensor，仅 RegTensor/MaskReg/`__ubuf__*`）/ 禁 A3 高阶 API（用 `AscendC::MicroAPI::Add` 等）/ 禁 callee 交叉调用（SIMD 只调 `__simd_callee__`，SIMT 只调 `__simt_callee__`）/ VF 必须 inline / VF 必须 void / 禁 pass-by-reference（仅 `__ubuf__ T*` 或 PoD）。
- **专属规则**：VF 参数仅 `__ubuf__ T*`/PoD；VF 修饰符 inline+void；单 VF 内 RegTensor≤32、MaskReg≤8；传入 VF_CALL 的 LocalTensor 须 GetPhyAddr 转 `__ubuf__*`；UB DCache 预留（SIMD+SIMT 混合预留 8KB，SIMT DCache≥32KB）。

## 改动 3 — Step6 编码自检：新增 A5 专属自检行（决策 4）

Step6 表新增（仅 A5 Regbase 适用）：

| 检查项 | 方法 | 失败处理 |
|---|---|---|
| VF 函数签名合规 | `__simd_vf__`/`__simt_vf__` 必须 inline void，参数仅 `__ubuf__ T*`/PoD | status=fail |
| RegTensor 数量合规 | 单 VF 内 RegTensor 声明 ≤32 | status=fail |
| MaskReg 数量合规 | 单 VF 内 MaskReg 声明 ≤8 | status=fail |
| Membase API 入侵 | VF 函数体内禁 DataCopy/TILING_KEY_IS/A3 高阶 API（无 MicroAPI 命名空间）；Cube 部分搬运不限 | status=fail |
| SIMD/SIMT 隔离 | `__simd_vf__` 不调 `__simt_callee__`，反之亦然 | status=fail |
| GetPhyAddr 地址转换完整 | 传入 VF_CALL/asc_vf_call 的 LocalTensor 均经 GetPhyAddr 转 `__ubuf__*` | status=fail |

## 顺序

1. TDD 先写测试（见下）。
2. SKILL.md 统一改（④+⑤ 一次改完，避免 skill 多次大改）：改动 1（Step3）→ 改动 2（Step4 红线）→ 改动 3（Step6 A5 自检）+ ⑤ 的维3/维4/维5（同 Step6 表）。
3. 跑测试至绿。

## 验证（TDD）

`tests/ut/orchestration/test_codegen_a5_constraints.py`（参考 `test_codegen_upstream_reuse.py::TestSkillDocSourceContract` grep 断言写法）：
- `test_step3_points_a5_knowledge_to_ascendc_dev_knowledge`：SKILL.md Step3 含 `SIMD_API` + `Reg矢量计算` + `910D_knowledge_extra`（两处指向），不含 `evolution-knowledge`（决策 3：不依赖未加载 skill）。
- `test_step4_has_a5_regbase_redlines`：SKILL.md 含「Vector 执行域」定义 + 九条关键词（`禁 A3 DataCopy`/`GetPhyAddr`/`MicroAPI`/`inline`/`void`/`__ubuf__`/`SIMD`/`SIMT`）。（**as-built 2026-07-25**：原 `禁 TILING_KEY_IS` 关键词断言已随 TilingKey 全链路正向化改为 `ASCENDC_TPL`，见 `../tilingkey-ascendc-tpl-unification/`。）
- `test_step4_has_a5_quota_rules`：含 `RegTensor` + `≤32`（或 `不超过 32`）+ `MaskReg` + `≤8`（或 `不超过 8`）+ DCache 预留。
- `test_step6_has_a5_selfcheck_rows`：Step6 含 A5 自检项（VF 签名合规 / RegTensor 数量 / MaskReg 数量 / Membase API 入侵 / SIMD/SIMT 隔离 / GetPhyAddr）。
- `test_no_external_regbase_vf_test_dependency`：SKILL.md 不含 `regbase-vf-test`、`vf_verified`、`coding_index`、`RECORD_DIR`、`CTX_DRIFT`（决策 4：不吸收 driver 机制 / 不复制 ascendskills）。
- 既有 codegen 用例不回归（delivery + upstream_reuse 16 用例）。
全量：`pytest tests/ut -m "not heavy_llm"`，0 回归。

## 后续（不在本轮）

- heavy_llm E2E（§3.11 跑前用户确认）：A5 算子真跑 codegen，确认 agent 按 A5 红线编码、VF 函数 inline void/RegTensor≤32 等不违例、产出可编译。
