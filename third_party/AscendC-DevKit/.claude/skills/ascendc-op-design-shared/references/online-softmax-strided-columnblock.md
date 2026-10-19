# online-softmax（dim=1 融合 exp）跨步列块模板 tiling 参数公式（A5 Regbase）

> **定位**：SoftmaxFamily 融合算子（softmax(dim=1) + 后置逐元素如 exp / 非尾轴归一化族）中
> "规约轴跨步、内层连续尾轴 > 1"（跨步列块，路由条件 `rDim>1`，rank∈[3,8]）分支的**已验证
> 参数公式**。产权层为详设（split → vf-design → buffer-kernel）。
>
> **来源与已验证范围**：本公式在 softmax_exp（T2 模板）推导中收敛，并对照 7 个真实 case
> 脚本复算一致（case 表见 §4）。**同族算子（softmax+exp/×scale/×bias、
> 非尾轴 norm）在 A5、同样 route 下可直接套用**，只需替换"规约方向是否恒 N + 后置逐元素"；
> 若融合链加入跨行归约，公式作废，按各自概设重建。使用前先核对 `general_design.json` 的
> 轴优先级与本页一致（D0=B 优先 + Dtail 列块补足、规约轴恒不跨核）。

## 1. 统一视图与工作单元

```
x (ND, 连续) → [B, N, R]：B=x.shape[0]（外层独立轴）、N=x.shape[1]（规约轴，softmax dim）、
                     R=prod(x.shape[2:]) > 1（内层连续尾轴）
工作单元 = (b, colBlock)：b∈[0,B)，colIdx∈[0,colTileCount)
          覆盖 x[b, 0..N, colIdx*colTileElem .. +rSize] 的跨步 slab
核间指派：w = b*colTileCount + colIdx（B 优先线性序）；for(w=blockIdx; w<W; w+=blockDim) 轮转
blockDim = min(运行时核数 GetCoreNumAiv(), W)     # 运行时核数，非 hw_params 字面值
```

## 2. 封闭公式（host 推导，全部字段入 TilingData，kernel 零除法）

常量（A5 / hw_params.json 唯一来源）：`UB=253952`（另有保留 8KB 见注）、`ALIGN=32`、
`fp32 line=8 元素`、`DMA 块粒度保护下限=32 元素`（=128B fp32 行宽 = 4×32B line）。

| 参数 | 公式 | 说明 |
|---|---|---|
| `rowBytes` | `AlignUp(colTileElem×4, 32)` | **fp32-worst 规划**（三 dtype 同值），使 tiling 与 dtype 无关 |
| UB 预算约束 | `(2×nTileElem + 3) × rowBytes ≤ UB` | 2=双 slab（buffer_num=2），3=mRun/sRun/mTmp 三个 fp32 行向量；行内 VF 中间量寄存器驻留不占 UB（A5） |
| **P1** N 整轴驻留 | `nTileElem = nDim`（若 `nDim ≤ 3966`） | 3966=单列 1-line 行宽下可驻留 N 上限 `floor((floor(UB/32)−3)/2)`；`rT_budget = 8×floor(UB/(32×(2·nDim+3)))` |
| **P2** N-split 兜底 | `colTileElem=min(rDim,32)`；`nTileElem=floor((floor(UB/rowBytes)−3)/2)`；`nTileCount=ceil(nDim/nTileElem)` | 仅 `nDim>3966` 触发（在线多块 rescale + 输出 pass 重读） |
| **P3** 并行度 cap | `coreTarget = 14×运行时核数`；若 `bDim≥coreTarget` 不 cap；否则 `cap = max(floor8(rDim/ceil(coreTarget/bDim)), 32)` | floor8=取 8 的倍数；cap 保证核占用 + 均衡（见 §3） |
| **P4** 合成 | `colTileElem = min(rDim, rT_budget, cap)`；`rDim<8 → colTileElem=rDim` | |
| **P5** 计数 | `colTileCount=ceil(rDim/colTileElem)`、`rLastTileElem = rDim mod colTileElem（0→colTileElem）`、`nTileCount=ceil(nDim/nTileElem)`、`nLastTileElem` 同理、`W = bDim×colTileCount` | |

