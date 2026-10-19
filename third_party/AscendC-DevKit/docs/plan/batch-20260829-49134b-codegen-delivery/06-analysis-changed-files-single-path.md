# P4 changed-files 单通路收口（git 全量派生 + 契约元数据分离）— L3 方案分析（2026-08-31）

> 层级：**L3 / 方案分析**。记录选项、取舍、理由；拍板后冻结。
> 上游：`01-problems.md` P4 + 用户扩展需求（2026-08-31：三个契约 json 与源码分离、
> 消除每轮告警）。范围与 P4 原题同族同收口，合为一个 step。

## 问题定义（两支同根）

1. **自报双轨残留**（P4 原题）：git 权威派生已建成后（20260810 修复），自报通路
   （解析+并集+双向 WARN+两处 prompt 填表教学）未删——纯噪音 + prompt 负担
   （§2.5 过渡并存；§1.14 "让模型填表"）；
2. **契约元数据污染源码改动面**（用户扩展）：`codegen_manifest.json` /
   `decision_log.json` / `changed_files.json` 按契约写在 op_dir 根，git 视作未跟踪
   新文件 → ① agent 不自报它们 → 每轮 `git diff found changes the agent didn't
   report` WARN 必响；② 混进派生"算子源码改动"报告（它们不是算子改动）；
   ③ artifacts/codegen/ 源码与元数据混放。

同根：**框架契约元数据与算子源码两类实体混在同一个 git 真值面上**，旧自报通路
又放大了混淆。

## 方案主体（三件，一个名单串起来）

### A. git 补 deleted 派生（删自报前的功能保全）

自报残存的唯一真实功能 = per-file `deleted` 标签（缺它则纯 diff 发现的删除文件因
读不到内容被静默丢弃，不进审计产物）。补法：`repo_guard` 新增
`deleted_paths(repo_root, op_dir, baseline)`（`git diff --name-only --diff-filter=D`，
与 `changed_paths` 同款式返回 repo-relative）——删除信息由 git 构造性派生，
不依赖 LLM 纪律。

### B. 删自报通路（§2.5 收口）

- `_parse_changed_files_report` + 并集 + 双向交叉校验 WARN + `_names_file` 后缀
  归一化补丁，整段删除；
- 派生报告 `op` 标签从 git 来（A 的 deleted_paths）；
- 两处 prompt 填表教学删除（codegen.py:2325-2329 共享 prompt 段 + perf.py:322）；
  保留"用 `git diff --name-only` 自验改动"一句（帮模型自检，非填表）。

### C. 单点契约元数据名单 `CONTRACT_FILES`（§1.15，泛化现有特判）

```python
CONTRACT_FILES = frozenset({"codegen_manifest.json", "decision_log.json",
                            "changed_files.json"})
```

放 `domain/artifact.py`（artifact 契约知识域，ArtifactContract 旁）。**顶层精确
匹配**（`rel in CONTRACT_FILES`，不 basename 模糊匹配——防误伤子目录同名文件）。
名单单点定义、两处消费：

| 层 | 名单语义 |
|---|---|
| 收集侧（`_collect_changed_sources`） | 名单文件**不进派生 changed-source 报告**（它们不是算子改动）；**仍收集进内存 dict**（下游 `artifacts.get("decision_log.json")` 等读点零改动） |
| 落盘侧（`_persist_sources`） | 名单文件写到 `artifacts/codegen/_contract/`，源码照旧平铺 |

三文件三层精确语义（实现与测试的对照表）：

| 文件 | 内存 dict | 派生报告 | 落盘位置 |
|---|---|---|---|
| 算子源码 | ✓ | ✓ | `artifacts/codegen/` |
| codegen_manifest / decision_log | ✓（收集） | ✗ | `artifacts/codegen/_contract/` |
| changed_files.json | ✓（**框架派生版**覆盖，agent 版不收集——现状语义保留） | ✗ | `artifacts/codegen/_contract/` |

降级路径（无基线 `_scan_working_dir`）同步：删 `pop("changed_files.json")`
特判，统一由名单落盘路由（dict 语义不变）。

## A5 影响判定（已实证，零契约破坏）

regbase codegen 与 A3 同在 `codegen.py` stage 类（:959 按 profile 选 skill），
`_persist_sources` 8 调用点、backend 收集、repo_guard 均 A3/A5 共享。A5 吃到的
是对称收益（WARN 同困扰 A5、deleted 标签/分离布局同理）；A5 的 skill（不教自报，
grep 零命中）、写入契约（`$CODE_PATH/`）、内存读点**零改动**。artifacts 布局变化
对同事可见，知会即可（非技术必须）。

## 否决项

| 否决方案 | 死因 |
|---|---|
| 挪元数据写入位置（op_dir → workspace 侧） | 位置契约 **A3/A5 共享**（regbase SKILL:351 同款），动它=改 A5 skill+base 机制+双侧读点，需同事确认——名单路由以零契约变更达到同样可见效果；结构上最理想但范围不抵 |
| artifacts 不再收集元数据（纯排除） | 丢 crash 取证价值——P1 复盘实证用过 artifacts/codegen/codegen_manifest.json（rollback 后唯一幸存副本）；**分离而非删除** |
| 保留 WARN 降级为静默/debug 级 | 纯信息性、无可操作消费方（派生已是权威），留着=维护两套认知；删 |
| 收紧自报格式教学（把表教清楚） | LLM 纪律填表，§1.14；信息 100% 可由 git 构造性派生 |
| 改 `changed_paths` 返回类型带 op 标签 | 调用方多处（rollback 等），破坏面大；新增 `deleted_paths` 独立方法零破坏 |

## 原则映射（审计结论 2026-08-31，全绿）

§1.14（git 真值，删填表）；§2.5（删旧通路，唯一通路=git 派生）；§2.9（构造性
派生优于检查门——WARN 即旧检查门）；§1.15（名单单点+泛化 changed_files.json
特判；deleted 派生单点在 repo_guard）；§1.12/§2.x（prompt 删教学，无算子耦合）；
§2.3（I/O 契约位置不动，A5 零感知）。

## 测试策略

- repo_guard：tmp git repo fixture 造 修改/新增/**删除** 三态，`deleted_paths`
  精确命中删除集、与 `changed_paths` 一致性；
- _collect：自报文件存在但被忽略（dict 无自报独有路径）；派生报告仅源码
  （名单三文件不进）；**deleted 文件进报告且 op="deleted"**、dict 记空内容；
  降级路径无 pop 特判仍正确路由；
- _persist_sources：名单 → `_contract/`、源码平铺、子目录 mkdir 正确；
- prompt 源级断言：codegen/perf prompt 不再含 changed_files.json 教学字样；
- 既有钉住 WARN/自报解析/后缀归一化的用例随通路删除（改写为钉住"无 WARN"）。
