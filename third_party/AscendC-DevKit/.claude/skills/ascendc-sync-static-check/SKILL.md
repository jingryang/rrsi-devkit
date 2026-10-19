---
name: ascendc-sync-static-check
description: |
  AscendC 核内同步问题的轻量快速静态筛查节点。通过代码扫描 + 模式匹配自动检查 7 类核内同步缺陷
  （EnQue/DeQue 配对、手动 SetFlag/WaitFlag、MTE2/MTE3 地址重叠、PipeBarrier、Mutex、Scalar 流水、TBuf 无同步），
  输出结构化问题清单 + 修复建议（JSON），供调用方（debugAgent）自行修改和验证。
  Use when: (1) 精度调试循环中 analyze_code 阶段需要快速筛查同步问题;
  (2) 任何 debugAgent 接收到代码+问题症状+失败用例后需要静态诊断同步层;
  (3) 用户说 "查同步", "sync check", "同步静态检查", "EnQue/DeQue 检查", "TBuf 同步".
  输入：代码路径 + 分析结果 + 失败用例 + (可选)诊断方案 scheme.
  输出：结构化 JSON 问题清单 + 修复建议，不修改代码、不执行测试.
  职责：只诊断，不修改，不验证（修改验证由调用方负责）.
  覆盖范围：仅核内同步；核间同步（SyncAll/IBSet/CrossCoreFlag）不覆盖.
  依赖：无（自包含，不委派其他 skill）.
---

# AscendC 核内同步静态检查节点

> **定位**：这是一个**独立、无状态、可插拔的诊断子节点**，不属于任何特定 debug agent 的状态机。
> 任何 debugAgent（precision-loop、手动调试、其他循环框架）都可以调用它。

## 核心价值

核内同步问题是 AscendC 算子精度 Bug 的**头号根因**（输出全0/随机错误/数据竞争），且：
- **可静态发现**：配对关系、eventID 来源、HardEvent 方向、PIPE_S 禁忌都能靠读代码发现
- **与数值诊断正交**：同步是"时序正确性"，数值精度是"计算正确性"，诊断思路完全不同
- **命中率高、成本低**：纯代码阅读 + 模式匹配，不需要跑测试

## 职责边界

| 维度 | sync_check 负责 | sync_check 不负责 |
|------|----------------|-----------------|
| 分析 | 静态代码扫描 + 模式匹配 | ❌ 执行测试、插桩、DumpTensor |
| 输出 | 问题清单 + 修复建议（JSON） | ❌ 实际修改代码 |
| 验证 | ❌ 不验证修复效果 | 修复验证由调用方负责 |
| 状态 | ❌ 无状态，不碰 checkpoint | 状态管理由外层 agent 负责 |
| 范围 | 仅核内同步 | ❌ 不覆盖核间同步 |

## 与其他 sync skill 的关系

> 本 skill **自包含**，不依赖/委派其他 skill。以下为定位区分，便于用户选择。

| Skill | 定位 | 适用场景 |
|-------|------|---------|
| **ascendc-sync-static-check**（本 skill） | **轻量快速筛查**，自动化，覆盖编程模型层（EnQue/DeQue/TBuf/Scalar/eventID资源），输出 JSON | 精度调试循环中的自动筛查 |
| ascendc-sync-incore-debug | **深度交互分析**，7步状态追踪表，聚焦手动 SetFlag/WaitFlag 密集代码，输出人类可读报告 | 复杂手动同步代码的深度诊断 |
| ascendc-sync-incore-tracker | **动态追踪**，注入软件状态追踪替代硬件同步 | 有可运行用例需运行时验证 |
| ascendc-sync | **同步机制指南**，场景选型 + 代码模式 + 陷阱 | 编码时选型参考 |

**本 skill 已借鉴 ascendc-sync-incore-debug 的核心知识**（SET+WAIT 屏障语义、HardEvent 方向判断法、状态流转、操作类型对照表等），写入自有 checklist 文件，不形成运行时依赖。

## 输入输出契约

### 输入

