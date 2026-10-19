# api_reference 文档索引

## AI CPU API

- [DataStoreBarrier](AI_CPU_API/DataStoreBarrier.md)
- [assert](AI_CPU_API/assert.md)
- [printf](AI_CPU_API/printf.md)

## SIMD API

### 其他数据类型

#### TensorDesc

- [GetDataObj](SIMD_API/其他数据类型/TensorDesc/GetDataObj.md)
- [GetDataPtr](SIMD_API/其他数据类型/TensorDesc/GetDataPtr.md)
- [GetDim](SIMD_API/其他数据类型/TensorDesc/GetDim.md)
- [GetIndex](SIMD_API/其他数据类型/TensorDesc/GetIndex.md)
- [GetShape](SIMD_API/其他数据类型/TensorDesc/GetShape.md)
- [SetShapeAddr](SIMD_API/其他数据类型/TensorDesc/SetShapeAddr.md)
- [TensorDesc简介](SIMD_API/其他数据类型/TensorDesc/TensorDesc简介.md)
- [构造和析构函数](SIMD_API/其他数据类型/TensorDesc/构造和析构函数.md)

- [BinaryRepeatParams](SIMD_API/其他数据类型/BinaryRepeatParams.md)
- [ListTensorDesc](SIMD_API/其他数据类型/ListTensorDesc.md)
- [ShapeInfo](SIMD_API/其他数据类型/ShapeInfo.md)
- [TPosition](SIMD_API/其他数据类型/TPosition.md)
- [UnaryRepeatParams](SIMD_API/其他数据类型/UnaryRepeatParams.md)
- [complex32/complex64](SIMD_API/其他数据类型/complex32_complex64.md)

### 基础API

#### Cube分组管理（ISASI）

##### CubeResGroupHandle

- [AllocMessage](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/AllocMessage.md)
- [AssignQueue](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/AssignQueue.md)
- [CreateCubeResGroup](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/CreateCubeResGroup.md)
- [CubeResGroupHandle使用说明](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/CubeResGroupHandle使用说明.md)
- [CubeResGroupHandle构造函数](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/CubeResGroupHandle构造函数.md)
- [FreeMessage](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/FreeMessage.md)
- [PostFakeMsg](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/PostFakeMsg.md)
- [PostMessage](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/PostMessage.md)
- [SetQuit](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/SetQuit.md)
- [SetSkipMsg](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/SetSkipMsg.md)
- [Wait](SIMD_API/基础API/Cube分组管理（ISASI）/CubeResGroupHandle/Wait.md)

##### GroupBarrier

- [Arrive](SIMD_API/基础API/Cube分组管理（ISASI）/GroupBarrier/Arrive.md)
- [GetWorkspaceLen](SIMD_API/基础API/Cube分组管理（ISASI）/GroupBarrier/GetWorkspaceLen.md)
- [GroupBarrier使用说明](SIMD_API/基础API/Cube分组管理（ISASI）/GroupBarrier/GroupBarrier使用说明.md)
- [GroupBarrier构造函数](SIMD_API/基础API/Cube分组管理（ISASI）/GroupBarrier/GroupBarrier构造函数.md)
- [Wait](SIMD_API/基础API/Cube分组管理（ISASI）/GroupBarrier/Wait.md)

##### KfcWorkspace

- [GetKfcWorkspace](SIMD_API/基础API/Cube分组管理（ISASI）/KfcWorkspace/GetKfcWorkspace.md)
- [UpdateKfcWorkspace](SIMD_API/基础API/Cube分组管理（ISASI）/KfcWorkspace/UpdateKfcWorkspace.md)
- [构造函数与析构函数](SIMD_API/基础API/Cube分组管理（ISASI）/KfcWorkspace/构造函数与析构函数.md)

#### Kernel Tiling

- [COPY_TILING_WITH_ARRAY](SIMD_API/基础API/Kernel_Tiling/COPY_TILING_WITH_ARRAY.md)
- [COPY_TILING_WITH_STRUCT](SIMD_API/基础API/Kernel_Tiling/COPY_TILING_WITH_STRUCT.md)
- [GET_TILING_DATA](SIMD_API/基础API/Kernel_Tiling/GET_TILING_DATA.md)
- [GET_TILING_DATA_MEMBER](SIMD_API/基础API/Kernel_Tiling/GET_TILING_DATA_MEMBER.md)
- [GET_TILING_DATA_PTR_WITH_STRUCT](SIMD_API/基础API/Kernel_Tiling/GET_TILING_DATA_PTR_WITH_STRUCT.md)
- [GET_TILING_DATA_WITH_STRUCT](SIMD_API/基础API/Kernel_Tiling/GET_TILING_DATA_WITH_STRUCT.md)
- [REGISTER_NONE_TILING](SIMD_API/基础API/Kernel_Tiling/REGISTER_NONE_TILING.md)
- [REGISTER_TILING_DEFAULT](SIMD_API/基础API/Kernel_Tiling/REGISTER_TILING_DEFAULT.md)
- [REGISTER_TILING_FOR_TILINGKEY](SIMD_API/基础API/Kernel_Tiling/REGISTER_TILING_FOR_TILINGKEY.md)
- [TILING_KEY_IS](SIMD_API/基础API/Kernel_Tiling/TILING_KEY_IS.md)
- [TILING_KEY_LIST](SIMD_API/基础API/Kernel_Tiling/TILING_KEY_LIST.md)
- [设置Kernel类型](SIMD_API/基础API/Kernel_Tiling/设置Kernel类型.md)

#### Memory数据搬运

##### DataCopy

- [DataCopy简介](SIMD_API/基础API/Memory数据搬运/DataCopy/DataCopy简介.md)
- [切片数据搬运](SIMD_API/基础API/Memory数据搬运/DataCopy/切片数据搬运.md)
- [基础数据搬运](SIMD_API/基础API/Memory数据搬运/DataCopy/基础数据搬运.md)
- [增强数据搬运](SIMD_API/基础API/Memory数据搬运/DataCopy/增强数据搬运.md)
- [多维数据搬运（ISASI）](SIMD_API/基础API/Memory数据搬运/DataCopy/多维数据搬运（ISASI）.md)
- [随路转换DN2NZ搬运（ISASI）](SIMD_API/基础API/Memory数据搬运/DataCopy/随路转换DN2NZ搬运（ISASI）.md)
- [随路转换ND2NZ搬运](SIMD_API/基础API/Memory数据搬运/DataCopy/随路转换ND2NZ搬运.md)
- [随路转换NZ2ND搬运](SIMD_API/基础API/Memory数据搬运/DataCopy/随路转换NZ2ND搬运.md)
- [随路量化激活搬运](SIMD_API/基础API/Memory数据搬运/DataCopy/随路量化激活搬运.md)

- [BroadCastVecToMM(ISASI)](SIMD_API/基础API/Memory数据搬运/BroadCastVecToMM（ISASI）.md)
- [Copy](SIMD_API/基础API/Memory数据搬运/Copy.md)
- [DataCopyPad(ISASI)](SIMD_API/基础API/Memory数据搬运/DataCopyPad（ISASI）.md)
- [ResetLoopModePara](SIMD_API/基础API/Memory数据搬运/ResetLoopModePara.md)
- [SetLoopModePara](SIMD_API/基础API/Memory数据搬运/SetLoopModePara.md)
- [SetPadValue(ISASI)](SIMD_API/基础API/Memory数据搬运/SetPadValue（ISASI）.md)

#### Memory矢量计算

##### 基础算术

- [Abs](SIMD_API/基础API/Memory矢量计算/基础算术/Abs.md)
- [Add](SIMD_API/基础API/Memory矢量计算/基础算术/Add.md)
- [Adds](SIMD_API/基础API/Memory矢量计算/基础算术/Adds.md)
- [Adds（灵活标量位置）](SIMD_API/基础API/Memory矢量计算/基础算术/Adds（灵活标量位置）.md)
- [BilinearInterpolation(ISASI)](SIMD_API/基础API/Memory矢量计算/基础算术/BilinearInterpolation（ISASI）.md)
- [Div](SIMD_API/基础API/Memory矢量计算/基础算术/Div.md)
- [Divs](SIMD_API/基础API/Memory矢量计算/基础算术/Divs.md)
- [Exp](SIMD_API/基础API/Memory矢量计算/基础算术/Exp.md)
- [LeakyRelu](SIMD_API/基础API/Memory矢量计算/基础算术/LeakyRelu.md)
- [Ln](SIMD_API/基础API/Memory矢量计算/基础算术/Ln.md)
- [Max](SIMD_API/基础API/Memory矢量计算/基础算术/Max.md)
- [Maxs](SIMD_API/基础API/Memory矢量计算/基础算术/Maxs.md)
- [Maxs（灵活标量位置）](SIMD_API/基础API/Memory矢量计算/基础算术/Maxs（灵活标量位置）.md)
- [Min](SIMD_API/基础API/Memory矢量计算/基础算术/Min.md)
- [Mins](SIMD_API/基础API/Memory矢量计算/基础算术/Mins.md)
- [Mins（灵活标量位置）](SIMD_API/基础API/Memory矢量计算/基础算术/Mins（灵活标量位置）.md)
- [Mul](SIMD_API/基础API/Memory矢量计算/基础算术/Mul.md)
- [Mull(ISASI)](SIMD_API/基础API/Memory矢量计算/基础算术/Mull（ISASI）.md)
- [Muls](SIMD_API/基础API/Memory矢量计算/基础算术/Muls.md)
- [Muls（灵活标量位置）](SIMD_API/基础API/Memory矢量计算/基础算术/Muls（灵活标量位置）.md)
- [Neg(ISASI)](SIMD_API/基础API/Memory矢量计算/基础算术/Neg（ISASI）.md)
- [Prelu(ISASI)](SIMD_API/基础API/Memory矢量计算/基础算术/Prelu（ISASI）.md)
- [Reciprocal](SIMD_API/基础API/Memory矢量计算/基础算术/Reciprocal.md)
- [Relu](SIMD_API/基础API/Memory矢量计算/基础算术/Relu.md)
- [Rsqrt](SIMD_API/基础API/Memory矢量计算/基础算术/Rsqrt.md)
- [Sqrt](SIMD_API/基础API/Memory矢量计算/基础算术/Sqrt.md)
- [Sub](SIMD_API/基础API/Memory矢量计算/基础算术/Sub.md)
- [Subs](SIMD_API/基础API/Memory矢量计算/基础算术/Subs.md)
- [更多样例](SIMD_API/基础API/Memory矢量计算/基础算术/更多样例.md)

##### 复合计算

- [AbsSub(ISASI)](SIMD_API/基础API/Memory矢量计算/复合计算/AbsSub（ISASI）.md)
- [AddDeqRelu](SIMD_API/基础API/Memory矢量计算/复合计算/AddDeqRelu.md)
- [AddRelu](SIMD_API/基础API/Memory矢量计算/复合计算/AddRelu.md)
- [AddReluCast](SIMD_API/基础API/Memory矢量计算/复合计算/AddReluCast.md)
- [Axpy](SIMD_API/基础API/Memory矢量计算/复合计算/Axpy.md)
- [CastDequant](SIMD_API/基础API/Memory矢量计算/复合计算/CastDequant.md)
- [ExpSub(ISASI)](SIMD_API/基础API/Memory矢量计算/复合计算/ExpSub（ISASI）.md)
- [FusedMulAdd](SIMD_API/基础API/Memory矢量计算/复合计算/FusedMulAdd.md)
- [MulAddDst](SIMD_API/基础API/Memory矢量计算/复合计算/MulAddDst.md)
- [MulAddRelu](SIMD_API/基础API/Memory矢量计算/复合计算/MulAddRelu.md)
- [MulCast](SIMD_API/基础API/Memory矢量计算/复合计算/MulCast.md)
- [MulsCast(ISASI)](SIMD_API/基础API/Memory矢量计算/复合计算/MulsCast（ISASI）.md)
- [SubRelu](SIMD_API/基础API/Memory矢量计算/复合计算/SubRelu.md)
- [SubReluCast](SIMD_API/基础API/Memory矢量计算/复合计算/SubReluCast.md)

##### 归约计算

- [BlockReduceMax](SIMD_API/基础API/Memory矢量计算/归约计算/BlockReduceMax.md)
- [BlockReduceMin](SIMD_API/基础API/Memory矢量计算/归约计算/BlockReduceMin.md)
- [BlockReduceSum](SIMD_API/基础API/Memory矢量计算/归约计算/BlockReduceSum.md)
- [GetReduceRepeatMaxMinSpr(ISASI)](SIMD_API/基础API/Memory矢量计算/归约计算/GetReduceRepeatMaxMinSpr（ISASI）.md)
- [GetReduceRepeatSumSpr(ISASI)](SIMD_API/基础API/Memory矢量计算/归约计算/GetReduceRepeatSumSpr（ISASI）.md)
- [PairReduceSum](SIMD_API/基础API/Memory矢量计算/归约计算/PairReduceSum.md)
- [ReduceMax](SIMD_API/基础API/Memory矢量计算/归约计算/ReduceMax.md)
- [ReduceMin](SIMD_API/基础API/Memory矢量计算/归约计算/ReduceMin.md)
- [ReduceSum](SIMD_API/基础API/Memory矢量计算/归约计算/ReduceSum.md)
- [RepeatReduceSum](SIMD_API/基础API/Memory矢量计算/归约计算/RepeatReduceSum.md)
- [WholeReduceMax](SIMD_API/基础API/Memory矢量计算/归约计算/WholeReduceMax.md)
- [WholeReduceMin](SIMD_API/基础API/Memory矢量计算/归约计算/WholeReduceMin.md)
- [WholeReduceSum](SIMD_API/基础API/Memory矢量计算/归约计算/WholeReduceSum.md)

##### 排序组合（ISASI）

- [GetMrgSortResult](SIMD_API/基础API/Memory矢量计算/排序组合（ISASI）/GetMrgSortResult.md)
- [MrgSort](SIMD_API/基础API/Memory矢量计算/排序组合（ISASI）/MrgSort.md)
- [MrgSort4](SIMD_API/基础API/Memory矢量计算/排序组合（ISASI）/MrgSort4.md)
- [ProposalConcat](SIMD_API/基础API/Memory矢量计算/排序组合（ISASI）/ProposalConcat.md)
- [ProposalExtract](SIMD_API/基础API/Memory矢量计算/排序组合（ISASI）/ProposalExtract.md)
- [RpSort16](SIMD_API/基础API/Memory矢量计算/排序组合（ISASI）/RpSort16.md)
- [Sort32](SIMD_API/基础API/Memory矢量计算/排序组合（ISASI）/Sort32.md)

##### 掩码操作

- [ResetMask](SIMD_API/基础API/Memory矢量计算/掩码操作/ResetMask.md)
- [SetMaskCount](SIMD_API/基础API/Memory矢量计算/掩码操作/SetMaskCount.md)
- [SetMaskNorm](SIMD_API/基础API/Memory矢量计算/掩码操作/SetMaskNorm.md)
- [SetVectorMask](SIMD_API/基础API/Memory矢量计算/掩码操作/SetVectorMask.md)

##### 数据填充

- [Brcb](SIMD_API/基础API/Memory矢量计算/数据填充/Brcb.md)
- [CreateVecIndex](SIMD_API/基础API/Memory矢量计算/数据填充/CreateVecIndex.md)
- [Duplicate](SIMD_API/基础API/Memory矢量计算/数据填充/Duplicate.md)
- [VectorPadding(ISASI)](SIMD_API/基础API/Memory矢量计算/数据填充/VectorPadding（ISASI）.md)

##### 数据转换

- [TransDataTo5HD](SIMD_API/基础API/Memory矢量计算/数据转换/TransDataTo5HD.md)
- [Transpose](SIMD_API/基础API/Memory矢量计算/数据转换/Transpose.md)

##### 数据重排（ISASI）

- [DeInterleave](SIMD_API/基础API/Memory矢量计算/数据重排（ISASI）/DeInterleave.md)
- [Interleave](SIMD_API/基础API/Memory矢量计算/数据重排（ISASI）/Interleave.md)

##### 比较与选择

- [Compare](SIMD_API/基础API/Memory矢量计算/比较与选择/Compare.md)
- [Compares](SIMD_API/基础API/Memory矢量计算/比较与选择/Compares.md)
- [Compares（灵活标量位置）](SIMD_API/基础API/Memory矢量计算/比较与选择/Compares（灵活标量位置）.md)
- [Compare（结果存入寄存器）](SIMD_API/基础API/Memory矢量计算/比较与选择/Compare（结果存入寄存器）.md)
- [GatherMask](SIMD_API/基础API/Memory矢量计算/比较与选择/GatherMask.md)
- [GetCmpMask(ISASI)](SIMD_API/基础API/Memory矢量计算/比较与选择/GetCmpMask（ISASI）.md)
- [Select](SIMD_API/基础API/Memory矢量计算/比较与选择/Select.md)
- [Select（灵活标量位置）](SIMD_API/基础API/Memory矢量计算/比较与选择/Select（灵活标量位置）.md)
- [SetCmpMask(ISASI)](SIMD_API/基础API/Memory矢量计算/比较与选择/SetCmpMask（ISASI）.md)

##### 离散与聚合

- [Gather](SIMD_API/基础API/Memory矢量计算/离散与聚合/Gather.md)
- [Gatherb(ISASI)](SIMD_API/基础API/Memory矢量计算/离散与聚合/Gatherb（ISASI）.md)
- [Scatter(ISASI)](SIMD_API/基础API/Memory矢量计算/离散与聚合/Scatter（ISASI）.md)

##### 类型转换

- [Cast](SIMD_API/基础API/Memory矢量计算/类型转换/Cast.md)
- [Truncate(ISASI)](SIMD_API/基础API/Memory矢量计算/类型转换/Truncate（ISASI）.md)

##### 逻辑计算

- [And](SIMD_API/基础API/Memory矢量计算/逻辑计算/And.md)
- [Ands](SIMD_API/基础API/Memory矢量计算/逻辑计算/Ands.md)
- [Not](SIMD_API/基础API/Memory矢量计算/逻辑计算/Not.md)
- [Or](SIMD_API/基础API/Memory矢量计算/逻辑计算/Or.md)
- [Ors](SIMD_API/基础API/Memory矢量计算/逻辑计算/Ors.md)
- [ShiftLeft](SIMD_API/基础API/Memory矢量计算/逻辑计算/ShiftLeft.md)
- [ShiftLeft（左移位数为Tensor）](SIMD_API/基础API/Memory矢量计算/逻辑计算/ShiftLeft（左移位数为Tensor）.md)
- [ShiftRight](SIMD_API/基础API/Memory矢量计算/逻辑计算/ShiftRight.md)
- [ShiftRight（右移位数为Tensor）](SIMD_API/基础API/Memory矢量计算/逻辑计算/ShiftRight（右移位数为Tensor）.md)

##### 量化设置

- [SetDeqScale](SIMD_API/基础API/Memory矢量计算/量化设置/SetDeqScale.md)

#### Reg矢量计算

##### MaskReg计算

