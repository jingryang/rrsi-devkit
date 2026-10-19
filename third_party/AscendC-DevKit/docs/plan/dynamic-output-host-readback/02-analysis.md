# 动态输出类算子（输出长度数据相关）— 源头知识 + 下游兜底方案分析（L3）

> 层级：**L3 / 方案分析**。记录有哪些选项、选了哪个、为什么；调研中演进、拍板后冻结。
> L1 事实见同目录 `01-problems.md`。本文回答一个问题：
> **「输出长度数据相关（变长输出）」这一类算子，怎么让设计多数情况直接选对、且 codegen/debug
> 在源头仍漏时有合法兜底？**

## 0. 决策总览

| # | 决策 | 状态 |
|---|------|------|
| D1 | 类边界用**结构特征**「输出长度数据相关（M 需 kernel 运行后得知）」切，不用 unique/NonZero 点名 | ✅ 拍板 |
| D2 | 同一份知识双消费点：design 源头告知（H01_select-sort.md）+ codegen/debug 兜底（维12 读回 API 确定写法 + 红线反馈修正） | ✅ 拍板（兜底落点见下「实施修正」：维12 单点，不另建 api-best-practices 卡） |
| D3 | 只改知识 + 一处红线反馈文案；**不加**产物 checkpoint/侦查预算/认知笔记等控模型 gate | ✅ 拍板（§1.14） |
| D4 | 红线门不新增"例外放行"——合法写法已存在且能过规则，缺的是触发时告知合法替代 | ✅ 拍板 |

---

## 1. 选项评估

### 选项 A：只加"红线例外/升级通道"（放行犯规写法）

- **被证伪**：成功版 unique 用 `aclrtMemcpy`，**没申请任何例外就通过了**。规则本身不拦
  正确路径——失败版死于"用了 `.to(kCPU)` + 反馈给死路"，不是规则拦了合法做法。
- 放行 `.to(kCPU)` 会让 moe_re_routing 类作弊（host 算值 copy 回）与 unique 类合法
  （读回 count 元数据）**不可分**——机械门退化为 LLM 自觉，正中维10③ 要堵的洞。
- **结论：不做**。例外通道是在给不存在的缺口打补丁，且破坏反作弊门。

### 选项 B：红线门识别「读回 count 元数据」语义，放行这一子类

- 优点：字面量层面保留门的确定性，仅对"读 8B count"精准豁免。
- 问题：`\d+ 字节标量回读`的识别要做 C++ 语义解析（区分读 count 槽 vs 读结果张量回 host
  算），框架 `_first_host_roundtrip` 是纯正则，为此引入代码分析是**复杂度大、易错**，且
  新算子换种写法（如读一个标量再据它算 shape）又漏——本质是给"按机制打补丁"。
- 违反 §1.12（结构信号派生）：判定会退化为"识别某种具体写法的特判表"。
- **结论：不做为门**；但"读回 count 定 size 是合法模式"这条**知识**（不是门的豁免）要进
  知识卡，让模型自觉走 `aclrtMemcpy` 而不是被拦后无路。

### 选项 C（拍板）：类知识双消费点 + 修正红线死路文案

把问题拆成两个正交修复：

**C1 源头（design）：补 `H01_select-sort.md` 变长输出机制的下游收尾**

`H01_select-sort.md:104/142/171` 现有变长输出行只到「workspace 暂存计数 + 前缀和算写出偏移
（ES3）」，**缺输出张量真实长度的最终确定**。补一段"变长输出闭环"：
- 机制 facet（喂 design）：变长输出 = 输出张量按上界分配 + kernel 末写 count 槽 +
  **host 回读 count → plugin `narrow` 收窄输出 shape**（InferShape 报上界，裁剪在 plugin）。
- 机制边界 facet（喂 design）：变长输出的真实长度只能由**单次 launch 的 kernel 运行后经
  host 回读**获得——host tiling 在 launch 前一次性静态计算、不消费上一次 launch 的设备运行期
  结果，故"先扫一遍定输出大小、再按该长度二次 launch"的两段式**没有标准通道**，是反模式
  （失败版 root cause）。正解 = 上界分配 + count 槽 + 单次 launch + host 回读裁剪。**单 kernel
  内的多趟/分桶迭代（LSD radix / presence bitmap 缩窗）不属两段 launch，不受此限**。

**C2 兜底（codegen/debug）：红线反馈对"动态输出"类给合法替代而非死路**

