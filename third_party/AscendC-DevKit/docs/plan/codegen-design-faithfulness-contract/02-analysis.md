# L3 方案分析 — codegen 结构忠实契约（三腿）

> 对应 L1 P1-P4。调研演进稿；本文为冻结版。

## 否决项（先立红线）

1. **硬禁 SetValue/GetValue**（机制禁令）：三重否决——①误伤合法点（数据依赖散射、
   tail 非对齐、TilingData 元数据、动态输出，设计本身需要标量点）；②机制特征封不死
   （`*(__gm__ T*)&x[i]`/宏包装同成本换名，§1.10 机制代理必被穿透）；③封死出口不给
   正路 → 竞态难题仍在，模型烧穿预算 halt，连诊断素材都没有。
2. **限制 for/while 数量**：循环是设计的骨架（`loop_framework` 本身就是
   for-core{for-tile{CopyIn…}}），病在循环体标量化不在循环数；循环数与性能无因果，
   纯机制特征代理（§1.10）。只会逼出手工展开/monolith。
3. **C++ 深度语义解析**（防指针标量解引用等变体）：脆弱、维护贵、超出「最小结构」
   （§1.14）。契约以声明优先，presence 检查只做簿记一致性，不做语义判定。

## 选定方案：三条腿

### 腿 1：设计标量点契约（声明式 + 证据式偏离，框架消费）

- **设计侧**（帮模型，知识前置）：`tiling_strategy.json` 增机器可读字段
  `scalar_access_points[]`（name / location-semantic / reason），声明义务落
  buffer-kernel 设计步（标量点在 buffer/kernel 设计时确定）、integrate 汇总；
  schema 加载期校验（§1.3）。
- **coder 侧**（AR-1 收口，不新增规则）：`scalar_access_points[].reference` 从
  自由文本收紧为**可校验引用**——必须命中设计声明的 name；无声明可引时该条转为
  `deviation_evidence` 结构（failure_signature / repro_or_log /
  why_no_vector_equivalent），并计入 design deviation。既有「DataCopy 等价物 → 理由
  不成立」条款不变。
- **框架侧**（消费点，§2.9 两正当性都满足）：codegen transition 在既有 manifest 机械
  校验 → 定向 retry 的同一通路（§1.15 单点）增一条校验：
  - 逐点：`reference ∈ 设计声明名` ∪ `带 deviation_evidence`，否则违约；
  - 簿记覆盖：op_kernel 源码 presence 检查（`SetValue(`/`GetValue(` 出现而清单空 →
    「有标量访问未声明」违约）；
  - 违约 → 定向 retry 反馈（逐条指名：向量化 / 补引用 / 补证据），不 halt。
- 正当性：跨产物一致性（设计↔代码↔日志，单一 producer 看不全，§2.9 ①）+ 可解决
  反馈渠道（定向 retry 即消费通道，§2.9 ②）。非 discover+regenerate。

### 腿 2：kernel 阶段错误的交棒证据（不吸收，带证据走）

- coder skill 自检节增交棒格式：会话内遇 kernel 阶段错误，**处置 = 结构化记录后交棒**
  （错误签名 / 复现 case 或日志 / 已排除方向），落 decision_log 交棒字段，随 D4 给
  precision——diagnose 带证据接手而非冷启动；
- 同步类错误（MTE/vector 交错、数据陈旧、非对齐形态）的交棒记录注明疑似类别并指向
  `ascendc-sync` 选型表——**指针非枚举**（§2.12：不列举错误类型，只给查证路标）。

### 腿 3：归属边界镜像进 coder skill（会话内不再吸收 kernel 阶段错误）

- coder skill 构建自检节增业务语义声明（§1.10）：**会话内自检范围 = 编译错误 +
  host 阶段错误（tiling/launch/注册——CPU 侧可推理验证，生产者自闭环 §2.9）；
  kernel 阶段错误（vector core 异常、运行期数据错、同步竞态形态）不在会话内吸收**——
  按原样交棒，框架 smoke 门会分类（`_classify_smoke_phase`：kernel → D4 precision），
  kernel 阶段 smoke 红是**合法交接**而非 coder 的失败；
- 判据与框架分类器同款结构信号（kernel 执行证据），不引入第二套词表；
- agent manifest（ascendc-coder.md）同步。

## 四把尺子

- 可维护：三腿各自单点（schema 一处、skill 收口既有 AR-1、校验并入既有通路）；
- 可扩展：新算子的标量点自动归位（设计声明驱动），kernel 错误自动流向 precision；
- 可诊断：违约逐条反馈、交棒证据落盘、边界判定与框架同判据；
- 架构合理：框架消费框架可判的（结构包含），语义判断留模型（deviation 论证）。

## 帮/控判据（§1.14）

