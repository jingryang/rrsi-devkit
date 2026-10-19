# 75 — cann_bench/__init__.py wrapper 确定性生成 + 退役 cannbench-adapt agent（L4 实施方案）

> 对应 L3：`75-cannbench-wrapper-discovery-analysis.md`（**已拍板方案 G + 退役 agent**，冻结）。
> 对应 L1：[[P112]]。
> 状态：**已实施（步骤 1-4 完成，UT/ST 绿）；步骤 5-6 待用户决策**（CMake 退役验证 + heavy_llm ST，§3.11）。
> 范式参照：`codegen_init.py`（确定性无 agent stage，`actions()→[]`、transition 做活）、P10（`_rename_mdef_schema_if_needed` 确定性后处理）。

## 0. 核心改动一句话

CannbenchAdaptStage 收敛为**确定性适配**：transition 里确定性生成 `cann_bench/__init__.py` wrapper（manifest 派生）+ 保留 P10 m.def rename + 保留 clean rebuild；**退役 cannbench-adapt LLM agent**（删 SpawnAgent + prompt + `.claude/agents/cannbench-adapt.md`，§2.5）。wrapper 三维{存在/参数名/转发目标}构造性保证（§2.9），不再靠 LLM + cannbench_eval discover。

## 1. 改动清单（顺序 = 机制 → stage 重构 → 退役 agent → 验证 → 测试）

### 1.1 确定性 wrapper 生成器（cannbench_adapt.py，新增方法）

新增 `_generate_and_inject_wrapper(self, state) -> tuple[bool, list[str]]`（返 `(injected, errors)`）：
- **派生 wrapper**（manifest 纯函数）：
  - `op_name = state.codegen_manifest["op_name"]`
  - `symbol_last = state.codegen_manifest["callable_target"]["symbol"].split(".")[-1]`（真实注册名，如 `npu_exp`）
  - `params = align_schema_params(op_spec)`（**已存在** cannbench_adapt.py:52，返 proto 参数序：inputs 名 + attrs 名；op_spec 取 `state.op_spec or state.requirement.op_spec`）
  - 生成：`def {op_name}({', '.join(params)}):\n    return torch.ops.cann_bench.{symbol_last}({', '.join(params)})\n`
- **定位 `cann_bench/__init__.py`**：复用/抽取 cannbench_eval 的 `_resolve_cann_bench_pkg_root`（cannbench_eval.py:133）同款路径解析（example 源 `cann_bench/` 包根，非 per-op 部署包——redeploy 会把 example→per-op，与 [[P97]] 流一致）。
- **幂等注入**：解析现有 `__init__.py`；若已有 `def {op_name}\(` → 比对参数名/转发目标，不一致则**替换**该 def 块；无则**追加**（参考已有 wrapper 位置/格式，加注释标 `# <op_name> wrapper (deterministic, cannbench_adapt)`）。用正则定位 def 块（轻量；def 形态固定）。
- **三维构造性保证**：① 生成必存在；② 参数名取 proto（=golden，cann-bench `func(**golden_params)` 关键字调对）；③ 转发目标取 symbol_last（真实 C++ 注册名，[[P98]] 同源）。

### 1.2 CannbenchAdaptStage 重构（确定性，仿 codegen_init）

- `actions(state, iteration)`：**删 SpawnAgent 分支**，改 `return []`（确定性无 agent，注释同 codegen_init.py:64）。仅保留 codegen_manifest/repo_root 缺失时的 `return []` 早退（已有）。
- `transition(state, result)`：
  1. **wrapper 注入**（新）：`injected, wrap_errors = self._generate_and_inject_wrapper(state)`。
  2. **P10 m.def rename**（保留）：`schema_renamed, p10_errors = self._rename_mdef_schema_if_needed(state)`。
  3. **clean rebuild**（保留）：`need_rebuild = injected or bool(schema_renamed)` → `Deployer().deploy(state, clean_build=True)`（rebuild + redeploy per-op，把 example 含新 wrapper 的 `__init__.py` 传到 per-op，[[P97]] 流）。
  4. `adapt_result = AdaptResult(adapted=injected or bool(schema_renamed), files_modified=(["cann_bench/__init__.py"] if injected else [])+..., errors=wrap_errors+p10_errors, schema_renamed=schema_renamed)`。
  - 删原 `agent_result` 解析分支（cannbench_adapt.py:130-155）——agent 已退役。

### 1.3 退役 cannbench-adapt agent（§2.5 唯一通路不留旧债）

- 删 `.claude/agents/cannbench-adapt.md`（无人再 spawn）。
- 删 cannbench_adapt.py 的 `_build_prompt`（:267-340）+ SpawnAgent 相关 import/分支。
- STAGE_SKILL_MAP / agent registry 里 cannbench-adapt 引用清理（若有）。

### 1.4 CMake 退役验证步（agent 不再管 CMake 后的兜底确认）

