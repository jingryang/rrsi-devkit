# SetFmatrix

**页面ID:** atlasascendc_api_07_0245  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0245.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

用于调用Load3Dv1/Load3Dv2时设置FeatureMap的属性描述。Load3Dv1/Load3Dv2的模板参数isSetFMatrix设置为false时，表示Load3Dv1/Load3Dv2传入的FeatureMap的属性（包括l1H、l1W、padList，参数介绍参考表4 LoadData3DParamsV1结构体内参数说明、表5 LoadData3DParamsV2结构体内参数说明）描述不生效，开发者需要通过该接口进行设置。

#### 函数原型

```
__aicore__ inline void SetFmatrix(uint16_t l1H, uint16_t l1W, const uint8_t padList[4], const FmatrixMode& fmatrixMode)
```

#### 参数说明

**表1 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| l1H | 输入 | 源操作数height，取值范围：l1H∈[1, 32767]。 |
| l1W | 输入 | 源操作数width，取值范围：l1W∈[1, 32767] 。 |
| padList | 输入 | padding列表 [padding_left, padding_right, padding_top, padding_bottom]，每个元素取值范围：[0,255]。默认为{0, 0, 0, 0}。 |
| 用于控制LoadData指令从left还是right寄存器获取信息。FmatrixMode类型，定义如下。当前只支持FMATRIX_LEFT，左右矩阵均使用该配置。 ``` enum class FmatrixMode : uint8_t {     FMATRIX_LEFT = 0,     FMATRIX_RIGHT = 1, }; ``` |  |  |

#### 约束说明

- 该接口需要配合load3Dv1/load3Dv2接口一起使用，需要在load3Dv1/load3Dv2接口之前调用。

#### 调用示例

```
uint16_t channelSize = 32;
uint16_t H = 4, W = 4;
uint8_t Kh = 2, Kw = 2;
uint16_t Cout = 16;
uint16_t C0, C1;
uint8_t dilationH = 2, dilationW = 2;

uint8_t padList[PAD_SIZE] = {0, 0, 0, 0};
AscendC::SetFmatrix(H, W, padList, FmatrixMode::FMATRIX_LEFT); // 使能FM内存排布模式， 从left寄存器获取信息
AscendC::SetLoadDataPaddingValue(0);
AscendC::SetLoadDataRepeat({0, 1, 0});
AscendC::SetLoadDataBoundary((uint32_t)0);
static constexpr AscendC::IsResetLoad3dConfig LOAD3D_CONFIG = {false,false};
AscendC::LoadData<fmap_T, LOAD3D_CONFIG>(featureMapA2, featureMapA1,
    { padList, H, W, channelSize, k, howoRound, 0, 0, 1, 1, Kw, Kh, dilationW, dilationH, false, false, 0 });
AscendC::LoadData(weightB2, weightB1, { 0, weRepeat, 1, 0, 0, false, 0 });
```
