# 内存层次详解

## 存储层次结构

```
┌─────────────────────────────────┐
│          GM (Global Memory)      │  容量：GB 级，所有核共享
│          DDR / HBM               │  访问：通过 MTE2/MTE3 DMA 搬运
├─────────────────────────────────┤
│          L2 Cache                │  容量：MB 级，片上缓存
│          (硬件管理)               │  访问：对软件透明
├─────────────────────────────────┤
│          L1 Buffer               │  容量：KB~MB 级
│          (软件管理)               │  访问：MTE1 搬运
├─────────────────────────────────┤
│     L0A / L0B / L0C Buffer       │  容量：KB 级，Cube 专用
│     (Cube 计算专用)               │  访问：Cube 指令直接使用
├─────────────────────────────────┤
│       UB (Unified Buffer)        │  容量：KB 级，每核独占
│       (Vector 计算工作区)         │  访问：Vector 指令直接使用
└─────────────────────────────────┘
```

## 各层级特点

### GM (Global Memory)

- **容量**: GB 级别，存储所有输入输出 Tensor
- **带宽**: 相对较低（具体值因芯片而异）
- **特点**: 所有 AI Core 共享，通过 DMA 引擎访问
- **编程接口**: `GlobalTensor`, `DataCopy`

### UB (Unified Buffer)

- **容量**: KB 级别（如 256KB），每个 AI Core 独占
- **带宽**: 极高，Vector 计算单元可直接读写
- **特点**: 是 Vector 计算的工作区，容量宝贵
- **编程接口**: `LocalTensor`, `TQue`, `TBuf`
- **关键约束**: 起始地址必须 32B 对齐

## 数据流动模式

### 典型 element-wise 算子的数据流

```
GM ──MTE2──→ UB(VECIN) ──Vector计算──→ UB(VECOUT) ──MTE3──→ GM
                  ↑                          │
                  └── TBuf(VECCALC) 临时空间 ──┘
```

### UB 空间分配

```
UB 总空间
├── VECIN  Queue: 输入数据缓冲（bufferNum 份）
├── VECOUT Queue: 输出数据缓冲（bufferNum 份）
├── VECCALC TBuf: 计算临时空间
└── 预留空间 (UB_RESERVE): 系统保留，不可使用
```

## 带宽层级（定性）

| 数据路径 | 带宽级别 | 延迟级别 |
|---------|---------|---------|
| GM → UB (MTE2) | 中 | 高 |
| UB → GM (MTE3) | 中 | 高 |
| UB 内部访问 (Vector) | 极高 | 极低 |
| L1 → UB (MTE1) | 高 | 中 |

> **注意**: 具体带宽数值因芯片型号而异，请参考 `chips/` 目录下的芯片规格文件。