三腿都不是「为抓模型错搭的规则」：腿 1 的设计标量图是**前置知识**（本次 coder 若被
明确告知「散射已声明、其余必须向量」，搜索空间骤减）；腿 2/3 是**卸压**（把设备调试
从 coder 职责域移走，交还给全副武装的 diagnose）。判据是结构不变式（声明集合包含
关系 + 结构信号边界），与「golden 一致即对」同构，非错误类型枚举。

## 范围边界（诚实声明）

- **并行度塌缩**（如强制单核）无机械可判的结构信号 → 腿 1 不覆盖；靠腿 2/3 的
  deviation 声明纪律（单核收敛须带证据）+ step-92 性能反压长线兜。
- **指针标量解引用**等变体绕过 presence 检查 → 接受；契约以声明优先，presence 只做
  簿记。
- 已知代价：少量「显然易修」的 kernel 小错也会流向 precision（多一次交接）——边界
  清晰优先，precision 本就拥有 kernel 正确性（run_tests 全量守护）。

## 冻结（2026-08-26）

三腿按上述落地；否决项不再议。实施顺序与验证见 L4。

## 修订（2026-08-26，用户追问「声明产出的正确性」压力测试后）

对冻结版三腿逐一反问「是否根因修复」，三项修正：

### 腿 1 反问：声明的产出能保证正确吗？——原方案有窟窿，补「声明锚」

- **承认缺口**：冻结版只设计了执法端（契约校验），未设计声明的**产出锚**——无锚的
  声明是又一张「模型填的表」（§1.14 自警），设计侧过度声明（declare-broad）会让
  reference 变成洗白通道，契约空转。
- **补全：声明 = 既有 R6 举证制分析的机器可读尾部，不是新表**。buffer-kernel R6 已
  要求对 gather/scatter/reduce 类路径「先假设向量化可用 → 列循环不变量 → 逐条『提取』
  或『经查证排除』，禁止以 idx 运行期为由直接判无」——`scalar_access_points[]` 每条
  必须挂该排除论证（对齐 tiling_results 既有 `verifiable_claims` 形态：derivation +
  verification），加载期校验；precision-perf 性能分析交叉印证（标量路径=性能风险项）。
- **可证伪性**：声明是「无向量化等价物」的否定性断言，双向可证伪——①知识库 API 等
  价物清单（AR-1 coder 侧已枚举：DataCopyPad/Gather/Scatter/Sort/CompareSwap，同一
  清单锚设计侧，§1.5 知识在资源）；②coder 若把声明点向量化成功 → 证明声明错 → 记
  设计侧改进信号（记录不设门）。
- 事实备注：本事故设计侧**本就过关**（只声明两点、主体向量式，R6 通过），失败纯在
  coder 扩张——产出锚是防未来设计侧洗白，非修本次。

### 腿 2 反问：交棒证据真解决问题吗？——诚实降级

- **承认冗余**：D4 通路本就携带 crash dump / 失败 case（crash sentinel）；diagnose 侧
  rules 路由已把同步类关键词指向 ascendc-sync（触发词表现成）。新造 `handoff_evidence`
  schema 是为省 diagnose 几轮重查加结构——按 §1.14 判据**删除**。
- 保留最小内核：coder 交棒前把已观察到的 kernel 错误现象记入 decision_log **既有字段
  `known_issues`**（schema 已存在，零新结构）。

### 腿 3 反问：skill 文本约束得住模型吗？——必要非充分，补两件

- **承认**：指令级软约束单独不成立——本次事故模型正是在「磨绿 smoke」压力下走偏；
  若 skill 完成判据仍暗示「smoke 绿才算完」，边界声明会被压力吃掉。
- **补全 a（完成判据形态）**：腿 3 必须写成**合格完成路径**而非禁令——「编译过 +
  host 阶段自检过 + kernel 阶段错误已记录（known_issues）交棒 = 合格完成」。给模型
  合法退出路径，而非只剥夺工具。
- **补全 b（强制力来自互补，非单腿）**：腿 3 降低吸收动机；模型仍吸收（标量化换绿
  smoke）时腿 1 契约兜住（无证据标量 → 定向 retry）；`_classify_smoke_phase` 门对到达
  的一切正确路由。失效链：腿 3 失效→腿 1 兜；腿 1 证据伪造→deviation 引用存在性
  校验（repro_or_log 须指向真实存在的产物路径——簿记非语义）+ 后续性能信号；两腿
  全过而性能仍差→step-92 选项①（性能反压）产权。

### 残余诚实声明（更新）

三腿全落地后，「向量化但 tiling 很差」的慢代码仍只能靠 eval 暴露——三腿**抬地板**
（消灭标量洗白与静默偏离），**不封顶**（性能质量）。根因拼图 = 三腿（结构忠实）+
step-92①（性能反压），缺一仍留洞。