- 退役前/后各跑一次真实 run，确认 `torch.ops.cann_bench.<op>` EXISTS（op 进 `_C`）——验证 codegen 强制产 per-op CMakeLists（codegen.py:1564-1569）+ P96 `file(GLOB)` + `clean_build=True` 足以覆盖 _C 收录，**无需 agent 编辑 CMake**。
- 若验证发现 op 不进 _C（codegen 漏 per-op CMake）：**不回退 agent**，而是确定性生成 per-op CMakeLists（`register_aclnn_plugin(<op>)`，参考已有算子模式）——延伸 1.1 的确定性生成到 CMake。落地时按实证决定是否需要。

## 2. TDD 验证

### 2.1 UT（确定性生成器 + stage，mock，不需 NPU）

`tests/ut/orchestration/test_cannbench_adapt_schema.py`（既有文件，扩）+ 可能新文件：
- **W1 三维**：给 manifest（op_name + callable_target.symbol，含 npu_ 前缀案例）+ op_spec → 生成 wrapper，断言 ① `def {op_name}` 存在 ② 参数名 == proto（align_schema_params）③ 转发目标 == symbol_last。
- **W2 幂等**：现有 `__init__.py` 已含该 op wrapper（参数名错/转发目标错）→ 再生成 → 断言**替换**为正确版（不重复 def、不残留旧）。
- **W3 幂等-无**：现有不含 → 生成 → 断言**追加**且不破坏既有 wrapper（add/sqrt 等）。
- **W4 stage 集成**：CannbenchAdaptStage.transition（mock Deployer）→ 断言 wrapper 注入 + adapt_result.files_modified 含 `cann_bench/__init__.py` + 不再 spawn agent（actions()==[]）。
- **W5 退役确认**：全仓 grep 确认无 `cannbench-adapt` agent spawn 残留（守护 §2.5）。

### 2.2 既有 UT 回归

- 既有 cannbench_adapt UT（test_cannbench_adapt_schema.py：rename/rebuild/clean_rebuild_failure 等）：agent 退役后这些用例（依赖 SpawnAgent mock）需改为确定性 transition 断言；`test_clean_rebuild_failure_sets_deploy_failed` 等保留（rebuild 失败路径不变）。

### 2.3 heavy_llm ST（§3.11，用户决策跑）

真实 cann-bench e2e：确定性 stage 后，scan_interfaces 发现算子（`operators` 非空）、wrapper 在 per-op `__init__.py`、`torch.ops.cann_bench.<op>` 可调、cann-bench eval 出分（非 discovery 断）。复核 issue.md 的 manifold 场景不再漏 wrapper。

## 3. 顺序与门

1. ✅ wrapper 生成器（1.1）+ UT W1/W2/W3 红→绿。
2. ✅ stage 重构（1.2）+ UT W4；既有 cannbench_adapt UT 回归改造（2.2）。
3. ✅ 退役 agent（1.3）+ UT W5。
4. ✅ 全量 UT（非 heavy_llm）零回归 —— 2917 passed / 7 skip / 0 fail。
5. ⏳ CMake 退役验证（1.4）：真实 run 确认 op 进 _C（或补确定性 CMake 生成）—— **待用户决策跑**。
6. ⏳ heavy_llm ST 由用户决策跑（§3.11）—— **待用户决策跑**。

> 实施附修（非 P112 本体，顺手修 pre-existing）：cannbench_eval `_run_eval` 返回类型注解
> `-> EvalResult` 更正为 `-> tuple[EvalResult, ErrorFeedback | None]`（P95-P99 遗留——生产
> 调用方 `cannbench_eval.py:96` 本就解包元组、`_parse_report` 也返元组，仅注解 + 1 个 ST 用例
> `test_eval_failure_dumps_full_stderr_to_subprocess_log` 过时未跟进）+ 该 ST 用例改为解包。

## 4. 影响面与回归

- CannbenchAdaptStage：agent → 确定性。adapt_result 形态微调（files_modified 来源变确定性注入，非 agent artifacts）。
- 下游 cannbench_eval：不变（仍扫 per-op `__init__.py` 的 wrapper；wrapper 现在确定性保证在）。
- codegen：不变（仍 best-effort 产 CMakeLists/导出提示；其 wrapper best-effort 提示可保留为冗余，cannbench_adapt 确定性兜底覆盖）。
- 既有 run 产物不迁（§1.4）。
- **复发面消除**：wrapper 三维构造性保证 + agent 退役（消除 LLM 非确定性）；UT W1-W4 纵深防回退。
- per-repo adapter 生命周期（L3 §8）：cann-bench adapter 到确定性化阶段；未来新仓 adapter 独立、可 agent-driven，不冲突。

## 5. 不做的事

- 不为 agent 旧形态加兼容/迁移（§1.4）。
- 不改 cann-bench 仓（外部；方案 E 长期建议另_track）。
- 不改 codegen 的 CMakeLists/导出 best-effort 提示（cannbench_adapt 确定性兜底；codegen 提示留作冗余）。
- 不把 wrapper 生成塞进 codegen（wrapper 是 cann-bench 发现契约，归 cann-bench adapter，§2.5 通路清晰）。
- 不在 CMake 退役验证通过前假定 agent CMake 活冗余——实证决定（1.4）。
