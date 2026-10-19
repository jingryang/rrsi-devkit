# 子 agent 通用执行协议（跨阶段共享）

本文件是 `run_tests` / `diagnose` / `printf_location` 三个 phase 子 agent 共享的执行纪律，与「当前 phase 该做什么」无关，只规定**怎么读文件、怎么写接力产物、怎么输出**。每个 phase skill 各自携带一份本文件（即插即用、自包含）。

> **框架关系**：你不是调度器，不控制循环。框架（CompositeGroup + GraphExecutor）按 `run_tests → diagnose → printf_location` 的 transition_table 驱动；每次进一个 phase，spawn 你**单次执行**，你读接力文件、写本 phase 产物、输出 RESULT 行即返回。路由判断（`status` / `current_case_index` 推进 / `pool_exhausted` 等）由框架读 `control.json` 完成，**你不要替框架做路由**。

---

## 0. 接力文件布局（混合切分）

所有接力产物落在 `{debug_artifacts_dir}/`（通常 `output/<run_id>/artifacts/debug/<op_name>/`）下，分层存储：

| 文件 | 角色 | 你是否读写 |
|---|---|---|
| `control.json` | FW 路由切片 + 跨域共享态（`status`/`failed_case_queue`/`current_case_index`/`debug_state`/`printf_location_result` + init 配置；`history` 由框架从 `precision_<phase>.json._summary` 物化）。**无 `best_*` 字段**：最优被测代码/计数由框架从测量史派生，无 agent 可写对象 | 按本 phase 契约：读路由相关字段、写本 phase 负责的字段；**history 只读（FW 拥有）——你只写 `_summary`** |
| `phases/<phase_stem>/precision_<phase>.json` | 本 phase 的单 owner 深数据（你 own 的产物，按 phase 分子目录去冲突） | **你全权读写**（这是你的产出契约，schema 在本 skill `schema/` 下） |
| `report.json` | 跨 phase 叙事日志（每个 phase 追加一条 stage 条目，在根目录） | 追加你的 stage 条目 |
| `{label}_iter-N/run.log` + `result.json` | CLI `run-cases` 产出（log + 结构化结果，`last_run_log`/`last_result_json` 字段引用其绝对路径） | **框架/CLI 拥有，你只读** |

**跨 phase 文件完整路径表**（`debug_artifacts_dir` 由框架注入到 prompt）：

| phase 产物文件 | 完整路径 |
|---|---|
| `precision_run_tests.json` | `{debug_artifacts_dir}/phases/run_tests/precision_run_tests.json` |
| `precision_diagnose.json` | `{debug_artifacts_dir}/phases/diagnose/precision_diagnose.json` |
| `precision_printf.json` | `{debug_artifacts_dir}/phases/printf_location/precision_printf.json` |
| `precision_comment_bisect.json` | `{debug_artifacts_dir}/phases/comment_bisect/precision_comment_bisect.json` |
| `scope_verdict.json` | `{debug_artifacts_dir}/phases/scope_guard/scope_verdict.json` |
| `precision_bounds_check.json` | `{debug_artifacts_dir}/phases/bounds_check/precision_bounds_check.json` |

跨 phase 读时构造完整路径：`os.path.join(debug_artifacts_dir, "phases/<stem>/<filename>")`。

**关键**：框架路由**只读 `control.json`**。你写 `control.json` 时只改本 phase 负责的字段，**不要整体重写**、不要删别人的字段。

**框架路由计数器（子 agent 只读、绝不写，由框架 `transition` 确定性维护）**：`corrective_cycles` / `refine_cycles` / `consecutive_aborts` / `run_iter_counter` / `diagnose_stalls`。你读 `control.json` 时会看到这些顶层字段——它们是框架路由/收敛信号，非你的产出。read-modify-write `control.json` 时**原样保留**，禁止改写、删除或写入非 int 值（框架侧 `int()` 解析，改坏即崩）。

---

## 1. JSON 安全写入（防 context 压缩丢数据，最高优先级）