- [DeInterleave](SIMD_API/基础API/Reg矢量计算/MaskReg计算/DeInterleave.md)
- [Interleave](SIMD_API/基础API/Reg矢量计算/MaskReg计算/Interleave.md)
- [Move](SIMD_API/基础API/Reg矢量计算/MaskReg计算/Move.md)
- [MoveMask](SIMD_API/基础API/Reg矢量计算/MaskReg计算/MoveMask.md)
- [Pack](SIMD_API/基础API/Reg矢量计算/MaskReg计算/Pack.md)
- [Select](SIMD_API/基础API/Reg矢量计算/MaskReg计算/Select.md)
- [UnPack](SIMD_API/基础API/Reg矢量计算/MaskReg计算/UnPack.md)

##### Reg数据搬运

- [MaskReg搬入](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/MaskReg搬入.md)
- [MaskReg搬出](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/MaskReg搬出.md)
- [Move](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/Move.md)
- [连续对齐搬入](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/连续对齐搬入.md)
- [连续对齐搬出](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/连续对齐搬出.md)
- [连续非对齐搬入](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/连续非对齐搬入.md)
- [连续非对齐搬出](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/连续非对齐搬出.md)
- [非连续对齐搬入](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/非连续对齐搬入.md)
- [非连续对齐搬出](SIMD_API/基础API/Reg矢量计算/Reg数据搬运/非连续对齐搬出.md)

##### 同步控制

- [LocalMemBar](SIMD_API/基础API/Reg矢量计算/同步控制/LocalMemBar.md)

##### 基础算术

- [Abs](SIMD_API/基础API/Reg矢量计算/基础算术/Abs.md)
- [Add](SIMD_API/基础API/Reg矢量计算/基础算术/Add.md)
- [AddC](SIMD_API/基础API/Reg矢量计算/基础算术/AddC.md)
- [Adds](SIMD_API/基础API/Reg矢量计算/基础算术/Adds.md)
- [Div](SIMD_API/基础API/Reg矢量计算/基础算术/Div.md)
- [Exp](SIMD_API/基础API/Reg矢量计算/基础算术/Exp.md)
- [LeakyRelu](SIMD_API/基础API/Reg矢量计算/基础算术/LeakyRelu.md)
- [Ln](SIMD_API/基础API/Reg矢量计算/基础算术/Ln.md)
- [Log](SIMD_API/基础API/Reg矢量计算/基础算术/Log.md)
- [Log10](SIMD_API/基础API/Reg矢量计算/基础算术/Log10.md)
- [Log2](SIMD_API/基础API/Reg矢量计算/基础算术/Log2.md)
- [Max](SIMD_API/基础API/Reg矢量计算/基础算术/Max.md)
- [Maxs](SIMD_API/基础API/Reg矢量计算/基础算术/Maxs.md)
- [Min](SIMD_API/基础API/Reg矢量计算/基础算术/Min.md)
- [Mins](SIMD_API/基础API/Reg矢量计算/基础算术/Mins.md)
- [Mul](SIMD_API/基础API/Reg矢量计算/基础算术/Mul.md)
- [Mull](SIMD_API/基础API/Reg矢量计算/基础算术/Mull.md)
- [Muls](SIMD_API/基础API/Reg矢量计算/基础算术/Muls.md)
- [Neg](SIMD_API/基础API/Reg矢量计算/基础算术/Neg.md)
- [Prelu](SIMD_API/基础API/Reg矢量计算/基础算术/Prelu.md)
- [Relu](SIMD_API/基础API/Reg矢量计算/基础算术/Relu.md)
- [Sqrt](SIMD_API/基础API/Reg矢量计算/基础算术/Sqrt.md)
- [Sub](SIMD_API/基础API/Reg矢量计算/基础算术/Sub.md)
- [SubC](SIMD_API/基础API/Reg矢量计算/基础算术/SubC.md)

##### 复合计算

- [AbsSub](SIMD_API/基础API/Reg矢量计算/复合计算/AbsSub.md)
- [Axpy](SIMD_API/基础API/Reg矢量计算/复合计算/Axpy.md)
- [ExpSub](SIMD_API/基础API/Reg矢量计算/复合计算/ExpSub.md)
- [MulAddDst](SIMD_API/基础API/Reg矢量计算/复合计算/MulAddDst.md)
- [MulDstAdd](SIMD_API/基础API/Reg矢量计算/复合计算/MulDstAdd.md)
- [MulsCast](SIMD_API/基础API/Reg矢量计算/复合计算/MulsCast.md)

##### 寄存器数据类型

- [AddrReg](SIMD_API/基础API/Reg矢量计算/寄存器数据类型/AddrReg.md)
- [MaskReg](SIMD_API/基础API/Reg矢量计算/寄存器数据类型/MaskReg.md)
- [RegTensor](SIMD_API/基础API/Reg矢量计算/寄存器数据类型/RegTensor.md)

##### 归约计算

- [PairReduceElem](SIMD_API/基础API/Reg矢量计算/归约计算/PairReduceElem.md)
- [Reduce](SIMD_API/基础API/Reg矢量计算/归约计算/Reduce.md)
- [ReduceDataBlock](SIMD_API/基础API/Reg矢量计算/归约计算/ReduceDataBlock.md)

##### 数据压缩

- [Pack](SIMD_API/基础API/Reg矢量计算/数据压缩/Pack.md)
- [UnPack](SIMD_API/基础API/Reg矢量计算/数据压缩/UnPack.md)
- [Unsqueeze](SIMD_API/基础API/Reg矢量计算/数据压缩/Unsqueeze.md)

##### 数据填充

- [Duplicate](SIMD_API/基础API/Reg矢量计算/数据填充/Duplicate.md)

##### 数据类型

- [CastTrait](SIMD_API/基础API/Reg矢量计算/数据类型/CastTrait.md)
- [MaskMergeMode](SIMD_API/基础API/Reg矢量计算/数据类型/MaskMergeMode.md)
- [PostLiteral](SIMD_API/基础API/Reg矢量计算/数据类型/PostLiteral.md)
- [RegLayout](SIMD_API/基础API/Reg矢量计算/数据类型/RegLayout.md)
- [RoundMode](SIMD_API/基础API/Reg矢量计算/数据类型/RoundMode.md)
- [SatMode](SIMD_API/基础API/Reg矢量计算/数据类型/SatMode.md)

##### 数据重排

- [DeInterleave](SIMD_API/基础API/Reg矢量计算/数据重排/DeInterleave.md)
- [Interleave](SIMD_API/基础API/Reg矢量计算/数据重排/Interleave.md)

##### 比较与选择

- [Compare](SIMD_API/基础API/Reg矢量计算/比较与选择/Compare.md)
- [Compares](SIMD_API/基础API/Reg矢量计算/比较与选择/Compares.md)
- [Select](SIMD_API/基础API/Reg矢量计算/比较与选择/Select.md)
- [Squeeze](SIMD_API/基础API/Reg矢量计算/比较与选择/Squeeze.md)

##### 直方图计算

- [Histograms](SIMD_API/基础API/Reg矢量计算/直方图计算/Histograms.md)

##### 离散与聚合

- [Gather](SIMD_API/基础API/Reg矢量计算/离散与聚合/Gather.md)
- [GatherB](SIMD_API/基础API/Reg矢量计算/离散与聚合/GatherB.md)
- [Gather（支持寄存器为源操作数）](SIMD_API/基础API/Reg矢量计算/离散与聚合/Gather（支持寄存器为源操作数）.md)
- [Scatter](SIMD_API/基础API/Reg矢量计算/离散与聚合/Scatter.md)

##### 类型转换

- [Cast](SIMD_API/基础API/Reg矢量计算/类型转换/Cast.md)
- [Truncate](SIMD_API/基础API/Reg矢量计算/类型转换/Truncate.md)

##### 系统变量访问

- [ClearSpr](SIMD_API/基础API/Reg矢量计算/系统变量访问/ClearSpr.md)
- [GetSpr](SIMD_API/基础API/Reg矢量计算/系统变量访问/GetSpr.md)

##### 索引操作

- [Arange](SIMD_API/基础API/Reg矢量计算/索引操作/Arange.md)

##### 逻辑计算

- [And](SIMD_API/基础API/Reg矢量计算/逻辑计算/And.md)
- [Not](SIMD_API/基础API/Reg矢量计算/逻辑计算/Not.md)
- [Or](SIMD_API/基础API/Reg矢量计算/逻辑计算/Or.md)
- [ShiftLeft](SIMD_API/基础API/Reg矢量计算/逻辑计算/ShiftLeft.md)
- [ShiftLefts](SIMD_API/基础API/Reg矢量计算/逻辑计算/ShiftLefts.md)
- [ShiftRight](SIMD_API/基础API/Reg矢量计算/逻辑计算/ShiftRight.md)
- [ShiftRights](SIMD_API/基础API/Reg矢量计算/逻辑计算/ShiftRights.md)
- [Xor](SIMD_API/基础API/Reg矢量计算/逻辑计算/Xor.md)

- [asc_vf_call](SIMD_API/基础API/Reg矢量计算/asc_vf_call.md)

#### 原子操作

- [AtomicAdd](SIMD_API/基础API/原子操作/AtomicAdd.md)
- [AtomicCas](SIMD_API/基础API/原子操作/AtomicCas.md)
- [AtomicExch](SIMD_API/基础API/原子操作/AtomicExch.md)
- [AtomicMax](SIMD_API/基础API/原子操作/AtomicMax.md)
- [AtomicMin](SIMD_API/基础API/原子操作/AtomicMin.md)
- [DisableDmaAtomic](SIMD_API/基础API/原子操作/DisableDmaAtomic.md)
- [GetStoreAtomicConfig(ISASI)](SIMD_API/基础API/原子操作/GetStoreAtomicConfig（ISASI）.md)
- [MarkStamp](SIMD_API/基础API/原子操作/MarkStamp.md)
- [SetAtomicAdd](SIMD_API/基础API/原子操作/SetAtomicAdd.md)
- [SetAtomicMax(ISASI)](SIMD_API/基础API/原子操作/SetAtomicMax（ISASI）.md)
- [SetAtomicMin(ISASI)](SIMD_API/基础API/原子操作/SetAtomicMin（ISASI）.md)
- [SetAtomicType](SIMD_API/基础API/原子操作/SetAtomicType.md)
- [SetStoreAtomicConfig(ISASI)](SIMD_API/基础API/原子操作/SetStoreAtomicConfig（ISASI）.md)

#### 同步控制

##### 任务间同步

- [SetNextTaskStart](SIMD_API/基础API/同步控制/任务间同步/SetNextTaskStart.md)
- [WaitPreTaskEnd](SIMD_API/基础API/同步控制/任务间同步/WaitPreTaskEnd.md)

##### 核内同步

###### Mutex（ISASI）

- [Lock](SIMD_API/基础API/同步控制/核内同步/Mutex（ISASI）/Lock.md)
- [Unlock](SIMD_API/基础API/同步控制/核内同步/Mutex（ISASI）/Unlock.md)
- [简介](SIMD_API/基础API/同步控制/核内同步/Mutex（ISASI）/简介.md)

###### TQueSync

- [Nop](SIMD_API/基础API/同步控制/核内同步/TQueSync/Nop.md)
- [SetFlag/WaitFlag](SIMD_API/基础API/同步控制/核内同步/TQueSync/SetFlag_WaitFlag.md)
- [模板参数](SIMD_API/基础API/同步控制/核内同步/TQueSync/模板参数.md)

- [AllocMutexID (ISASI)](SIMD_API/基础API/同步控制/核内同步/AllocMutexID_（ISASI）.md)
- [DataSyncBarrier(ISASI)](SIMD_API/基础API/同步控制/核内同步/DataSyncBarrier（ISASI）.md)
- [PipeBarrier(ISASI)](SIMD_API/基础API/同步控制/核内同步/PipeBarrier（ISASI）.md)
- [ReleaseMutexID (ISASI)](SIMD_API/基础API/同步控制/核内同步/ReleaseMutexID_（ISASI）.md)
- [SetFlag/WaitFlag(ISASI)](SIMD_API/基础API/同步控制/核内同步/SetFlag_WaitFlag（ISASI）.md)
- [同步控制简介](SIMD_API/基础API/同步控制/核内同步/同步控制简介.md)

##### 核间同步

- [CrossCoreSetFlag(ISASI)](SIMD_API/基础API/同步控制/核间同步/CrossCoreSetFlag（ISASI）.md)
- [CrossCoreWaitFlag(ISASI)](SIMD_API/基础API/同步控制/核间同步/CrossCoreWaitFlag（ISASI）.md)
- [IBSet](SIMD_API/基础API/同步控制/核间同步/IBSet.md)
- [IBWait](SIMD_API/基础API/同步控制/核间同步/IBWait.md)
- [InitDetermineComputeWorkspace](SIMD_API/基础API/同步控制/核间同步/InitDetermineComputeWorkspace.md)
- [NotifyNextBlock](SIMD_API/基础API/同步控制/核间同步/NotifyNextBlock.md)
- [SyncAll](SIMD_API/基础API/同步控制/核间同步/SyncAll.md)
- [WaitPreBlock](SIMD_API/基础API/同步控制/核间同步/WaitPreBlock.md)

#### 工具函数

##### NumericLimits

- [DeNormMin](SIMD_API/基础API/工具函数/NumericLimits/DeNormMin.md)
- [Infinity](SIMD_API/基础API/工具函数/NumericLimits/Infinity.md)
- [Lowest](SIMD_API/基础API/工具函数/NumericLimits/Lowest.md)
- [Max](SIMD_API/基础API/工具函数/NumericLimits/Max.md)
- [Min](SIMD_API/基础API/工具函数/NumericLimits/Min.md)
- [NegativeInfinity](SIMD_API/基础API/工具函数/NumericLimits/NegativeInfinity.md)
- [QuietNaN](SIMD_API/基础API/工具函数/NumericLimits/QuietNaN.md)
- [SignalingNaN](SIMD_API/基础API/工具函数/NumericLimits/SignalingNaN.md)
- [简介](SIMD_API/基础API/工具函数/NumericLimits/简介.md)

- [Async](SIMD_API/基础API/工具函数/Async.md)
- [CeilDivision](SIMD_API/基础API/工具函数/CeilDivision.md)
- [GetRuntimeUBSize](SIMD_API/基础API/工具函数/GetRuntimeUBSize.md)
- [GetSsbufBaseAddr](SIMD_API/基础API/工具函数/GetSsbufBaseAddr.md)
- [GetTaskRatio](SIMD_API/基础API/工具函数/GetTaskRatio.md)
- [GetUBSizeInBytes](SIMD_API/基础API/工具函数/GetUBSizeInBytes.md)
- [GetVecLen](SIMD_API/基础API/工具函数/GetVecLen.md)

#### 标量计算

- [Cast（float转bfloat16_t）](SIMD_API/基础API/标量计算/Cast（float转bfloat16_t）.md)
- [Cast（float转half/int32_t）](SIMD_API/基础API/标量计算/Cast（float转half_int32_t）.md)
- [Cast（多类型转float）](SIMD_API/基础API/标量计算/Cast（多类型转float）.md)
- [CountBitsCntSameAsSignBit](SIMD_API/基础API/标量计算/CountBitsCntSameAsSignBit.md)
- [CountLeadingZero](SIMD_API/基础API/标量计算/CountLeadingZero.md)
- [GetBitCount](SIMD_API/基础API/标量计算/GetBitCount.md)
- [GetSFFValue](SIMD_API/基础API/标量计算/GetSFFValue.md)
- [ReadGmByPassDCache(ISASI)](SIMD_API/基础API/标量计算/ReadGmByPassDCache（ISASI）.md)
- [WriteGmByPassDCache(ISASI)](SIMD_API/基础API/标量计算/WriteGmByPassDCache（ISASI）.md)

#### 矩阵计算（ISASI）

##### 数据搬运

###### LoadData

- [Load2D](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadData/Load2D.md)
- [Load2DBitMode](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadData/Load2DBitMode.md)
- [Load2DMX](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadData/Load2DMX.md)
- [Load3D](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadData/Load3D.md)
- [Load3DBitMode](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadData/Load3DBitMode.md)

- [Fill](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/Fill.md)
- [Fixpipe](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/Fixpipe.md)
- [LoadDataUnzip](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadDataUnzip.md)
- [LoadDataWithSparse](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadDataWithSparse.md)
- [LoadDataWithTranspose](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadDataWithTranspose.md)
- [LoadImageToLocal](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadImageToLocal.md)
- [LoadUnzipIndex](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/LoadUnzipIndex.md)
- [SetAippFunctions](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetAippFunctions.md)
- [SetFixPipeAddr](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetFixPipeAddr.md)
- [SetFixPipeClipRelu](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetFixPipeClipRelu.md)
- [SetFixPipeConfig](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetFixPipeConfig.md)
- [SetFixpipeNz2ndFlag](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetFixpipeNz2ndFlag.md)
- [SetFixpipePreQuantFlag](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetFixpipePreQuantFlag.md)
- [SetFmatrix](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetFmatrix.md)
- [SetFmatrixBitMode](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetFmatrixBitMode.md)
- [SetLoadDataBoundary](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetLoadDataBoundary.md)
- [SetLoadDataPaddingValue](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetLoadDataPaddingValue.md)
- [SetLoadDataRepeat](SIMD_API/基础API/矩阵计算（ISASI）/数据搬运/SetLoadDataRepeat.md)

##### 矩阵计算

- [Conv2D（废弃）](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/Conv2D（废弃）.md)
- [Gemm（废弃）](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/Gemm（废弃）.md)
- [Mmad](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/Mmad.md)
- [MmadBitMode](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/MmadBitMode.md)
- [MmadWithSparse](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/MmadWithSparse.md)
- [SetHF32Mode](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/SetHF32Mode.md)
- [SetHF32TransMode](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/SetHF32TransMode.md)
- [SetMMColumnMajor](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/SetMMColumnMajor.md)
- [SetMMRowMajor](SIMD_API/基础API/矩阵计算（ISASI）/矩阵计算/SetMMRowMajor.md)

#### 系统变量访问

- [GetArchVersion](SIMD_API/基础API/系统变量访问/GetArchVersion.md)
- [GetBlockIdx](SIMD_API/基础API/系统变量访问/GetBlockIdx.md)
- [GetBlockNum](SIMD_API/基础API/系统变量访问/GetBlockNum.md)
- [GetCtrlSpr(ISASI)](SIMD_API/基础API/系统变量访问/GetCtrlSpr（ISASI）.md)
- [GetDataBlockSizeInBytes](SIMD_API/基础API/系统变量访问/GetDataBlockSizeInBytes.md)
- [GetProgramCounter(ISASI)](SIMD_API/基础API/系统变量访问/GetProgramCounter（ISASI）.md)
- [GetSubBlockIdx(ISASI)](SIMD_API/基础API/系统变量访问/GetSubBlockIdx（ISASI）.md)
- [GetSubBlockNum(ISASI)](SIMD_API/基础API/系统变量访问/GetSubBlockNum（ISASI）.md)
- [GetSystemCycle(ISASI)](SIMD_API/基础API/系统变量访问/GetSystemCycle（ISASI）.md)
- [InitSocState](SIMD_API/基础API/系统变量访问/InitSocState.md)
- [ResetCtrlSpr(ISASI)](SIMD_API/基础API/系统变量访问/ResetCtrlSpr（ISASI）.md)
- [SetCtrlSpr(ISASI)](SIMD_API/基础API/系统变量访问/SetCtrlSpr（ISASI）.md)

