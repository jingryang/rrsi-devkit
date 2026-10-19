# 43 — 任意 stage 强制重跑入口（L4 实施方案）

> 工作线：self-evolution
> 状态：**已实施**（2026-07-13）；UT 23 新增 + 全量 1911 绿；resume 相关 ST 4 passed（0 回归）
> 关联 L3：`47-stage-rerun-analysis.md`
> L1 问题：`06-problems.md` P77

## 改动（函数级）

### `orchestration/base.py` — `Stage.rerun_reset_fields()` 新增（默认 = output provides）

```python
def rerun_reset_fields(self) -> list[str]:
    return list(self.output_contract().provides)
```
默认返回 stage 的 `output_contract().provides`——它每次（重新）产出的字段，fresh 重跑从干净状态开始（如 `perf_iterations=0` 防 `perf.py:344` verify↔perf guard 误路由）。

### `orchestration/stages/codegen.py` — `CodegenStage.rerun_reset_fields()` override

```python
def rerun_reset_fields(self) -> list[str]:
    return list(self.output_contract().provides) + ["codegen_consecutive_failures"]
```
断路器（`codegen.py:156`）不在 output_contract.provides 但门控重入；stale trip 会卡住 fresh 重跑（同 `_resume_breaker_reset` zero 之理）。

### `orchestration/kernel/state.py` — `State.defaults_for(field_names)` classmethod 新增

`dataclasses.fields(State)` 取声明默认；返回 `with_updates(**...)` 可用的 dict；未知字段跳过（caller 可整包传 `rerun_reset_fields()` 输出，无需过滤）。

### `application/dispatcher.py` — 4 个新函数

1. **`_resolve_rerun_target(workflow, target)`**：用户输入（全路径 / 裸名 / 后缀）→ 唯一全路径。重名裸名 → None（要求全路径）。
2. **`_rerun_invalidate(node_status, workflow, target_path) -> (new_ns, found, stages)`**：P52 clean-prefix 作废，target 作**inclusive** 断点（对比 `_resume_node_status` 的 first-bad+1）。target 子树 + 各 enclosing SequentialGroup 内 target 之后的所有 sibling 作废；**ForkJoin sibling 平行独立不作废**。关键修：作废目标时**同时 pop 所有祖先 group 的 key**（否则 executor 的 skip guard `graph_executor.py:174` 按 group path 跳过整组）。返回被作废的 atomic Stage 列表（供计数器重置）。
3. **`_delete_session_sidecars(workspace)`**：删 `<run>/agents/*.session.json`——**fresh-not-resume 核心保证**。codegen.actions 读 sidecar 发 resume spawn；删之 → fresh spawn（走已有单通路，§2.5）。安全性见 L3。
4. **`_apply_rerun(state, workflow, target_path, workspace) -> State`**：组合（1）node_status 作废（2）sidecar 删除（3）命中 stage 的 `rerun_reset_fields` 重置到默认（4）清指向命中 stage 的 `last_error`。target 不在树 → ValueError。

### `application/dispatcher.py` — 入口接线

- 早校验（line ~452）：`--rerun-from` 无 `--resume` → `EX_USAGE`（rerun 针对已存在 run）。
- resume 分支取 workflow 后、`all_done` 短路前（line ~522）：resolve target（None → `EX_USAGE` + 列 node_status 键提示）→ `_apply_rerun`。**必须在 all_done 之前**——rerun 要 un-complete 一个之前全完成的 run。

### `cli/commands/run.py` — `--rerun-from` flag

`@click.option("--rerun-from", ...)` + 签名 + `task_request["rerun_from"]`。help 明示「requires --resume」「prior agent session NOT continued—agents spawn fresh」「Use to re-validate a stage after iteratively optimizing it」。

## 验证（TDD §3.1，UT mock §3.8）

`tests/ut/orchestration/test_rerun.py` 23 例：
- **`_rerun_invalidate` 树走**（8）：sequential target+downstream / 首节点 / 末节点 / group 子树 / **forkjoin sibling 不作废** / forkjoin 父 sequential 下游作废 / 未知 target / executor end-to-end 重跑正确集。
- **`_resolve_rerun_target`**（4）：全路径 / 裸名 / 未知 / 重名裸名 None。
- **`Stage.rerun_reset_fields`**（3）：默认=provides / codegen 含断路器 / perf 含 loop guard。
- **`State.defaults_for`**（2）：取默认 / 跳未知。
- **`_apply_rerun`**（6）：reset provides / reset codegen 断路器 / **删 sidecar（fresh-spawn 核心守卫）** / 清匹配 last_error / 保留 upstream last_error / 未知 target raise。

全量回归：UT 1911 绿；resume 相关 ST（`test_resume_cli` + `test_predesign_chip_gate_resume`）4 passed，0 回归。

## 不改（关键边界）

- **graph_executor 遍历/skip 逻辑**——node_status 是唯一权威，rerun 只改 node_status。
- **stage 类**（除 codegen 加 override）——`rerun_reset_fields` 默认够用。
- **event schema**——rerun 用 console log + 命中 stage 名，不入新 event 类型。
- **SDK session sidecar 机制全局**——codegen 读 sidecar 是对的（resume 场景），rerun 删之即可，不新增 ignore 标志。
- **incremental mode**——不做（perf guard 误路由风险 + 无清晰用例，§1.4）。

## heavy_llm（§3.11）

本改动不改 LLM 链路（rerun 触发 fresh spawn 是确定性路径）。端到端「rerun codegen → fresh agent 不 resume 旧 session → 重跑」属 heavy_llm，不默认跑；交付前由用户决策。未跑则诚实记录。
