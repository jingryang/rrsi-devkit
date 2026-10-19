# 49 — PrecisionComparer 协议化：rule × backend 正交 + 解除 P78 选项 E 暂缓（L3 方案分析）

> 工作线：self-evolution
> 状态：**✅ 已实施（v1，2026-07-15）**
> 关联 L4：`49-precision-comparer-protocol-impl.md`
> L1 问题：`06-problems.md` P79
> 承接：P78（`48-precision-spec-threading-{analysis,impl}.md`，选项 E 暂缓判据失效）

## 背景：合并回退了 P78 的两个落地

P78（commit `7696279`）选定方案 B，核心两个承诺：
1. **维度 A（阈值贯穿）**：proto `precision_thresholds` → `OperatorSpec.precision_thresholds` → runner。
2. **维度 B（方法自包含）**：devkit 自实现标准方法（MERE/MARE/bit-exact/...），**零 import cann-bench**（§1.7）。

合并 commit `082c02f` 取 origin/main runner 后，**两个承诺在生产链路都没成立**（详见 L1 P79 事实节）：
- 维度 A：proto 真值三路径无消费点（`_custom_th` 硬编 / `_DTYPE_THRESHOLDS_FALLBACK` 自带表 / `task_loader._derive_thresholds` 读错字段名 `thresholds` vs proto 真键 `precision_thresholds`）；`OperatorSpec.precision_thresholds` 悬空（`grep '.precision_thresholds'` 零命中）；`debug_service` 注释称优先 op_spec 但未桥接 `.precision_thresholds → dtype_thresholds=`。
- 维度 B：runner 重新 `try import cann-bench`（路径嗅探 `'tasks/' in golden_source_path` 塞 `sys.path` → `from kernel_eval.utils.compare import compare_tensors`）。P78 自实现 `precision_compare.py` 已就绪但 UT-only（runner 未用）。

P78 选 B 时**暂缓了选项 E（协议化）**，暂缓理由（`48-analysis.md:65-69`）：「唯一出题方=cann-bench，cann-bench adapter 空置属 §1.4 unused flexibility；且不省重写（B 仍需作默认比较器）」。

**本方案解除 P78 选项 E 暂缓**——暂缓判据在三件事后失效（见下「为何现在解除」）。

## 精度判定的两个维度

精度判定可拆成两条**正交**的独立维度（任一单独成立都不够）：

- **维度 A（阈值/tolerance）**：判「差多少算过」。per-dtype 阈值，proto 覆盖默认。**DQ 冤杀的根因在此**——int8 真值 `1.0` 没贯穿，runner 用 `1e-2`。
- **维度 B（比较方法/method）**：判「怎么算这个差」。MERE/MARE（相对误差）vs abs-diff（绝对误差）vs 精确匹配 vs bit-exact。维度 B 是独立的质量维度，与 A 无关。

P78 把两者打包进方案 B（自实现标准方法覆盖 B，阈值数据传递覆盖 A）。合并回退后两者都得补。**P79 把两条维度显式正交化**，让它们各自可独立演化。

## 四层可替换性图谱

精度判定有四层「可替换点」，P79 明确产权分层（每层只在一处可换）：

| 层 | 替换什么 | 性质 | P79 处置 |
|---|---|---|---|
| **L1 阈值（数据）** | per-dtype 阈值 | 数据（dict） | **实现**：proto `precision_thresholds` 贯穿进 `CompareRule.dtype_thresholds`，删三处误读/硬编 |
| **L2 方法实现（backend）** | 谁来算（devkit 自实现 / cann-bench） | 实现（class） | **实现**：`PrecisionComparer` 协议 + `DevkitComparer`（默认，§1.7）/ `CannbenchComparer`（可选注入） |
| **L3 比较模式（rule schema）** | 单标杆 / 双标杆 / 区间 | 语义（rule 对象演化） | **预留接口**：`CompareRule` 用对象不用散参数，未来扩 schema 不动协议签名 |
| **L4 引擎（执行介质）** | callable / command | 介质（backend 子型） | **预留接口**：backend 协议不假设 callable，未来 `CommandBackend` 按需 |

P79 范围：**实现 L1 + L2，预留 L3 + L4 的接口形状（不实现）**。这是 §2.7（不为假想需求固化脚手架）与「协议签名不留死扣」（用户共识：预留成本极低）的平衡。

## 为何现在解除 P78 选项 E 暂缓

P78 暂缓 E 的判据是「唯一出题方=cann-bench，adapter 空置=unused flexibility」。三件事使该判据失效：

1. **合并改变了状态**：P78 暂缓 E 的隐含前提是「B 已经让 runner 不与具体出题方耦合（自实现 + 数据传递）」。合并回退后这个前提**没成立**——runner 现实里就是 import cann-bench 的。协议化（E）反而是把「可换」从隐含变成显式契约，去掉路径嗅探这种脆弱判定（§1.7：运行时不应靠 `'tasks/' in path` 反推出题方）。