**禁止先把 `control.json` / `precision_<phase>.json` / `report.json` 整体 Read 到 context 再整体 Write 回去。** 长时间运行后系统会自动压缩历史消息，靠对话记忆中的 JSON 内容重拼整个文件会丢字段、丢历史。

**唯一允许的写入方式**：用 Bash 执行 python3 脚本，做原子化的「读取文件 → 定位目标 → 只修改本 phase 负责的字段 → 写回 → 打印验证」。骨架固定，各 phase 只替换要写的具体字段：

```bash
python3 << 'PYEOF'
import json, os
CTRL = "{control_path}"
with open(CTRL) as f:
    cp = json.load(f)
# —— control.json：只改本 phase 负责的路由字段 ——
# ⚠ 禁止 cp["history"].append(...)：history 由框架 transition 从你 phase json 的
#   _summary 物化（含 timestamp/phase/round 等框架控制字段）。你只写 _summary。
# cp["<YOUR_CONTROL_FIELD>"] = <value>
with open(CTRL, "w") as f:
    json.dump(cp, f, indent=2, ensure_ascii=False)
print(f"control.json: status={cp.get('status')}")

# —— 本 phase 的 per-phase json（你 own，整体结构由你维护）——
PHASE = "{phase_json_path}"
phase = json.load(open(PHASE)) if os.path.exists(PHASE) else {}
# _summary：框架从此字段物化 control.json.history 的本轮条目（具体字段见各 phase 模板）
phase["_summary"] = {
    "<YOUR_SUMMARY_FIELD>": "<value>",
}
# phase["<YOUR_PHASE_FIELD>"] = <value>
with open(PHASE, "w") as f:
    json.dump(phase, f, indent=2, ensure_ascii=False)
print(f"{os.path.basename(PHASE)}: _summary keys={list(phase.get('_summary', {}).keys())}")
PYEOF
```

写入后验证（防误覆盖）：
```bash
python3 -c "import json; d=json.load(open('{control_path}')); print(f'control status:{d.get(\"status\")} history(FW-owned):{len(d.get(\"history\",[]))}')"
```

`report.json` 同理：python3 读取 → 找到/创建当前迭代条目 → 追加本 phase 的 stage 条目 → 写回 → 验证 iterations 条目数未减少。

> 你仍可用 Read 工具读取 JSON 分析内容，但**写入必须走上述 python3 模式**。

---

## 2. 输出最小化（必须遵守）

所有结果已通过 `control.json` / `precision_<phase>.json` / `report.json` 传递给框架，**不要在最终输出里复述这些文件的内容**。

- 最终输出只需一句话概括本 phase 结果，不超过 50 字
- **最终输出不得为空**，至少一句非空文字 + 恰好一行 `RESULT:` 协议（见各 phase 模板末尾）

---

## 3. 文件读取规范（默认）

- **大文件不整体 Read**：源文件/日志超过 phase 模板注明的行数阈值时，先 `grep -n "<关键词>"` 定位，只 Read 命中行的上下文（前后 20~30 行）
- **大日志用 tail + grep 提取**：不要把几百行的测试/编译/printf 日志整段 Read 进 context，用 `tail -N` 取尾部摘要，`grep -iE "fail|error|diff|mismatch|nan|inf"` 提取关键行
- 具体行数阈值、需要读哪些专属文件（gate 文档、算子源文件、`last_result_json`/`last_run_log` 指向的产物），见各 phase 模板

---

## 4. 精简策略（context 收缩时）

子 agent 因 token 超限 / 文件过大 / 超时失败时，框架会以更严格的指令重派（分两级，上限 2，超过降级为「分析失败」）。

**你自身不得以「token 预算不足」「上下文太长」为由主动停止或空手返回。** 若必须收缩，按精简方向继续完成本 phase 并输出 RESULT 行：

- 通用降级方向：读取范围进一步收窄（更小行数阈值、更少候选文件）、输出长度进一步收窄、处理步骤进一步精简（如只尝试 1 个方案 / 只检查最关键 1-2 项）
- 具体到每个 phase 该精简哪些动作，见各 phase 模板末尾「精简策略」小节
