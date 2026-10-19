# L3 方案分析：st-design 特殊取值域覆盖 + 泛化去重 + 覆盖报告诚实化

> 对应 L1：`01-problems.md`（P1/P2/P3；P4 相邻未处理）。
> 拍板后冻结；决策与权衡只在本层。

## 0. 范围与边界

- **落点**：`.claude/skills/ascendc-st-design/scripts/`（skill 自闭环，§2.1）。
  L1 P1/P2/P3 的根因均在 skill 脚本，不在 DevKit 框架层；不在本 stage 打补丁（§2.9）。
- **不动的既有取舍**：`grid` 含 inf/nan 属 out-of-domain（需求/golden 已判定，§1.13 golden 为权威）
  ——本工作只修复「x 声明要覆盖的特殊值却没生成」，不把 grid 的 out-of-domain 决策翻掉。
- **不动的设计选择**：L1 的「两两组合只在离散因子间做、排除 `.value_range`」保持不变
  （它是性能取舍，非本缺陷根因；改它属另一产权线）。
- **P4（空 tensor 列名失配）**：本工作不处理，L1 已留证据；它属「派生脚本 schema 迁移」，另立。

## 1. P1（特殊取值域漏生成）方案

### 方案 A：补全 value_range 覆盖到「声明域」（**选用**）

- 在 `generate_all_cases` 收尾加 `complete_value_range_coverage`：对每个
  `{param}.value_range_{dtype}`，若某声明 range 在「同 dtype 的已生成用例」中缺席，
  克隆一条同 dtype 用例并覆盖其 `value_range` 补回。
- **构造性保证**：只要某 dtype 有基用例，该 dtype 的**全部**声明 range 必出现。
- 正确性依据：value_range 对张量是**叶子因子**（无下游依赖它；张量 `.value` 不存在），
  覆盖它不破坏其它约束；克隆保持 dtype 不变，故 dtype 链约束仍成立。

### 方案 B：接线已存在的 `expand_value_range_for_dtype`（扩展全部 range 组合）

- 事实：脚本内已有 `expand_value_range_for_dtype(combinations, random_select=False)`，**当前是死代码**（未被调用），
  设计意图是扩展出所有 range 组合。
- 否决理由：anchor 组合 24 × x范围(~27) × grid范围(~11) ≈ 7000+，`--max-cases 2000` 会**截断**；
  截断取的是前若干组合，哪几个 dtype 先出现取决于 anchor 笛卡尔序 → **覆盖无保证**（可能全被 fp16 占满，
  fp32 特殊值全丢）。需再叠一层「保覆盖的采样」，复杂度更高。

### 方案 C：多次重采样直到各声明值出现

- 否决：非确定性（随机不保证终止/覆盖），且与 `--seed` 可复现诉求冲突；不解决根因。

### 四把尺子（A）

- **可维护**：value_range 是叶子、覆盖是加性步骤，不牵动约束求解不变式。
- **可扩展**：新 dtype / 新 value_range 自动归位（按声明域驱动，无需逐点补）。
- **可诊断**：配合 P3 后，若仍漏生成会显式报 <100%，不再静默。
- **架构合理**：落在「因子取值生成」职责内（生成阶段保证覆盖），不越到用例选择层。

## 2. P1（假性重复凑数）方案

- `generate_all_cases` **删除** `while len < max_cases: 重复拼接` 循环；`max_cases` 退化为**上界**
  （不足即不足，不再制造重复）。
- 理由：重复行不增加任何覆盖，只会放大下游选择/执行开销，并让「2000 条」成为假象（可诊断性差）。

## 3. P2（L1 泛化用例重复）方案

### 方案 A：补齐改为「未选中且内容不重复」的候选（**选用**）

- `pad_cases` 改为：候选 = 未被选中的行，按内容键去重后补齐；`seed` 控制 shuffle 可复现；
  候选耗尽即停止（允许少于 `--target-count`，L1 规范为 ≤N）。
- **构造性保证**：产出中不存在内容重复行；池中不同内容的条数即 L1 上限。
- 报告同步：`generate_L1_report` 的 `padded_case_count` 用**实际**补齐数（`final_count - selected`），不再假设
  「一定补到 target」。

### 否决项

