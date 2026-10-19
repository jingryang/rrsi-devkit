# P4 changed-files 单通路收口 — L4 实施方案（2026-08-31）

> 层级：**L4 / 实施方案**。改哪个函数、什么顺序、怎么验证。
> 上游：`06-analysis-changed-files-single-path.md`（L3，已拍板冻结）。
> 盘点结论（已实证，无 TBD）：
> - 收集：`capabilities/agent/_shared.py:744-860`（`_collect_changed_sources`）；
> - 落盘：`orchestration/stages/codegen.py:4011`（`_persist_sources`，8 调用点
>   A3/A5 共享）；
> - git 真值：`infra/repo_guard.py:192`（`changed_paths` = diff ∪ ls-files --others，
>   返回 repo-relative）；
> - prompt 教学：`codegen.py:2325-2329`（共享 prompt 段）+ `perf.py:322`；
> - 内存读点（不动，验证用）：`codegen.py:2916/:3658`
>   （`artifacts.get("decision_log.json")`）、`:1719`（`Path(op_dir)/...`）、
>   manifest 读点（transition）；
> - 测试钉住面：`tests/ut/capabilities/test_capabilities.py`、
>   `tests/ut/infra/test_repo_guard.py`。

## 改动 1：`domain/artifact.py` — 名单常量（单点定义）

```python
#: 框架契约元数据文件（op_dir 顶层）——非算子源码改动：不进派生 changed-source
#: 报告，落盘路由 artifacts/<stage>/_contract/。内存 dict 照常携带（下游读点
#: 零改动）。§1.15 单点：收集侧与落盘侧两处消费，新增契约文件加一行。
CONTRACT_FILES = frozenset({
    "codegen_manifest.json",
    "decision_log.json",
    "changed_files.json",
})
```

匹配语义：**顶层精确匹配**（`rel in CONTRACT_FILES`），不做 basename 模糊匹配
（防误伤子目录同名文件）。

## 改动 2：`infra/repo_guard.py` — deleted 派生（新增方法，零破坏）

`changed_paths` 保持 `list[str]` 返回不变（rollback 等既有调用方零感知），新增：

```python
def deleted_paths(self, repo_root, op_dir, baseline_ref) -> list[str]:
    """Repo-relative paths DELETED under op_dir since baseline
    (git diff --name-only --diff-filter=D)。与 changed_paths 同款守卫
    （_enabled/baseline/git-repo 检查）与 scope。"""
```

实现即一条 `_git(repo_root, "diff", "--name-only", "--diff-filter=D",
baseline_ref, "--", str(op_dir))`。

## 改动 3：`_shared.py _collect_changed_sources` — 删自报 + 报告纯化

- **删**：`_parse_changed_files_report`（整个函数）、`_names_file` 后缀归一化、
  双向 WARN、`report_paths`/union 全部分支；
- **收集面** = `diff_paths`（git 权威，本就含未跟踪新文件）；
- **op 标签**：`deleted_set = repo_guard.deleted_paths(...)`（转换 op_dir 相对同
  现有循环）；`op = "deleted" if rel in deleted_set else "modified"`；deleted →
  `artifacts[rel] = ""`（记路径不读内容——现有语义，标签来源从自报换成 git）；
- **降级路径**（无基线扫描）：删 `scanned.pop("changed_files.json")` 特判——
  dict 照带，落盘由名单统一路由；
- **派生报告**：`{"changed_files": [{"path": p, "op": ...} for p in sorted(diff_set)
  if p not in CONTRACT_FILES]}`（名单排除=报告纯源码；同时吸收原
  `diff_set.discard("changed_files.json")` 特判）；
- `artifacts["changed_files.json"] = 派生报告`（照旧——框架派生版覆盖）；
- docstring 更新：Authority = git diff only（删 D2 union 表述，注明 20260831 收口）。

## 改动 4：`codegen.py _persist_sources` — 名单落盘路由

`norm` 归一化后：

```python
if norm in CONTRACT_FILES:
    target = dest / "_contract" / norm
else:
    target = dest / norm
```

