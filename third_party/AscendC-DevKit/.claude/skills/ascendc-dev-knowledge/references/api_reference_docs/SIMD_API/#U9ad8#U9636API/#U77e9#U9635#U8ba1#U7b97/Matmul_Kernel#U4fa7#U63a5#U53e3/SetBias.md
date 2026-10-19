# SetBias

**页面ID:** atlasascendc_api_07_0635  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0635.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品            AI Core | √ |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

设置矩阵乘的Bias。

#### 函数原型

```
__aicore__ inline void SetBias(const GlobalTensor<BiasT>& biasGlobal)
```

```
__aicore__ inline void SetBias(const LocalTensor<BiasT>& inputBias)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| biasGlobal | 输入 | Bias矩阵。类型为GlobalTensor。          Atlas 350 加速卡，支持的数据类型为:half/bfloat16_t/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t                       Atlas A3 训练系列产品            /             Atlas A3 推理系列产品            ，支持的数据类型为：half/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t                       Atlas 推理系列产品            AI Core，支持的数据类型为：half/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t                       Atlas A2 训练系列产品            /             Atlas A2 推理系列产品            ，支持的数据类型为：half/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t                       Atlas 200I/500 A2 推理产品            ，支持的数据类型为：half/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t          A矩阵、B矩阵、Bias支持的数据类型组合可参考Matmul输入输出数据类型的组合说明；在MxMatmul场景，A矩阵、B矩阵、Bias支持的数据类型组合可参考MatmulTypeWithScale参数说明。 |
| inputBias | 输入 | Bias矩阵。类型为LocalTensor，支持的TPosition为TSCM/VECOUT。          Atlas 350 加速卡，支持的数据类型为:half/bfloat16_t/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t                       Atlas A3 训练系列产品            /             Atlas A3 推理系列产品            ，支持的数据类型为：half/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t                       Atlas 推理系列产品            AI Core，支持的数据类型为：half/float/int32_t                       Atlas A2 训练系列产品            /             Atlas A2 推理系列产品            ，支持的数据类型为：half/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t                       Atlas 200I/500 A2 推理产品            ，支持的数据类型为：half/float/int32_t，其中仅在A、B的数据类型为int8_t时，Bias的数据类型可以设置为int32_t          A矩阵、B矩阵、Bias支持的数据类型组合可参考Matmul输入输出数据类型的组合说明；在MxMatmul场景，A矩阵、B矩阵、Bias支持的数据类型组合可参考MatmulTypeWithScale参数说明 。 |

#### 约束说明

- 在Matmul Tiling计算中，必须配置TCubeTiling结构中的isBias参数为1，即使能Bias后，才能调用本接口设置Bias矩阵。
- 传入的Bias地址空间大小需要保证不小于singleN。
- 对于Atlas 350 加速卡，Bias矩阵的内存逻辑位置为TSCM且数据类型为float或int32_t时，Bias矩阵的LocalTensor空间必须64字节对齐。

#### 调用示例

```
REGIST_MATMUL_OBJ(&pipe, GetSysWorkSpacePtr(), mm, &tiling);
mm.SetTensorA(gm_a);
mm.SetTensorB(gm_b);
if (tiling.isBias) {
    mm.SetBias(gmBias);  // 设置Bias
}
mm.IterateAll(gm_c);
mm.End();
```
