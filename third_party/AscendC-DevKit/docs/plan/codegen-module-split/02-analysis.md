# L3 方案分析 — CodegenStage 职责拆分为 Mixin 族（God module 治理）

- 层级：**L3 / 方案分析**。记录选项、取舍、理由。调研中演进，拍板后冻结。
- 上游：`01-problems.md` P1（事实产权在 L1，此处只引用）。
- 状态：**已拍板（2026-09-08）**——用户确认按本方案执行（「在保证方案符合软件重构原则的情况下，按你的建议做」）。
- 下游：`03-impl-*.md` L4（按刀产出）。

---

## 一、决策问题

`CodegenStage` 单类 4300 行、5 职责簇，持续膨胀为 God module（L1 P1）。要把**单类内部按内聚切模块**，
同时**保持公共 API 不变**（§1.1 编排层 consumer 依赖 stage 注册 / transition 签名）。

「按软件重构原则」具体化为三条硬约束：

1. **行为零变化**：只做机械搬迁（原样剪切、零语义改写）；不改任何判断/路径/日志/返回。
2. **公共 API 不变**：`CodegenStage` 仍是注册入口（`registry.py:32`）、`integrate.py` 仍能
   `CodegenStage._expected_code_files(state)`、测试仍从 `stages.codegen` 取 `CodegenStage`。
3. **迁移可验证**：每刀搬迁后 codegen 簇 565 例 + 全量 UT 4297 例回归全绿，才允许下一刀。

## 二、候选方案

### 方案 1 — 子包：`stages/codegen/`（`__init__.py` 收敛 + 每域一模块）

把整个类压实成包，`init` 重新定义 `CodegenStage` 类、方法以 `from ... import` 回填。

- 优点：模块名短、物理文件最小；域与文件一一对应。
- 缺点（否决理由）：
  - **类定义要重新声明**——`@register_stage` 装饰点必须留在 `__init__.py`，但方法体散落各
    文件再 trade，本质是「在一个文件里 class 定义 + 别文件函数回填」的伪类，破坏 Python
    `class` 的隐式协议（MRO / `functools` / patch 目标全变）；
  - 测试 `from ...codegen import CodegenStage` 仍可，但 `inspect.getsource` / 确定性静态引用
    的语义会悬空；
  - 每域文件的内部 import 依赖 `__init__` 的循环可达，拆解后 import graph 更绕。

### 方案 2 — Mixin 族：`codegen_stage_mixin/*.py`，各切成 mixin，`CodegenStage(Stage, *Mixins)`（选）

类只保留「编排壳」（`actions` / `transition` / contract / `_expected_code_files` / `rerun_*`），
其余按域切成多个 mixin，`CodegenStage` 多继承收敛。

- 优点：
  - **方法仍是类方法**：`self.x` / `cls.x` 跨 mixin 天然可达（Python 多继承线性 MRO），
    `_persist_sources` / `_render_build_feedback_section` 跨域共享直接可用，**零 import 依赖**；
  - **`integrate.py:97` `CodegenStage._expected_code_files(state)` 原样可用**（静态方法在基类 mixin 上，经类属性访问同样解析）；
  - **类级常量原地可用**：`_SMOKE_MARKER_RE` / `_classify_smoke_phase` / `_REQUIRED_MANIFEST_KEYS` /
    `_MANIFEST_DEBUG_NOTE_FIELDS` 放对应 mixin，`self._classify_smoke_phase` 跨 MRO 消解；
  - **测试零改动**：无任何用例 patch 到 `CodegenStage.<方法名>` / `stages.codegen.<方法名>`，
    只有 `stages.codegen.Path`（`_regbase_skill_root` 拆走时改 patch 目标为其所在模块即可）；
  - `@classmethod` 的 `_smoke_last_marker` / `_smoke_error_signature` 互相引用 `cls`，在 mixin
    里完全等价；
  - **增量落地**：可按刀先加 mixin、后注释旧方法（`git mv` 语义），每刀可独立回归。
- 缺点：
  - mixin 名冗长（`regbase_mixin.py`）；但在同域名下是行业惯例，可接受。

### 方案 3 — 域模块模块级函数（不挂类）

把 `_validate_scalar_contract` / `classify_smoke_failure_phase` 这种已在模块级的函数继续推广，
各域收敛成模块级函数 + `CodegenStage` 只留转发壳。

- 优点：纯函数最易测。
- 缺点（否决）：拆分后 `_persist_sources` 等多依赖模块级常量 + mixin 状态，函数签名会急剧
  膨胀（一坨 context 参数）——破坏可读性；且 `classify_smoke_failure_phase` 转发自
  `staticmethod(classify_smoke_failure_phase)` 的先例已证明模块级函数 + 类属性别名的
  组合在这里够用，不需要为所有域强制。