（`target.parent.mkdir(parents=True)` 已支持子目录。）内存 dict 的 key **不变**
——路由只在落盘处发生，下游 `artifacts.get(...)` 读点零改动。

## 改动 5：两处 prompt 删填表教学

- `codegen.py:2325-2329`：删"必须写 changed_files.json + 格式示例 + 据其核对"
  三行半；保留并改写 :2329 为"完成后用
  `git diff --name-only -- op_host/ op_kernel/ op_api/ op_plugin/` 自验改动文件"
  （删"核对 changed_files.json 完整性"从句）；
- `perf.py:322`：删"完成后更新 changed_files.json"行。

## 实施顺序（TDD，§3.1）

1. **红测 repo_guard**（`test_repo_guard.py`，tmp git repo fixture 造三态）：
   `deleted_paths` 命中删除集 / 无删除时空 / 与 changed_paths 的删除子集一致；
2. **红测收集**（`test_capabilities.py`）：①自报文件存在但 dict/报告零自报
   独有路径（自报通路已死）；②派生报告**仅源码**（三契约文件不进）；③删除文件
   进报告 `op="deleted"` 且 dict 空内容（无自报参与）；④降级路径无特判仍正确；
   ⑤源级断言：`_shared.py` 无 `lists files git diff`/`_names_file` 残留；
3. **红测落盘**（codegen stage UT）：名单三文件落 `_contract/`、源码平铺、
   `decision_log.json` 内容正确；两轮调用幂等（无 `codegen/codegen/` 嵌套回归）；
4. **红测 prompt**（源级）：codegen/perf prompt 渲染结果不含
   `changed_files.json` 教学字样；
5. 实施改动 1→2（repo_guard 绿）→3（收集绿）→4（落盘绿）→5（prompt 绿）；
6. 随通路删除改写既有钉住用例（WARN/自报解析/后缀归一化 → 钉"无 WARN"）。

## 验证

```bash
PYTHONPATH=src pytest tests/ut/infra/test_repo_guard.py -q
PYTHONPATH=src pytest tests/ut/capabilities/test_capabilities.py -k "changed" -q
PYTHONPATH=src pytest tests/ut/orchestration/ -k "persist or codegen" -q
PYTHONPATH=src pytest tests/ut --quick -q          # 全量
PYTHONPATH=src pytest tests/st -m "not heavy_llm" -q  # 全量 ST（§3.6 默认模式）
```

不新增 heavy_llm（无 LLM 链路改动；收集/落盘是确定性层）。真实链路验证由下批
批跑承担：codegen 跑完日志**零 changed-files WARN**、`artifacts/codegen/_contract/`
三件齐、派生报告纯源码。

## 判据（完成的定义）

- 派生 changed_files.json 仅含算子源码，删除文件 `op="deleted"` 由 git 派生；
- `artifacts/codegen/_contract/{codegen_manifest,decision_log,changed_files}.json`
  落位，源码平铺不变；
- 内存 dict key 不变（下游读点零改动——用例 :2916/:3658 既有断言全绿即证）；
- grep 判据（§1.15）：`CONTRACT_FILES` 定义仅 domain/artifact.py 一处；
  `_names_file`/`lists files git diff` 全仓零残留；
- codegen/perf prompt 渲染无 changed_files.json 教学字样；
- A5 侧零文件改动（git diff 确认 regbase SKILL/agent 不在本次变更集）。

## 风险清单

| 风险 | 缓解 |
|---|---|
| 删自报后某隐蔽读点仍要自报内容 | 盘点已穷举（读点全列）；全量 UT/ST 回归网 |
| `_contract/` 布局对同事工具/习惯的影响 | 无程序化依赖（run_manifest 按前缀分类不敏感）；知会即可 |
| deleted_paths 与 changed_paths 双查询轻微重复（两次 git 调用） | 每次 spawn 多 ~10ms；正确性优先，不做单查询合并优化 |
| 降级路径删 pop 特判后行为变化 | 降级 dict 多带 changed_files.json → 落盘路由 `_contract/`，语义更一致（用例④钉住） |