2. **用户需求扩大了边界**：本轮用户明确追问——换双标杆、注入对比命令、多评测仓复用同一通路。这些是真实可能出现的扩展点（命令注入 = L4，双标杆 = L3，多仓复用 = L2 backend 可换），不是「unused flexibility」。暂缓判据「唯一出题方」被这些需求直接推翻。

3. **autoload 冲突在 subprocess 模型消化**：P78 选项 C 否决 `import cann-bench` 的硬理由是 torch_npu autoload 冲突（需 `TORCH_DEVICE_BACKEND_AUTOLOAD=0`）。当前 runner 在 subprocess harness 里跑比较（`48-impl.md` 的 run_test 解耦方向），`CannbenchComparer` **注入时才 import**（默认 `DevkitComparer` 零 import），import 失败软降级——autoload 副作用被隔离到可选注入路径，不污染默认链路。

**结论**：E 不再是「空置的 unused flexibility」，而是「让维度 B 显式可换、消除路径嗅探、为用户已表达的多模式/命令注入需求留正交扩展点」。解除暂缓，落地为 rule × backend 正交架构。

## 选项

### 维度 A（阈值贯穿）的修复

#### A-1. 桥接 op_spec.precision_thresholds → CompareRule（rule 的真值来源）

`debug_service` 读 `op_spec.precision_thresholds`（proto 真值，P78 已 thread 进 spec）+ cann-bench 对齐默认表 → 组装 `CompareRule.dtype_thresholds`（proto 覆盖默认），传给 runner。删 `task_loader._derive_thresholds`（读错字段名）与 runner `_custom_th` 硬编、`_DTYPE_THRESHOLDS_FALLBACK` 自带表移到 rule 构建处。

> **拍板（实施时定，2026-07-15）**：rule 构建 + comparer 选择的**装配点落在 L3 `run_precision_cases`**，**不**在 L2 `debug_service`——L2 只算 `use_cannbench_checker = bool(task_test_cases)` flag 传下去（§1.1 分层：L2 不 import L6 adapter，L3 独占 NPURunner）。`merge_thresholds(op_spec.precision_thresholds)` 在 `run_precision_cases` 内调（懒导入，保持 runner/编排模块 torch-free）。详见 L4。

- ✅ §2.5（单通路：阈值唯一来源 = proto 进 spec → CompareRule → runner）。
- ✅ §1.7（默认链路零外部依赖）。
- ✅ §1.4（删错字段误读/硬编，不留过渡分支）。

#### A-2.（否决）只改 task_loader 字段名

仅把 `proto.get("thresholds")` 改成 `proto.get("precision_thresholds")`。
- ✗ 不彻底：`task_loader` 读的是 cann-bench task 目录里的 proto（评测产物），与 devkit 自己的 requirement proto 解析（`requirement.read_proto_precision`）是**两条不同通路**；且 `_custom_th` 硬编、op_spec 悬空仍在。只打一处补丁不消除「三路径无消费点」的结构问题（§1.2 架构合理）。

### 维度 B（方法）的协议化

#### B-1. PrecisionComparer 协议 + DevkitComparer 默认 + CannbenchComparer 可选注入 ✅ 选定

```python
# domain 层：纯数据（无 torch/无 adapter import，§1.1 domain 零依赖）
@dataclass(frozen=True)
class CompareRule:
    """精度判定规则（数据）。当前承载 per-dtype 阈值（单标杆）。
    预留：未来双标杆/区间只扩字段，协议签名 harness_setup_lines/aggregate 不变。"""
    dtype_thresholds: dict[str, float]

# adapters 层：subprocess-harness 策略（backend 侧）——非主进程 compare 可调用
# （张量在 subprocess harness 内，主进程拿不到；见 L4 关键架构约束）
class PrecisionComparer(Protocol):
    def harness_setup_lines(self, rule: CompareRule) -> list[str]: ...  # 注入 harness 顶部 import 行
    def aggregate(self, rule: CompareRule, case_details: list[dict]) -> bool: ...  # 主进程聚合

# 实现层
class DevkitComparer:        # §1.7 自包含默认：setup=[]（abs-diff 用 harness 内 numpy），aggregate=judge
class CannbenchComparer:     # 可选注入：setup 注入 kernel_eval import（软降级 warn），aggregate=judge
```

> **拍板（实施时定，2026-07-15）**：协议签名从草案的「主进程 `compare(rule, output, golden, dtype)`」收敛为「`harness_setup_lines` + `aggregate`」**策略对象**——精度比较在 subprocess harness 内执行（张量在那），主进程只注入 setup import 行 + 聚合回传的 `case_details`。**不引入** `CaseCompareResult`/`HarnessComparePlan`/`PrecisionOutcome` 等中间结构（§2.7 不为假想统一抽象）。

