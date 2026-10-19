# 02 — 方案分析（L3）

> 状态：**方案冻结**（2026-07-29，用户拍板）。引用 L1 `01-problems.md` P1-P6 的事实，
> 本文件只写选项/决策/理由（事实产权在 L1，代码改动产权在 L4）。

## 问题定位一句话

P1+P2+P3：codegen smoke 有意只做符号解析（step-31 §5 接线门设计），但 `smoke_passed`
字段语义承诺「实际调用验证可调用」——契约不一致让 `smoke_passed=True` 成为虚假绿灯，
执行类缺陷被推到 precision_debug 才暴露（断裂点）。

## 三个选项

### 选项 A — 升级 smoke 为真实执行探测（**选定**）

smoke 对 torch_op/pybind 复用 precision_debug 同款 harness，真实 `fn()` 调用一次最小 case
（单用例、无 golden、不验精度），`smoke_passed=True` 名副其实 = 可执行。
- 仍守 codegen 边界（接线 + 可执行都是 codegen 产出物），精度仍归 run-cases——是**扩展
  step-31 §5 接线门边界**（接线 → 接线+可执行），不是取消正交分工。
- 代价：smoke 从毫秒级纯 CPU getattr 变秒级真实 NPU 执行 + 需卡；harness 把 case 异常吞成
  exit 0 + `case_details[].error`，判据须解析 JSON（不能只看 returncode）。

### 选项 B — 保持接线门、修正 `smoke_passed` 契约语义

smoke 维持 step-31 设计（只验注册），修正字段语义/文档明确「接线通过 ≠ 可调用」，下游不被
绿灯误导。最轻、不碰 step-31 分工。代价：codegen 仍不验执行能力，「到 debug 才知不能调用」
不消除。

### 选项 C — 加可执行预检层

smoke 维持接线门，codegen 闭环另加一个「真实调用最小 case」预检（接线/可执行/精度三层）。
代价：引入第三个 gate、codegen 变重需 NPU（同 A）、与 step-31「两 gate 正交」哲学有张力。

## 决策：选项 A

用户拍板（原话「现在我就需要 smoke 跑一个用例，否则 codegen 和 precision 之间会有明显的
断裂点」）。选 A 的理由：

1. **消除断裂点**（用户核心诉求）：smoke 与 run-cases 用同一套执行验证机制（复用
   `NPURunner._build_test_harness`），构造性保证 smoke 通过 ⇒ precision_debug 能调用。
2. **`smoke_passed` 名副其实**：实现回到字段语义（verification.py:65「实际调用一次算子
   验证可调用」），消除 P2 契约不一致。
3. **codegen 已 requires_npu**（`workflow.py:377`）：smoke 用 NPU 不增加新环境依赖。
4. **复用既有通路**（§2.5）：不重写 harness 序列化逻辑，复用 precision_debug 的
   `_build_test_harness`，零拆分共享模板。

## 与 step-31 §5 的关系（扩展边界，非推翻）

step-31 §5 的核心不变式——「smoke 失败域 = codegen 产出物，守 precision_debug 边界；
精度归 run-cases」——本步**保留**。扩展的是 smoke 的失败域：从「接线/注册/.so 加载」扩到
「接线 + 可执行（fn() 不崩）」。两者都是 codegen 产出物缺陷，smoke 仍守 codegen 边界、
不越界到精度（精度对比仍只在 run-cases 发生）。精度门仍归 precision_debug。

## 四把尺子复核（§1.2）

- **可维护**：复用 `_build_test_harness` 单一通路（§2.5），smoke/run-cases 同一套执行机制，
  澄清了「smoke_passed = 实际调用验证」既有不变式。
- **可扩展**：新 callable kind 若需 smoke，统一走 harness 真实调用；aclnn 暂无探针仍 fail-closed。
- **可诊断**：smoke 失败落 `subprocess/*.log`（既有 `_persist_subprocess_output`）；
  `case_details[0].error` 携带 kernel 异常 repr（§1.2 不静默吞）。
- **架构合理**：改动落 deploy 边界（L3）复用 runner harness（L6），向下依赖合法（§1.1）；
  卡用 `state.npu_id` hard-pin（card_pool 在 redeploy 子进程不可用，§2.5 不留 false-safety）。

## 不做（边界）

- **不动 A5**（P5）：A5 s5-compile 伪造 smoke_passed 是独立问题，暂缓。
- **不动 precision_debug run_tests**：它读 `last_deploy.json`（`debug_service.py:116`）不读
  codegen 的 smoke 信号；反而因 codegen 交出的算子已验过可执行，precision_debug 首轮 run-cases
  不再撞「调用就崩」。
- **aclnn 不覆盖**：保持 fail-closed 现状（harness 也不支持 aclnn）。
- **不改 `smoke_passed` 字段名/schema**：语义本就要求真实调用，改名无收益。