#### 缓存控制

- [DataCacheCleanAndInvalid](SIMD_API/基础API/缓存控制/DataCacheCleanAndInvalid.md)
- [DataCachePreload](SIMD_API/基础API/缓存控制/DataCachePreload.md)
- [GetICachePreloadStatus(ISASI)](SIMD_API/基础API/缓存控制/GetICachePreloadStatus（ISASI）.md)
- [ICachePreLoad(ISASI)](SIMD_API/基础API/缓存控制/ICachePreLoad（ISASI）.md)

#### 调试接口

##### CPU孪生调试

- [GmAlloc](SIMD_API/基础API/调试接口/CPU孪生调试/GmAlloc.md)
- [GmFree](SIMD_API/基础API/调试接口/CPU孪生调试/GmFree.md)
- [ICPU_RUN_KF](SIMD_API/基础API/调试接口/CPU孪生调试/ICPU_RUN_KF.md)
- [ICPU_SET_TILING_KEY](SIMD_API/基础API/调试接口/CPU孪生调试/ICPU_SET_TILING_KEY.md)
- [SetKernelMode](SIMD_API/基础API/调试接口/CPU孪生调试/SetKernelMode.md)

##### 上板打印

- [DumpAccChkPoint](SIMD_API/基础API/调试接口/上板打印/DumpAccChkPoint.md)
- [DumpTensor](SIMD_API/基础API/调试接口/上板打印/DumpTensor.md)
- [PrintTimeStamp](SIMD_API/基础API/调试接口/上板打印/PrintTimeStamp.md)
- [printf](SIMD_API/基础API/调试接口/上板打印/printf.md)

##### 异常检测

- [CheckLocalMemoryIA(ISASI)](SIMD_API/基础API/调试接口/异常检测/CheckLocalMemoryIA（ISASI）.md)
- [Trap](SIMD_API/基础API/调试接口/异常检测/Trap.md)
- [ascendc_assert](SIMD_API/基础API/调试接口/异常检测/ascendc_assert.md)
- [assert](SIMD_API/基础API/调试接口/异常检测/assert.md)

##### 性能统计

- [MetricsProfStart](SIMD_API/基础API/调试接口/性能统计/MetricsProfStart.md)
- [MetricsProfStop](SIMD_API/基础API/调试接口/性能统计/MetricsProfStop.md)

#### 资源管理

##### Pipe和Que框架

###### TBuf

- [Get](SIMD_API/基础API/资源管理/Pipe和Que框架/TBuf/Get.md)
- [GetWithOffset](SIMD_API/基础API/资源管理/Pipe和Que框架/TBuf/GetWithOffset.md)
- [TBuf构造函数](SIMD_API/基础API/资源管理/Pipe和Que框架/TBuf/TBuf构造函数.md)
- [TBuf简介](SIMD_API/基础API/资源管理/Pipe和Que框架/TBuf/TBuf简介.md)

###### TBufPool

- [InitBufPool](SIMD_API/基础API/资源管理/Pipe和Que框架/TBufPool/InitBufPool.md)
- [InitBuffer](SIMD_API/基础API/资源管理/Pipe和Que框架/TBufPool/InitBuffer.md)
- [Reset](SIMD_API/基础API/资源管理/Pipe和Que框架/TBufPool/Reset.md)
- [TBufPool构造函数](SIMD_API/基础API/资源管理/Pipe和Que框架/TBufPool/TBufPool构造函数.md)
- [TBufPool简介](SIMD_API/基础API/资源管理/Pipe和Que框架/TBufPool/TBufPool简介.md)

###### TPipe

- [AllocEventID](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/AllocEventID.md)
- [Destroy](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/Destroy.md)
- [FetchEventID](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/FetchEventID.md)
- [GetBaseAddr](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/GetBaseAddr.md)
- [Init](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/Init.md)
- [InitBufPool](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/InitBufPool.md)
- [InitBuffer](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/InitBuffer.md)
- [InitSpmBuffer](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/InitSpmBuffer.md)
- [ReadSpmBuffer](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/ReadSpmBuffer.md)
- [ReleaseEventID](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/ReleaseEventID.md)
- [Reset](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/Reset.md)
- [TPipe构造函数](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/TPipe构造函数.md)
- [WriteSpmBuffer](SIMD_API/基础API/资源管理/Pipe和Que框架/TPipe/WriteSpmBuffer.md)

###### TQue

- [AllocTensor](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/AllocTensor.md)
- [DeQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/DeQue.md)
- [EnQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/EnQue.md)
- [FreeTensor](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/FreeTensor.md)
- [GetTensorCountInQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/GetTensorCountInQue.md)
- [HasIdleBuffer](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/HasIdleBuffer.md)
- [HasTensorInQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/HasTensorInQue.md)
- [TQue简介](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/TQue简介.md)
- [VacantInQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/VacantInQue.md)

###### TQueBind

- [AllocTensor](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/AllocTensor.md)
- [DeQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/DeQue.md)
- [EnQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/EnQue.md)
- [FreeAllEvent](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/FreeAllEvent.md)
- [FreeTensor](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/FreeTensor.md)
- [GetTensorCountInQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/GetTensorCountInQue.md)
- [HasIdleBuffer](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/HasIdleBuffer.md)
- [HasTensorInQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/HasTensorInQue.md)
- [InitBufHandle](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/InitBufHandle.md)
- [InitStartBufHandle](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/InitStartBufHandle.md)
- [TQueBind构造函数](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/TQueBind构造函数.md)
- [TQueBind简介](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/TQueBind简介.md)
- [VacantInQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TQueBind/VacantInQue.md)

###### TSCM

- [AllocTensor](SIMD_API/基础API/资源管理/Pipe和Que框架/TSCM/AllocTensor.md)
- [DeQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TSCM/DeQue.md)
- [EnQue](SIMD_API/基础API/资源管理/Pipe和Que框架/TSCM/EnQue.md)
- [FreeTensor](SIMD_API/基础API/资源管理/Pipe和Que框架/TSCM/FreeTensor.md)
- [TSCM简介](SIMD_API/基础API/资源管理/Pipe和Que框架/TSCM/TSCM简介.md)

###### 自定义TBufPool

- [EXTERN_IMPL_BUFPOOL宏](SIMD_API/基础API/资源管理/Pipe和Que框架/自定义TBufPool/EXTERN_IMPL_BUFPOOL宏.md)
- [GetBufHandle](SIMD_API/基础API/资源管理/Pipe和Que框架/自定义TBufPool/GetBufHandle.md)
- [GetCurAddr](SIMD_API/基础API/资源管理/Pipe和Que框架/自定义TBufPool/GetCurAddr.md)
- [GetCurBufSize](SIMD_API/基础API/资源管理/Pipe和Que框架/自定义TBufPool/GetCurBufSize.md)
- [Init](SIMD_API/基础API/资源管理/Pipe和Que框架/自定义TBufPool/Init.md)
- [Reset](SIMD_API/基础API/资源管理/Pipe和Que框架/自定义TBufPool/Reset.md)
- [SetCurAddr](SIMD_API/基础API/资源管理/Pipe和Que框架/自定义TBufPool/SetCurAddr.md)
- [SetCurBufSize](SIMD_API/基础API/资源管理/Pipe和Que框架/自定义TBufPool/SetCurBufSize.md)

- [GetTPipePtr](SIMD_API/基础API/资源管理/Pipe和Que框架/GetTPipePtr.md)

##### 临时空间管理

###### workspace

- [GetSysWorkSpacePtr](SIMD_API/基础API/资源管理/临时空间管理/workspace/GetSysWorkSpacePtr.md)
- [GetUserWorkspace](SIMD_API/基础API/资源管理/临时空间管理/workspace/GetUserWorkspace.md)
- [SetSysWorkSpace](SIMD_API/基础API/资源管理/临时空间管理/workspace/SetSysWorkSpace.md)

- [PopStackBuffer](SIMD_API/基础API/资源管理/临时空间管理/PopStackBuffer.md)

##### 内存管理

###### LocalMemAllocator

- [Alloc](SIMD_API/基础API/资源管理/内存管理/LocalMemAllocator/Alloc.md)
- [GetCurAddr](SIMD_API/基础API/资源管理/内存管理/LocalMemAllocator/GetCurAddr.md)
- [LocalMemAllocator构造函数](SIMD_API/基础API/资源管理/内存管理/LocalMemAllocator/LocalMemAllocator构造函数.md)
- [LocalMemAllocator简介](SIMD_API/基础API/资源管理/内存管理/LocalMemAllocator/LocalMemAllocator简介.md)

### 基础数据结构

#### Coordinate

- [Coordinate简介](SIMD_API/基础数据结构/Coordinate/Coordinate简介.md)
- [Crd2Idx](SIMD_API/基础数据结构/Coordinate/Crd2Idx.md)
- [MakeCoord](SIMD_API/基础数据结构/Coordinate/MakeCoord.md)

#### GlobalTensor

- [GetPhyAddr](SIMD_API/基础数据结构/GlobalTensor/GetPhyAddr.md)
- [GetShapeInfo](SIMD_API/基础数据结构/GlobalTensor/GetShapeInfo.md)
- [GetSize](SIMD_API/基础数据结构/GlobalTensor/GetSize.md)
- [GetValue](SIMD_API/基础数据结构/GlobalTensor/GetValue.md)
- [GlobalTensor构造函数](SIMD_API/基础数据结构/GlobalTensor/GlobalTensor构造函数.md)
- [GlobalTensor简介](SIMD_API/基础数据结构/GlobalTensor/GlobalTensor简介.md)
- [ReinterpretCast](SIMD_API/基础数据结构/GlobalTensor/ReinterpretCast.md)
- [SetGlobalBuffer](SIMD_API/基础数据结构/GlobalTensor/SetGlobalBuffer.md)
- [SetL2CacheHint](SIMD_API/基础数据结构/GlobalTensor/SetL2CacheHint.md)
- [SetShapeInfo](SIMD_API/基础数据结构/GlobalTensor/SetShapeInfo.md)
- [SetValue](SIMD_API/基础数据结构/GlobalTensor/SetValue.md)
- [operator()](SIMD_API/基础数据结构/GlobalTensor/operator（）.md)
- [operator[]](SIMD_API/基础数据结构/GlobalTensor/operator[].md)

#### Layout

- [GetShape](SIMD_API/基础数据结构/Layout/GetShape.md)
- [GetStride](SIMD_API/基础数据结构/Layout/GetStride.md)
- [Layout构造函数](SIMD_API/基础数据结构/Layout/Layout构造函数.md)
- [Layout简介](SIMD_API/基础数据结构/Layout/Layout简介.md)
- [MakeLayout](SIMD_API/基础数据结构/Layout/MakeLayout.md)
- [MakeShape](SIMD_API/基础数据结构/Layout/MakeShape.md)
- [MakeStride](SIMD_API/基础数据结构/Layout/MakeStride.md)
- [is_layout](SIMD_API/基础数据结构/Layout/is_layout.md)
- [layout](SIMD_API/基础数据结构/Layout/layout.md)
- [运算符重载](SIMD_API/基础数据结构/Layout/运算符重载.md)

#### LocalTensor

- [GetLength](SIMD_API/基础数据结构/LocalTensor/GetLength.md)
- [GetPhyAddr](SIMD_API/基础数据结构/LocalTensor/GetPhyAddr.md)
- [GetPosition](SIMD_API/基础数据结构/LocalTensor/GetPosition.md)
- [GetShapeInfo](SIMD_API/基础数据结构/LocalTensor/GetShapeInfo.md)
- [GetSize](SIMD_API/基础数据结构/LocalTensor/GetSize.md)
- [GetUserTag](SIMD_API/基础数据结构/LocalTensor/GetUserTag.md)
- [GetValue](SIMD_API/基础数据结构/LocalTensor/GetValue.md)
- [LocalTensor构造函数](SIMD_API/基础数据结构/LocalTensor/LocalTensor构造函数.md)
- [LocalTensor简介](SIMD_API/基础数据结构/LocalTensor/LocalTensor简介.md)
- [Print](SIMD_API/基础数据结构/LocalTensor/Print.md)
- [ReinterpretCast](SIMD_API/基础数据结构/LocalTensor/ReinterpretCast.md)
- [SetAddrWithOffset](SIMD_API/基础数据结构/LocalTensor/SetAddrWithOffset.md)
- [SetBufferLen](SIMD_API/基础数据结构/LocalTensor/SetBufferLen.md)
- [SetShapeInfo](SIMD_API/基础数据结构/LocalTensor/SetShapeInfo.md)
- [SetSize](SIMD_API/基础数据结构/LocalTensor/SetSize.md)
- [SetUserTag](SIMD_API/基础数据结构/LocalTensor/SetUserTag.md)
- [SetValue](SIMD_API/基础数据结构/LocalTensor/SetValue.md)
- [ToFile](SIMD_API/基础数据结构/LocalTensor/ToFile.md)
- [operator()](SIMD_API/基础数据结构/LocalTensor/operator（）.md)
- [operator[]](SIMD_API/基础数据结构/LocalTensor/operator[].md)

#### TensorTrait

- [GetLayout](SIMD_API/基础数据结构/TensorTrait/GetLayout.md)
- [MakeTensorTrait](SIMD_API/基础数据结构/TensorTrait/MakeTensorTrait.md)
- [SetLayout](SIMD_API/基础数据结构/TensorTrait/SetLayout.md)
- [TensorTrait构造函数](SIMD_API/基础数据结构/TensorTrait/TensorTrait构造函数.md)
- [TensorTrait简介](SIMD_API/基础数据结构/TensorTrait/TensorTrait简介.md)
- [is_tensorTrait](SIMD_API/基础数据结构/TensorTrait/is_tensorTrait.md)
- [更多样例](SIMD_API/基础数据结构/TensorTrait/更多样例.md)

### 高阶API

#### HCCL通信类

##### HCCL Context

- [GetHcclContext](SIMD_API/高阶API/HCCL通信类/HCCL_Context/GetHcclContext.md)
- [SetHcclContext](SIMD_API/高阶API/HCCL通信类/HCCL_Context/SetHcclContext.md)

##### HCCL Kernel侧接口

- [AllGather](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/AllGather.md)
- [AllReduce](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/AllReduce.md)
- [AlltoAll](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/AlltoAll.md)
- [AlltoAllV](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/AlltoAllV.md)
- [AlltoAllvWrite](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/AlltoAllvWrite.md)
- [BatchWrite](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/BatchWrite.md)
- [Commit](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/Commit.md)
- [Finalize](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/Finalize.md)
- [GetQueueNum](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/GetQueueNum.md)
- [GetRankDim](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/GetRankDim.md)
- [GetRankId](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/GetRankId.md)
- [GetWindowsInAddr](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/GetWindowsInAddr.md)
- [GetWindowsOutAddr](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/GetWindowsOutAddr.md)
- [HCCL使用说明](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/HCCL使用说明.md)
- [HCCL模板参数](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/HCCL模板参数.md)
- [InitV2](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/InitV2.md)
- [Init（废弃）](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/Init（废弃）.md)
- [InterHcclGroupSync](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/InterHcclGroupSync.md)
- [Iterate](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/Iterate.md)
- [Query](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/Query.md)
- [QueueBarrier](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/QueueBarrier.md)
- [ReduceScatter](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/ReduceScatter.md)
- [SetCcTilingV2](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/SetCcTilingV2.md)
- [SetCcTiling（废弃）](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/SetCcTiling（废弃）.md)
- [SetReduceDataTypeAbility（废弃）](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/SetReduceDataTypeAbility（废弃）.md)
- [Wait](SIMD_API/高阶API/HCCL通信类/HCCL_Kernel侧接口/Wait.md)

##### HCCL Tiling侧接口

- [GetTiling](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/GetTiling.md)
- [HCCL Tiling使用说明](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/HCCL_Tiling使用说明.md)
- [HCCL Tiling构造函数](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/HCCL_Tiling构造函数.md)
- [SetAlgConfig](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetAlgConfig.md)
- [SetCommBlockNum](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetCommBlockNum.md)
- [SetCommEngine](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetCommEngine.md)
- [SetDebugMode](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetDebugMode.md)
- [SetGroupName](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetGroupName.md)
- [SetOpType](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetOpType.md)
- [SetQueueNum](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetQueueNum.md)
- [SetReduceType](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetReduceType.md)
- [SetSkipBufferWindowCopy](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetSkipBufferWindowCopy.md)
- [SetSkipLocalRankCopy](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetSkipLocalRankCopy.md)
- [SetStepSize](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/SetStepSize.md)
- [TilingData结构体](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/TilingData结构体.md)
- [v1版本TilingData（废弃）](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/v1版本TilingData（废弃）.md)
- [v2版本TilingData（废弃）](SIMD_API/高阶API/HCCL通信类/HCCL_Tiling侧接口/v2版本TilingData（废弃）.md)

#### 卷积计算

##### Conv3D

###### Conv3D Kernel侧接口

- [Conv3D使用说明](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/Conv3D使用说明.md)
- [Conv3D模板参数](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/Conv3D模板参数.md)
- [End](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/End.md)
- [Init](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/Init.md)
- [IterateAll](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/IterateAll.md)
- [SetBias](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/SetBias.md)
- [SetInput](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/SetInput.md)
- [SetInputStartPosition](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/SetInputStartPosition.md)
- [SetSingleOutputShape](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/SetSingleOutputShape.md)
- [SetWeight](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Kernel侧接口/SetWeight.md)

###### Conv3D Tiling侧接口

- [Conv3D Tiling使用说明](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/Conv3D_Tiling使用说明.md)
- [Conv3D Tiling构造函数](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/Conv3D_Tiling构造函数.md)
- [GetTiling](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/GetTiling.md)
- [SetBiasType](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetBiasType.md)
- [SetDilation](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetDilation.md)
- [SetGroups](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetGroups.md)
- [SetInputType](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetInputType.md)
- [SetOrgInputShape](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetOrgInputShape.md)
- [SetOrgWeightShape](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetOrgWeightShape.md)
- [SetOutputType](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetOutputType.md)
- [SetPadding](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetPadding.md)
- [SetSingleOutputShape](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetSingleOutputShape.md)
- [SetSingleWeightShape](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetSingleWeightShape.md)
- [SetStride](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetStride.md)
- [SetWeightType](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/SetWeightType.md)
- [TConv3DApiTiling结构体](SIMD_API/高阶API/卷积计算/Conv3D/Conv3D_Tiling侧接口/TConv3DApiTiling结构体.md)

##### Conv3DBackpropFilter

###### Conv3DBackpropFilter Kernel侧接口

- [Conv3DBackpropFilter使用说明](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/Conv3DBackpropFilter使用说明.md)
- [End](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/End.md)
- [GetTensorC](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/GetTensorC.md)
- [Init](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/Init.md)
- [Iterate](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/Iterate.md)
- [SetGradOutput](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/SetGradOutput.md)
- [SetInput](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/SetInput.md)
- [SetSingleShape](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/SetSingleShape.md)
- [SetStartPosition](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Kernel侧接口/SetStartPosition.md)

###### Conv3DBackpropFilter Tiling侧接口

