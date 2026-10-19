# SIMT host Dynamic UB 引导 — 方案分析（L3）

> 调研/取舍记录。问题见 `01-problems.md`（P1/P2），改哪些文件见 `03-impl.md`。

## 选项与取舍

### 关键事实（调研冻结）
1. `SetLocalMemorySize` ≡ `SetDynUBufSize`：后者是当前接口，前者是头文件标注 deprecated 的纯 wrapper（`return SetDynUBufSize(...)`），二者运行时语义完全一致。
2. 主线仓 `ops-nn` arch35 SIMT tiling **92 处全部调用旧名** `SetLocalMemorySize`（同函数），且在 SIMT 模板才调、SIMD 不调——证明这是 SIMT host 的标准动作且被生产依赖；也说明"照抄主线仓"会把 deprecated 名带进生成代码。
3. API 语义：默认 0 = "算子不使用 Dynamic UB"。运行时 SIMT 共享内存窗口有兜底默认（SingleOperatorLaunch 默认 0→8KB，实测可放大），故小 footprint 算子漏配也能碰巧通过（gather 实例）。

### 决策 D1：生成代码写哪个接口名
- A：照主线仓写 `SetLocalMemorySize`（与 92 处同构，mainline 兼容）。
- B：写当前接口 `SetDynUBufSize`。
- **选 B**：语义完全一致、无行为差异；CANN 头文件已标 deprecated 并注明后续移除；生成代码无历史包袱（§1.4 不做向后兼容，写干净不留废弃包装）。教学时保留"主线仓源码片段是旧名、语义一致"的桥接说明，避免读真实算子时困惑。

### 决策 D2：是否先做真机端到端实证再落引导
- A：本地 cann_bench gather 拷贝上改 host 调用 + 放大 SIMT buffer，走 aclnn GE 多次 build/run 对拍（~30-45 分钟）。
- B：先不实证，直接补引导。
- **选 B（用户拍板 2026-09-02）**。理由：接口有效性证据已足够强——①官方 API 文档（SIMT 语义、默认 0）；②CANN 9.1 头文件（两接口同函数）；③主线仓 92 处生产用法（同一函数被全量 SIMT tiling 依赖）。实证留作后续可选项（D 兜底），本轮不阻断引导落地。与 §1.13/§1.11 同向：真跑产出是强证据，但此处权威源（API/头文件/主线仓）已构成确定性语义，非弱探测。

### 决策 D3：引导放哪里（范围）
- A：只改 simt skill 知识层（把旧名教学升级为新名 + 废弃桥接）。
- B：A + 在设计/编码链 SIMT 命中处补一条 host 配置引导（防"流程不经过 simt skill"的编码 agent 漏配）。
- C：B + general-design、Membase 链、kimi 逐条旧名教学全改。
- **选 B**：SIMT 宿主场景只在 A5 Regbase 链（tiling → regbase 编码），这两处是 SIMT 引导的权威注入点；general-design 是概设（不落 host impl API）、Membase 无 SIMT，均无必要承载 → 避免重复引导（§2.8 流程不内联重复数据）。kimi 是 391 条调研快照、含大量主线仓逐字源码片段——**只改"教学格"，不动 verbatim snippet**（保溯源），并在教学格加"旧名=同函数废弃名"桥接。

### 决策 D4：编码侧防护形态
- regbase 编码 B2（host tiling）自检加一行：结构信号判 SIMT（设计产物编程模型/计算单元标 SIMT，不认算子名，§1.12）→ 缺 `SetDynUBufSize` 即就地改。属既有自检表内一行、就地改不 halt（§2.9 本 agent 内自检闭环），不是新增控制模型的重 gate（§1.14 最小结构）。

### 排除项
- 不改 `ascendc-simt-operator-design-patterns/SKILL.md` 之外的流程再立词表（单一权威源 §1.9/§1.5）；不在多 skill 重复整段配方，只留 simt skill 一处配方 + 链上指针。

### 决策 D5（阶段 B，路径 1 工具缺口闭合）
- **选 C**：给 SingleOperatorLaunch 三个公开入口（`_KernelFunction.__call__` / `profile` / `SourceModule.__call__`）加可选 `simt_share_memory_size=None` kwarg，经共享 seam `_make_launch_args` 透传（默认 None/0 → RTS 8KB 兜底，**不改变既有默认行为**；负数抛 ValueError）。
- 对比 A（只改文档让用户低层手工构造 LaunchKernelArgs）：低层注入绕开工具诊断管线（OOB/printf/同步异常处理），isolated VF 测试体验与守护都差 → 不选。对比 B（把默认从 0 抬到更大）：会改变所有既有 SIMT 测试语义 → 不选。
- 验证策略：纯 seam UT + fake-device 转发 UT + 真机 smoke（复用 ub_probe_custom 64KB：默认 8KB 窗 vs 显式 65536 全 PASS），不依赖 heavy 链路。