`codegen.py:669` 红线文案"把 host 算值逻辑迁回 kernel/tiling"对输出长度数据相关类是死路
（M 运行期才知、kernel/tiling 无 M 归宿）。改为：命中时若证据指向"读回标量元数据定输出
size"（如命中串出现在 narrow/切片输出 shape 前），反馈补充合法替代——"数据相关输出长度
需 host 定：用 `aclrtSynchronizeStream` + `aclrtMemcpy(D2H)` 读回 count 标量元数据，勿用
`.to(kCPU)`"。

判定依据（要不要加"若证据指向"这一条件判断）：
- **最小可接受**：反馈文案直接附加一句"若为数据相关输出长度收窄（读回 count 标量定 shape），
  合法写法是 `aclrtSynchronizeStream + aclrtMemcpy(D2H)`，勿用 `.to(kCPU)`；确为 host 算
  值再 copy 回才需迁回 kernel"。不加语义判断——文案给两类路径，让模型按实情选。
- 是否进一步做"命中行含 narrow/切片/8B 则优先推合法替代"的轻判据：待定，倾向先不加
  （避免 §1.12 特判化；先靠文案 + 知识卡，观察复现率再定）。

**C3（不做，已否）**：产物 checkpoint / 侦查预算 / 认知物化笔记等"强制模型收敛"机制
——见 `diagnose-model-convergence-gap/`，属模型能力问题，本次不控模型（§1.14）。

---

## 2. 为什么"同一份知识双消费点"是对的（对用户判断的确认与精化）

用户判断：把问题总结为一大类知识，**设计阶段告知**（源头）、**codegen/debug 阶段兜底**。

确认成立，且优于我此前把 M3/M4 拆成两项：
- 同一份知识 = 「输出长度数据相关 → 上界分配 + count 槽 + host 回读 + plugin narrow；
  禁两段式 launch；合法 API 是 `aclrtMemcpy` 非 `.to(kCPU)`」。knowledge 是"帮模型"不是
  "控模型"（§1.14 留帮删控），源头喂它让多数情况直接选对，下游兜底吸收"源头仍漏"的剩余。
- 实证：成功版设计给机制 → codegen 只选 API（`aclrtMemcpy`）→ 下游几乎零兜底；
  失败版设计不给 → codegen 临场发明 → 触红线 → 死路。**源头告知确能消掉多数失败**。

精化（诚实边界）：能被统一的是**注入模板 + 类边界**，不是把 adaptive 的 tiling-key 契约病
也塞进这张卡。那张卡是另一类知识（launch 层错误签名→分层首查），须独立成卡——但**注入模板
（机制 facet 喂 design + 合法路径 facet 喂 codegen/debug）两个类共用**。一张卡两种病会糊。
本次只落"动态输出"卡，adaptive 的 launch 契约卡单独讨论。

---

## 3. 类边界（§1.12 结构信号，非点名）

判定一个算子是否属本类（structure signal，进知识卡引导自检）：
- **输出某维长度由输入数据的运行期内容决定**（如去重后唯一数、非零元素数、cumsum 末值），
  而非输入 shape 可静态推导；
- 该长度在 InferShape 时不可知 → 输出张量只能按上界分配；
- 上界分配的输出须在返回前收窄到真实长度 → 真实长度只能由 kernel 运行后经回读获得。

属此类（举例供测试，不作分类锚点）：去重类（输出唯一集合）、非零/索引收集类、按数据裁剪类。
不属此类：TopK/ArgMax（定长输出 k 静态已知）、mask 填充类（输出定长）。

---

## 4. 消费点落地（改动最小化，符合 §1.5 / §2.7）

| 消费点 | 载体 | 改动 |
|--------|------|------|
| design 源头 | `.claude/skills/ascendc-op-general-design/references/patterns/atomic/H01_select-sort.md` | 变长输出小节补"host 回读 + plugin narrow"机制 + 机制边界（两段式 prescan→relaunch 无标准通道、是反模式；单 kernel 内多趟/分桶迭代不受限） |
| codegen 兜底 | `.claude/skills/ascendc-op-dev-coding/SKILL.md`【维12】动态长度输出定型 | **补读回 API 的确定写法**（合法 `aclrtSynchronizeStream`+`aclrtMemcpy(D2H)` 标量回读 vs 禁用 `.to(kCPU)` 整张搬回 + 区别判据）——不另建 api-best-practices 卡（见下「实施修正」） |
| 红线反馈 | `src/ascendc_devkit/orchestration/stages/codegen.py` `_plugin_host_offload_error` | 文案分两类：①真 host 算值→迁回 kernel；②数据相关输出长度→`aclrtMemcpy(D2H)` 读 count，勿用 `.to(kCPU)` |
| design 路由 | `ascendc-op-design-template-division` / general-design 命中 H01 时自动获得 | 无新增机制，靠 H01 既有加载路径 |

