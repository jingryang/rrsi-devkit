# L1 问题记录 — codegen 脚手架未被有效验证，坏脚手架流入 precision_debug

> 本目录 = 一次工作。四层见 ../README.md。L1 只陈述事实/证据，不提方案。

## P1 — smoke 门判据太弱，`smoke_passed=True` 不足以证明脚手架正确
- `deploy.py:_smoke_script`（改前）：`kind != "torch_op"`（如 aclnn）→ 脚本只 `print(...)`，
  `python -c` 必 exit 0 → `smoke_passed=True`（空验放行）。
- `kind == "torch_op"` → 只 assert `torch.ops.<ns>.<op>` 能解析，不验 schema/可调用；
  `__import__(ns)` 的 `except Exception: pass` 吞掉注册副作用错误（丢失根因）。
- 后果：坏脚手架拿 `smoke_passed=True` 通过 codegen 的 halt 门 → 流入 precision_debug（debugger），
  后者浪费轮次修脚手架问题。
- 停机管道本身无漏洞（已核对 `runner.py:410-411` own_error 先于 contract 判 failed；
  `graph_executor` break 先于转移表）——洞在 smoke 判据强度。

## P2 — 脚手架类型（调用协议）由非确定性 Agent 现填，无单一权威源
- `codegen.py`（改前）prompt 让 Agent 在 `codegen_manifest.callable_target.kind` 自行声明
  torch_op/aclnn。选择权在 LLM 手里，profile 不参与 → 同仓不同 run 可能填不同值 = 漂移源头。
- `runner.py:364`（改前）默认 `kind = "torch_op"`——隐藏的第二真相源，kind-less manifest
  被当 torch_op。

## P3 — cann-bench 专有 torch_op 约定硬编码进通用出口
- `runner.py` 默认 torch_op、`cannbench_adapt.py:395` 硬编码 `torch.ops.cann_bench.*`。
- 与既有共识冲突：`cannbench_adapt.py:41` 自述「不入 codegen skill 避免耦合 cann-bench 调用约定」。

---

# L3 方案分析（拍板冻结）

## 决策 D1 — 选择粒度：仓级 profile 单选
scaffolding 类型定在 `profile.scaffolding = {supported: [...], selected}`，整仓统一。
不引入算子级覆盖（避免第二处选择点 = 避免再开漂移面）。

## 决策 D2 — kind 产权：profile 全权，Agent 不填 kind
Agent 只写 `callable_target.symbol`（算子相关），`kind` 由 codegen 从 profile 注入。
Agent 若仍写 kind → warn 并覆盖（可诊断，§1.2）。

## 核心不变式
> scaffolding 类型是单一权威源 `profile.scaffolding.selected`，所有消费者只读不改，
> Agent 产物只能被校验、不能成为第二真相源。

## 决策 D3 — 删除 `codegen_init` 的按仓 aclnn 判断（改后）
初判曾想「不动」,理由是 op_api/op_plugin 是文件布局轴、与调用协议正交,不能折进 scaffolding。
布局轴正交这半句成立,但「不动」结论错了:那个 `_ACLNN_REPO_NAMES` 仓名 substring 匹配
本身就是与 cann-bench/omni-ops 耦合的硬编码(违反 §1.5/§1.7),必须去。
用户进一步指出:aclnn(op_api/op_plugin)本质是**几乎所有算子都要的通用代码**,
需求既非仓级、也非干净的算子级开关,且「多生成也不算错」。
→ 正确改动不是「把仓名列表移进 profile」(那只是换个地方存错误抽象),
而是**删掉整个按仓/按 scaffolding 判断,无条件声明四段**。加 profile 字段=为不存在的需求
过早建机制(§1.2),不做。真出现「必须不生成 aclnn」的算子级需求时再讨论。

---

# L4 实施记录（已完成）

1. **domain**：`repository.py` 加 `Scaffolding{supported,selected}` + `VALID_SCAFFOLDING_KINDS`
   + `RepositoryProfile.scaffolding` 字段 + `scaffolding_kind()` + `from_yaml._parse_scaffolding`
   （加载期校验 selected∈supported、kind∈valid，§1.3）。
2. **schema**：`resources/schemas/repository/profile.json` 加 scaffolding 对象（enum + required）。
3. **profile**：`cann-bench.yaml` 加 `scaffolding: {supported:[torch_op,aclnn,pybind], selected:torch_op}`。
4. **codegen**：prompt 声明协议由 profile 选定、禁 Agent 写 kind；transition 加
   `_inject_scaffolding_kind`（从 profile 注入/覆盖 kind，divergent 时 warn）；
   callable_target 校验从 `{kind,symbol}` 改为「symbol 必需、kind 由 profile 供」。
