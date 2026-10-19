# SetTensorScaleA

**页面ID:** atlasascendc_api_07_0633  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0633.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品            AI Core | x |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

MxMatmul场景，设置矩阵乘中左矩阵的量化系数矩阵scaleA。

#### 函数原型

```
__aicore__ inline void SetTensorScaleA(const GlobalTensor<ScaleT>& gm, bool isTransposeScaleA = false);
```

```
__aicore__ inline void SetTensorScaleA(const LocalTensor<ScaleT>& leftMatrix, bool isTransposeScaleA = false);
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| gm | 输入 | 量化系数scaleA矩阵。类型为GlobalTensor。          Atlas 350 加速卡，支持的数据类型为：fp8_e8m0_t |
| leftMatrix | 输入 | 量化系数scaleA矩阵。类型为LocalTensor，支持的TPosition为TSCM/VECOUT。          Atlas 350 加速卡，支持的数据类型为：fp8_e8m0_t |
| isTransposeScaleA | 输入 | scaleA矩阵是否需要转置。          参数支持的取值如下：                     - false：默认值，scaleA矩阵不转置。           - true：scaleA矩阵转置。                    **注意****：**                     - scaleA矩阵为NZ格式时，该参数只支持取值为false。           - 若scaleA矩阵的SCALE_ISTRANS参数设置为true，除scaleA为NZ格式场景，该参数支持取值为true、false，即运行时scaleA矩阵可以转置和非转置交替使用。           - 若scaleA矩阵的SCALE_ISTRANS参数设置为false，该参数只支持取值为false，若强行设置为true，精度会有异常。                    对于有Bias输入的场景，为了确保Tiling侧与Kernel侧L1 Buffer空间计算大小保持一致及结果精度正确，该参数取值必须与Kernel侧定义A矩阵MatmulTypeWithScale的SCALE_ISTRANS参数以及Tiling侧SetScaleAType()接口的isScaleTrans参数保持一致，即有Bias输入的场景，上述三个参数必须同时设置为true或同时设置为false。 |

#### 约束说明

- 传入的scaleA地址空间大小必须不小于singleCoreM*singleCoreK/32。
- 当使能MixDualMaster（双主模式）场景时，即模板参数enableMixDualMaster设置为true，不支持使用该接口。

#### 调用示例

```
REGIST_MATMUL_OBJ(&pipe, GetSysWorkSpacePtr(), mm, &tiling);
mm.SetTensorA(gm_a);
mm.SetTensorB(gm_b);
mm.SetTensorScaleA(gm_scaleA);    // 设置左矩阵的量化系数矩阵scaleA
mm.SetTensorScaleB(gm_scaleB);
if (tiling.isBias) {
    mm.SetBias(gmBias);
}
mm.IterateAll(gm_c);
mm.End();
```
