# 注册名派生源修正 — 源头规则 + 机械校验实施（L4）

> 层级：**L4 / 实施方案**。记录改哪个文件、什么顺序、怎么验证。
> 前置：`01-problems.md`（L1 根因 + 归属修正）、`02-analysis.md`（L3 方案 D0-D3）。
> 实现「注册名从落盘目录名（golden snake）派生 Pascal，不从 proto 抄」+ 生成期机械校验。

## 0. 改动总览

| 项 | 文件 | 改动 |
|---|---|---|
| 源头·规则 | `.claude/skills/ascendc-op-dev-coding/SKILL.md` | 注册名派生指令：从 `state.op_name` snake_to_pascal，禁抄 proto operator.name |
| 源头·规则 | `ascendc-op-design-shared/references/OpDef渲染规格映射.md` | class 名派生 + example 去 Pascal 误导 |
| 源头·规则 | `ascendc-op-req-analysis` schema/references | op_name 语义：以 golden 入口为准 |
| 机械校验 | `src/ascendc_devkit/orchestration/stages/codegen.py` | 出口校验注册名反推 == 落盘名 |
| 判定函数 | 单点函数 `runtime_camelsnake` | 复刻 runtime 反推（§1.15） |

## 1. 判定函数（机械校验核心）

新增 `runtime_camelsnake(reg_name: str) -> str`（复刻 CANN runtime 对注册名的 camel→snake 反推，
从日志/实测推导）：

```python
import re
def runtime_camelsnake(name: str) -> str:
    s = re.sub(r'([a-zA-Z])([0-9])', r'\1_\2', name)   # 字母+数字边界: er3D→er_3D
    s = re.sub(r'([0-9])([A-Z])', r'\1_\2', s)          # 数字+大写: 3D→3_D
    s = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', s)        # 大写+小写
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s).lower()
```

验证（L3 §1）：`runtime_camelsnake(snake_to_pascal(落盘名)) == 落盘名` 对含 `_3d`/`_2d`/无数字段成立。
判定 = `runtime_camelsnake(注册名) == 落盘目录末段`。

## 2. 机械校验（codegen 出口，compile 前）

**位置**：`codegen.py` 产物收尾、`Deployer().compile` 前（既有契约校验同层，~3120-3160）。

**动作**：
```python
# 注册名派生源校验：注册名 runtime 反推须命中落盘目录名（config 文件名基底）
from <shared> import runtime_camelsnake, snake_to_pascal
_op_reg = 提取注册名(产物)   # def.cpp OP_ADD 或 op_api ADD_TO_LAUNCHER_LIST_AICORE
_disk   = state.op_name 或 rel_op_dir 末段    # 落盘目录名 = golden snake
if _op_reg and _disk and runtime_camelsnake(_op_reg) != _disk:
    # 注册名抄了 proto/别处 → 拦，指引从 op_name 派生
    return state.with_updates(last_error=ErrorFeedback(
        stage_name="codegen", error_type="reg_name_mismatch",
        message=(f"注册名 {_op_reg!r} runtime 反推 {runtime_camelsnake(_op_reg)!r} "
                 f"≠ 落盘目录名 {_disk!r}（派生 config 文件名）。注册名须从 op_name "
                 f"({_disk}) 经 snake_to_pascal 派生（得 {snake_to_pascal(_disk)!r}），"
                 f"勿直接抄 proto 的 operator.name。"), ...))
```

拦截失败走 codegen 定向 retry（与既有 retry 路由一致）。

## 3. 源头规则（skill / 渲染规格 / req schema）

### 3.1 `ascendc-op-dev-coding/SKILL.md` 注册名派生指令

在 OpDef / L2 API（`ADD_TO_LAUNCHER_LIST_AICORE`）/ plugin `m.def` 的注册名处，统一补一条：

> **注册名（`OP_ADD`/class/`ADD_TO_LAUNCHER_LIST_AICORE` 首参/`m.def` op）的 Pascal 一律从
> `op_name`（snake，落盘目录名，golden 权威）经 `snake_to_pascal` 派生**（每 `_` 段 capitalize 后拼接）。
> **禁止直接抄 proto/requirement 的 `operator.name`**——proto 的 Pascal 可能与 golden snake 的
> Pascal 不一致（数字段 `3d`/`2d` 的大小写），抄它会让 runtime 按注册名反推找不到以落盘目录名
> 命名的 config → 361001。以 `op_name`/落盘目录名为准，proto 名仅作参考。

### 3.2 `OpDef渲染规格映射.md:184`

- `class 名 = op_name（首字母大写保 PascalCase）` 补注：op_name 权威源 = `state.op_name`（golden snake 落盘目录名），
  派生用 `snake_to_pascal`（逐 `_` 段 capitalize），**非** proto 的 Pascal 直抄。
- schema example `"op_name": "Add"`（Pascal）与 golden snake 冲突 → 注"op_name 以 golden 入口函数名为准（snake），
  示例为示意非 Pascal 化依据"。