5. **runner**：`runner.py` 删除 `kind` 默认 torch_op，空 kind → ValueError（§3.7）。
6. **skill schema**：`codegen_manifest.json` callable_target_doc 说明 kind 是仓级决策、Agent 只写 symbol。
7. **smoke**：`deploy.py:_smoke_script` 三 kind 真实探针（torch_op 去 silent-swallow + surface import err；
   pybind import+getattr+callable；aclnn 诚实 hard-fail；unknown fail-closed）。
8. **codegen_init**：删除 `_ACLNN_REPO_NAMES` + `_repo_needs_aclnn` 按仓判断，
   `_build_sections` 无条件声明四段；`input_contract` 不再硬 require profile。

## 验证
- UT 全量 2308 pass / 7 skip（cann-bench env skip，对齐基线）。
- 新增 UT：scaffolding 加载校验 6 例 + smoke_script 三 kind 探针 5 例 + kind 注入/覆盖/缺 symbol/prompt 5 例。
- 4 份 profile 均过 jsonschema 校验。
- Stub ST 44 pass；真机 NPU ST（`test_npu.py` 真实 kernel deploy→smoke→precision）6 pass / 2 skip（外部 ops-nn 仓）。
- **真机 heavy_llm（2026-07-18，环境已具备，opencode CLI 1.18.3 装后）跑全部 12 个：10 pass / 2 fail**：
  - ✅ **`test_smoke.py::test_full_pipeline` PASS**——本次改动核心端到端守护（codegen→smoke→halt 全链路）。
  - ✅ design/testdesign TUI 自闭环 5 例、session_resume 3 例、anchor 1 例全 pass。
  - ⚠️ 2 fail = `test_subagent_dispatch_dual_backend[claude/opencode]`——**与本改动无关的既有非确定性**：
    该用例是纯 D3 subagent 派发连通性探针（禁 codegen/redeploy/碰算子，与 scaffolding 零重叠），
    stash 掉本改动后 clean HEAD 同样 fail。根因是 model（GLM-5.2 endpoint）在 3 次 bounded retry
    内未产出 marker（§3.10 非确定性，用例自己的失败信息也写「may be LLM non-compliance rather than a
    D3 defect」）。初判为「既有 §3.10 flaky」，深挖后确认是**真实结构缺陷**，已根治（见 F4）。
  - 同类：`test_tool_permission_dual_backend[claude]`——同样深挖为真实缺陷，已根治（见 F4）。

## Follow-up
- F2：aclnn 真实 smoke 探针尚未实现——当前 aclnn 分支诚实 hard-fail（§3.7）。选 aclnn 前须先补。
- F3：omni-ops/ops-nn/ops-transformer 真实调用协议未知，暂留 legacy fallback(torch_op)，需按各仓补 `scaffolding`。
- **F4（已根治 2026-07-18）**：两个 flaky 真机 ST 深挖后非「LLM 抖动」，是 3 个真实缺陷：
  1. `test_subagent_dispatch` 的 primary 选了**不存在的 manifest** `ascendc-precision-debugger`
     → 拿默认工具集（无 Agent、Task 被禁）→ 结构上无法派发。**修**：改用真正持有 `Agent`
     工具的生产 agent `ascendc-coder-regbase`（其职责即 orchestrate sub-agents），
     测真实自主派发链路，无权限面改动。
  2. **claude 后端 `AgentResult.transcript` 恒为 None**（3 处构造都没传 `transcript=`），
     transcript 文件明明落盘却读不到 → 测试的 transcript 观测恒失效。**修**：sdk_backend
     捕获 `transcript.name` 路径注入 3 处 AgentResult（客观 bug，根治观测盲点）。
  3. `test_tool_permission` 要求**创建**新文件，但 design-generator 只授 `Edit`(改已存在文件)+`Bash`，
     **不授 `Write`**；model 时而挑不可用的 `Write` 被拦 → flaky。**修**：prompt 明确指示用
     `Bash`（design-generator 真实持有、能创建的授权工具），消除工具自选抖动，真权限回归仍会 fail。
  - 验证：4 个变体（2 test × claude/opencode）真机全 PASS，claude 变体连跑稳定复现。