- 保持重复补齐：违反 L1 语义（无新覆盖）且是本次用户显式指出的问题。
- 把 `.value_range` 加进 L1 两两组合以「自然扩充」：改变既有性能取舍、组合空间放大，属另一产权线；
  本次只保证「补齐不重复」。特殊值覆盖由 L0（门槛）负责（P1 修复后具备）。
- 跨 L0/L1 去重：合并产物中 L1 会是 L0 内容的超集（同池），存在轻度重复；但这是「同一池被两级各选一次」的
  既有结构，不在本问题范围，留观（不新增机制，§1.14）。

## 4. P3（覆盖报告自证 100%）方案

### 方案 A：目标域 = 声明值 ∪ 实际值，且只保留已物化因子列（**选用**）

- `extract_all_factor_values` 改为：先由 `04_测试因子.yaml` 构造**声明域**（`.shape` 过滤、
  `value_range_{dtype}` 归一为 `{param}.value_range`），再与实际 df 取值取并集。
- 两条必要约束（否则制造假缺口）：
  1. **只保留在 df 中实际物化的列**——否则未参与用例的属性 `.exist`（如 `interpolation_mode.exist`）
     会进目标且永远覆盖不到。
  2. **声明值需归一化到 df 读回表示**——`list` → `str(list)`（CSV 落盘/读回即该字符串形式）；
     `bool`/`int`/`str` 原样（pandas 读回类型与声明一致）。
- 正确性：修复 P1 后「声明域 ⊆ 实际域」，报告仍 100%；若将来再漏生成，则显式 <100% 暴露缺口。

### 方案 B：保持自证，仅另加声明缺口诊断字段

- 考虑过（改动更小、不影响其它算子选择行为），但目标域仍自证 → 主报告继续误导；
  且需额外把 factors 透传进报告生成，管线改动并不小。否决。

## 5. 与 golden/需求权威的关系（§1.13）

- 本次不新增任何「以工程猜测覆盖 golden」的分支：补全的 range 全部来自
  `04_测试因子.yaml`（value_range 声明本身由需求/golden 决定）。
- `grid` 的 out-of-domain（inf/nan 不合法）保持设计阶段既定决策，本层不翻。

## 6. 验证策略

- **UT（确定性，§3.8）**：`tests/ut/skills/test_st_design_scripts.py` 12 例，分别守护
  complete_value_range_coverage / pad_cases 去重 / extract_all_factor_values 声明域 / generate_all_cases 不凑数。
- **真实管线回放**：用该 run 的 `design/03,04,05,06` 重跑
  `generate_factor_values.py` → `generate_test_cases.py (L0/L1)` → `merge_test_cases.py`，
  断言：声明 range 全出现、L0 含 inf/nan、L1 内容无重复、报告 100% 且分母含声明值、下游 `parse_testcase_csv` 可解析。

## 7. P5（结构过集中）方案

### 方案 A：结构键去重 + 不同结构基用例轮转（**选用**）

- 新增 `_structure_key(case)`：用例中**排除全部 `*.value_range`** 后的因子取值元组
  （形状/dtype/维度/属性/存在性）。对每个 (param, dtype) 收集「不同结构模板」的基用例，
  补缺失 range 时按序**轮转**选基（取代恒取 `same_dtype[0]`）。
- **构造性**：range 全声明覆盖保证不变（仍逐 range 补，只是选基不同）；排除所有
  value_range 使「结构相同 ⇔ 形状/属性一致」——轮转即把 range 分摊到不同形状，下游
  L0 自然获得形状/属性多样性。
- **可扩展**：结构键按「是否 `.value_range` 结尾」机械判定，不认具体因子名（§1.12）；新算子自动归位。
- 否决：
  - 只按形状去重（写死 `.shape`）：漏掉属性/维度差异，且耦合因子名。
  - 在 L0 选择层事后去重/打散：属下游兜底，病灶（同构基）仍在生成层（§2.9 就地修）。
  - 不补多余 range（改由 L0 直接生成）：推翻 P1 的构造性覆盖保证，回到「随机能否覆盖」。

## 8. P5 四把尺子

- **可维护**：只改克隆基的选取，覆盖保证（不变式）与约束无关性均不动。
- **可扩展**：结构键机械判定、轮转对任意因子集成立。
- **可诊断**：L0 用例的结构分布可直接观测（unique struct ↑、max repeat ↓）。
- **架构合理**：落在「因子取值生成」职责内（生成阶段保证覆盖质量），不越到用例选择层。