- ✅ §1.7（默认 `DevkitComparer` 零 import cann-bench；`CannbenchComparer` 的 import 副作用隔离到注入路径）。
- ✅ §2.5（唯一通路 = 协议；具体 backend 由 config 显式选，不靠 `'tasks/' in path` 嗅探）。
- ✅ §1.6（业务层持有 Protocol，实现经 adapter 注入）。
- ✅ 正交：维度 A（rule.data）与维度 B（backend.impl）独立演化——换阈值不改 backend，换 backend 不改 rule。
- ✅ 预留 L3/L4 形状：`harness_setup_lines(rule)`/`aggregate(rule, ...)` 用 rule 对象，`PrecisionComparer` 是 Protocol——扩双标杆只动 rule schema（加字段），加 CommandBackend 只新增一个 adapter，协议签名稳定。
- **关键区分（≠ P78 否决的 C）**：P78 否决 C 是「import cann-bench callable 当入参」=运行时外部依赖未减。B-1 默认链路**不 import cann-bench**（DevkitComparer 自实现），CannbenchComparer 是显式可选注入——默认满足 §1.7，注入是用户主动选的权威路径，不是兜底。autoload 冲突只在注入路径，且 subprocess 隔离。

#### B-2.（否决）保留 runner try import + 路径嗅探

维持 origin/main 的 `sys.path` 嗅探 + `from kernel_eval...import`。
- ✗ §1.7（路径嗅探反推出题方，运行时外部依赖未声明）；脆弱（`'tasks/' in path` 是隐式约定，proto 改名/目录变就哑火）。
- ✗ §2.5（隐式双通路：嗅探命中走 cann-bench，否则 abs-diff——选哪个由路径字符串决定，不由 config 决定）。
- ✗ 不可诊断（import 失败静默 `except ImportError: pass` 退 abs-diff，错误被吞）。

#### B-3.（否决）删除 cann-bench 后端，只留 DevkitComparer

激进地连 `CannbenchComparer` 都不建，runner 永远自实现。
- ✗ 损失权威对齐：cann-bench 是出题方，其 `compare_tensors` 是精度判定的权威实现（DQ 那例 bit-exact 一致靠它判过）。devkit 自实现是 **parity 复刻**，不是权威本身。用户明确要保留 cann-bench 权威路径（cann-bench 任务走 cann-bench 真实 compare）。只留自实现 = 丢掉权威校验口。
- ✗ 与用户既定「cann-bench 任务用 cann-bench 真实 compare_tensors」冲突。

## 决策

**选 A-1 + B-1**，rule × backend 正交：

- **维度 A**：proto 真值经 `OperatorSpec.precision_thresholds` 桥接成 `CompareRule.dtype_thresholds`（proto 覆盖 cann-bench 对齐默认表），传入 runner。删 `task_loader._derive_thresholds`（字段名误读）、删 runner `_custom_th` 硬编、`_DTYPE_THRESHOLDS_FALLBACK` 上移为 rule 构建处的规范默认表。
- **维度 B**：`PrecisionComparer` 协议（`domain`）+ `DevkitComparer`（默认，`adapters`，调 `precision_compare.py`，§1.7）+ `CannbenchComparer`（可选注入，注入时 import，软降级）。backend 由 config 显式选，删 runner try import + 路径嗅探。
- **L3/L4 预留（不实现）**：`CompareRule` 用对象（不写死单标杆字段），`PrecisionComparer` 不假设 callable——双标杆 rule / `CommandBackend` / 远程后端按需再加，协议签名稳定。

**YAGNI 红线（§2.7）**：P79 不为假想需求**实现** `CommandBackend`、双标杆 rule、远程后端；只让协议**形状**不堵死它们（rule 用对象、backend 是 Protocol）。「预留接口形状」成本极低，「预留接口实现」是过度设计——只做前者。

**解除 P78 选项 E 暂缓**：E 从「unused flexibility」升格为「维度 B 显式可换 + 消路径嗅探 + 服务用户已表达的多模式/命令注入需求」。P78 选 B 的隐含前提（自实现 + 数据传递已让 runner 不耦合出题方）因合并回退而没成立，故 B-1 协议化是补齐而非重复造轮子。

## 与 step 40 的关系（正交）

step 40（run_test 与 cann-bench 解耦：测试执行外部化）把**测试执行整体**做成外部命令通用契约。P79 把**精度对比这一具体维度**做 rule × backend 协议化。两者方向一致（都把 cann-bench 依赖从「隐式 import」变成「显式契约」），但**职责正交**：step 40 管「跑测试」，P79 管「判精度」。P79 落在精度对比器边界内，不外扩到测试执行编排。

详见 L4。