> **实施修正（2026-09-08，相对本表既有措辞）**：C2 原计划「新增 api-best-practices 卡」在实施时发现**不必要**——codegen skill `ascendc-op-dev-coding/SKILL.md` 既有【维12】动态长度输出定型（0f2ff389 引入）已覆盖"回路 + 偏移对齐 + 空输出信号"全部**机制**，是 plugin 契约的唯一产权方；其**真缺口**仅是「读回 API 怎么写」这一层（失败版死于用 `.to(kCPU)` 触红线，而非不知道要读回）。按 §1.15/§2.5（散点不重复、唯一通路）把 API 确定写法补进既有【维12】，不另建重复卡——机制归维12、API 写法归维12 同段，一处讲全，避免"同一事实散在两 skill"漂移。

改动均为"知识/文案"，不加 gate、不加产物契约、不加状态机——符合 §1.14（不加控模型结构）
与 §2.1/§2.5（skill 即插即用、无新旧并存）。

---

## 5. 验证（§3 TDD——知识改动以可复现对照为验证）

1. **知识卡实测正确性**（§2.12/用户要求"写 api-best-practices 必须实测"）：用成功版 unique
   `aclrtMemcpy` 写法作为该卡的**真值锚**——卡里的每个 API 调用片段必须与已上板跑通
   （20260827-95e52f 出分）的代码一致，不做未验证的推广断言。
2. **复验判据（可证伪）**：重跑失败版 unique 任务（同 golden/设计/测试）到 codegen：
   - 若设计阶段因 H01 补全而不再导向两段式死路、codegen 走 `aclrtMemcpy` 合规过红线
     → 源头修复生效；
   - 若设计仍漏（新 agent 未必读 H01 该段）但红线反馈给合法替代后 codegen 能自行纠正
     → 兜底生效；
   - 两者都不生效 → 回查是否仍是模型无收敛能力（与 diagnose-model-convergence-gap 同源）。
3. 红线反馈文案改动以 UT 守护：现有 `test_codegen_host_offload.py` 断言文案/路由，补动态输出
   子例（命中 narrow 收窄场景给出合法替代而非死路）。

## 5.1 实施记录（2026-09-08，落地后固化）

| 项 | 载体 | 落地内容 |
|----|------|---------|
| C1 机制补充 | `H01_select-sort.md:104` | 变长输出小节补「变长输出闭环」机制 facet（上界分配 + count 槽 + host 回读 + plugin narrow；InferShape 报上界、裁剪在 plugin）+ 机制边界 facet（host tiling 静态计算 → 两段式 prescan→relaunch 无标准通道、是反模式；单 kernel 内多趟/分桶迭代不受限） |
| C2 API 写法 | `ascendc-op-dev-coding/SKILL.md`【维12】 | 补「读回 API 确定写法」：合法 `aclrtSynchronizeStream`+`aclrtMemcpy(D2H)`（8B 标量，附成功版真值锚片段）/ 禁用 `.to(kCPU)` / 区别判据（固定小字节元数据 vs 数据本体） |
| C2 红线反馈 | `codegen.py _plugin_host_offload_error` | 文案分两类处置：①真 host 算值 → 迁回 kernel；②数据相关输出长度收窄 → `aclrtMemcpy(D2H)` 读 count、勿用 `.to(kCPU)`（不再是单路径死路） |
| 调和 | `ascendc-op-dev-coding/SKILL.md`【维10】 | 补「变长输出判界」：narrow 到 kernel 写回的真实长度 = 接口适配（合法）；plugin 自行决定/重算长度 = 越界。消掉维10②「slice 决策」措辞与维12 必需窄化的张力 |

UT：`test_codegen_host_offload.py` 新增动态输出子例（断言红线文案含合法替代 aclrtMemcpy(D2H)/勿用 .to(kCPU)，非死路）——7 passed。
知识/文案类改动（H01 / 维10 / 维12）无独立 UT，以本表 + §5 复验判据（第 2 条，可证伪）为验证。

## 6. 不做清单（防范围蔓延）

- 不加"例外放行"门（选项 A 否）。
- 不加语义级 C++ 解析识别读 count（选项 B 否）。
- 不加产物 checkpoint/侦查预算/认知笔记等控模型 gate（与诊断收敛问题分离）。
- 不处理 adaptive 的 launch 层 tiling-key 契约病（另一类知识，单独讨论）。
