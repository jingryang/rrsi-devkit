# 平台差异化参考（A3 vs A5）

> 本文件汇总 AscendC 算子设计涉及的主要平台差异。各 skill 在涉及平台差异化推导时引用本文，无需在 SKILL.md 中重复描述。
>
> **硬件数值唯一来源（P24）**：精确硬件数值以 `hw_params.json`（来自 ascend-hardware chip spec）
> 为唯一来源；下表的数值仅为约数/定性对比，**对质或落盘时一律以 `hw_params.json` 为准**，
> 不要把本表数值当作 ground truth（曾因多源副本漂移出现 192/240/248/256KB 四值并存）。

## 核心参数对比

| 参数 | A3 (Ascend910B) | A5 (Ascend950) |
|------|----------------|----------------|
| **UB 大小** | ~192 KB | ~248 KB |
| **AICore 数量** | 固定（如 24/40） | 随 Tier 变化（8~36），需动态适配 |
| **架构模型** | Membase（中间结果占 UB） | Regbase（中间结果驻留寄存器，不占 UB） |
| **常驻数据** | 全量占用 UB | `__ubuf__` 地址 + 寄存器传递，不强制使用 TBuf |
| **同步模型** | SetFlag / WaitFlag | Mutex + LocalMemBar |
| **寄存器约束** | N/A | 32 RegTensor / 8 MaskReg |
| **Vector 函数** | 直接流水线 | `__simd_vf__`（连续逐元素）或 `__simt_vf__`（不规则分支），通过 VF_CALL 调用 |
| **Cast 时机** | CopyIn 后立即升精度，CopyOut 前降精度 | 可在 VF 函数内部完成，时机更灵活 |
| **L0A 分形** | ZZ | NZ |

## 对设计的影响

### Tiling 设计
| 维度 | A3 影响 | A5 影响 |
|------|---------|---------|
| D 维度全量处理上限 | 受 ~192KB UB 限制，D 较小可全量 | 受 ~248KB UB 限制，D 更大也可全量 |
| 核间切分 | 固定核数 | 需动态核数适配，blockIdx 公式需支持 Tier 变化 |
| 常驻数据 UB 占用 | 全量计算 | 中间结果不占 UB，实际占用更小 |
| Buffer 分配 | TQue/TBuf | VF 函数使用 `__ubuf__` 地址而非 LocalTensor |

### Kernel 设计
| 维度 | A3 | A5 |
|------|----|----|
| Compute 函数结构 | Init/CopyIn/Compute/CopyOut | 需进一步拆分为 VF_CALL 子函数 |
| 同步 | SetFlag/WaitFlag 流水线 | Mutex+LocalMemBar，流水线深度和重叠策略不同 |

### 精度设计
| 维度 | A3 | A5 |
|------|----|----|
| Subnormal | 硬件直接处理 | 软仿可能需要额外关注 |

> **使用方式**：在 SKILL.md 的步骤描述中，如需区分平台则引用："详见 `ascendc-op-design-shared/references/platform_diff.md`"。
