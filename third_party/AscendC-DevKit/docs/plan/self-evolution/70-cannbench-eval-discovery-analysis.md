# 70 — e2e cann-bench 评测「算子发现链路」三层失败（A/B/C）方案分析

> 层级：**L3 / 方案分析**。回答「有哪些选项、选了哪个、为什么」。
> 问题事实见 `06-problems.md` [[P95]]/[[P96]]/[[P97]]；A 的实施见 `70-cannbench-eval-discovery-impl.md`。

## 问题域

run `20260722-022209-e08f46`（exp 算子）cannbench_eval `pass_rate=0.00`，根因是 cann-bench「算子发现链路」上**三层独立缺陷叠加**：

| 层 | 问题 | 性质 |
|---|---|---|
| A（[[P95]]）| `import cann_bench` 失败（PYTHONPATH 缺包目录）| 确定性框架 bug |
| B（[[P96]]）| exp 没进 `_C.abi3.so`（CMake cache/GLOB 陷阱 + 无 _C 重建环节）| 框架流程 + cann-bench 构建陷阱 |
| C（[[P97]]）| scan 发现 exp 但 `operators:[]`（kernel_eval 纳入失配）| 待查 |

三层独立且层层前置：A 不修 → import 断（B/C 无从谈起）；A 修后 B 不修 → exp 不在 `_C`；A+B 修后 C 不修 → exp 不被纳入评测。本次先固化 A+B（已定位/已修），C 待查。

## 归属判定（排除法 + 反证）

对每层用「修复落在哪一侧」反证归属：

- **A**：修复 = 改 `cannbench_eval.py`（框架 stage）→ **框架缺陷**。非用户环境（PYTHONPATH 是 stage 内部构造，用户无配置项介入）、非 transient（确定性，任何环境复现）。
- **B**：修复 = clean rebuild（cann-bench build.sh）+ 框架缺重建环节 → **cann-bench 构建陷阱 + 框架流程缺陷**。非 codegen（exp/CMakeLists.txt 正确）、非 transient（重跑 adapt 不重建 _C，因 adapt rebuild 的是 opp）。
- **C**：待查（kernel_eval 纳入逻辑），倾向框架/匹配层。

## A — 选项与取舍

**问题**：PYTHONPATH 要补「cann_bench 包所在目录」。该目录 = `examples/<example>/`，但 example 名不固定（aclnn_launch_example / direct_launch_example / ...）。

| 选项 | 做法 | 取舍 |
|---|---|---|
| ① 硬编码 example 名 | PYTHONPATH 加 `repo_root/examples/aclnn_launch_example` | ✗ 违 §1.5（资源路径不硬编码）；换 example 即断 |
| ② 从 source_dir 路径推导 | source_dir 形如 `repo/examples/<ex>/csrc/ops/<op>`，取 `examples/<ex>` | △ 依赖路径结构假设，脆弱 |
| ③ **向上探测（选）** | 从 source_dir 向上找最近含 `cann_bench/` 的祖先（限 repo_root 内） | ✓ 不依赖路径假设；自动适配任意 example；越界安全 |

**选 ③**：构造性正确——cann_bench 包目录的定义本身就是「含 `cann_bench/` 子目录的 example 根」，向上探测即直接表达该定义，无需假设路径布局。

## B — 选项与取舍

**问题**：新增算子要进 `cann_bench/_C.abi3.so` 才能被 scan 发现，但 CMake INTERNAL cache/GLOB 增量不更新 + workflow 无 _C 重建环节。

| 选项 | 做法 | 取舍 |
|---|---|---|
| ① **手动 clean rebuild（短期，选）** | `rm -rf build_py && bash build.sh` | ✓ 立即可用、已实证 exp 进 _C；✗ 每次新算子要手动 |
| ② 框架强制 clean rebuild _C（根治，待做）| deploy/adapt 后、eval 前加「重建 _C」步骤 | ✓ 框架自闭环；待实施（涉及 stage 编排 + build.sh 调用 + 耗时/磁盘）|
| ③ cann-bench 修 build 陷阱 | `file(GLOB ... CONFIGURE_DEPENDS)` / `ALL_PLUGIN_SRCS` 不用 cache | ✓ 治本；✗ cann-bench 是外部只读依赖，仅提建议 |

**当前选 ①**（手动，已验证 exp 进 _C）；② 列为框架根治待办；③ 提 issue 建议。

**显式否决「重跑 cannbench-adapt」**：adapt rebuild 的是 opp（per-op 部署包），**不重建 `_C`**（`cannbench_adapt.py:261`）——重跑 adapt 解决不了 B。这是 B 与「adapt 被 transient API 击中」的关键区分：adapt 那次 partial（transient）只是雪上加霜，即使 adapt 成功跑完，B 依然存在。

## C — 待查（不本次拍板）

scan 发现 exp（`torch.ops.cann_bench.exp` EXISTS）但 `operators:[]`。待读 `kernel_eval` 的 `package_manager`/evaluator 匹配代码定位（scan 发现 → operators 纳入 的衔接）。可能方向：`--operator Exp` 过滤 + tasks 用例匹配、或 torch.ops 接口需 `__init__.py` wrapper 才被认作可用接口。

## 拍板

- **A（[[P95]]）**：选 helper 向上探测（选项③），commit `6fec78c5` 已实施 + 6 UT。
- **B（[[P96]]）**：根因定位 + 手动 clean rebuild 可解（已实证）；框架根治（选项②）列为待办。
- **C（[[P97]]）**：待查，不阻塞 A/B 固化。