### 3.3 req-analysis

op_spec 的 op_name 语义（`op_spec_schema.md:74` + schema example）补：以 golden 入口函数名为准（snake）。

## 4. 实施顺序

1. 判定函数 `runtime_camelsnake` + UT（独立可测）。
2. 机械校验（codegen 出口）+ UT。
3. skill / 渲染规格 / req schema 文本规则（无 UT，随 codegen 自检生效）。

## 5. 验证

- **UT 派生**：`runtime_camelsnake(snake_to_pascal(name)) == name` 对 `adaptive_avg_pool_3d`/`add`/`conv_2d`/多下划线。
- **UT 校验**：注册名 `AdaptiveAvgPool3D`（抄 proto）→ 拦；`AdaptiveAvgPool3d`（派生）→ 放行。
- **复验**：adaptive task 上 coder 按派生规则写注册名 → smoke 过、361001 消失。
- **回归**：add/sqrt（注册名本就从落盘派生）不受影响；req/design 无 op_name 相关回归。

## 6. 不做清单

- 不改 runtime / CANN 工具链。
- 不改上游 task 命名 / golden / proto。
- 不做 deploy 后补发副本为主方案（仅覆盖历史产物，见 L3 §4）。
- 不加产物 checkpoint/回炉等控模型 gate。

## 7. 实施记录（2026-09-08，落地后固化）

### 7.1 实际落点（相对 §0-4 既定方案的增量事实）

- **单点判定函数**：新建 `src/ascendc_devkit/domain/op_name.py`（§1.15 单点）——`snake_to_pascal`
  （正向派生）、`runtime_camelsnake`（激进反推）/`runtime_snake_lenient`（宽松反推，两族与
  runtime 实测依序一致）、`runtime_config_candidates`、`registration_matches_disk`。
  `CannbenchScorer.snake_to_pascal` 改为**委托**本模块（原 eval 侧实现在 §2.5 删除，两处不再漂移）。
- **判定从「相等」细化为「成员包含」**：`registration_matches_disk(reg, disk)` 用
  `disk ∈ {runtime 候选集}`，精确复刻 runtime 对数字段注册名的**两族候选**（如
  `AdaptiveAvgPool3d` → 激进 `adaptive_avg_pool_3d` + 宽松 `adaptive_avg_pool3d`）。
  用相等会把边界形态恰好不同的合法注册名误拦（如落盘 `adaptive_avg_pool3d` + 注册 `Pool3d`，
  激进反推 `pool_3d` ≠ `pool3d`，但 runtime 宽松候选命中）。成员包含避免了该误拦，且
  proto 大写 D 抄写在含数字段边界的落盘名上仍精确拦下。
- **机械校验扫描范围**：`_registrations_from_artifacts` 只扫 **AICore 注册宏**——`op_host/*_def.cpp`
  的 `OP_ADD` 首参 + `op_api/*.cpp` 的 `ADD_TO_LAUNCHER_LIST_AICORE` 首参。`op_plugin` 的
  `m.def` snake **不参与**比对（它驱动 eval 符号、可合法加 `npu_` 前缀，与 config 查找无直接因果）。
- **校验位置**：codegen `_transition_membase` 内、`profile_kind == "torch_op"` 分支**之外**
  （全 scaffolding kind——config 反推错位是 driver/runtime 层，与 plugin 协议无关）、
  `missing_sections`/compile 之前。命中 → `_plugin_schema_retry`（与契约门同预算/逃生，
  reason=reg_name_mismatch → `_collect_schema_feedback` kind='reg_name' 专属反馈段 →
  `_render_build_feedback_section` 渲染给下轮 coder）。
- **落盘名真源**：优先 **`op_dir` 目录名**（编译器 config 文件名派生源 `op_file = op_dir + '.json'`
  的机制真源）——带前缀 profile（如 omni-ops `ai_infra_`）目录名 = 前缀 + 短名 ≠ strip 后的
  `state.op_name`，比对必须用目录名（用短名会误拦从目录名正确派生的注册名，review 发现后修正）；
  无 op_dir（profile-less 单元态）回退 `state.op_name`（无前缀仓二者一致）；皆空则跳过不误伤。

### 7.2 验证（UT 全绿）

- `tests/ut/domain/test_op_name.py`（21 例）：round-trip 派生必命中 / proto 大写 D 必拦 /
  无边界落盘名宽松候选命中不误拦。
- `tests/ut/orchestration/test_codegen_reg_name.py`（9 例）：def.cpp `OP_ADD` + op_api
  `ADD_TO_LAUNCHER_LIST_AICORE` 的拦/放行、无 op_name 跳过、m.def 不参与、transition 全路径
  定向 retry（feedback kind='reg_name'）。
- 回归：全 `tests/ut/orchestration/` + `tests/ut/domain/`（2341 例）绿；`test_cannbench_scorer.py`
  snake UT 绿（委托不破坏原 API）。