- [Conv3DBackpropFilter Tiling使用说明](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/Conv3DBackpropFilter_Tiling使用说明.md)
- [Conv3DBackpropFilter Tiling构造函数](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/Conv3DBackpropFilter_Tiling构造函数.md)
- [GetTiling](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/GetTiling.md)
- [SetDilation](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetDilation.md)
- [SetGradOutputShape](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetGradOutputShape.md)
- [SetGradOutputType](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetGradOutputType.md)
- [SetInputShape](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetInputShape.md)
- [SetInputType](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetInputType.md)
- [SetPadding](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetPadding.md)
- [SetStride](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetStride.md)
- [SetWeightShape](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetWeightShape.md)
- [SetWeightType](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/SetWeightType.md)
- [TConv3DBpFilterTiling结构体](SIMD_API/高阶API/卷积计算/Conv3DBackpropFilter/Conv3DBackpropFilter_Tiling侧接口/TConv3DBpFilterTiling结构体.md)

##### Conv3DBackpropInput

###### Conv3DBackpropInput Kernel侧接口

- [Conv3DBackpropInput使用说明](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/Conv3DBackpropInput使用说明.md)
- [End](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/End.md)
- [GetTensorC](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/GetTensorC.md)
- [Init](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/Init.md)
- [Iterate](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/Iterate.md)
- [SetGradOutput](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/SetGradOutput.md)
- [SetSingleShape](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/SetSingleShape.md)
- [SetStartPosition](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/SetStartPosition.md)
- [SetWeight](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Kernel侧接口/SetWeight.md)

###### Conv3DBackpropInput Tiling侧接口

- [Conv3DBackpropInput Tiling使用说明](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/Conv3DBackpropInput_Tiling使用说明.md)
- [Conv3DBackpropInput Tiling构造函数](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/Conv3DBackpropInput_Tiling构造函数.md)
- [GetTiling](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/GetTiling.md)
- [SetDilation](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetDilation.md)
- [SetGradOutputShape](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetGradOutputShape.md)
- [SetGradOutputType](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetGradOutputType.md)
- [SetInputShape](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetInputShape.md)
- [SetInputType](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetInputType.md)
- [SetOutputPadding](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetOutputPadding.md)
- [SetPadding](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetPadding.md)
- [SetStride](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetStride.md)
- [SetWeightShape](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetWeightShape.md)
- [SetWeightType](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/SetWeightType.md)
- [TConv3DBackpropInputTiling结构体](SIMD_API/高阶API/卷积计算/Conv3DBackpropInput/Conv3DBackpropInput_Tiling侧接口/TConv3DBackpropInputTiling结构体.md)

#### 张量变换

- [Broadcast](SIMD_API/高阶API/张量变换/Broadcast.md)
- [Fill](SIMD_API/高阶API/张量变换/Fill.md)
- [GetBroadCastMaxMinTmpSize](SIMD_API/高阶API/张量变换/GetBroadCastMaxMinTmpSize.md)
- [GetTransDataMaxMinTmpSize](SIMD_API/高阶API/张量变换/GetTransDataMaxMinTmpSize.md)
- [Pad](SIMD_API/高阶API/张量变换/Pad.md)
- [Pad Tiling](SIMD_API/高阶API/张量变换/Pad_Tiling.md)
- [TransData](SIMD_API/高阶API/张量变换/TransData.md)
- [Transpose](SIMD_API/高阶API/张量变换/Transpose.md)
- [Transpose Tiling](SIMD_API/高阶API/张量变换/Transpose_Tiling.md)
- [UnPad](SIMD_API/高阶API/张量变换/UnPad.md)
- [UnPad Tiling](SIMD_API/高阶API/张量变换/UnPad_Tiling.md)

#### 归一化操作

- [BatchNorm](SIMD_API/高阶API/归一化操作/BatchNorm.md)
- [BatchNorm Tiling](SIMD_API/高阶API/归一化操作/BatchNorm_Tiling.md)
- [DeepNorm](SIMD_API/高阶API/归一化操作/DeepNorm.md)
- [DeepNorm Tiling](SIMD_API/高阶API/归一化操作/DeepNorm_Tiling.md)
- [GroupNorm](SIMD_API/高阶API/归一化操作/GroupNorm.md)
- [GroupNorm Tiling](SIMD_API/高阶API/归一化操作/GroupNorm_Tiling.md)
- [LayerNorm](SIMD_API/高阶API/归一化操作/LayerNorm.md)
- [LayerNorm Tiling](SIMD_API/高阶API/归一化操作/LayerNorm_Tiling.md)
- [LayerNormGrad](SIMD_API/高阶API/归一化操作/LayerNormGrad.md)
- [LayerNormGrad Tiling](SIMD_API/高阶API/归一化操作/LayerNormGrad_Tiling.md)
- [LayerNormGradBeta](SIMD_API/高阶API/归一化操作/LayerNormGradBeta.md)
- [LayerNormGradBeta Tiling](SIMD_API/高阶API/归一化操作/LayerNormGradBeta_Tiling.md)
- [Normalize](SIMD_API/高阶API/归一化操作/Normalize.md)
- [Normalize Tiling](SIMD_API/高阶API/归一化操作/Normalize_Tiling.md)
- [RmsNorm](SIMD_API/高阶API/归一化操作/RmsNorm.md)
- [RmsNorm Tiling](SIMD_API/高阶API/归一化操作/RmsNorm_Tiling.md)
- [WelfordFinalize](SIMD_API/高阶API/归一化操作/WelfordFinalize.md)
- [WelfordFinalize Tiling](SIMD_API/高阶API/归一化操作/WelfordFinalize_Tiling.md)
- [WelfordUpdate](SIMD_API/高阶API/归一化操作/WelfordUpdate.md)
- [WelfordUpdate Tiling](SIMD_API/高阶API/归一化操作/WelfordUpdate_Tiling.md)

#### 归约操作

##### Mean接口

- [GetMeanMaxMinTmpSize](SIMD_API/高阶API/归约操作/Mean接口/GetMeanMaxMinTmpSize.md)
- [GetMeanTmpBufferFactorSize](SIMD_API/高阶API/归约操作/Mean接口/GetMeanTmpBufferFactorSize.md)
- [Mean](SIMD_API/高阶API/归约操作/Mean接口/Mean.md)

##### ReduceAll接口

- [GetReduceAllMaxMinTmpSize](SIMD_API/高阶API/归约操作/ReduceAll接口/GetReduceAllMaxMinTmpSize.md)
- [ReduceAll](SIMD_API/高阶API/归约操作/ReduceAll接口/ReduceAll.md)

##### ReduceAny接口

- [GetReduceAnyMaxMinTmpSize](SIMD_API/高阶API/归约操作/ReduceAny接口/GetReduceAnyMaxMinTmpSize.md)
- [ReduceAny](SIMD_API/高阶API/归约操作/ReduceAny接口/ReduceAny.md)

##### ReduceMax接口

- [GetReduceMaxMaxMinTmpSize](SIMD_API/高阶API/归约操作/ReduceMax接口/GetReduceMaxMaxMinTmpSize.md)
- [ReduceMax](SIMD_API/高阶API/归约操作/ReduceMax接口/ReduceMax.md)

##### ReduceMean接口

- [GetReduceMeanMaxMinTmpSize](SIMD_API/高阶API/归约操作/ReduceMean接口/GetReduceMeanMaxMinTmpSize.md)
- [ReduceMean](SIMD_API/高阶API/归约操作/ReduceMean接口/ReduceMean.md)

##### ReduceMin接口

- [GetReduceMinMaxMinTmpSize](SIMD_API/高阶API/归约操作/ReduceMin接口/GetReduceMinMaxMinTmpSize.md)
- [ReduceMin](SIMD_API/高阶API/归约操作/ReduceMin接口/ReduceMin.md)

##### ReduceProd接口

- [GetReduceProdMaxMinTmpSize](SIMD_API/高阶API/归约操作/ReduceProd接口/GetReduceProdMaxMinTmpSize.md)
- [ReduceProd](SIMD_API/高阶API/归约操作/ReduceProd接口/ReduceProd.md)

##### ReduceSum接口

- [GetReduceSumMaxMinTmpSize](SIMD_API/高阶API/归约操作/ReduceSum接口/GetReduceSumMaxMinTmpSize.md)
- [ReduceSum](SIMD_API/高阶API/归约操作/ReduceSum接口/ReduceSum.md)

##### ReduceXorSum接口

- [GetReduceXorSumMaxMinTmpSize](SIMD_API/高阶API/归约操作/ReduceXorSum接口/GetReduceXorSumMaxMinTmpSize.md)
- [ReduceXorSum](SIMD_API/高阶API/归约操作/ReduceXorSum接口/ReduceXorSum.md)

##### Sum接口

- [GetSumMaxMinTmpSize](SIMD_API/高阶API/归约操作/Sum接口/GetSumMaxMinTmpSize.md)
- [Sum](SIMD_API/高阶API/归约操作/Sum接口/Sum.md)

#### 排序操作

- [Concat](SIMD_API/高阶API/排序操作/Concat.md)
- [Extract](SIMD_API/高阶API/排序操作/Extract.md)
- [GetConcatTmpSize](SIMD_API/高阶API/排序操作/GetConcatTmpSize.md)
- [GetSortLen](SIMD_API/高阶API/排序操作/GetSortLen.md)
- [GetSortMaxMinTmpSize](SIMD_API/高阶API/排序操作/GetSortMaxMinTmpSize.md)
- [GetSortOffset](SIMD_API/高阶API/排序操作/GetSortOffset.md)
- [GetSortTmpSize](SIMD_API/高阶API/排序操作/GetSortTmpSize.md)
- [MrgSort](SIMD_API/高阶API/排序操作/MrgSort.md)
- [Sort](SIMD_API/高阶API/排序操作/Sort.md)
- [TopK](SIMD_API/高阶API/排序操作/TopK.md)
- [TopK Tiling](SIMD_API/高阶API/排序操作/TopK_Tiling.md)

#### 数学计算

##### Acosh接口

- [Acosh](SIMD_API/高阶API/数学计算/Acosh接口/Acosh.md)
- [GetAcoshMaxMinTmpSize](SIMD_API/高阶API/数学计算/Acosh接口/GetAcoshMaxMinTmpSize.md)
- [GetAcoshTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Acosh接口/GetAcoshTmpBufferFactorSize.md)

##### Acos接口

- [Acos](SIMD_API/高阶API/数学计算/Acos接口/Acos.md)
- [GetAcosMaxMinTmpSize](SIMD_API/高阶API/数学计算/Acos接口/GetAcosMaxMinTmpSize.md)
- [GetAcosTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Acos接口/GetAcosTmpBufferFactorSize.md)

##### Asinh接口

- [Asinh](SIMD_API/高阶API/数学计算/Asinh接口/Asinh.md)
- [GetAsinhMaxMinTmpSize](SIMD_API/高阶API/数学计算/Asinh接口/GetAsinhMaxMinTmpSize.md)
- [GetAsinhTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Asinh接口/GetAsinhTmpBufferFactorSize.md)

##### Asin接口

- [Asin](SIMD_API/高阶API/数学计算/Asin接口/Asin.md)
- [GetAsinMaxMinTmpSize](SIMD_API/高阶API/数学计算/Asin接口/GetAsinMaxMinTmpSize.md)
- [GetAsinTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Asin接口/GetAsinTmpBufferFactorSize.md)

##### Atanh接口

- [Atanh](SIMD_API/高阶API/数学计算/Atanh接口/Atanh.md)
- [GetAtanhMaxMinTmpSize](SIMD_API/高阶API/数学计算/Atanh接口/GetAtanhMaxMinTmpSize.md)
- [GetAtanhTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Atanh接口/GetAtanhTmpBufferFactorSize.md)

##### Atan接口

- [Atan](SIMD_API/高阶API/数学计算/Atan接口/Atan.md)
- [GetAtanMaxMinTmpSize](SIMD_API/高阶API/数学计算/Atan接口/GetAtanMaxMinTmpSize.md)
- [GetAtanTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Atan接口/GetAtanTmpBufferFactorSize.md)

##### Axpy接口

- [Axpy](SIMD_API/高阶API/数学计算/Axpy接口/Axpy.md)
- [GetAxpyMaxMinTmpSize](SIMD_API/高阶API/数学计算/Axpy接口/GetAxpyMaxMinTmpSize.md)
- [GetAxpyTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Axpy接口/GetAxpyTmpBufferFactorSize.md)

##### BitwiseAnd接口

- [BitwiseAnd](SIMD_API/高阶API/数学计算/BitwiseAnd接口/BitwiseAnd.md)
- [GetBitwiseAndMaxMinTmpSize](SIMD_API/高阶API/数学计算/BitwiseAnd接口/GetBitwiseAndMaxMinTmpSize.md)
- [GetBitwiseAndTmpBufferFactorSize](SIMD_API/高阶API/数学计算/BitwiseAnd接口/GetBitwiseAndTmpBufferFactorSize.md)
- [LogicalNot](SIMD_API/高阶API/数学计算/BitwiseAnd接口/LogicalNot.md)

##### BitwiseNot接口

- [BitwiseNot](SIMD_API/高阶API/数学计算/BitwiseNot接口/BitwiseNot.md)
- [GetBitwiseNotMaxMinTmpSize](SIMD_API/高阶API/数学计算/BitwiseNot接口/GetBitwiseNotMaxMinTmpSize.md)
- [GetBitwiseNotTmpBufferFactorSize](SIMD_API/高阶API/数学计算/BitwiseNot接口/GetBitwiseNotTmpBufferFactorSize.md)

##### BitwiseOr接口

- [BitwiseOr](SIMD_API/高阶API/数学计算/BitwiseOr接口/BitwiseOr.md)
- [GetBitwiseOrMaxMinTmpSize](SIMD_API/高阶API/数学计算/BitwiseOr接口/GetBitwiseOrMaxMinTmpSize.md)
- [GetBitwiseOrTmpBufferFactorSize](SIMD_API/高阶API/数学计算/BitwiseOr接口/GetBitwiseOrTmpBufferFactorSize.md)

##### BitwiseXor接口

- [BitwiseXor](SIMD_API/高阶API/数学计算/BitwiseXor接口/BitwiseXor.md)
- [GetBitwiseXorMaxMinTmpSize](SIMD_API/高阶API/数学计算/BitwiseXor接口/GetBitwiseXorMaxMinTmpSize.md)
- [GetBitwiseXorTmpBufferFactorSize](SIMD_API/高阶API/数学计算/BitwiseXor接口/GetBitwiseXorTmpBufferFactorSize.md)

##### Ceil接口

- [Ceil](SIMD_API/高阶API/数学计算/Ceil接口/Ceil.md)
- [GetCeilMaxMinTmpSize](SIMD_API/高阶API/数学计算/Ceil接口/GetCeilMaxMinTmpSize.md)
- [GetCeilTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Ceil接口/GetCeilTmpBufferFactorSize.md)

##### Clamp接口

- [Clamp](SIMD_API/高阶API/数学计算/Clamp接口/Clamp.md)
- [ClampMax](SIMD_API/高阶API/数学计算/Clamp接口/ClampMax.md)
- [ClampMin](SIMD_API/高阶API/数学计算/Clamp接口/ClampMin.md)
- [GetClampMaxMinTmpSize](SIMD_API/高阶API/数学计算/Clamp接口/GetClampMaxMinTmpSize.md)
- [GetClampTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Clamp接口/GetClampTmpBufferFactorSize.md)

##### Cosh接口

- [Cosh](SIMD_API/高阶API/数学计算/Cosh接口/Cosh.md)
- [GetCoshMaxMinTmpSize](SIMD_API/高阶API/数学计算/Cosh接口/GetCoshMaxMinTmpSize.md)
- [GetCoshTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Cosh接口/GetCoshTmpBufferFactorSize.md)

##### Cos接口

- [Cos](SIMD_API/高阶API/数学计算/Cos接口/Cos.md)
- [GetCosMaxMinTmpSize](SIMD_API/高阶API/数学计算/Cos接口/GetCosMaxMinTmpSize.md)
- [GetCosTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Cos接口/GetCosTmpBufferFactorSize.md)

##### CumSum接口

- [CumSum](SIMD_API/高阶API/数学计算/CumSum接口/CumSum.md)
- [GetCumSumMaxMinTmpSize](SIMD_API/高阶API/数学计算/CumSum接口/GetCumSumMaxMinTmpSize.md)

##### Digamma接口

- [Digamma](SIMD_API/高阶API/数学计算/Digamma接口/Digamma.md)
- [GetDigammaMaxMinTmpSize](SIMD_API/高阶API/数学计算/Digamma接口/GetDigammaMaxMinTmpSize.md)
- [GetDigammaTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Digamma接口/GetDigammaTmpBufferFactorSize.md)

##### Erfc接口

- [Erfc](SIMD_API/高阶API/数学计算/Erfc接口/Erfc.md)
- [GetErfcMaxMinTmpSize](SIMD_API/高阶API/数学计算/Erfc接口/GetErfcMaxMinTmpSize.md)
- [GetErfcTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Erfc接口/GetErfcTmpBufferFactorSize.md)

##### Erf接口

- [Erf](SIMD_API/高阶API/数学计算/Erf接口/Erf.md)
- [GetErfMaxMinTmpSize](SIMD_API/高阶API/数学计算/Erf接口/GetErfMaxMinTmpSize.md)
- [GetErfTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Erf接口/GetErfTmpBufferFactorSize.md)

##### Exp接口

- [Exp](SIMD_API/高阶API/数学计算/Exp接口/Exp.md)
- [GetExpMaxMinTmpSize](SIMD_API/高阶API/数学计算/Exp接口/GetExpMaxMinTmpSize.md)
- [GetExpTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Exp接口/GetExpTmpBufferFactorSize.md)

##### Floor接口

- [Floor](SIMD_API/高阶API/数学计算/Floor接口/Floor.md)
- [GetFloorMaxMinTmpSize](SIMD_API/高阶API/数学计算/Floor接口/GetFloorMaxMinTmpSize.md)
- [GetFloorTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Floor接口/GetFloorTmpBufferFactorSize.md)

##### Fma接口

- [Fma](SIMD_API/高阶API/数学计算/Fma接口/Fma.md)
- [GetFmaMaxMinTmpSize](SIMD_API/高阶API/数学计算/Fma接口/GetFmaMaxMinTmpSize.md)
- [GetFmaTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Fma接口/GetFmaTmpBufferFactorSize.md)

##### Fmod接口

- [Fmod](SIMD_API/高阶API/数学计算/Fmod接口/Fmod.md)
- [GetFmodMaxMinTmpSize](SIMD_API/高阶API/数学计算/Fmod接口/GetFmodMaxMinTmpSize.md)
- [GetFmodTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Fmod接口/GetFmodTmpBufferFactorSize.md)

##### Frac接口

- [Frac](SIMD_API/高阶API/数学计算/Frac接口/Frac.md)
- [GetFracMaxMinTmpSize](SIMD_API/高阶API/数学计算/Frac接口/GetFracMaxMinTmpSize.md)
- [GetFracTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Frac接口/GetFracTmpBufferFactorSize.md)

##### Hypot接口

- [GetHypotMaxMinTmpSize](SIMD_API/高阶API/数学计算/Hypot接口/GetHypotMaxMinTmpSize.md)
- [GetHypotTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Hypot接口/GetHypotTmpBufferFactorSize.md)
- [Hypot](SIMD_API/高阶API/数学计算/Hypot接口/Hypot.md)

