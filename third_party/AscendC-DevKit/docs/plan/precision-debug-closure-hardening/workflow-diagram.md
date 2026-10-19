# precision_debug 闭环工作流 — 所有路由 & 情况

## 顶层：7 阶段主流程

```mermaid
flowchart TD
    START([precision_debug 入口]) --> RT["❶ run_tests<br/>全量回归"]
    
    RT -->|"all_pass"| PASS(["✅ passed<br/>出 group"])
    RT -->|"rounds > 30"| EXH(["⛔ exhausted<br/>出 group"])
    RT -->|"首轮失败 + scope_checked=false"| SG["❷ scope_guard<br/>入口守卫"]
    RT -->|"has_failures<br/>scope_checked=true"| DG["❸ diagnose<br/>静态分析 + 建池"]
    RT -->|"agent_aborted<br/>(瞬态中断)"| RT
    RT -->|"abort_exhausted<br/>(连续 ≥3 次中断)"| EXH

    SG -->|"verdict=pass"| DG
    SG -->|"verdict=upstream"| UPS(["🛑 upstream<br/>出 group：上游问题"])
    SG -->|"agent_aborted"| SG
    SG -->|"abort_exhausted"| EXH

    DG -->|"done<br/>candidate_pool 已建立"| FIX["❹ fix<br/>候选池验证 + 应用"]
    DG -->|"agent_aborted"| DG
    DG -->|"abort_exhausted"| EXH

    FIX -->|"resolved / skip_done"| RT
    FIX -->|"applied_partial<br/>runtime 洋葱剥离"| DR["❺ diagnose_refine<br/>单条因果链评估"]
    FIX -->|"need_printf<br/>pool_exhausted+precision"| PL["❻ printf_location<br/>数值二分定位"]
    FIX -->|"need_comment_bisect<br/>pool_exhausted+runtime"| CB["❼ comment_bisect<br/>注释二分定位"]
    FIX -->|"partial_output<br/>per-output 部分改善"| RT
    FIX -->|"retry / regression / skip_more"| FIX
    FIX -->|"agent_aborted"| FIX
    FIX -->|"abort_exhausted"| EXH

    DR -->|"done<br/>因果链成立"| FIX
    DR -->|"fallback<br/>因果链不成立"| DG
    DR -->|"refine_cycles ≥ 3"| EXH
    DR -->|"agent_aborted"| DR
    DR -->|"abort_exhausted"| EXH

    PL -->|"located<br/>二分定位到行"| FIX
    PL -->|"continue<br/>继续二分"| PL
    PL -->|"printf_more<br/>cc 耗尽+更多 case"| FIX
    PL -->|"printf_done<br/>cc 耗尽+最后 case"| RT
    PL -->|"deploy_broken<br/>deploy 连续失败≥3"| EXH
    PL -->|"exhausted"| EXH
    PL -->|"agent_aborted"| PL
    PL -->|"abort_exhausted"| EXH

    CB -->|"located<br/>二分定位到行"| FIX
    CB -->|"continue<br/>继续二分"| CB
    CB -->|"case_more<br/>cc 耗尽+更多 case"| FIX
    CB -->|"case_done<br/>cc 耗尽+最后 case"| RT
    CB -->|"deploy_broken"| EXH
    CB -->|"exhausted"| EXH
    CB -->|"agent_aborted"| CB
    CB -->|"abort_exhausted"| EXH

    style PASS fill:#2d6,vue
    style EXH fill:#a60
    style UPS fill:#a60
    style RT fill:#36c,color:#fff
    style FIX fill:#c36,color:#000
    style SG fill:#369,color:#fff
    style DG fill:#369,color:#fff
    style DR fill:#369,color:#fff
    style PL fill:#369,color:#fff
    style CB fill:#369,color:#fff
```

---

## Fix 阶段路由（12 条，按优先级）

```mermaid
flowchart TD
    FIX_in([fix.transition 入口]) --> A0{"agent 产出了输出？"}
    A0 -->|否<br/>consecutive_aborts+1| A1{"consecutive_aborts ≥ 3？"}
    A1 -->|是| EXH(["abort_exhausted→⛔ escalate"])
    A1 -->|否| RT_self(["agent_aborted→🔄 re-spawn fix"])
    
    A0 -->|是| P2{"corrective_cycles ≥ 8？"}
    P2 -->|是 + more_cases| SK1(["skip_more→⏭ 下一 case"])
    P2 -->|是 + last case| SK2(["skip_done→🔄 run_tests"])

    P2 -->|否| P3{"applied_partial？<br/>runtime洋葱剥离"}
    P3 -->|是| DR(["→❺ diagnose_refine"])
    
    P3 -->|否| P4{"regression？<br/>fix引入硬件trap"}
    P4 -->|是| FIX_self(["→🔄 fix<br/>取修正candidate"])

    P4 -->|否| P5{"partial_output？<br/>per-output部分改善"}
    P5 -->|是| RT_partial(["→🔄 run_tests<br/>commit保留<br/>感知进展"])

    P5 -->|否| P6{"already_resolved？<br/>case已由之前commit修复"}
    P6 -->|是| RT_res(["→🔄 run_tests<br/>全量回归确认"])

    P6 -->|否| P7{"case_skipped？<br/>attempt耗尽/cc跳case"}
    P7 -->|是 + mores| SK3(["skip_more→⏭下一case"])
    P7 -->|是 + last| SK4(["skip_done→🔄run_tests"])

    P7 -->|否| P8{"pool_exhausted？<br/>无pending candidate"}
    P8 -->|是+compilation| SK5(["skip→⏭下一case<br/>compilation不可二分"])
    P8 -->|是+runtime| CB(["need_comment_bisect→❼注释二分"])
    P8 -->|是+precision| PL(["need_printf→❻printf二分"])

    P8 -->|否| P9{"还有pending hit？"}
    P9 -->|是| FIX_next(["retry→🔄 fix<br/>取下一个plan"])
    P9 -->|否| EXH2(["exhausted→⛔ escalate"])

    style FIX_in fill:#c36,color:#000
    style EXH fill:#a60
    style EXH2 fill:#a60
    style DR fill:#69c,color:#000
    style PL fill:#69c,color:#000
    style CB fill:#69c,color:#000
    style RT_partial fill:#2a6,color:#fff
    style RT_res fill:#2a6,color:#fff
    style FIX_self fill:#c63,color:#fff
    style FIX_next fill:#c63,color:#fff
```