---

## 三、拍板决策

| # | 决策 | 内容 |
|---|---|---|
| D1 | 选方案 2 | Mixin 族：`stages/codegen_stage_mixin/` 子包（下含多个 mixin 模块），`CodegenStage(Stage, *Mixins)` |
| D2 | 拆成 5 个 mixin | 契石门 / 反馈渲染 / 部署 / prompt 组装 / regbase 专用 |
| D3 | 编排壳留在 `CodegenStage` | `actions` / `transition` / contract / `_expected_code_files` / `rerun_*` / mid-mix `transition_membase` 不动 |
| D4 | 零行为改写 | 原样剪切方法体；仅当发生「文件归属变更」移动后，`@register_stage` / `class` 声明不随迁 |
| D5 | 每刀一步回归 | 每刀搬迁后：`pytest tests/ut/orchestration/test_codegen*.py` + `pytest tests/ut/orchestration/ -q -k 'codegen'` 全绿才切下一刀 |
| D6 | 最终回归 | 全量 UT（~4297）+ 真实批量 smoke（batch_self_evolve）绿 |
| D7 | 模块级函数不动 | `_validate_scalar_contract` / `classify_smoke_failure_phase` / `_json_text` / `_first_host_roundtrip` / `_registrations_from_artifacts` 保持原位（已被 `precision_debug_substages.py` / UT 引用） |

## 四、刀序（从低风险到高风险）

每刀都以「先求文件干净、后求 diff 明显」为目标。**注意**：迁移是 `git mv` 语义而非手动复制——
用 `git mv` 保留历史（`git mv` 会因文件移动自动跟踪），从 `codegen.py` 剪到新文件。

| 刀 | 内容 | 关注 |
|---|---|---|
| **刀 0（预检）** | 固化 `_validate_scalar_contract` / `classify_smoke_failure_phase` 模块级函数 + 5 簇覆盖密度基线 | 已由前序会话测过 |
| **刀 1** | regbase mixin（2074 行→拆出 ~994 行） | 与 membase 共享面最小；regbase 错误权重走 `ERROR_WEIGHTS` 模块级常量，原样不动 |
| **刀 2** | 契石门 mixin（~790 行） | `_expected_code_files` 及契约门 helpers 迁出（`integrate.py` 引用不变） |
| **刀 3** | 反馈渲染 mixin（~894 行） | 渲渲染依赖 `_render_smoke_facts_lines` 等纯渲染，不动 `_persist_sources` |
| **刀 4** | 部署 mixin（`_read_deploy_result` / `_persist_sources`，~59 行） | `_persist_sources` 两端都依赖，留 mixin 被 B/C/D 域引用 |
| **刀 5（收尾）** | prompt 组装 mixin（`_materialize_inputs` / `_programming_model_for` / `_build_codegen_prompt` / `_build_s2/s4/vf/s5_prompt` 视 regbase 归属决定） | 依赖前面 mixin 的渲染函数 |

> 注：刀序只反映**迁移顺序**，不改变最终归属。`_build_s2/s4/vf/s5_prompt` 与 regbase 强耦合，
> 实际归宿建议一并进 regbase mixin（刀 1 完成），`_build_codegen_prompt` 则是 membase + 反馈域
> 的组装体，留 prompt mixin（刀 5）。

---

## 五、风险与边界（诚实）

- **行为零改写**是理想目标；现实中唯一可能微变的是 `import` 表达式顶层（`from ... import` 移到
  目标模块），但它只影响模块加载期，不影响方法内调用。任何发现的方法体改动都必须是
  **逐字剪切**，不做解释性小修——不得顺手「改进」方法。
- **`test_codegen_regbase_phases.py:1881/1914`（patch `stages.codegen.Path`）**：`_regbase_skill_root`
  迁到 regbase mixin 后，patch 目标需同步改为新模块（`...codegen_stage_mixin.regbase.Path`）。这是
  测试唯一需要跟随搬迁的点，属预期内。
- **类级常量**：`_SMOKE_MARKER_RE` 等随所在 mixin 迁移；`_classify_smoke_phase` 别名随反馈 mixin 迁移。
- **`@register_stage`** 装饰点留在 `CodegenStage`（编排壳），不随 mixin 走。

---

## 六、验证标准

1. 每刀后 `pytest tests/ut/orchestration/test_codegen_regbase_phases.py tests/ut/orchestration/test_codegen*.py` 全绿；
2. 全量 UT（~4297）全绿；
3. 无测试因 patch 目标改变而失败（除预期 2 处 helper patch 更新）；
4. `CodegenStage` 公共 API（`integrate.py` / `registry.py` / 两个 dispatcher UT）行为不变；
5. 最后跑 1 个重型 smoke 批量（batch_self_evolve，用户确认后）。