##### IsFinite接口

- [IsFinite](SIMD_API/高阶API/数学计算/IsFinite接口/IsFinite.md)

##### IsInf接口

- [GetIsInfMaxMinTmpSize](SIMD_API/高阶API/数学计算/IsInf接口/GetIsInfMaxMinTmpSize.md)
- [GetIsInfTmpBufferFactorSize](SIMD_API/高阶API/数学计算/IsInf接口/GetIsInfTmpBufferFactorSize.md)
- [IsInf](SIMD_API/高阶API/数学计算/IsInf接口/IsInf.md)

##### IsNan接口

- [GetIsNanMaxMinTmpSize](SIMD_API/高阶API/数学计算/IsNan接口/GetIsNanMaxMinTmpSize.md)
- [GetIsNanTmpBufferFactorSize](SIMD_API/高阶API/数学计算/IsNan接口/GetIsNanTmpBufferFactorSize.md)
- [IsNan](SIMD_API/高阶API/数学计算/IsNan接口/IsNan.md)

##### Lgamma接口

- [GetLgammaMaxMinTmpSize](SIMD_API/高阶API/数学计算/Lgamma接口/GetLgammaMaxMinTmpSize.md)
- [GetLgammaTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Lgamma接口/GetLgammaTmpBufferFactorSize.md)
- [Lgamma](SIMD_API/高阶API/数学计算/Lgamma接口/Lgamma.md)

##### LogicalAnds接口

- [GetLogicalAndsMaxMinTmpSize](SIMD_API/高阶API/数学计算/LogicalAnds接口/GetLogicalAndsMaxMinTmpSize.md)
- [GetLogicalAndsTmpBufferFactorSize](SIMD_API/高阶API/数学计算/LogicalAnds接口/GetLogicalAndsTmpBufferFactorSize.md)
- [LogicalAnds](SIMD_API/高阶API/数学计算/LogicalAnds接口/LogicalAnds.md)

##### LogicalAnd接口

- [GetLogicalAndMaxMinTmpSize](SIMD_API/高阶API/数学计算/LogicalAnd接口/GetLogicalAndMaxMinTmpSize.md)
- [GetLogicalAndTmpBufferFactorSize](SIMD_API/高阶API/数学计算/LogicalAnd接口/GetLogicalAndTmpBufferFactorSize.md)
- [LogicalAnd](SIMD_API/高阶API/数学计算/LogicalAnd接口/LogicalAnd.md)

##### LogicalNot接口

- [GetLogicalNotMaxMinTmpSize](SIMD_API/高阶API/数学计算/LogicalNot接口/GetLogicalNotMaxMinTmpSize.md)
- [GetLogicalNotTmpBufferFactorSize](SIMD_API/高阶API/数学计算/LogicalNot接口/GetLogicalNotTmpBufferFactorSize.md)

##### LogicalOrs接口

- [GetLogicalOrsMaxMinTmpSize](SIMD_API/高阶API/数学计算/LogicalOrs接口/GetLogicalOrsMaxMinTmpSize.md)
- [GetLogicalOrsTmpBufferFactorSize](SIMD_API/高阶API/数学计算/LogicalOrs接口/GetLogicalOrsTmpBufferFactorSize.md)
- [LogicalOrs](SIMD_API/高阶API/数学计算/LogicalOrs接口/LogicalOrs.md)

##### LogicalOr接口

- [GetLogicalOrMaxMinTmpSize](SIMD_API/高阶API/数学计算/LogicalOr接口/GetLogicalOrMaxMinTmpSize.md)
- [GetLogicalOrTmpBufferFactorSize](SIMD_API/高阶API/数学计算/LogicalOr接口/GetLogicalOrTmpBufferFactorSize.md)
- [LogicalOr](SIMD_API/高阶API/数学计算/LogicalOr接口/LogicalOr.md)

##### LogicalXor接口

- [GetLogicalXorMaxMinTmpSize](SIMD_API/高阶API/数学计算/LogicalXor接口/GetLogicalXorMaxMinTmpSize.md)
- [GetLogicalXorTmpBufferFactorSize](SIMD_API/高阶API/数学计算/LogicalXor接口/GetLogicalXorTmpBufferFactorSize.md)
- [LogicalXor](SIMD_API/高阶API/数学计算/LogicalXor接口/LogicalXor.md)

##### Log接口

- [GetLogMaxMinTmpSize](SIMD_API/高阶API/数学计算/Log接口/GetLogMaxMinTmpSize.md)
- [GetLogTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Log接口/GetLogTmpBufferFactorSize.md)
- [Log](SIMD_API/高阶API/数学计算/Log接口/Log.md)

##### Power接口

- [GetPowerMaxMinTmpSize](SIMD_API/高阶API/数学计算/Power接口/GetPowerMaxMinTmpSize.md)
- [GetPowerTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Power接口/GetPowerTmpBufferFactorSize.md)
- [Power](SIMD_API/高阶API/数学计算/Power接口/Power.md)

##### Rint接口

- [GetRintMaxMinTmpSize](SIMD_API/高阶API/数学计算/Rint接口/GetRintMaxMinTmpSize.md)
- [GetRintTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Rint接口/GetRintTmpBufferFactorSize.md)
- [Rint](SIMD_API/高阶API/数学计算/Rint接口/Rint.md)

##### Round接口

- [GetRoundMaxMinTmpSize](SIMD_API/高阶API/数学计算/Round接口/GetRoundMaxMinTmpSize.md)
- [GetRoundTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Round接口/GetRoundTmpBufferFactorSize.md)
- [Round](SIMD_API/高阶API/数学计算/Round接口/Round.md)

##### Sign接口

- [GetSignMaxMinTmpSize](SIMD_API/高阶API/数学计算/Sign接口/GetSignMaxMinTmpSize.md)
- [GetSignTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Sign接口/GetSignTmpBufferFactorSize.md)
- [Sign](SIMD_API/高阶API/数学计算/Sign接口/Sign.md)

##### SinCos接口

- [GetSinCosMaxMinTmpSize](SIMD_API/高阶API/数学计算/SinCos接口/GetSinCosMaxMinTmpSize.md)
- [GetSinCosTmpBufferFactorSize](SIMD_API/高阶API/数学计算/SinCos接口/GetSinCosTmpBufferFactorSize.md)
- [SinCos](SIMD_API/高阶API/数学计算/SinCos接口/SinCos.md)

##### Sinh接口

- [GetSinhMaxMinTmpSize](SIMD_API/高阶API/数学计算/Sinh接口/GetSinhMaxMinTmpSize.md)
- [GetSinhTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Sinh接口/GetSinhTmpBufferFactorSize.md)
- [Sinh](SIMD_API/高阶API/数学计算/Sinh接口/Sinh.md)

##### Sin接口

- [GetSinMaxMinTmpSize](SIMD_API/高阶API/数学计算/Sin接口/GetSinMaxMinTmpSize.md)
- [GetSinTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Sin接口/GetSinTmpBufferFactorSize.md)
- [Sin](SIMD_API/高阶API/数学计算/Sin接口/Sin.md)

##### Tanh接口

- [GetTanhMaxMinTmpSize](SIMD_API/高阶API/数学计算/Tanh接口/GetTanhMaxMinTmpSize.md)
- [GetTanhTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Tanh接口/GetTanhTmpBufferFactorSize.md)
- [Tanh](SIMD_API/高阶API/数学计算/Tanh接口/Tanh.md)

##### Tan接口

- [GetTanMaxMinTmpSize](SIMD_API/高阶API/数学计算/Tan接口/GetTanMaxMinTmpSize.md)
- [GetTanTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Tan接口/GetTanTmpBufferFactorSize.md)
- [Tan](SIMD_API/高阶API/数学计算/Tan接口/Tan.md)

##### Trunc接口

- [GetTruncMaxMinTmpSize](SIMD_API/高阶API/数学计算/Trunc接口/GetTruncMaxMinTmpSize.md)
- [GetTruncTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Trunc接口/GetTruncTmpBufferFactorSize.md)
- [Trunc](SIMD_API/高阶API/数学计算/Trunc接口/Trunc.md)

##### Where接口

- [GetWhereMaxMinTmpSize](SIMD_API/高阶API/数学计算/Where接口/GetWhereMaxMinTmpSize.md)
- [GetWhereTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Where接口/GetWhereTmpBufferFactorSize.md)
- [Where](SIMD_API/高阶API/数学计算/Where接口/Where.md)

##### Xor接口

- [GetXorMaxMinTmpSize](SIMD_API/高阶API/数学计算/Xor接口/GetXorMaxMinTmpSize.md)
- [GetXorTmpBufferFactorSize](SIMD_API/高阶API/数学计算/Xor接口/GetXorTmpBufferFactorSize.md)
- [Xor](SIMD_API/高阶API/数学计算/Xor接口/Xor.md)

- [更多样例](SIMD_API/高阶API/数学计算/更多样例.md)

#### 数据过滤

- [DropOut](SIMD_API/高阶API/数据过滤/DropOut.md)
- [GetDropOutMaxMinTmpSize](SIMD_API/高阶API/数据过滤/GetDropOutMaxMinTmpSize.md)
- [GetSelectMaxMinTmpSize](SIMD_API/高阶API/数据过滤/GetSelectMaxMinTmpSize.md)
- [Select](SIMD_API/高阶API/数据过滤/Select.md)

#### 激活函数

##### GeGLU接口

- [GeGLU](SIMD_API/高阶API/激活函数/GeGLU接口/GeGLU.md)
- [GetGeGLUMaxMinTmpSize](SIMD_API/高阶API/激活函数/GeGLU接口/GetGeGLUMaxMinTmpSize.md)
- [GetGeGLUTmpBufferFactorSize](SIMD_API/高阶API/激活函数/GeGLU接口/GetGeGLUTmpBufferFactorSize.md)

##### Gelu接口

- [FasterGelu](SIMD_API/高阶API/激活函数/Gelu接口/FasterGelu.md)
- [FasterGeluV2](SIMD_API/高阶API/激活函数/Gelu接口/FasterGeluV2.md)
- [Gelu](SIMD_API/高阶API/激活函数/Gelu接口/Gelu.md)
- [GetGeluMaxMinTmpSize](SIMD_API/高阶API/激活函数/Gelu接口/GetGeluMaxMinTmpSize.md)

##### LogSoftMax接口

- [LogSoftMax](SIMD_API/高阶API/激活函数/LogSoftMax接口/LogSoftMax.md)
- [LogSoftMax Tiling](SIMD_API/高阶API/激活函数/LogSoftMax接口/LogSoftMax_Tiling.md)

##### ReGlu接口

- [GetReGluMaxMinTmpSize](SIMD_API/高阶API/激活函数/ReGlu接口/GetReGluMaxMinTmpSize.md)
- [ReGlu](SIMD_API/高阶API/激活函数/ReGlu接口/ReGlu.md)

##### Sigmoid接口

- [GetSigmoidMaxMinTmpSize](SIMD_API/高阶API/激活函数/Sigmoid接口/GetSigmoidMaxMinTmpSize.md)
- [Sigmoid](SIMD_API/高阶API/激活函数/Sigmoid接口/Sigmoid.md)

##### Silu接口

- [GetSiluTmpSize](SIMD_API/高阶API/激活函数/Silu接口/GetSiluTmpSize.md)
- [Silu](SIMD_API/高阶API/激活函数/Silu接口/Silu.md)

##### SoftMax接口

- [AdjustSoftMaxRes](SIMD_API/高阶API/激活函数/SoftMax接口/AdjustSoftMaxRes.md)
- [IsBasicBlockInSoftMax](SIMD_API/高阶API/激活函数/SoftMax接口/IsBasicBlockInSoftMax.md)
- [SimpleSoftMax](SIMD_API/高阶API/激活函数/SoftMax接口/SimpleSoftMax.md)
- [SoftMax](SIMD_API/高阶API/激活函数/SoftMax接口/SoftMax.md)
- [SoftMax Tiling使用说明](SIMD_API/高阶API/激活函数/SoftMax接口/SoftMax_Tiling使用说明.md)
- [SoftMax/SimpleSoftMax Tiling](SIMD_API/高阶API/激活函数/SoftMax接口/SoftMax_SimpleSoftMax_Tiling.md)
- [SoftmaxFlash](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxFlash.md)
- [SoftmaxFlash Tiling接口](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxFlash_Tiling接口.md)
- [SoftmaxFlashV2](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxFlashV2.md)
- [SoftmaxFlashV2 Tiling接口](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxFlashV2_Tiling接口.md)
- [SoftmaxFlashV3](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxFlashV3.md)
- [SoftmaxFlashV3 Tiling接口](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxFlashV3_Tiling接口.md)
- [SoftmaxGrad](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxGrad.md)
- [SoftmaxGrad Tiling接口](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxGrad_Tiling接口.md)
- [SoftmaxGradFront](SIMD_API/高阶API/激活函数/SoftMax接口/SoftmaxGradFront.md)

##### SwiGLU接口

- [GetSwiGLUMaxMinTmpSize](SIMD_API/高阶API/激活函数/SwiGLU接口/GetSwiGLUMaxMinTmpSize.md)
- [GetSwiGLUTmpBufferFactorSize](SIMD_API/高阶API/激活函数/SwiGLU接口/GetSwiGLUTmpBufferFactorSize.md)
- [SwiGLU](SIMD_API/高阶API/激活函数/SwiGLU接口/SwiGLU.md)

##### Swish接口

- [GetSwishTmpSize](SIMD_API/高阶API/激活函数/Swish接口/GetSwishTmpSize.md)
- [Swish](SIMD_API/高阶API/激活函数/Swish接口/Swish.md)

#### 矩阵计算

##### Matmul Kernel侧接口

- [AsyncGetTensorC](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/AsyncGetTensorC.md)
- [ClearBias](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/ClearBias.md)
- [DisableBias](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/DisableBias.md)
- [End](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/End.md)
- [GetBasicConfig](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetBasicConfig.md)
- [GetBatchC](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetBatchC.md)
- [GetBatchTensorC](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetBatchTensorC.md)
- [GetIBShareNormConfig](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetIBShareNormConfig.md)
- [GetMDLConfig](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetMDLConfig.md)
- [GetMMConfig](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetMMConfig.md)
- [GetMatmulApiTiling](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetMatmulApiTiling.md)
- [GetNormalConfig](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetNormalConfig.md)
- [GetOffsetC](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetOffsetC.md)
- [GetSpecialMDLConfig](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetSpecialMDLConfig.md)
- [GetSubBlockIdx](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetSubBlockIdx.md)
- [GetTensorC](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/GetTensorC.md)
- [Init](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/Init.md)
- [Iterate](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/Iterate.md)
- [IterateAll](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/IterateAll.md)
- [IterateBatch](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/IterateBatch.md)
- [IterateNBatch](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/IterateNBatch.md)
- [MatmulCallBackFunc](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/MatmulCallBackFunc.md)
- [MatmulConfig](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/MatmulConfig.md)
- [MatmulPolicy](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/MatmulPolicy.md)
- [Matmul使用说明](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/Matmul使用说明.md)
- [Matmul模板参数](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/Matmul模板参数.md)
- [Matmul特性场景](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/Matmul特性场景.md)
- [REGIST_MATMUL_OBJ](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/REGIST_MATMUL_OBJ.md)
- [SetAntiQuantScalar](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetAntiQuantScalar.md)
- [SetAntiQuantVector](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetAntiQuantVector.md)
- [SetBatchNum](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetBatchNum.md)
- [SetBias](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetBias.md)
- [SetHF32](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetHF32.md)
- [SetLocalWorkspace](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetLocalWorkspace.md)
- [SetOrgShape](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetOrgShape.md)
- [SetQuantScalar](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetQuantScalar.md)
- [SetQuantVector](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetQuantVector.md)
- [SetSelfDefineData](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetSelfDefineData.md)
- [SetSingleShape](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetSingleShape.md)
- [SetSparseIndex](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetSparseIndex.md)
- [SetSubBlockIdx](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetSubBlockIdx.md)
- [SetTail](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetTail.md)
- [SetTensorA](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetTensorA.md)
- [SetTensorB](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetTensorB.md)
- [SetTensorScaleA](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetTensorScaleA.md)
- [SetTensorScaleB](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetTensorScaleB.md)
- [SetUserDefInfo](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetUserDefInfo.md)
- [SetWorkspace](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/SetWorkspace.md)
- [WaitGetTensorC](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/WaitGetTensorC.md)
- [WaitIterateAll](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/WaitIterateAll.md)
- [WaitIterateBatch](SIMD_API/高阶API/矩阵计算/Matmul_Kernel侧接口/WaitIterateBatch.md)

##### Matmul Tiling侧接口

###### Matmul Tiling类

- [EnableBias](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/EnableBias.md)
- [EnableL1BankConflictOptimise](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/EnableL1BankConflictOptimise.md)
- [EnableMultiCoreSplitK](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/EnableMultiCoreSplitK.md)
- [GetBaseK](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/GetBaseK.md)
- [GetBaseM](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/GetBaseM.md)
- [GetBaseN](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/GetBaseN.md)
- [GetCoreNum](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/GetCoreNum.md)
- [GetSingleShape](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/GetSingleShape.md)
- [GetTiling](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/GetTiling.md)
- [Matmul Tiling类使用说明](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/Matmul_Tiling类使用说明.md)
- [Matmul Tiling类构造函数](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/Matmul_Tiling类构造函数.md)
- [SetALayout](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetALayout.md)
- [SetAType](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetAType.md)
- [SetAlignSplit](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetAlignSplit.md)
- [SetBLayout](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetBLayout.md)
- [SetBType](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetBType.md)
- [SetBatchInfoForNormal](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetBatchInfoForNormal.md)
- [SetBatchNum](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetBatchNum.md)
- [SetBias](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetBias.md)
- [SetBiasType](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetBiasType.md)
- [SetBufferSpace](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetBufferSpace.md)
- [SetCLayout](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetCLayout.md)
- [SetCType](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetCType.md)
- [SetDequantType](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetDequantType.md)
- [SetDim](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetDim.md)
- [SetDoubleBuffer](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetDoubleBuffer.md)
- [SetFixSplit](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetFixSplit.md)
- [SetMadType](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetMadType.md)
- [SetMatmulConfigParams](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetMatmulConfigParams.md)
- [SetOrgShape](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetOrgShape.md)
- [SetScaleAType](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetScaleAType.md)
- [SetScaleBType](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetScaleBType.md)
- [SetShape](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetShape.md)
- [SetSingleRange](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetSingleRange.md)
- [SetSingleShape](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetSingleShape.md)
- [SetSparse](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetSparse.md)
- [SetSplitK](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetSplitK.md)
- [SetSplitRange](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetSplitRange.md)
- [SetTraverse](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/SetTraverse.md)
- [TCubeTiling结构体](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/Matmul_Tiling类/TCubeTiling结构体.md)

###### 获取Matmul计算所需空间

