# precision-debug harness 拒绝 Optional/可空 attr 致全量 halt — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：批跑 run `20260805-152456-8b48b2` 下算子 `resize_bilinear`
>（工作区 `output/20260805-152456-8b48b2/20260805-152456-0762df/`）的精度调试产物 +
> 框架源码。RCA 详见会话分析；本文只固化客观事实。

## 背景：halt 发生在哪

整条流水线 design → codegen → deploy 全部 ok，算子编译出 `libcust_opapi.so`（87984 B）、
smoke 通过、提交在 `456bf5a`。halt 发生在 `precision_debug/scope_guard`，`scope_verdict=upstream`
（甩给 `test_design`），整条 run 以「Workflow halted … quota exhausted at condition 'upstream'」收尾。
**0 条用例真正上板**（`run_tests_iter-0/` 空、`precision_run_tests.json.last_result_json=null`）。

---

## P1 — harness `_validate_attrs` 拒绝 Optional/可空 attr 的 `None` 值（致死主因）

**现象**：`run-cases` 在跑任何一条用例**之前**就于 schema 校验期抛
`[PD-CONTRACT] test_cases[17].attrs['output_size'] has unsupported type NoneType` 并 abort，
0/20 用例执行。

**证据**：
- `artifacts/debug/resize_bilinear/run_iter_0.log`（共 4 行，第 3 行）：
  `Error: [PD-CONTRACT] test_cases[17].attrs['output_size'] has unsupported type NoneType`
- 抛错点：`src/ascendc_devkit/adapters/npu/runner.py:225 _validate_attrs`（`HarnessContractError`
  自动加 `[PD-CONTRACT]` 前缀，见 `domain/exceptions.py:127-133`）。
- 校验逻辑（`runner.py:237-295`）：取 `expected = attr_spec.type`，仅在 `expected ∈
  {"int","float","str","list[int]","bool"}` 时走对应 typed 分支；**任何分支都不接受 `None`**，
  兜底分支（`:291-295`）对 `not isinstance(v,(int,float,str))` 抛 `has unsupported type {typename}`。
- golden（权威源 §1.13）`artifacts/requirement/golden.py`：
  `output_size: Optional[List[int]] = None`、`scale_factor: Optional[List[float]] = None`，
  二者**互斥、各自 Optional、默认 None**。
- `artifacts/requirement/requirement.json` attrs：`output_size {type:ListInt, default:null}`、
  `scale_factor {type:ListFloat, default:null}` —— 忠实记录了 golden 的 Optional 语义。
- `artifacts/staging/test_cases.json` index 17 / 19：
  `{"output_size": null, "align_corners": false, "scale_factor": [2.0, 2.0]}` /
  `{"output_size": null, ..., "scale_factor": [0.5, 2.0]}` —— 为 scale_factor 路径用例**故意**
  置 `output_size=null`，忠实覆盖互斥分支。

**影响**：校验器没有 nullable/Optional 概念，把「attr 合法缺省哨兵 None」当「类型错误」拒掉。
任何带「可空 / 互斥 / 默认 None」attr 的算子都会撞墙（与 resize_bilinear 无关，§1.12 通用缺陷）。
harness 在 schema 闸门 abort，后续 precision/runtime 真实缺陷根本无从暴露。

## P2 — attr 类型名格式漂移 + 缺 `list[float]` 分支（把 P1 推进致死兜底分支的诱因）

**现象**：requirement 用 PascalCase `"ListInt"/"ListFloat"`，校验器只认小写
`"int"/"float"/"str"/"list[int]"/"bool"`，且**根本没有 `"list[float]"` 分支**。

**证据**：
- `_validate_attrs` 的 typed 分支（`runner.py:254-280`）穷举为 `int/float/str/list[int]/bool`，
  无 `list[float]`、无 `ListInt/ListFloat`。
- `domain/operator.py:184` `type=e.get("type") or e.get("dtype","")` —— requirement 条目的
  `"type"` 字段**原样**进 `AttrSpec.type`，无规范化。故 `"ListInt"` 原样抵达校验器。
- `domain/operator.py:46-48` `AttrSpec.type` 注释自称取值 `"int" | "float" | "str" | "list[int]"`，
  与 requirement 实际产出的 `"ListInt"/"ListFloat"` 已脱节。
