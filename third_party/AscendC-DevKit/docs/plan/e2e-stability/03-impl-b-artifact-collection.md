# L4 实施方案 B — 设计阶段产物收集重构

> 层级：**L4 / 实施方案**。具体改哪个函数、怎么验证。
> 覆盖问题：P4, P5（见 `01-problems.md`）

## 核心思路

设计阶段产物文件名由 `artifact_contract()` 声明且全部新建在空工作目录，不从 `_collect_changed_sources` 的 git diff / scan 路径收集，直接从磁盘读。

## 改动文件 1：`src/ascendc_devkit/orchestration/stages/design_substages.py`

**位置**：`_parse_single` 方法（第 321-338 行），替换为：

```python
def _parse_single(self, state, result, field, filename):
    """Parse one required JSON artifact; design stages read from disk directly."""
    from pathlib import Path
    errors: list[str] = []

    # 路径 1：从 working_dir 直接读文件（确定性，设计阶段适用）
    wd = result.get("_working_dir")
    if wd is not None:
        fpath = Path(wd) / filename
        if fpath.is_file():
            try:
                raw = {filename: fpath.read_text(encoding="utf-8")}
                parsed, errors = self.artifact_contract().parse(raw)
                if field in parsed:
                    logs = self._capture_decision_log(state, raw)
                    return state.with_updates(
                        **{field: parsed[field],
                           "decision_logs": logs,
                           "user_feedback": "",
                           "last_error": None}), True  # P5: 清除 sticky error
            except (OSError, json.JSONDecodeError) as e:
                errors = [str(e)]

    # 路径 2：fallback agent_result.artifacts（兼容 codegen 等场景）
    agent_result = result.get("agent_result")
    if agent_result is not None and getattr(agent_result, "artifacts", None):
        parsed, errors = self.artifact_contract().parse(agent_result.artifacts)
        logs = self._capture_decision_log(state, agent_result.artifacts)
        if field in parsed:
            return state.with_updates(
                **{field: parsed[field],
                   "decision_logs": logs,
                   "user_feedback": "",
                   "last_error": None}), True  # P5: 清除 sticky error

    return self._error(
        state, "; ".join(errors) or f"{self.name}: missing {filename}"), False
```

## 改动文件 2：`src/ascendc_devkit/orchestration/kernel/runner.py`

已在 `03-impl-a-fail-strategy.md` 中覆盖：`result["_working_dir"] = action.working_dir`。

## 改动文件 3：`src/ascendc_devkit/capabilities/agent/sdk_backend.py`

**位置**：`_collect` 方法（第 800-821 行），codegen 路径加基线检查：

```python
def _collect(self, cwd, repo_baseline, repo_root) -> dict[str, str]:
    if not cwd:
        return {}
    if not repo_baseline:
        # codegen 必须有基线；设计阶段不走此路径
        raise ValueError("codegen requires a git baseline")
    guard = RepoGuard(...) if repo_baseline else None
    return _collect_changed_sources(Path(cwd), repo_guard=guard, ...)
```

## 改动文件 4：`src/ascendc_devkit/orchestration/stages/context.py`

**位置**：baseline 建立逻辑。git 不可用或不在此库 → 报错。

## 验证方法

1. 单测：mock working_dir，写入 contract 声明文件，验证 `_parse_single` 正确解析（含 sticky last_error 清除断言）
2. 集成：真实 agent 写入产物文件后 crash，验证 transition 仍能从磁盘读回文件
3. Codegen：移除 git → 验证抛 PreconditionError