- [BatchMatmulGetTmpBufSize](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/获取Matmul计算所需空间/BatchMatmulGetTmpBufSize.md)
- [BatchMatmulGetTmpBufSizeV2](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/获取Matmul计算所需空间/BatchMatmulGetTmpBufSizeV2.md)
- [MatmulGetTmpBufSize](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/获取Matmul计算所需空间/MatmulGetTmpBufSize.md)
- [MatmulGetTmpBufSizeV2](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/获取Matmul计算所需空间/MatmulGetTmpBufSizeV2.md)
- [MultiCoreMatmulGetTmpBufSize](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/获取Matmul计算所需空间/MultiCoreMatmulGetTmpBufSize.md)
- [MultiCoreMatmulGetTmpBufSizeV2](SIMD_API/高阶API/矩阵计算/Matmul_Tiling侧接口/获取Matmul计算所需空间/MultiCoreMatmulGetTmpBufSizeV2.md)

#### 索引计算

- [Arange](SIMD_API/高阶API/索引计算/Arange.md)
- [GetArangeMaxMinTmpSize](SIMD_API/高阶API/索引计算/GetArangeMaxMinTmpSize.md)

#### 量化操作

- [AntiQuantize](SIMD_API/高阶API/量化操作/AntiQuantize.md)
- [AscendAntiQuant](SIMD_API/高阶API/量化操作/AscendAntiQuant.md)
- [AscendDequant](SIMD_API/高阶API/量化操作/AscendDequant.md)
- [AscendQuant](SIMD_API/高阶API/量化操作/AscendQuant.md)
- [Dequantize](SIMD_API/高阶API/量化操作/Dequantize.md)
- [GetAntiQuantizeMaxMinTmpSize](SIMD_API/高阶API/量化操作/GetAntiQuantizeMaxMinTmpSize.md)
- [GetAntiQuantizeTmpBufferFactorSize](SIMD_API/高阶API/量化操作/GetAntiQuantizeTmpBufferFactorSize.md)
- [GetAscendAntiQuantMaxMinTmpSize](SIMD_API/高阶API/量化操作/GetAscendAntiQuantMaxMinTmpSize.md)
- [GetAscendAntiQuantTmpBufferFactorSize](SIMD_API/高阶API/量化操作/GetAscendAntiQuantTmpBufferFactorSize.md)
- [GetAscendDequantMaxMinTmpSize](SIMD_API/高阶API/量化操作/GetAscendDequantMaxMinTmpSize.md)
- [GetAscendDequantTmpBufferFactorSize](SIMD_API/高阶API/量化操作/GetAscendDequantTmpBufferFactorSize.md)
- [GetAscendQuantMaxMinTmpSize](SIMD_API/高阶API/量化操作/GetAscendQuantMaxMinTmpSize.md)
- [GetAscendQuantTmpBufferFactorSize](SIMD_API/高阶API/量化操作/GetAscendQuantTmpBufferFactorSize.md)
- [GetDequantizeMaxMinTmpSize](SIMD_API/高阶API/量化操作/GetDequantizeMaxMinTmpSize.md)
- [GetDequantizeTmpBufferFactorSize](SIMD_API/高阶API/量化操作/GetDequantizeTmpBufferFactorSize.md)
- [GetQuantizeMaxMinTmpSize](SIMD_API/高阶API/量化操作/GetQuantizeMaxMinTmpSize.md)
- [GetQuantizeTmpBufferFactorSize](SIMD_API/高阶API/量化操作/GetQuantizeTmpBufferFactorSize.md)
- [Quantize](SIMD_API/高阶API/量化操作/Quantize.md)

#### 随机函数

- [PhiloxRandom](SIMD_API/高阶API/随机函数/PhiloxRandom.md)

- [通用说明和约束](SIMD_API/通用说明和约束.md)

## SIMT API

### Atomic函数

- [asc_atomic_add](SIMT_API/Atomic函数/asc_atomic_add.md)
- [asc_atomic_and](SIMT_API/Atomic函数/asc_atomic_and.md)
- [asc_atomic_cas](SIMT_API/Atomic函数/asc_atomic_cas.md)
- [asc_atomic_dec](SIMT_API/Atomic函数/asc_atomic_dec.md)
- [asc_atomic_exch](SIMT_API/Atomic函数/asc_atomic_exch.md)
- [asc_atomic_inc](SIMT_API/Atomic函数/asc_atomic_inc.md)
- [asc_atomic_max](SIMT_API/Atomic函数/asc_atomic_max.md)
- [asc_atomic_min](SIMT_API/Atomic函数/asc_atomic_min.md)
- [asc_atomic_or](SIMT_API/Atomic函数/asc_atomic_or.md)
- [asc_atomic_sub](SIMT_API/Atomic函数/asc_atomic_sub.md)
- [asc_atomic_xor](SIMT_API/Atomic函数/asc_atomic_xor.md)

### Warp函数

- [asc_activemask](SIMT_API/Warp函数/asc_activemask.md)
- [asc_all](SIMT_API/Warp函数/asc_all.md)
- [asc_any](SIMT_API/Warp函数/asc_any.md)
- [asc_ballot](SIMT_API/Warp函数/asc_ballot.md)
- [asc_reduce_add](SIMT_API/Warp函数/asc_reduce_add.md)
- [asc_reduce_max](SIMT_API/Warp函数/asc_reduce_max.md)
- [asc_reduce_min](SIMT_API/Warp函数/asc_reduce_min.md)
- [asc_shfl](SIMT_API/Warp函数/asc_shfl.md)
- [asc_shfl_down](SIMT_API/Warp函数/asc_shfl_down.md)
- [asc_shfl_up](SIMT_API/Warp函数/asc_shfl_up.md)
- [asc_shfl_xor](SIMT_API/Warp函数/asc_shfl_xor.md)

### 使能Cache Hints的Load

#### Store函数

- [asc_ldca](SIMT_API/使能Cache_Hints的Load_Store函数/asc_ldca.md)
- [asc_ldcg](SIMT_API/使能Cache_Hints的Load_Store函数/asc_ldcg.md)
- [asc_stcg](SIMT_API/使能Cache_Hints的Load_Store函数/asc_stcg.md)
- [asc_stwt](SIMT_API/使能Cache_Hints的Load_Store函数/asc_stwt.md)

### 同步函数

- [asc_syncthreads](SIMT_API/同步函数/asc_syncthreads.md)
- [asc_threadfence](SIMT_API/同步函数/asc_threadfence.md)
- [asc_threadfence_block](SIMT_API/同步函数/asc_threadfence_block.md)

### 向量类型构造函数

- [make_bfloat162](SIMT_API/向量类型构造函数/make_bfloat162.md)
- [make_char2](SIMT_API/向量类型构造函数/make_char2.md)
- [make_char4](SIMT_API/向量类型构造函数/make_char4.md)
- [make_float2](SIMT_API/向量类型构造函数/make_float2.md)
- [make_float4](SIMT_API/向量类型构造函数/make_float4.md)
- [make_half2](SIMT_API/向量类型构造函数/make_half2.md)
- [make_int2](SIMT_API/向量类型构造函数/make_int2.md)
- [make_int4](SIMT_API/向量类型构造函数/make_int4.md)
- [make_long2](SIMT_API/向量类型构造函数/make_long2.md)
- [make_long4](SIMT_API/向量类型构造函数/make_long4.md)
- [make_longlong2](SIMT_API/向量类型构造函数/make_longlong2.md)
- [make_longlong4](SIMT_API/向量类型构造函数/make_longlong4.md)
- [make_short2](SIMT_API/向量类型构造函数/make_short2.md)
- [make_short4](SIMT_API/向量类型构造函数/make_short4.md)
- [make_uchar2](SIMT_API/向量类型构造函数/make_uchar2.md)
- [make_uchar4](SIMT_API/向量类型构造函数/make_uchar4.md)
- [make_uint2](SIMT_API/向量类型构造函数/make_uint2.md)
- [make_uint4](SIMT_API/向量类型构造函数/make_uint4.md)
- [make_ulong2](SIMT_API/向量类型构造函数/make_ulong2.md)
- [make_ulong4](SIMT_API/向量类型构造函数/make_ulong4.md)
- [make_ulonglong2](SIMT_API/向量类型构造函数/make_ulonglong2.md)
- [make_ulonglong4](SIMT_API/向量类型构造函数/make_ulonglong4.md)
- [make_ushort2](SIMT_API/向量类型构造函数/make_ushort2.md)
- [make_ushort4](SIMT_API/向量类型构造函数/make_ushort4.md)

### 数学函数

- [__brev](SIMT_API/数学函数/brev.md)
- [__byte_perm](SIMT_API/数学函数/byte_perm.md)
- [__clz](SIMT_API/数学函数/clz.md)
- [__ffs](SIMT_API/数学函数/ffs.md)
- [__habs](SIMT_API/数学函数/habs.md)
- [__hfma](SIMT_API/数学函数/hfma.md)
- [__hmax](SIMT_API/数学函数/hmax.md)
- [__hmin](SIMT_API/数学函数/hmin.md)
- [__mul64hi](SIMT_API/数学函数/mul64hi.md)
- [__mul_i32toi64](SIMT_API/数学函数/mul_i32toi64.md)
- [__mulhi](SIMT_API/数学函数/mulhi.md)
- [__popc](SIMT_API/数学函数/popc.md)
- [__umul64hi](SIMT_API/数学函数/umul64hi.md)
- [__umulhi](SIMT_API/数学函数/umulhi.md)
- [acosf](SIMT_API/数学函数/acosf.md)
- [acoshf](SIMT_API/数学函数/acoshf.md)
- [asinf](SIMT_API/数学函数/asinf.md)
- [asinhf](SIMT_API/数学函数/asinhf.md)
- [atan2f](SIMT_API/数学函数/atan2f.md)
- [atanf](SIMT_API/数学函数/atanf.md)
- [atanhf](SIMT_API/数学函数/atanhf.md)
- [cbrtf](SIMT_API/数学函数/cbrtf.md)
- [copysignf](SIMT_API/数学函数/copysignf.md)
- [cosf](SIMT_API/数学函数/cosf.md)
- [coshf](SIMT_API/数学函数/coshf.md)
- [cospif](SIMT_API/数学函数/cospif.md)
- [cyl_bessel_i0f](SIMT_API/数学函数/cyl_bessel_i0f.md)
- [cyl_bessel_i1f](SIMT_API/数学函数/cyl_bessel_i1f.md)
- [erfcf](SIMT_API/数学函数/erfcf.md)
- [erfcinvf](SIMT_API/数学函数/erfcinvf.md)
- [erfcxf](SIMT_API/数学函数/erfcxf.md)
- [erff](SIMT_API/数学函数/erff.md)
- [erfinvf](SIMT_API/数学函数/erfinvf.md)
- [exp10f](SIMT_API/数学函数/exp10f.md)
- [exp2f](SIMT_API/数学函数/exp2f.md)
- [expf](SIMT_API/数学函数/expf.md)
- [expm1f](SIMT_API/数学函数/expm1f.md)
- [fabsf](SIMT_API/数学函数/fabsf.md)
- [fdimf](SIMT_API/数学函数/fdimf.md)
- [fdividef](SIMT_API/数学函数/fdividef.md)
- [fmaf](SIMT_API/数学函数/fmaf.md)
- [fmaxf](SIMT_API/数学函数/fmaxf.md)
- [fminf](SIMT_API/数学函数/fminf.md)
- [fmodf](SIMT_API/数学函数/fmodf.md)
- [frexpf](SIMT_API/数学函数/frexpf.md)
- [h2cos](SIMT_API/数学函数/h2cos.md)
- [h2exp](SIMT_API/数学函数/h2exp.md)
- [h2exp10](SIMT_API/数学函数/h2exp10.md)
- [h2exp2](SIMT_API/数学函数/h2exp2.md)
- [h2log](SIMT_API/数学函数/h2log.md)
- [h2log10](SIMT_API/数学函数/h2log10.md)
- [h2log2](SIMT_API/数学函数/h2log2.md)
- [h2rcp](SIMT_API/数学函数/h2rcp.md)
- [h2rsqrt](SIMT_API/数学函数/h2rsqrt.md)
- [h2sin](SIMT_API/数学函数/h2sin.md)
- [h2sqrt](SIMT_API/数学函数/h2sqrt.md)
- [h2tanh](SIMT_API/数学函数/h2tanh.md)
- [hcos](SIMT_API/数学函数/hcos.md)
- [hexp](SIMT_API/数学函数/hexp.md)
- [hexp10](SIMT_API/数学函数/hexp10.md)
- [hexp2](SIMT_API/数学函数/hexp2.md)
- [hlog](SIMT_API/数学函数/hlog.md)
- [hlog10](SIMT_API/数学函数/hlog10.md)
- [hlog2](SIMT_API/数学函数/hlog2.md)
- [hrcp](SIMT_API/数学函数/hrcp.md)
- [hrsqrt](SIMT_API/数学函数/hrsqrt.md)
- [hsin](SIMT_API/数学函数/hsin.md)
- [hsqrt](SIMT_API/数学函数/hsqrt.md)
- [htanh](SIMT_API/数学函数/htanh.md)
- [hypotf](SIMT_API/数学函数/hypotf.md)
- [ilogbf](SIMT_API/数学函数/ilogbf.md)
- [j0f](SIMT_API/数学函数/j0f.md)
- [j1f](SIMT_API/数学函数/j1f.md)
- [jnf](SIMT_API/数学函数/jnf.md)
- [labs](SIMT_API/数学函数/labs.md)
- [ldexpf](SIMT_API/数学函数/ldexpf.md)
- [lgammaf](SIMT_API/数学函数/lgammaf.md)
- [llabs](SIMT_API/数学函数/llabs.md)
- [llmax](SIMT_API/数学函数/llmax.md)
- [llmin](SIMT_API/数学函数/llmin.md)
- [log10f](SIMT_API/数学函数/log10f.md)
- [log1pf](SIMT_API/数学函数/log1pf.md)
- [log2f](SIMT_API/数学函数/log2f.md)
- [logbf](SIMT_API/数学函数/logbf.md)
- [logf](SIMT_API/数学函数/logf.md)
- [modff](SIMT_API/数学函数/modff.md)
- [nearbyintf](SIMT_API/数学函数/nearbyintf.md)
- [nextafterf](SIMT_API/数学函数/nextafterf.md)
- [norm3df](SIMT_API/数学函数/norm3df.md)
- [norm4df](SIMT_API/数学函数/norm4df.md)
- [normcdff](SIMT_API/数学函数/normcdff.md)
- [normcdfinvf](SIMT_API/数学函数/normcdfinvf.md)
- [normf](SIMT_API/数学函数/normf.md)
- [powf](SIMT_API/数学函数/powf.md)
- [rcbrtf](SIMT_API/数学函数/rcbrtf.md)
- [remainderf](SIMT_API/数学函数/remainderf.md)
- [remquof](SIMT_API/数学函数/remquof.md)
- [rhypotf](SIMT_API/数学函数/rhypotf.md)
- [rnorm3df](SIMT_API/数学函数/rnorm3df.md)
- [rnorm4df](SIMT_API/数学函数/rnorm4df.md)
- [rnormf](SIMT_API/数学函数/rnormf.md)
- [rsqrtf](SIMT_API/数学函数/rsqrtf.md)
- [scalblnf](SIMT_API/数学函数/scalblnf.md)
- [scalbnf](SIMT_API/数学函数/scalbnf.md)
- [signbit](SIMT_API/数学函数/signbit.md)
- [sincosf](SIMT_API/数学函数/sincosf.md)
- [sincospif](SIMT_API/数学函数/sincospif.md)
- [sinf](SIMT_API/数学函数/sinf.md)
- [sinhf](SIMT_API/数学函数/sinhf.md)
- [sinpif](SIMT_API/数学函数/sinpif.md)
- [sqrtf](SIMT_API/数学函数/sqrtf.md)
- [tanf](SIMT_API/数学函数/tanf.md)
- [tanhf](SIMT_API/数学函数/tanhf.md)
- [tanpif](SIMT_API/数学函数/tanpif.md)
- [tgammaf](SIMT_API/数学函数/tgammaf.md)
- [ullmax](SIMT_API/数学函数/ullmax.md)
- [ullmin](SIMT_API/数学函数/ullmin.md)
- [umax](SIMT_API/数学函数/umax.md)
- [umin](SIMT_API/数学函数/umin.md)
- [y0f](SIMT_API/数学函数/y0f.md)
- [y1f](SIMT_API/数学函数/y1f.md)
- [ynf](SIMT_API/数学函数/ynf.md)

### 核函数定义

- [asc_vf_call](SIMT_API/核函数定义/asc_vf_call.md)

### 比较函数

- [__hisinf](SIMT_API/比较函数/hisinf.md)
- [__hisnan](SIMT_API/比较函数/hisnan.md)
- [isfinite](SIMT_API/比较函数/isfinite.md)
- [isinf](SIMT_API/比较函数/isinf.md)
- [isnan](SIMT_API/比较函数/isnan.md)

### 类型转换

