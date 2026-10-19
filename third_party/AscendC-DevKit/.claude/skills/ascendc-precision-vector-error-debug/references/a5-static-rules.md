# A5 VECTOR_ERROR 静态规则索引

仅在 `scan_a5_vector_risks.py` 生成候选后，按 `candidate_ranking` 的 Top-K
子类型读取对应小节。本文用于解释候选和设计验证实验，不把静态命中当成已确认根因。

所有 MicroAPI 的签名、对齐、dtype、分发模式和资源限制，都必须按目标 SoC
及当前 CANN 的 910D 文档复核；本文和扫描器不替代权威 API 文档。

## `gm_ub_transport`

- `A5-MTE-001`：DataCopy/DataCopyPad 搬运点。核对 GM/UB 方向、地址来源、
  长度和 stride 的单位、尾块范围以及目标 buffer 容量。
- TQue 只表明数据通路经过队列；结合 `queue_lifecycle` 一并检查，不能裸删
  DataCopy 或单独删除队列生命周期操作。

## `ub_reg_load_store`

- `A5-LS-001`：LoadAlign/StoreAlign/LoadUnAlign/StoreUnAlign 访问点。核对
  地址来源、元素数、LoadDist/StoreDist 和 PostUpdate 语义。
- `A5-LS-002`：VF 内看到 LoadUnAlign、未看到 LoadUnAlignPre。
- `A5-LS-003`：VF 内看到 StoreUnAlign、未看到 StoreUnAlignPost。
- `A5-LS-004`：StoreAlign 参数中未识别出 mask。需先确认实际命中的
  overload；MaskReg 自身搬出等 overload 不能按 RegTensor Store 规则误判。

## `mask_tail`

- `A5-MASK-001`：UpdateMask 会修改传入 scalar。核对 scalar 是否在正确的
  row/tile/repeat 层重置，以及模板 dtype 对应的 VL。
- `A5-MASK-002`：Store mask 的 dtype、有效 lane 数和目标元素类型必须一致。
- 对齐 shape 正常而尾块 shape 失败时，提高本类候选优先级；静态 token 只能
  给出候选，不能证明尾块计算有错。

## `address_generation`

- `A5-ADDR-001`：CreateAddrReg 的 index/stride 宽度、元素单位和乘加范围。
- `A5-ADDR-002`：Load/Store/DataCopy 参数中的显式地址算术。结合 tiling
  实际值检查 byte/element 单位和最后一次访问范围。

## `layout_cast_dist`

- `A5-LAYOUT-001`：Cast 可能改变寄存器分量布局，尤其是位宽变化方向。
- `A5-LAYOUT-002/003`：同一 VF 中的 Cast 与 LoadDist/StoreDist 必须作为
  一个布局契约检查。具体 dist 枚举和 dtype 支持只能从当前 910D 文档确认。
- 静态扫描不推断模板类型宽度，因此这些命中保持 `candidate`。

## `vf_call_abi`

- `A5-VF-001`：VF 应是 inline void；参数只使用受支持的 UB pointer/POD
  形式，不传 reference、array 或 struct。
- `A5-VF-002`：LocalTensor 不能作为 VF 实参直接传递，应核对
  `GetPhyAddr` 和 `__ubuf__` 指针转换。
- `A5-VF-003`：TQue、Alloc/EnQue/DeQue/Free、DataCopy 等高层搬运/队列
  操作不应进入 SIMD/SIMT VF。
- `A5-VF-004`：核对 VF_CALL/asc_vf_call 与 SIMD/SIMT callee 域一致。

## `incore_sync`

- `A5-SYNC-001`：同一 UB 地址出现 Store→Load 且源码中无 LocalMemBar。
  编译器可能自动插同步，因此只作为候选；结合指令 trace 确认。
- `A5-SYNC-002`：已有 LocalMemBar 时核对 src/dst pipeline 是否与实际
  RAW/WAR/WAW 依赖一致，不能因为“有 barrier”就判定正确。

## `queue_lifecycle`

- `A5-QUEUE-001`：TQue buffer 数和生产消费链候选。
- `A5-QUEUE-002/003`：同一 receiver 在当前源文件中缺少
  Alloc/Free 或 EnQue/DeQue 对侧操作。操作可能跨源文件或模板展开，因此
  仍需人工确认路径，不自动修改。

## `crosscore_tscm`

- `A5-CROSS-001/003`：Set/Wait 的路径对称性、模板参数、event ID 和消费次数。
- `A5-CROSS-002`：TSCM/L1 生产者和消费者的核角色、可见性与同步。
- `finalize` 或 intermittent 证据会提高本类候选，但不会把
  kernel/PC 虚构映射到源码行。

## `tiling_boundary`

- `A5-TILE-001`：tail/remain/actual length、GetBlockIdx/GetBlockNum 等
  边界锚点。重点核对空任务、最后一核、最后一个 repeat、非对齐尾部。
- 该类只提供低置信度定位入口；必须带入失败 case 的具体 tiling 值验证。