| 输入项 | 必填 | 说明 |
|--------|------|------|
| `operator_dir` | ✅ | 算子源码目录（绝对路径），至少包含 `op_kernel/*.cpp` 和 `op_kernel/*.h` |
| `analysis_result` | ✅ | 前序阶段的代码分析结论，至少包含：问题症状描述（如"输出全0"、"部分对部分错"）、怀疑的根因方向（如有） |
| `failed_cases` | ✅ | 失败的测试用例信息（shape/dtype/参数），帮助聚焦检查范围 |
| `scheme` | ❌ | 可选诊断方案/侧重点，不传则全量检查。取值见下方 |

`scheme` 取值：
- `"full"`（默认）：全量检查 7 类
- `"EnQue/DeQue only"`：只查 A 类
- `"TBuf focus"`：只查 H 类 + A 类
- `"Scalar focus"`：只查 G 类
- `"quick"`：只查 A 类 + D1（PIPE_S）

### 输出

结构化 JSON，schema 见 [references/sync-check-prompt.md](references/sync-check-prompt.md) §输出格式。

```json
{
  "check_summary": "发现 N 个同步问题，其中 M 个 critical",
  "findings": [
    {
      "id": "A1",
      "severity": "critical",
      "category": "EnQue/DeQue",
      "location": "op_kernel/xxx.h:120",
      "description": "DataCopy 后直接 Compute，缺少 EnQue/DeQue 同步",
      "evidence": "DataCopy(xLocal, xGm, size);  // 行120\nCast(...);              // 行121，无中间同步",
      "suggestion": "在 DataCopy 后添加 EnQue，Compute 前 DeQue；或临时用 PipeBarrier<PIPE_ALL> 验证（注意掩盖效应）",
      "confidence": "high"
    }
  ],
  "clean_areas": [
    "B类 SetFlag/WaitFlag：未使用手动同步，无风险"
  ]
}
```

## 检查类别总览

详细检查项见 [references/sync-static-checklist.md](references/sync-static-checklist.md)。

| 类别 | 优先级 | 覆盖 | 核心检查 |
|------|--------|------|---------|
| **A** | 致命 | EnQue/DeQue 配对 | DataCopy 后是否有同步、AllocTensor/FreeTensor 配对 |
| **B** | 致命/高危 | 手动 SetFlag/WaitFlag | 配对、eventID 来源、HardEvent 方向、**eventID 资源超限** |
| **C** | 高危 | MTE2/MTE3 地址重叠 | 多 DataCopy 目标重叠、原子操作 |
| **D** | 高危 | PipeBarrier | PIPE_S 禁忌、PIPE_ALL 滥用 |
| **E** | 高危 | Mutex | Lock/Unlock 配对、与 TQue 混用 |
| **G** | 致命 | Scalar 流水 | GetValue/SetValue 的跨流水同步 |
| **H** | 致命 | TBuf 无同步容器 | TBuf 搬入搬出缺手动 flag |
| **I** | 致命 | TBuf 跨流水搬运同步 | 搬入缺 MTE2_V、循环中计算后搬出缺 V_MTE2、尽量不用 TBuf 做 GM 搬运 |

## 集成模式

### 被精度调试循环调用

precision-loop 的 `analyze_code` 阶段内部可调用本节点：

```
analyze_code 子 agent 内部流程：
  1. 读 checkpoint 获取 root_cause / failure_type / 失败用例
  2. 组装输入，调用 sync-static-check
  3. 接收问题清单
  4. 将问题清单与自己的代码分析结合，产出最终 fix_plan
  5. 写入 checkpoint
```

这种模式**不改变** precision-loop 的状态机和 checkpoint 结构。

### 被任意 debugAgent 调用

```
任意 debugAgent:
  → 收集代码路径 + 问题症状 + 失败用例
  → 调用 sync-static-check
  → 接收问题清单 + 建议
  → 自行处理（修改、验证、或反馈给用户）
```

## References

- [sync-static-checklist.md](references/sync-static-checklist.md) — 7 类检查项完整版（含正确/错误代码模式 + 原理）
- [sync-symptoms.md](references/sync-symptoms.md) — 常见同步问题表现形式（独立可迭代）
- [sync-check-prompt.md](references/sync-check-prompt.md) — 子 agent prompt 模板
- [README.md](references/README.md) — 子 agent 调用指南