- [__asc_cvt_float2_to_fp8x2](SIMT_API/类型转换/asc_cvt_float2_to_fp8x2.md)
- [__bfloat1622float2](SIMT_API/类型转换/bfloat1622float2.md)
- [__bfloat162bfloat162](SIMT_API/类型转换/bfloat162bfloat162.md)
- [__bfloat162bfloat16_rd](SIMT_API/类型转换/bfloat162bfloat16_rd.md)
- [__bfloat162bfloat16_rn](SIMT_API/类型转换/bfloat162bfloat16_rn.md)
- [__bfloat162bfloat16_rna](SIMT_API/类型转换/bfloat162bfloat16_rna.md)
- [__bfloat162bfloat16_ru](SIMT_API/类型转换/bfloat162bfloat16_ru.md)
- [__bfloat162bfloat16_rz](SIMT_API/类型转换/bfloat162bfloat16_rz.md)
- [__bfloat162float](SIMT_API/类型转换/bfloat162float.md)
- [__bfloat162half_rd](SIMT_API/类型转换/bfloat162half_rd.md)
- [__bfloat162half_rd_sat](SIMT_API/类型转换/bfloat162half_rd_sat.md)
- [__bfloat162half_rn](SIMT_API/类型转换/bfloat162half_rn.md)
- [__bfloat162half_rn_sat](SIMT_API/类型转换/bfloat162half_rn_sat.md)
- [__bfloat162half_rna](SIMT_API/类型转换/bfloat162half_rna.md)
- [__bfloat162half_rna_sat](SIMT_API/类型转换/bfloat162half_rna_sat.md)
- [__bfloat162half_ru](SIMT_API/类型转换/bfloat162half_ru.md)
- [__bfloat162half_ru_sat](SIMT_API/类型转换/bfloat162half_ru_sat.md)
- [__bfloat162half_rz](SIMT_API/类型转换/bfloat162half_rz.md)
- [__bfloat162half_rz_sat](SIMT_API/类型转换/bfloat162half_rz_sat.md)
- [__bfloat162int_rd](SIMT_API/类型转换/bfloat162int_rd.md)
- [__bfloat162int_rn](SIMT_API/类型转换/bfloat162int_rn.md)
- [__bfloat162int_rna](SIMT_API/类型转换/bfloat162int_rna.md)
- [__bfloat162int_ru](SIMT_API/类型转换/bfloat162int_ru.md)
- [__bfloat162int_rz](SIMT_API/类型转换/bfloat162int_rz.md)
- [__bfloat162ll_rd](SIMT_API/类型转换/bfloat162ll_rd.md)
- [__bfloat162ll_rn](SIMT_API/类型转换/bfloat162ll_rn.md)
- [__bfloat162ll_rna](SIMT_API/类型转换/bfloat162ll_rna.md)
- [__bfloat162ll_ru](SIMT_API/类型转换/bfloat162ll_ru.md)
- [__bfloat162ll_rz](SIMT_API/类型转换/bfloat162ll_rz.md)
- [__bfloat162uint_rd](SIMT_API/类型转换/bfloat162uint_rd.md)
- [__bfloat162uint_rn](SIMT_API/类型转换/bfloat162uint_rn.md)
- [__bfloat162uint_rna](SIMT_API/类型转换/bfloat162uint_rna.md)
- [__bfloat162uint_ru](SIMT_API/类型转换/bfloat162uint_ru.md)
- [__bfloat162uint_rz](SIMT_API/类型转换/bfloat162uint_rz.md)
- [__bfloat162ull_rd](SIMT_API/类型转换/bfloat162ull_rd.md)
- [__bfloat162ull_rn](SIMT_API/类型转换/bfloat162ull_rn.md)
- [__bfloat162ull_rna](SIMT_API/类型转换/bfloat162ull_rna.md)
- [__bfloat162ull_ru](SIMT_API/类型转换/bfloat162ull_ru.md)
- [__bfloat162ull_rz](SIMT_API/类型转换/bfloat162ull_rz.md)
- [__e4m3x22float2](SIMT_API/类型转换/e4m3x22float2.md)
- [__e5m2x22float2](SIMT_API/类型转换/e5m2x22float2.md)
- [__float22bfloat162_rd](SIMT_API/类型转换/float22bfloat162_rd.md)
- [__float22bfloat162_rd_sat](SIMT_API/类型转换/float22bfloat162_rd_sat.md)
- [__float22bfloat162_rn](SIMT_API/类型转换/float22bfloat162_rn.md)
- [__float22bfloat162_rn_sat](SIMT_API/类型转换/float22bfloat162_rn_sat.md)
- [__float22bfloat162_rna](SIMT_API/类型转换/float22bfloat162_rna.md)
- [__float22bfloat162_rna_sat](SIMT_API/类型转换/float22bfloat162_rna_sat.md)
- [__float22bfloat162_ru](SIMT_API/类型转换/float22bfloat162_ru.md)
- [__float22bfloat162_ru_sat](SIMT_API/类型转换/float22bfloat162_ru_sat.md)
- [__float22bfloat162_rz](SIMT_API/类型转换/float22bfloat162_rz.md)
- [__float22bfloat162_rz_sat](SIMT_API/类型转换/float22bfloat162_rz_sat.md)
- [__float22half2_rd](SIMT_API/类型转换/float22half2_rd.md)
- [__float22half2_rd_sat](SIMT_API/类型转换/float22half2_rd_sat.md)
- [__float22half2_rn](SIMT_API/类型转换/float22half2_rn.md)
- [__float22half2_rn_sat](SIMT_API/类型转换/float22half2_rn_sat.md)
- [__float22half2_rna](SIMT_API/类型转换/float22half2_rna.md)
- [__float22half2_rna_sat](SIMT_API/类型转换/float22half2_rna_sat.md)
- [__float22half2_ro](SIMT_API/类型转换/float22half2_ro.md)
- [__float22half2_ro_sat](SIMT_API/类型转换/float22half2_ro_sat.md)
- [__float22half2_ru](SIMT_API/类型转换/float22half2_ru.md)
- [__float22half2_ru_sat](SIMT_API/类型转换/float22half2_ru_sat.md)
- [__float22half2_rz](SIMT_API/类型转换/float22half2_rz.md)
- [__float22half2_rz_sat](SIMT_API/类型转换/float22half2_rz_sat.md)
- [__float22hif82_rh](SIMT_API/类型转换/float22hif82_rh.md)
- [__float22hif82_rh_sat](SIMT_API/类型转换/float22hif82_rh_sat.md)
- [__float22hif82_rna](SIMT_API/类型转换/float22hif82_rna.md)
- [__float22hif82_rna_sat](SIMT_API/类型转换/float22hif82_rna_sat.md)
- [__float2bfloat16](SIMT_API/类型转换/float2bfloat16.md)
- [__float2bfloat162_rn](SIMT_API/类型转换/float2bfloat162_rn.md)
- [__float2bfloat16_rd](SIMT_API/类型转换/float2bfloat16_rd.md)
- [__float2bfloat16_rd_sat](SIMT_API/类型转换/float2bfloat16_rd_sat.md)
- [__float2bfloat16_rn](SIMT_API/类型转换/float2bfloat16_rn.md)
- [__float2bfloat16_rn_sat](SIMT_API/类型转换/float2bfloat16_rn_sat.md)
- [__float2bfloat16_rna](SIMT_API/类型转换/float2bfloat16_rna.md)
- [__float2bfloat16_rna_sat](SIMT_API/类型转换/float2bfloat16_rna_sat.md)
- [__float2bfloat16_ru](SIMT_API/类型转换/float2bfloat16_ru.md)
- [__float2bfloat16_ru_sat](SIMT_API/类型转换/float2bfloat16_ru_sat.md)
- [__float2bfloat16_rz](SIMT_API/类型转换/float2bfloat16_rz.md)
- [__float2bfloat16_rz_sat](SIMT_API/类型转换/float2bfloat16_rz_sat.md)
- [__float2float_rd](SIMT_API/类型转换/float2float_rd.md)
- [__float2float_rn](SIMT_API/类型转换/float2float_rn.md)
- [__float2float_rna](SIMT_API/类型转换/float2float_rna.md)
- [__float2float_ru](SIMT_API/类型转换/float2float_ru.md)
- [__float2float_rz](SIMT_API/类型转换/float2float_rz.md)
- [__float2half](SIMT_API/类型转换/float2half.md)
- [__float2half_rd](SIMT_API/类型转换/float2half_rd.md)
- [__float2half_rd_sat](SIMT_API/类型转换/float2half_rd_sat.md)
- [__float2half_rn](SIMT_API/类型转换/float2half_rn.md)
- [__float2half_rn_sat](SIMT_API/类型转换/float2half_rn_sat.md)
- [__float2half_rna](SIMT_API/类型转换/float2half_rna.md)
- [__float2half_rna_sat](SIMT_API/类型转换/float2half_rna_sat.md)
- [__float2half_ro](SIMT_API/类型转换/float2half_ro.md)
- [__float2half_ro_sat](SIMT_API/类型转换/float2half_ro_sat.md)
- [__float2half_ru](SIMT_API/类型转换/float2half_ru.md)
- [__float2half_ru_sat](SIMT_API/类型转换/float2half_ru_sat.md)
- [__float2half_rz](SIMT_API/类型转换/float2half_rz.md)
- [__float2half_rz_sat](SIMT_API/类型转换/float2half_rz_sat.md)
- [__float2int_rd](SIMT_API/类型转换/float2int_rd.md)
- [__float2int_rn](SIMT_API/类型转换/float2int_rn.md)
- [__float2int_rna](SIMT_API/类型转换/float2int_rna.md)
- [__float2int_ru](SIMT_API/类型转换/float2int_ru.md)
- [__float2int_rz](SIMT_API/类型转换/float2int_rz.md)
- [__float2ll_rd](SIMT_API/类型转换/float2ll_rd.md)
- [__float2ll_rn](SIMT_API/类型转换/float2ll_rn.md)
- [__float2ll_rna](SIMT_API/类型转换/float2ll_rna.md)
- [__float2ll_ru](SIMT_API/类型转换/float2ll_ru.md)
- [__float2ll_rz](SIMT_API/类型转换/float2ll_rz.md)
- [__float2uint_rd](SIMT_API/类型转换/float2uint_rd.md)
- [__float2uint_rn](SIMT_API/类型转换/float2uint_rn.md)
- [__float2uint_rna](SIMT_API/类型转换/float2uint_rna.md)
- [__float2uint_ru](SIMT_API/类型转换/float2uint_ru.md)
- [__float2uint_rz](SIMT_API/类型转换/float2uint_rz.md)
- [__float2ull_rd](SIMT_API/类型转换/float2ull_rd.md)
- [__float2ull_rn](SIMT_API/类型转换/float2ull_rn.md)
- [__float2ull_rna](SIMT_API/类型转换/float2ull_rna.md)
- [__float2ull_ru](SIMT_API/类型转换/float2ull_ru.md)
- [__float2ull_rz](SIMT_API/类型转换/float2ull_rz.md)
- [__float_as_int](SIMT_API/类型转换/float_as_int.md)
- [__float_as_uint](SIMT_API/类型转换/float_as_uint.md)
- [__floats2bfloat162_rn](SIMT_API/类型转换/floats2bfloat162_rn.md)
- [__floats2half2_rn](SIMT_API/类型转换/floats2half2_rn.md)
- [__half22float2](SIMT_API/类型转换/half22float2.md)
- [__half22hif82_rh](SIMT_API/类型转换/half22hif82_rh.md)
- [__half22hif82_rh_sat](SIMT_API/类型转换/half22hif82_rh_sat.md)
- [__half22hif82_rna](SIMT_API/类型转换/half22hif82_rna.md)
- [__half22hif82_rna_sat](SIMT_API/类型转换/half22hif82_rna_sat.md)
- [__half2bfloat16_rd](SIMT_API/类型转换/half2bfloat16_rd.md)
- [__half2bfloat16_rn](SIMT_API/类型转换/half2bfloat16_rn.md)
- [__half2bfloat16_rna](SIMT_API/类型转换/half2bfloat16_rna.md)
- [__half2bfloat16_ru](SIMT_API/类型转换/half2bfloat16_ru.md)
- [__half2bfloat16_rz](SIMT_API/类型转换/half2bfloat16_rz.md)
- [__half2float](SIMT_API/类型转换/half2float.md)
- [__half2half_rd](SIMT_API/类型转换/half2half_rd.md)
- [__half2half_rn](SIMT_API/类型转换/half2half_rn.md)
- [__half2half_rna](SIMT_API/类型转换/half2half_rna.md)
- [__half2half_ru](SIMT_API/类型转换/half2half_ru.md)
- [__half2half_rz](SIMT_API/类型转换/half2half_rz.md)
- [__half2int_rd](SIMT_API/类型转换/half2int_rd.md)
- [__half2int_rn](SIMT_API/类型转换/half2int_rn.md)
- [__half2int_rna](SIMT_API/类型转换/half2int_rna.md)
- [__half2int_ru](SIMT_API/类型转换/half2int_ru.md)
- [__half2int_rz](SIMT_API/类型转换/half2int_rz.md)
- [__half2ll_rd](SIMT_API/类型转换/half2ll_rd.md)
- [__half2ll_rn](SIMT_API/类型转换/half2ll_rn.md)
- [__half2ll_rna](SIMT_API/类型转换/half2ll_rna.md)
- [__half2ll_ru](SIMT_API/类型转换/half2ll_ru.md)
- [__half2ll_rz](SIMT_API/类型转换/half2ll_rz.md)
- [__half2uint_rd](SIMT_API/类型转换/half2uint_rd.md)
- [__half2uint_rn](SIMT_API/类型转换/half2uint_rn.md)
- [__half2uint_rna](SIMT_API/类型转换/half2uint_rna.md)
- [__half2uint_ru](SIMT_API/类型转换/half2uint_ru.md)
- [__half2uint_rz](SIMT_API/类型转换/half2uint_rz.md)
- [__half2ull_rd](SIMT_API/类型转换/half2ull_rd.md)
- [__half2ull_rn](SIMT_API/类型转换/half2ull_rn.md)
- [__half2ull_rna](SIMT_API/类型转换/half2ull_rna.md)
- [__half2ull_ru](SIMT_API/类型转换/half2ull_ru.md)
- [__half2ull_rz](SIMT_API/类型转换/half2ull_rz.md)
- [__halves2bfloat162](SIMT_API/类型转换/halves2bfloat162.md)
- [__halves2half2](SIMT_API/类型转换/halves2half2.md)
- [__hif822float2](SIMT_API/类型转换/hif822float2.md)
- [__hif822half2](SIMT_API/类型转换/hif822half2.md)
- [__high2bfloat16](SIMT_API/类型转换/high2bfloat16.md)
- [__high2bfloat162](SIMT_API/类型转换/high2bfloat162.md)
- [__high2float](SIMT_API/类型转换/high2float.md)
- [__high2half](SIMT_API/类型转换/high2half.md)
- [__high2half2](SIMT_API/类型转换/high2half2.md)
- [__highs2bfloat162](SIMT_API/类型转换/highs2bfloat162.md)
- [__highs2half2](SIMT_API/类型转换/highs2half2.md)
- [__int2bfloat16_rd](SIMT_API/类型转换/int2bfloat16_rd.md)
- [__int2bfloat16_rn](SIMT_API/类型转换/int2bfloat16_rn.md)
- [__int2bfloat16_rna](SIMT_API/类型转换/int2bfloat16_rna.md)
- [__int2bfloat16_ru](SIMT_API/类型转换/int2bfloat16_ru.md)
- [__int2bfloat16_rz](SIMT_API/类型转换/int2bfloat16_rz.md)
- [__int2float_rd](SIMT_API/类型转换/int2float_rd.md)
- [__int2float_rn](SIMT_API/类型转换/int2float_rn.md)
- [__int2float_rna](SIMT_API/类型转换/int2float_rna.md)
- [__int2float_ru](SIMT_API/类型转换/int2float_ru.md)
- [__int2float_rz](SIMT_API/类型转换/int2float_rz.md)
- [__int2half_rd](SIMT_API/类型转换/int2half_rd.md)
- [__int2half_rd_sat](SIMT_API/类型转换/int2half_rd_sat.md)
- [__int2half_rn](SIMT_API/类型转换/int2half_rn.md)
- [__int2half_rn_sat](SIMT_API/类型转换/int2half_rn_sat.md)
- [__int2half_rna](SIMT_API/类型转换/int2half_rna.md)
- [__int2half_rna_sat](SIMT_API/类型转换/int2half_rna_sat.md)
- [__int2half_ru](SIMT_API/类型转换/int2half_ru.md)
- [__int2half_ru_sat](SIMT_API/类型转换/int2half_ru_sat.md)
- [__int2half_rz](SIMT_API/类型转换/int2half_rz.md)
- [__int2half_rz_sat](SIMT_API/类型转换/int2half_rz_sat.md)
- [__int_as_float](SIMT_API/类型转换/int_as_float.md)
- [__ll2bfloat16_rd](SIMT_API/类型转换/ll2bfloat16_rd.md)
- [__ll2bfloat16_rn](SIMT_API/类型转换/ll2bfloat16_rn.md)
- [__ll2bfloat16_rna](SIMT_API/类型转换/ll2bfloat16_rna.md)
- [__ll2bfloat16_ru](SIMT_API/类型转换/ll2bfloat16_ru.md)
- [__ll2bfloat16_rz](SIMT_API/类型转换/ll2bfloat16_rz.md)
- [__ll2float_rd](SIMT_API/类型转换/ll2float_rd.md)
- [__ll2float_rn](SIMT_API/类型转换/ll2float_rn.md)
- [__ll2float_rna](SIMT_API/类型转换/ll2float_rna.md)
- [__ll2float_ru](SIMT_API/类型转换/ll2float_ru.md)
- [__ll2float_rz](SIMT_API/类型转换/ll2float_rz.md)
- [__ll2half_rd](SIMT_API/类型转换/ll2half_rd.md)
- [__ll2half_rn](SIMT_API/类型转换/ll2half_rn.md)
- [__ll2half_rna](SIMT_API/类型转换/ll2half_rna.md)
- [__ll2half_ru](SIMT_API/类型转换/ll2half_ru.md)
- [__ll2half_rz](SIMT_API/类型转换/ll2half_rz.md)
- [__low2bfloat16](SIMT_API/类型转换/low2bfloat16.md)
- [__low2bfloat162](SIMT_API/类型转换/low2bfloat162.md)
- [__low2float](SIMT_API/类型转换/low2float.md)
- [__low2half](SIMT_API/类型转换/low2half.md)
- [__low2half2](SIMT_API/类型转换/low2half2.md)
- [__lowhigh2highlow](SIMT_API/类型转换/lowhigh2highlow.md)
- [__lows2bfloat162](SIMT_API/类型转换/lows2bfloat162.md)
- [__lows2half2](SIMT_API/类型转换/lows2half2.md)
- [__uint2bfloat16_rd](SIMT_API/类型转换/uint2bfloat16_rd.md)
- [__uint2bfloat16_rn](SIMT_API/类型转换/uint2bfloat16_rn.md)
- [__uint2bfloat16_rna](SIMT_API/类型转换/uint2bfloat16_rna.md)
- [__uint2bfloat16_ru](SIMT_API/类型转换/uint2bfloat16_ru.md)
- [__uint2bfloat16_rz](SIMT_API/类型转换/uint2bfloat16_rz.md)
- [__uint2float_rd](SIMT_API/类型转换/uint2float_rd.md)
- [__uint2float_rn](SIMT_API/类型转换/uint2float_rn.md)
- [__uint2float_rna](SIMT_API/类型转换/uint2float_rna.md)
- [__uint2float_ru](SIMT_API/类型转换/uint2float_ru.md)
- [__uint2float_rz](SIMT_API/类型转换/uint2float_rz.md)
- [__uint2half_rd](SIMT_API/类型转换/uint2half_rd.md)
- [__uint2half_rd_sat](SIMT_API/类型转换/uint2half_rd_sat.md)
- [__uint2half_rn](SIMT_API/类型转换/uint2half_rn.md)
- [__uint2half_rn_sat](SIMT_API/类型转换/uint2half_rn_sat.md)
- [__uint2half_rna](SIMT_API/类型转换/uint2half_rna.md)
- [__uint2half_rna_sat](SIMT_API/类型转换/uint2half_rna_sat.md)
- [__uint2half_ru](SIMT_API/类型转换/uint2half_ru.md)
- [__uint2half_ru_sat](SIMT_API/类型转换/uint2half_ru_sat.md)
- [__uint2half_rz](SIMT_API/类型转换/uint2half_rz.md)
- [__uint2half_rz_sat](SIMT_API/类型转换/uint2half_rz_sat.md)
- [__uint_as_float](SIMT_API/类型转换/uint_as_float.md)
- [__ull2bfloat16_rd](SIMT_API/类型转换/ull2bfloat16_rd.md)
- [__ull2bfloat16_rn](SIMT_API/类型转换/ull2bfloat16_rn.md)
- [__ull2bfloat16_rna](SIMT_API/类型转换/ull2bfloat16_rna.md)
- [__ull2bfloat16_ru](SIMT_API/类型转换/ull2bfloat16_ru.md)
- [__ull2bfloat16_rz](SIMT_API/类型转换/ull2bfloat16_rz.md)
- [__ull2float_rd](SIMT_API/类型转换/ull2float_rd.md)
- [__ull2float_rn](SIMT_API/类型转换/ull2float_rn.md)
- [__ull2float_rna](SIMT_API/类型转换/ull2float_rna.md)
- [__ull2float_ru](SIMT_API/类型转换/ull2float_ru.md)
- [__ull2float_rz](SIMT_API/类型转换/ull2float_rz.md)
- [__ull2half_rd](SIMT_API/类型转换/ull2half_rd.md)
- [__ull2half_rn](SIMT_API/类型转换/ull2half_rn.md)
- [__ull2half_rna](SIMT_API/类型转换/ull2half_rna.md)
- [__ull2half_ru](SIMT_API/类型转换/ull2half_ru.md)
- [__ull2half_rz](SIMT_API/类型转换/ull2half_rz.md)
- [__ushort_as_bfloat16](SIMT_API/类型转换/ushort_as_bfloat16.md)
- [__ushort_as_half](SIMT_API/类型转换/ushort_as_half.md)
- [简介](SIMT_API/类型转换/简介.md)

