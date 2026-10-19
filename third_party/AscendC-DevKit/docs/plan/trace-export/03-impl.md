# L4 实施方案 — 轨迹导出工具进工程

> 前置：L3 `02-analysis.md` 已冻结。验证命令见文末。

## 改动清单

### 1. `scripts/trace_export/reconstruct_opencode_request.py`（平移，零改动）

从 PanguTraceProcess 原样拷贝。其 `find_config / reconstruct_session /
ENGINE_MCP_TOOLS` 被入口 import 复用；自身 CLI 保持可用。

### 2. `scripts/trace_export/convert_to_sft.py`（改造）

- 删 `DEFAULT_META["teacher"]="glm-5.3"` 写死值 → 模板常量置空串；
- 新增 `derive_teacher(record)`：取 `session.model.id`（str 或 dict 两形态兼容），
  缺失落 ""；
- `convert_record(record, teacher=None)`：teacher 非 None 用之，None 走派生；
- `check_record` 从 main 内嵌函数提到模块级（逻辑不变）；
- 新增 `export_jsonl(records, output_dir, teacher=None) -> tuple[int,int,int]`
  （slow 数、fast 数、质检 issue 数）：排序 → 逐条 convert → 分类写两个 JSONL
  → 逐条 check + 时间序检查（构造保证有序，报告确认）；
- `main()` 重构为：读目录 → `export_jsonl` → 按返回码退出；CLI 行为不变。

### 3. `scripts/trace_export/export_trace.py`(新增入口)

- `resolve_runs(id_, runs_root)`：D2 三态位置判定，命中不了/多义抛
  `TraceExportError`（exit 2）；
- `find_db / load_config / build_canonical_records / write_canonical`：
  只读打开 db（WAL 安全）→ 可选 `--session` 子串过滤（同 recon needle 语义）
  → 复用 `recon.reconstruct_session` 建 canonical 记录并按时间序落盘；
- `export_run(...)`：单 run 全链路（canonical + export_jsonl），无 db 抛
  TraceExportError；
- `export_code(run_dir, out_dir)`：拷贝 `<run>/artifacts/codegen/` →
  `<out>/code/`（终版算子代码随轨迹带出）；源缺失 WARN 跳过不算失败；
- `export_run(...)`：单 run 全链路（canonical + export_jsonl + code），无 db 抛
  TraceExportError；
- `main()`：逐 run 编排（SKIP/FAIL/OK 分类计数），末尾汇总，
  exit 0 ⟺ ok≥1 且 fail==0。
- 参数：`<id>`、`--runs-root output`、`--out trace_export`、
  `--session SUBSTR`、`--teacher MODEL`、`--no-code`。

### 4. `scripts/export_trace.sh`（新增 shell 入口）

配置写头部、执行零参数（用户拍板：不做命令行参数，否则与直调 Python 无异）：
`RUN_ID`/`BATCH_ID` 二选一（都空/都填 fail-fast exit 2）、`RUNS_ROOT`/`OUT_ROOT`
留空锚定仓根、`SESSION_FILTER`/`TEACHER` 留空透传缺省语义、`WITH_CODE=1/0`；
带命令行参数一律拒绝。逻辑单源仍在 `export_trace.py`，本脚本只做配置校验+转发。

### 5. `.gitignore`

追加 `trace_export/`（导出产物不进仓，与 output/ 同类）。

### 6. `tests/ut/scripts/test_trace_export.py`（新增 UT，TDD）

合成最小 schema fixture（session/message/part 三表 + opencode-config.json +
state_snapshot.json），importlib 按 path 加载 scripts 模块：

| 用例 | 守护 |
|------|------|
| resolve flat run | 规则① |
| resolve batch 过滤非 run 子目录 | 规则②（cann_bench 类目录不入列） |
| resolve nested exec 唯一命中 / 多义报错 / 未找到报错 | 规则③ |
| 单 run 端到端：canonical 条数 + slow/fast 归类 + 首条 system + teacher=日志模型 id | 主链路 |
| `--teacher` 显式覆盖生效 | D3 flag |
| batch 导出输出路径 `<out>/<batch>/<exec>/` | D5 |
| 终版代码拷贝到 `<out>/.../code/`；`--no-code` 跳过；缺 artifacts 记 WARN 不算失败 | D5 |

## 顺序

1→2→3→4→5（依赖序）；5 与 1–3 并行亦可，但按 TDD 先写用例再实现 3。

## 验证

```bash
python3 -m pytest tests/ut/scripts/test_trace_export.py -v      # 新 UT
python3 scripts/trace_export/export_trace.py <真实run_id> \
    --runs-root /home/x00584171/code/AscendC-DevKit/output \
    --out /tmp/opencode/trace_smoke                             # 真实 db 只读冒烟
```
