# in-place/out-of-place 交付契约 — 方案分析（L3）

> 层级：**L3 方案分析**。记录有哪些选项、选了哪个、为什么。调研中演进、拍板后冻结。
> 事实见 `01-problems.md`，实施配方见 `03-impl-mutation-mode.md`。
> **状态：已冻结（2026-07-24）**。

## 关键区分（方案成立的前提）

in-place/out-of-place 在两个层面都出现，必须拆开：

| 层面 | 含义 | 归属 |
|---|---|---|
| **算子语义写法特性** | 算子本质：输出是否与输入同张量（原地更新） | 算子规格维度，requirement 显式声明 |
| **交付契约** | 算子结果怎么交给调用方 | cann-bench 框架级统一约定（所有算子 out-of-place 返回，golden 全 clone+return） |

`advance_step_v2` = 语义 in-place + 交付 out-of-place 返回，两者不矛盾。plugin 的 clone+return 即把"语义 in-place"
包装成"交付 out-of-place 返回"的桥。

## 候选方案

| 候选 | 要点 | 取舍 |
|---|---|---|
| **A. codegen-only** | 只改 `ascendc-op-dev-coding` 补 Plugin 规则 + 自检项（plugin 签名 == schema） | **否决**：治标。违反 §2.9（构造性保证优先于检查门——这是 discover+regenerate 门）、§1.8（契约缺失是上游问题，末端补是兜底）。同类 in-place 算子仍复发 |
| **B. 上游显式化 + mutation_mode + 保留 access_mode** | requirement 加算子级 `mutation_mode`，per-tensor `access_mode` 也保留，两字段 | 中间方案。引入两套读写声明（mutation_mode + access_mode + design 的 `io` 文字），仍有矛盾源；access_mode 价值待质疑 |
| **C. 删 access_mode、留 mutation_mode** | requirement 删 per-tensor `access_mode`，新增算子级 `mutation_mode`；per-tensor 读写改由 inputs/outputs 同名关系承载 | **✅ 冻结选定** |
| **D. 纯 inputs/outputs 关系驱动** | 无 mutation_mode 无 access_mode，全靠同名关系 + codegen 通用规则推导 | **否决**：可诊断性差。"是否 in-place"完全隐式，无显式声明可做 §1.3 自洽校验；推导错只能等 eval 暴露（回到现状） |

## 选定方案 C 的四把尺子评估

**① 可维护** — 删冗余 access_mode；唯一事实源 = inputs/outputs 同名关系 + mutation_mode；
消除"`io` 文字 / access_mode / 同名关系"三套读写声明打架。✓

**② 可扩展** — 新算子声明 inputs/outputs（同名关系）+ mutation_mode，下游自动正确归位；
无需维护 access_mode 与同名关系的一致性。✓

**③ 可诊断** — mutation_mode 显式 + §1.3 自洽校验（`mutation_mode=in_place` ⇔ 存在同名 input-output 对）；
矛盾在 requirement 阶段机械捕获；access_mode 删了反而少一处矛盾源。✓

**④ 架构合理** — 算子级写法特性显式声明落在 requirement（需求理解职责）；
per-tensor 读写从 inputs/outputs 客观关系读；交付契约走 codegen 通用规则。各层职责清晰，不越层。✓

## 两个关键洞察（支撑 C 优于 B/D）

### 洞察 1 — access_mode 是 inputs/outputs 关系的冗余投影，可删

`access_mode` 三值是 inputs/outputs name 集合关系的**确定性投影**，无独立信息：

| access_mode | 等价的 inputs/outputs 关系 |
|---|---|
| `read_only` | 只在 inputs，不在 outputs |
| `write_only` | 只在 outputs，不在 inputs |
| `read_write` | 同名出现在 inputs 和 outputs |

任一张量的访问模式都能从 name 在哪个集合机械推出，无歧义、无反例。留 access_mode 是重复声明，
反而制造"两套读写声明可能矛盾"的风险。

### 洞察 2 — mutation_mode 必须显式（不能像 access_mode 那样靠推导）

`mutation_mode` 也能从"有无同名对"推导，为何不删？因为两者性质不同：

- **access_mode** 是 inputs/outputs 关系的**机械投影**（同名就是 read_write，是定义不是判断）→ 冗余，可删。
- **mutation_mode** 承载**交付契约语义**（plugin 要 clone+return），是高抽象层设计事实，
  且要作为 §1.3 校验的**声明端** —— 没有显式声明就没有可对照的事实，矛盾无信号（推导错只能等 eval 暴露）。

故是"删冗余的 access_mode、留显式的 mutation_mode"，不是两个都删、也不是都留。

## 冻结结论

- requirement：**删** per-tensor `access_mode`；顶层新增算子级 `mutation_mode: in_place | out_of_place`（必填）；
  per-tensor 读写由 inputs/outputs 同名关系承载（同名=read_write、仅input=read_only、仅output=write_only）；
  §1.3 校验 `mutation_mode` ⇔ 同名 input-output 对自洽。
- design：继承 `mutation_mode`；删 `io` 文字字段；per-tensor 读写从同名关系读。
- codegen：消费 `mutation_mode` + 框架级"统一 out-of-place 返回交付"规则 —— in-place 算子的同名状态张量 clone 后 return。
- 交付契约（统一 out-of-place 返回）作为 codegen 通用规则，不进 per-算子字段（cann-bench 对所有算子统一要求）。

具体改哪个 skill 哪一节、字段定义、校验写法、plugin 正确形态、验证方式 → `03-impl-mutation-mode.md`。

## 待确认项（不阻塞方案冻结，阻塞实施）

- `ascendc-op-req-analysis` skill 归属（mutation_mode 字段 + 删 access_mode 的主落点）：frontmatter 无 owner 标注，
  倾向用户侧但记忆未明确 —— 动手前必须确认，若归同事则 step-1 转 handoff。
- `ascendc-op-dev-coding-regbase`（A5）的 plugin 生成归同事 → step-4 必为 handoff。