### 精度转换

- [ceilf](SIMT_API/精度转换/ceilf.md)
- [floorf](SIMT_API/精度转换/floorf.md)
- [h2ceil](SIMT_API/精度转换/h2ceil.md)
- [h2floor](SIMT_API/精度转换/h2floor.md)
- [h2rint](SIMT_API/精度转换/h2rint.md)
- [h2trunc](SIMT_API/精度转换/h2trunc.md)
- [hceil](SIMT_API/精度转换/hceil.md)
- [hfloor](SIMT_API/精度转换/hfloor.md)
- [hrint](SIMT_API/精度转换/hrint.md)
- [htrunc](SIMT_API/精度转换/htrunc.md)
- [llrintf](SIMT_API/精度转换/llrintf.md)
- [llroundf](SIMT_API/精度转换/llroundf.md)
- [lrintf](SIMT_API/精度转换/lrintf.md)
- [lroundf](SIMT_API/精度转换/lroundf.md)
- [rintf](SIMT_API/精度转换/rintf.md)
- [roundf](SIMT_API/精度转换/roundf.md)
- [truncf](SIMT_API/精度转换/truncf.md)

- [内置宏](SIMT_API/内置宏.md)
- [简介](SIMT_API/简介.md)

## Utils API

### C++标准库

#### 容器函数

- [get](Utils_API/C++标准库/容器函数/get.md)
- [make_tuple](Utils_API/C++标准库/容器函数/make_tuple.md)
- [tuple](Utils_API/C++标准库/容器函数/tuple.md)

#### 数学函数

- [abs](Utils_API/C++标准库/数学函数/abs.md)
- [sqrt](Utils_API/C++标准库/数学函数/sqrt.md)

#### 算法

- [max](Utils_API/C++标准库/算法/max.md)
- [min](Utils_API/C++标准库/算法/min.md)

#### 类型特性

- [add_const](Utils_API/C++标准库/类型特性/add_const.md)
- [add_cv](Utils_API/C++标准库/类型特性/add_cv.md)
- [add_lvalue_reference](Utils_API/C++标准库/类型特性/add_lvalue_reference.md)
- [add_pointer](Utils_API/C++标准库/类型特性/add_pointer.md)
- [add_rvalue_reference](Utils_API/C++标准库/类型特性/add_rvalue_reference.md)
- [add_volatile](Utils_API/C++标准库/类型特性/add_volatile.md)
- [conditional](Utils_API/C++标准库/类型特性/conditional.md)
- [enable_if](Utils_API/C++标准库/类型特性/enable_if.md)
- [integral_constant](Utils_API/C++标准库/类型特性/integral_constant.md)
- [is_array](Utils_API/C++标准库/类型特性/is_array.md)
- [is_base_of](Utils_API/C++标准库/类型特性/is_base_of.md)
- [is_const](Utils_API/C++标准库/类型特性/is_const.md)
- [is_convertible](Utils_API/C++标准库/类型特性/is_convertible.md)
- [is_floating_point](Utils_API/C++标准库/类型特性/is_floating_point.md)
- [is_integral](Utils_API/C++标准库/类型特性/is_integral.md)
- [is_pointer](Utils_API/C++标准库/类型特性/is_pointer.md)
- [is_reference](Utils_API/C++标准库/类型特性/is_reference.md)
- [is_same](Utils_API/C++标准库/类型特性/is_same.md)
- [is_void](Utils_API/C++标准库/类型特性/is_void.md)
- [remove_const](Utils_API/C++标准库/类型特性/remove_const.md)
- [remove_cv](Utils_API/C++标准库/类型特性/remove_cv.md)
- [remove_pointer](Utils_API/C++标准库/类型特性/remove_pointer.md)
- [remove_reference](Utils_API/C++标准库/类型特性/remove_reference.md)
- [remove_volatile](Utils_API/C++标准库/类型特性/remove_volatile.md)

#### 通用工具

- [integer_sequence](Utils_API/C++标准库/通用工具/integer_sequence.md)

### RTC

- [RTC简介](Utils_API/RTC/RTC简介.md)
- [RTC错误码](Utils_API/RTC/RTC错误码.md)
- [aclrtcCompileProg](Utils_API/RTC/aclrtcCompileProg.md)
- [aclrtcCreateProg](Utils_API/RTC/aclrtcCreateProg.md)
- [aclrtcDestroyProg](Utils_API/RTC/aclrtcDestroyProg.md)
- [aclrtcGetBinData](Utils_API/RTC/aclrtcGetBinData.md)
- [aclrtcGetBinDataSize](Utils_API/RTC/aclrtcGetBinDataSize.md)
- [aclrtcGetCompileLog](Utils_API/RTC/aclrtcGetCompileLog.md)
- [aclrtcGetCompileLogSize](Utils_API/RTC/aclrtcGetCompileLogSize.md)

### Tiling下沉

- [DEVICE_IMPL_OP_OPTILING](Utils_API/Tiling下沉/DEVICE_IMPL_OP_OPTILING.md)

### Tiling数据结构注册

- [TilingData结构定义](Utils_API/Tiling数据结构注册/TilingData结构定义.md)
- [TilingData结构注册](Utils_API/Tiling数据结构注册/TilingData结构注册.md)

### Tiling模板编程

- [ASCENDC_TPL_SEL_PARAM](Utils_API/Tiling模板编程/ASCENDC_TPL_SEL_PARAM.md)
- [模板参数定义](Utils_API/Tiling模板编程/模板参数定义.md)

### Tiling调测

#### ContextBuilder

- [AddAttr](Utils_API/Tiling调测/ContextBuilder/AddAttr.md)
- [AddInputTd](Utils_API/Tiling调测/ContextBuilder/AddInputTd.md)
- [AddOutputTd](Utils_API/Tiling调测/ContextBuilder/AddOutputTd.md)
- [AddPlatformInfo](Utils_API/Tiling调测/ContextBuilder/AddPlatformInfo.md)
- [BuildKernelRunContext](Utils_API/Tiling调测/ContextBuilder/BuildKernelRunContext.md)
- [BuildTilingContext](Utils_API/Tiling调测/ContextBuilder/BuildTilingContext.md)
- [CompileInfo](Utils_API/Tiling调测/ContextBuilder/CompileInfo.md)
- [ContextBuilder构造函数](Utils_API/Tiling调测/ContextBuilder/ContextBuilder构造函数.md)
- [Inputs](Utils_API/Tiling调测/ContextBuilder/Inputs.md)
- [IrInstanceNum](Utils_API/Tiling调测/ContextBuilder/IrInstanceNum.md)
- [KernelRunContextHolder结构定义](Utils_API/Tiling调测/ContextBuilder/KernelRunContextHolder结构定义.md)
- [NodeIoNum](Utils_API/Tiling调测/ContextBuilder/NodeIoNum.md)
- [Outputs](Utils_API/Tiling调测/ContextBuilder/Outputs.md)
- [PlatformInfo](Utils_API/Tiling调测/ContextBuilder/PlatformInfo.md)
- [SetOpNameType](Utils_API/Tiling调测/ContextBuilder/SetOpNameType.md)
- [TilingData](Utils_API/Tiling调测/ContextBuilder/TilingData.md)
- [Workspace](Utils_API/Tiling调测/ContextBuilder/Workspace.md)
- [简介](Utils_API/Tiling调测/ContextBuilder/简介.md)

#### OpTilingRegistry

- [GetTilingFunc](Utils_API/Tiling调测/OpTilingRegistry/GetTilingFunc.md)
- [LoadTilingLibrary](Utils_API/Tiling调测/OpTilingRegistry/LoadTilingLibrary.md)
- [构造和析构函数](Utils_API/Tiling调测/OpTilingRegistry/构造和析构函数.md)
- [简介](Utils_API/Tiling调测/OpTilingRegistry/简介.md)

### log

- [ASC_CPU_LOG](Utils_API/log/ASC_CPU_LOG.md)

### 原型注册与管理

#### OpAICPUDef

- [ComputeCost](Utils_API/原型注册与管理/OpAICPUDef/ComputeCost.md)
- [Engine](Utils_API/原型注册与管理/OpAICPUDef/Engine.md)
- [ExtendCfgInfo](Utils_API/原型注册与管理/OpAICPUDef/ExtendCfgInfo.md)
- [FlagAsync](Utils_API/原型注册与管理/OpAICPUDef/FlagAsync.md)
- [FlagPartial](Utils_API/原型注册与管理/OpAICPUDef/FlagPartial.md)
- [FunctionName](Utils_API/原型注册与管理/OpAICPUDef/FunctionName.md)
- [KernelSo](Utils_API/原型注册与管理/OpAICPUDef/KernelSo.md)
- [OpkernelLib](Utils_API/原型注册与管理/OpAICPUDef/OpkernelLib.md)
- [UserDefined](Utils_API/原型注册与管理/OpAICPUDef/UserDefined.md)

#### OpAICoreConfig

- [DynamicCompileStaticFlag](Utils_API/原型注册与管理/OpAICoreConfig/DynamicCompileStaticFlag.md)
- [DynamicFormatFlag](Utils_API/原型注册与管理/OpAICoreConfig/DynamicFormatFlag.md)
- [DynamicRankSupportFlag](Utils_API/原型注册与管理/OpAICoreConfig/DynamicRankSupportFlag.md)
- [DynamicShapeSupportFlag](Utils_API/原型注册与管理/OpAICoreConfig/DynamicShapeSupportFlag.md)
- [ExtendCfgInfo](Utils_API/原型注册与管理/OpAICoreConfig/ExtendCfgInfo.md)
- [Input](Utils_API/原型注册与管理/OpAICoreConfig/Input.md)
- [NeedCheckSupportFlag](Utils_API/原型注册与管理/OpAICoreConfig/NeedCheckSupportFlag.md)
- [OpAICoreConfig构造函数](Utils_API/原型注册与管理/OpAICoreConfig/OpAICoreConfig构造函数.md)
- [Output](Utils_API/原型注册与管理/OpAICoreConfig/Output.md)
- [PrecisionReduceFlag](Utils_API/原型注册与管理/OpAICoreConfig/PrecisionReduceFlag.md)

#### OpAICoreDef

- [AddConfig](Utils_API/原型注册与管理/OpAICoreDef/AddConfig.md)
- [LaunchWithZeroEleOutputTensors](Utils_API/原型注册与管理/OpAICoreDef/LaunchWithZeroEleOutputTensors.md)
- [SetCheckSupport](Utils_API/原型注册与管理/OpAICoreDef/SetCheckSupport.md)
- [SetOpSelectFormat](Utils_API/原型注册与管理/OpAICoreDef/SetOpSelectFormat.md)
- [SetTiling](Utils_API/原型注册与管理/OpAICoreDef/SetTiling.md)

#### OpAttrDef

- [Comment](Utils_API/原型注册与管理/OpAttrDef/Comment.md)
- [OpAttrDef](Utils_API/原型注册与管理/OpAttrDef/OpAttrDef.md)

#### OpDef

- [AICPU](Utils_API/原型注册与管理/OpDef/AICPU.md)
- [AICore](Utils_API/原型注册与管理/OpDef/AICore.md)
- [Attr](Utils_API/原型注册与管理/OpDef/Attr.md)
- [Comment](Utils_API/原型注册与管理/OpDef/Comment.md)
- [EnableFallBack](Utils_API/原型注册与管理/OpDef/EnableFallBack.md)
- [FormatMatchMode](Utils_API/原型注册与管理/OpDef/FormatMatchMode.md)
- [HostCPU](Utils_API/原型注册与管理/OpDef/HostCPU.md)
- [Input](Utils_API/原型注册与管理/OpDef/Input.md)
- [MC2](Utils_API/原型注册与管理/OpDef/MC2.md)
- [Output](Utils_API/原型注册与管理/OpDef/Output.md)
- [SetInferDataType](Utils_API/原型注册与管理/OpDef/SetInferDataType.md)
- [SetInferShape](Utils_API/原型注册与管理/OpDef/SetInferShape.md)
- [SetInferShapeRange](Utils_API/原型注册与管理/OpDef/SetInferShapeRange.md)

#### OpHostCPUDef

- [ComputeCost](Utils_API/原型注册与管理/OpHostCPUDef/ComputeCost.md)
- [Engine](Utils_API/原型注册与管理/OpHostCPUDef/Engine.md)
- [ExtendCfgInfo](Utils_API/原型注册与管理/OpHostCPUDef/ExtendCfgInfo.md)
- [FlagAsync](Utils_API/原型注册与管理/OpHostCPUDef/FlagAsync.md)
- [FlagPartial](Utils_API/原型注册与管理/OpHostCPUDef/FlagPartial.md)
- [FunctionName](Utils_API/原型注册与管理/OpHostCPUDef/FunctionName.md)
- [KernelSo](Utils_API/原型注册与管理/OpHostCPUDef/KernelSo.md)
- [OpKernelLib](Utils_API/原型注册与管理/OpHostCPUDef/OpKernelLib.md)
- [UserDefined](Utils_API/原型注册与管理/OpHostCPUDef/UserDefined.md)

#### OpMC2Def

- [HcclGroup](Utils_API/原型注册与管理/OpMC2Def/HcclGroup.md)
- [HcclServerType](Utils_API/原型注册与管理/OpMC2Def/HcclServerType.md)
- [OpMC2Def构造函数](Utils_API/原型注册与管理/OpMC2Def/OpMC2Def构造函数.md)
- [operator=](Utils_API/原型注册与管理/OpMC2Def/operator=.md)

#### OpParamDef

- [AutoContiguous](Utils_API/原型注册与管理/OpParamDef/AutoContiguous.md)
- [Comment](Utils_API/原型注册与管理/OpParamDef/Comment.md)
- [DataType](Utils_API/原型注册与管理/OpParamDef/DataType.md)
- [DataTypeForBinQuery](Utils_API/原型注册与管理/OpParamDef/DataTypeForBinQuery.md)
- [DataTypeList](Utils_API/原型注册与管理/OpParamDef/DataTypeList.md)
- [Follow](Utils_API/原型注册与管理/OpParamDef/Follow.md)
- [Format](Utils_API/原型注册与管理/OpParamDef/Format.md)
- [FormatForBinQuery](Utils_API/原型注册与管理/OpParamDef/FormatForBinQuery.md)
- [FormatList](Utils_API/原型注册与管理/OpParamDef/FormatList.md)
- [IgnoreContiguous](Utils_API/原型注册与管理/OpParamDef/IgnoreContiguous.md)
- [InitValue](Utils_API/原型注册与管理/OpParamDef/InitValue.md)
- [OutputShapeDependOnCompute](Utils_API/原型注册与管理/OpParamDef/OutputShapeDependOnCompute.md)
- [ParamType](Utils_API/原型注册与管理/OpParamDef/ParamType.md)
- [Scalar](Utils_API/原型注册与管理/OpParamDef/Scalar.md)
- [ScalarList](Utils_API/原型注册与管理/OpParamDef/ScalarList.md)
- [To](Utils_API/原型注册与管理/OpParamDef/To.md)
- [UnknownShapeFormat（废弃）](Utils_API/原型注册与管理/OpParamDef/UnknownShapeFormat（废弃）.md)
- [ValueDepend](Utils_API/原型注册与管理/OpParamDef/ValueDepend.md)
- [Version](Utils_API/原型注册与管理/OpParamDef/Version.md)
- [构造&拷贝构造函数](Utils_API/原型注册与管理/OpParamDef/构造&拷贝构造函数.md)

- [OpAICoreConfig注册接口（REGISTER_OP_AICORE_CONFIG）](Utils_API/原型注册与管理/OpAICoreConfig注册接口（REGISTER_OP_AICORE_CONFIG）.md)
- [原型注册接口（OP_ADD）](Utils_API/原型注册与管理/原型注册接口（OP_ADD）.md)

### 平台信息获取

#### PlatformAscendC

- [CalcTschNumBlocks](Utils_API/平台信息获取/PlatformAscendC/CalcTschNumBlocks.md)
- [GetCoreMemBw](Utils_API/平台信息获取/PlatformAscendC/GetCoreMemBw.md)
- [GetCoreMemSize](Utils_API/平台信息获取/PlatformAscendC/GetCoreMemSize.md)
- [GetCoreNum](Utils_API/平台信息获取/PlatformAscendC/GetCoreNum.md)
- [GetCoreNumAic](Utils_API/平台信息获取/PlatformAscendC/GetCoreNumAic.md)
- [GetCoreNumAiv](Utils_API/平台信息获取/PlatformAscendC/GetCoreNumAiv.md)
- [GetCoreNumVector](Utils_API/平台信息获取/PlatformAscendC/GetCoreNumVector.md)
- [GetCurNpuArch](Utils_API/平台信息获取/PlatformAscendC/GetCurNpuArch.md)
- [GetLibApiWorkSpaceSize](Utils_API/平台信息获取/PlatformAscendC/GetLibApiWorkSpaceSize.md)
- [GetResCubeGroupWorkSpaceSize](Utils_API/平台信息获取/PlatformAscendC/GetResCubeGroupWorkSpaceSize.md)
- [GetResGroupBarrierWorkSpaceSize](Utils_API/平台信息获取/PlatformAscendC/GetResGroupBarrierWorkSpaceSize.md)
- [GetSocVersion](Utils_API/平台信息获取/PlatformAscendC/GetSocVersion.md)
- [GetVecRegLen](Utils_API/平台信息获取/PlatformAscendC/GetVecRegLen.md)
- [PlatformAscendC简介](Utils_API/平台信息获取/PlatformAscendC/PlatformAscendC简介.md)
- [ReserveLocalMemory](Utils_API/平台信息获取/PlatformAscendC/ReserveLocalMemory.md)
- [构造及析构函数](Utils_API/平台信息获取/PlatformAscendC/构造及析构函数.md)

- [PlatformAscendCManager](Utils_API/平台信息获取/PlatformAscendCManager.md)

### 调测接口

- [TRACE_START](Utils_API/调测接口/TRACE_START.md)
- [TRACE_STOP](Utils_API/调测接口/TRACE_STOP.md)
- [__trap](Utils_API/调测接口/trap.md)
- [asc_dump](Utils_API/调测接口/asc_dump.md)
- [asc_mark_stamp](Utils_API/调测接口/asc_mark_stamp.md)
- [asc_prof_start](Utils_API/调测接口/asc_prof_start.md)
- [asc_prof_stop](Utils_API/调测接口/asc_prof_stop.md)
- [asc_time_stamp](Utils_API/调测接口/asc_time_stamp.md)
- [assert](Utils_API/调测接口/assert.md)
- [clock](Utils_API/调测接口/clock.md)
- [printf](Utils_API/调测接口/printf.md)

- [Ascend C API列表](Ascend_C_API列表.md)