---

## Per-Output 下沉路径（新增 detail）

```mermaid
flowchart LR
    subgraph before["修复前：双重缺陷互相掩盖（死循环）"]
        B1["FP-001 修 AG-1(TQue)"] --> B2["output[1] diff 1296→13 ✓<br/>output[0] 仍崩(AG-3 UB) ✗"]
        B2 --> B3["case 整体 fail"]
        B3 --> B4["❌ REFUTED + GIT ROLLBACK"]
        B4 --> B5["AG-1 有效修复被丢弃"]
        B5 --> B6["diagnose 重新分析"]
        B6 --> B7["又提 AG-1 变体"]
        B7 -.-> B1
    end

    subgraph after["修复后：per-output 下沉（累积收敛）"]
        A1["FP-001 修 AG-1"] --> A2["output[1] improved ✓<br/>output[0] 仍崩 ✗"]
        A2 --> A3["✅ partial_output<br/>→ commit 保留<br/>→ run_tests 回归"]
        A3 --> A4["diagnose<br/>看到 output[1] improved<br/>生成 AG-3 fix_plan"]
        A4 --> A5["FP-002 修 AG-3"]
        A5 --> A6["两个 output 都 pass"]
        A6 --> A7["✅ resolved<br/>→ case 推进"]
    end

    style B4 fill:#a30,color:#fff
    style B5 fill:#a30,color:#fff
    style A3 fill:#2a6,color:#fff
    style A7 fill:#2a6,color:#fff
```

---

## Agent Abort 退火（A0）

```mermaid
flowchart LR
    N0["0 次连续中断"] -->|"中断"| N1["1 次<br/>agent_aborted→re-spawn"]
    N1 -->|"中断"| N2["2 次<br/>agent_aborted→re-spawn"]
    N2 -->|"中断"| N3["3 次<br/>abort_exhausted→escalate ⛔"]
    N1 -->|"正常产出"| N0
    N2 -->|"正常产出"| N0
    N3 -->|"正常产出"| N0

    style N3 fill:#a30,color:#fff
    style N0 fill:#2a6,color:#fff
```

---

## case 队列推进

```mermaid
flowchart TD
    Q["failed_case_queue<br/>[case0 precision, case1 runtime, ...]"]
    Q --> WF["worker 取 current_case_index"]

    WF -->|"fix→resolved→RT回归→all_pass"| NX["current_case_index +1<br/>或 run_tests 全量通过时<br/>跳过已 resolved 的"]
    
    WF -->|"attempt ≥ max_attempts"| SK["_advance_current_case<br/>→ skip → current_case_index++"]
    
    WF -->|"cc ≥ 8"| APF["_advance_past_failure_type<br/>→ 跳过同 ftype case<br/>→ cc 重置为 0"]
    
    WF -->|"partial_output"| KEEP["commit 保留<br/>但 case 不推进<br/>继续同一 case"]
    
    NX -->|"index < len(queue)"| WF
    NX -->|"index ≥ len(queue)"| DONE(["最后一轮 run_tests<br/>exhausted / all_pass"])
    
    style KEEP fill:#2a6,color:#fff
```

---

## 三层收敛安全网

| 层级 | 计数器 | 触发线 | 动作 | 恢复 |
|------|--------|--------|------|------|
| 1️⃣ 语义收敛 | `rounds`（run_tests +1） | > 30 | exhausted → 出 group | - |
| 2️⃣ 小循环熔断 | `corrective_cycles`（fix/printf/bisect +1） | ≥ 8 | case_skipped → 推进 / run_tests | run_tests 归零 |
| 3️⃣ 中断退火 | `consecutive_aborts`（agent 无输出 +1） | ≥ 3 | abort_exhausted → 出 group | 正常产出归零 |
| 🆘 事后兜底 | graph_executor stagnation | 同一 pair 2 次 | halt | - |
| 🆘 最后保险 | CompositeGroup max_corrective | 200 | halt | - |