- **反证**：若 `"ListInt"` 被规范化成 `"list[int]"`，报错应是 `expected list[int], got None`；
  实际报的是**兜底分支**消息 `has unsupported type NoneType`，证明从未发生规范化。
- `scale_factor=[2.0,2.0]` 未报错，仅因它在兜底分支里 `isinstance(list)` 通过——即 P2 对所有
  list 型 attr 都潜伏，只是非 None 值碰巧没炸。

**影响**：所有 list 型 attr 绕过 typed 校验、落兜底分支；类型错误信息失真（该报「expected list」
却报「unsupported type」）。P1+P2 叠加，`output_size=None` 同时命中「无 nullable 概念」+「类型名
不匹配落兜底」，必死。

## P3 — scope_guard 把「harness 自家契约错误」误判为「上游 test_design 缺陷」（§2.9 归属越界）

**现象**：`scope_verdict=upstream`、`upstream_stage=test_design`，结论为「cases.yaml 写空
output_size 是上游缺陷，precision_debug 不改 cases.yaml → halt」。

**证据**：
- `artifacts/debug/resize_bilinear/phases/scope_guard/scope_verdict.json`：
  `scope_verdict=upstream`、`upstream_stage=test_design`。
- 抛错代码 `_validate_attrs` 在 `adapters/npu/runner.py`（框架/harness 自有代码），**不是**
  `cases.yaml`（test_design 产物）。ownership 实际在框架侧，与 test_design 无关。
- cases.yaml 本身**没错**（P1 已证：忠实 golden Optional 语义）——scope_guard 把「正确行为」
  当「缺陷」甩给上游。
- scope_guard 自相矛盾：同份 `scope_reason` 列出了正确修法「the harness schema must accept
  output_size=null when scale_factor is provided」（即 harness/框架侧修），却把归属钉成 test_design。

**影响**：门按「错误形态」（schema 类）而非「抛错代码 ownership」判归属，违反 §1.10
（横切判据用业务语义不用机制特征）。误判致 halt 甩给不会被修的上游，控制流兜底空转。

## P4 — 「19/20 passed」是算术假象，掩盖「0 条上板」（§3.4 掩盖风险）

**现象**：`precision_report.md` 报「通过/失败/崩溃 19/1/0」「最优 commit 456bf5a」「收敛趋势 19/20
passed」，但实际 0 条用例上板。

**证据**：
- `precision_run_tests.json.last_result_json = null`（无任何 per-case 结果）；
  `_summary` 仅 `failed_count=1, total_count=20`，无 `passed_count`、无 per-case detail。
- `control.json.best_passed_count=19, best_failed_count=1`。
- 推导源 `precision_debug_substages.py:847` 注释自承 `passed_count = total_count - failed_count`
  —— `19 = 20 − 1` 纯算术，不是真实通过。
- `run_tests_iter-0/` 目录空（0 文件），`run_iter_0.log` 4 行即终。

**影响**：把「未测」伪饰成「通过」，高估进度，误导复盘与交付判定（§1.2 可诊断 / §3.4 禁止掩盖）。

## P5 — `failure_type=compilation` 是关键词误判（schema 错被当 C++ 编译失败）

**现象**：`history[0].content.failure_type="compilation"`，scope_guard 自己标注「语义上是
Pydantic schema-contract 错，非 C++ 编译失败」。

**证据**：
- `control.json.history[0]`：`failure_type=compilation`，源自 `test_result=hard_error: [PD-CONTRACT]
  test_cases[17].output_size=None …`。
- 报错以 `Error:` 起首（`Error: [PD-CONTRACT] …`），命中 compilation 模式关键词（大小写不敏感）。
- scope_guard `scope_verdict.json` evidence 自承该误判。

**影响**：按「Error: 前缀」关键词判分类 = 机制特征代理（§1.10），致错误类别失真，干扰路由
（compilation 路径 vs schema/contract 路径处置不同）。

---

## 不属本轮（排除项）

- cases.yaml / test_cases.json 本身**无误**，不在修复范围（P1 已证其忠实 golden Optional 语义）；
  「在 loader 里把 output_size 从 scale_factor 兜底填值」属反向修正正确上游，不采纳。
- codegen 阶段的 manifest 参数名顺序漂移告警（`run.log:3611`，`scale_factor`/`align_corners` 顺序）
  是另一独立已知项（P10），cannbench_adapt 已有 rename 兜底，与本次 halt 无关，不在本轮。