循环结构（kernel，边界全读字段，唯一除法=每单元 1 次 `w→(b,colIdx)` 索引分解，摊销于
nDim×rSize 元素）：
```
对每个工作单元：mRun[0..rSize)=−inf; sRun=0（pad 通道同置安全值）
  统计 pass（N 在线）：slab=strided CopyIn(blockCount=nSize, blockLen=rSize, 行间隔=R 元素)
    → 行扫描 max→mTmp；mNew=max(mRun,mTmp)；mRun=exp(mRun−mNew)；sRun×=mRun；mRun=mNew
    → 逐行 e=exp(slab行−mRun)（寄存器内，不回写）；sRun+=e
  输出 pass：逐行 y=exp(e/sRun)，原位写回 slab → strided CopyOut
（nTileCount==1 时输出 pass 复用驻留 slab，无 GM 重读）
```

## 3. 并行度 cap 的量化依据（R3 达标）

- **核占用**：预算内最大化列块可能使列块数过少。例 `[3,7,13,4001]fp32` 无 cap 仅 42 工作单元
  =66% 核占用（逼近 R3 50% 下限）；cap 后 930 单元 → 64/64 核占用。
- **负载均衡**：轮转下每核 Q 或 Q−1 单元，尾列块在最少载核砸出 −1 空洞，最坏均衡界 `(Q−2)/Q`；
  `Q=14 → 85.7% ≥ 85%`。**实测 7 case 均衡（每核元素量 min/max）0.89~0.99**。
- cap 方向为增单元（并行安全），不违反概设"预算内最大化"意图——概设未覆盖核填充场景属遗漏，
  按此执行并标注。

## 4. 已验证真值表（softmax_exp T2，脚本复算一致）

| case | nTileElem | colTileElem | colTileCount | rLast | W | blockDim | UB bytes | balance |
|---|---|---|---|---|---|---|---|---|
| [363,367,373] bf16 | 367 | 80 | 5 | 53 | 1815 | 64 | 235840 | 0.951 |
| [3,7,13,4001] fp32 | 7 | 168 | 310 | 101 | 930 | 64 | 11424 | 0.907 |
| [11,13,17,67,67] fp32 | 13 | 928 | 83 | 337 | 913 | 64 | 107648 | 0.891 |
| [3,7,11,13,1009] fp16 | 7 | 480 | 301 | 281 | 903 | 64 | 32640 | 0.906 |
| [2,511,2049] fp32 | 511 | 32 | 65 | 1 | 130 | 64 | 131200 | 0.985 |
| [4,255,2049] bf16 | 255 | 32 | 65 | 1 | 260 | 64 | 65664 | 0.992 |
| [2,3,17,1024,101] fp32 | 3 | 3912 | 449 | 505 | 898 | 64 | 140832 | 0.991 |

（域外 totality 验证：[2,1000003,2] → nTileElem=3966/nTileCount=253/colTileElem=2/UB=253920≤253952。
所有 case `nTileCount=1`（N≤511 ≤ 3966 上限）。blockLen_bytes = colTileElem×4 非对齐用 DataCopyPad
吸收；UB 大 slack case 由 fp32-worst 规划 / 小块本质造成，属正常。）

## 5. 使用纪律

- **先查本表再推**：softmax 族 T2 路由命中时，把本页 §2 公式 + §4 表直接作为
  `verifiable_claims`（numeric_derivation, derived, source_pointer 指向本文件 + 该算子的
  general_design/template_division）的推导依据，**禁止从零重新枚举推导**（本表已覆盖同族
  case 的预算/均衡收敛值，重推是重复劳动且易返工）。
- 数字矛盾时先核对"是否 8 倍数/是否 cap 绑定/是否 DMA 下限 32 绑定"三态，再谈改公式。
- 行距一致性 / DataCopyPad pad 语义见 `datacopy-stride-consistency.md`。
