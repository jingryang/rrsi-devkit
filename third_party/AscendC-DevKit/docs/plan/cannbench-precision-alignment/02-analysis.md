# L3 方案分析：devkit 精度判定完全对齐 cann-bench 生产评测

> 调研中演进，拍板后冻结。关联 L1：`cannbench-precision-alignment/01-problems.md`（P1-P5）。

## 对齐目标（两个层次）

| 层次 | 目标语义 | 判定与参考 | 覆盖 |
|---|---|---|---|
| A | devkit `compare_outputs` == cann-bench `compare_tensors`（**同输入**：都不传 native） | 三值域都传参考时的语义统一；无参考时行为一致 | 非病态场景 |
| B（**选定**） | devkit 评测 == cann-bench **生产评测**（fp64 golden + native CPU 参考 + #92 兜底） | harness 传真实同精度参考 + fp64 权威 golden | 全部场景 |

**为什么必须层次 B**：层次 A 只对齐「比较函数」，但 devkit 生产 harness 从不传 native 参考（L1 P3），`cpu_diff≡0` → 小值域/相消恒触发零容忍、正常值域无 #92 兜底。即便把判定函数改成 ratio≤2，只要不传真实参考，`cpu_error_count` 仍恒 0，与 cann-bench 生产（总是传 native_output）在「CPU 参考自身也脏」的场景（深归约/相消桶，gelu 实证）必然分歧。

**关键洞察**：有效 native 参考的前提 = 存在 fp64 golden。devkit 现状 golden 是原生精度跑的，把它当 native 参考传 = `cpu_diff≡0`（无对比价值）。故必须 harness 跑**两遍 golden**（fp64 作权威、原生作同精度参考）——即 cann-bench `golden_precision=fp64_cpu` 的完整复刻。

## 选项

### A. 只改比较函数（层次 A） ✗ 否决
- 只把 `precision_compare.py` 小值域/相消改 ratio≤2 + 补 #92，不碰 harness。
- ✗ L1 P3/P4 未解决：`cpu_error_count` 恒 0，病态场景（CPU 参考脏）仍误杀。gelu 假性不通过会重现。
- 结论：不解决「生产评测对齐」这一用户诉求。

### B. 比较函数 + harness 两遍 golden + native 参考（层次 B） ✅ 选定
- **比较函数**：小值域/相消恒 ratio≤2；正常值域补 #92 兜底；`OutputVerdict` 增加 `normal_*` 字段（对齐 `CompareResult`）。
- **harness**：新增 `_upcast_fp64`（对齐 `tensors_to_fp64_cpu`，只升浮点）；CANN/FALLBACK 两路各跑两遍 golden——fp64 作 golden、原生作 native_refs/native_output。
- **容忍策略**：完全对齐 = 放弃 2026-08-01 的「防 golden=1e-6/output=65504 假阳性」守卫（用户明确接受）。
- ✅ 四把尺子：
  - **可维护**：恢复 P69 既定不变式「devkit 精度判定 == cann-bench 生产」；parity UT 逐 case 对拍守护。
  - **可扩展**：新 dtype/新场景自动归位（同一阈值表 + 同一判定逻辑）。
  - **可诊断**：`normal_*` 字段透出，diagnose/scope_guard 可区分失败值域；`_upcast_fp64` 对 int/bool 透传留痕。
  - **架构合理**：判定数学落 `precision_compare`（L6 比较器），golden 计算落 harness（执行侧），不越层。

### C. 保留零容忍 + 只加 harness 传 native（session 历史修法） ✗ 否决
- 用户副本（`yaolu-0810-bk`）曾实现此路线：harness 传 native_refs 但不删零容忍分支。
- 只消除「CPU 参考也脏」的病态误杀；「CPU 参考干净 + NPU 小值域 1-2 错」仍比 cann-bench 严（小值域 CPU 参考几乎总干净 → 残余分歧大）。
- 与用户选定目标「完全对齐」冲突。否决。

## 决策（2026-08-10 用户拍板）

**选 B：完全对齐 cann-bench 生产评测。**

1. `precision_compare.py` 三值域完全对齐（删零容忍 + 补 #92 + `normal_*` 字段透出）。
2. harness 两路 fp64 golden + native 参考。
3. 防假阳性守卫（golden=1e-6/output=65504）**放弃**，用户明确接受。
4. fp64 golden 恒开、不引配置（§1.4 不留 unused flexibility）；golden 对硬编码 dtype 自动 downcast 时如实反映（golden 自限精度，非 checker 缺陷）。
