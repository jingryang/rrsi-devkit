# 跨步列块 online-softmax（统计 pass + 输出 pass，mRun/sRun 常驻）

## 适用判据

softmax(dim=1) 融合（+exp/scale 等后置逐元素）且**内层连续尾轴 R=prod(shape[2:])>1、
规约轴 N 跨步**的跨步列块分支（route `rDim>1`，rank∈[3,8]，A5 Regbase）。此时行是
"一列 R 长向量"沿 N 方向逐行扫描，需要 **online 单遍统计**（每 N-tile 只需两趟，不做 N 行全
驻留的两遍行归约）。与 `experience-softmax-normalize.md`（R 整驻留、逐行 ReduceMax/ReduceSum
两遍）的差别在于：向量轴是**列块 rSize**、统计沿 N 行进、mRun/sRun 是**跨 N-tile 常驻累加器**。

## VF 分解（statistics pass + output pass 两族 VF）

工作单元 (b, colBlock)：slab = nTileElem 行 × rSize 列；mRun/sRun/mTmp 三个 fp32 行向量 =
`colTileElem` 宽（对齐到 `rowBytes=AlignUp(colTileElem×4,32)`）。

| VF | 操作 | 依赖 | 中间量 |
|----|------|------|--------|
| VF_0 统计（scan1） | 逐行 `rowMax` → `mTmp`；`mNew=max(mRun,mTmp)`；`rescale=exp(mRun−mNew)`；`sRun×=rescale`；`mRun=mNew` | 需 mRun/sRun 跨块常驻 | mNew/rescale 寄存器内、mRun/sRun UB 行向量 |
| VF_1 统计（scan2） | 逐行 `e=exp(row−mRun)`（**寄存器内不回写**）；`sRun+=e` | VF_0 后 | e 寄存器、sRun UB |
| VF_2 输出 | 逐行 `y=exp(e/sRun)`→Cast 原生 dtype→原位写回 slab 行 | VF_0/VF_1 后（跨引擎同步一次） | 全寄存器；行回写 |

- **行内中间量（exp 值、行 max、rescale）一律寄存器驻留，不回写 UB**（A5 Regbase：VF 行内中间量
  寄存器不占 UB；这是 `(2·nTileElem+3)×rowBytes` 预算可行的前提——只有 slab 双 ping-pong +
  mRun/sRun/mTmp 占 UB）。
- **rescale 的 -inf 语义**：首 N-tile mRun=−inf → `exp(−inf−mNew)=0`，天然跳过（不分支）。
  累加器 pad 通道安全值：mRun pad=−inf、sRun pad=0，随 DataCopyPad 安全值一起保证不污染。
- **nTileCount==1（N≤3966，7/7 已验 case）**：统计 pass 未回写 slab，输出 pass 直接复用驻留
  原始 x，无 GM 重读；`nTileCount>1` 才需输出 pass 前 CopyIn 重读该 tile。
- **dtype**：slab 原生 dtype 直入（fp16/bf16/fp32），统计链在 fp32（Cast 到 fp32 仅每行首列块
  或经 UNPACK），输出再 Cast 回原生。fp32-worst 规划使 colTileElem/nTileElem 与 dtype 无关。

## 寄存器预算（≤32 RegTensor / 8 MaskReg，峰值时）

- VF_0/VF_1：~4~6 data RegTensor（slab 行、mRun/mTmp、e、rescale）+ 1~2 MaskReg。
- VF_2：~8 data（mRun/sRun、row、rowF32、e、y、yNat）+ mask，峰值仍 ≤32/8。
- 行循环用 `POST_MODE_UPDATE` 自动递增地址，行索引外提。

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| rescale 路径首块错误 / NaN | mRun=−inf 初值 + `exp(−inf−(−inf))` 未护 | 首块走 `mRun=−inf → rescale=0` 语义（乘法天然跳过），禁 `mRun−mNew` 出现 −inf−(−inf) |
| 累加器被尾块污染 | DataCopyPad pad 通道进 mRun/sRun | pad 通道写安全值（mRun=−inf / sRun=0） |
| 输出 pass 读到被改的 x | nTileCount>1 时误复用统计后的 slab | 分块时输出 pass 前 CopyIn 重读该 tile；nTileCount==1 复用才安全 |
| half/bf16 首跑 OOB | DX=half 走 UNPACK+Cast 两指令越界 | 先 fp32 验证通过再泛化（同 elementwise/reduce 通用经验） |

## 关键参数（跨段一致，勿重推）

colTileElem/nTileElem/cap/均衡与 UB 预算 `(2·nTileElem+3)×rowBytes ≤ UB` 的**封闭公式 + 已验
真值表**见 `ascendc-op-design-shared/references/online-softmax-strided-columnblock.md`（split 段
锁定，vf/buffer-kernel 直接消费，不重推）。

## 横切标签

`multi-dtype`、`mask-tail`、`reduce`（online）、`stateful-accumulator`（mRun/sRun 跨 tile 常驻）、
`unaligned-2d`（跨步 strided DataCopyPad）。

## 实证来源

- `softmax_exp` T2 模板（task_0003，统计/输出两 pass VF 分解 + 7 case 位级/nTileCount=1 验证）
