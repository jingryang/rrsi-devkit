# SetSubBlockIdx

**页面ID:** atlasascendc_api_07_0662  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0662.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

设置当前AIV核的ID。分离架构下，一个AI Core由Cube Core（AIC）和Vector Core（AIV）按照一定比例1：N进行组合，其中N个AIV核的ID分别为0, 1, ..., N-1。

#### 函数原型

```
__aicore__ inline void SetSubBlockIdx(uint8_t subBlockIdx)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| subBlockIdx | 输入 | 当前AIV核的ID。 |

#### 约束说明

- 该接口仅支持在分离架构下使用。
- 在分离架构中，AIV核的ID会在REGIST_MATMUL_OBJ()接口内部自动初始化和赋值。如果在算子程序中使用了REGIST_MATMUL_OBJ()接口，则不建议调用此接口；若未使用REGIST_MATMUL_OBJ()接口，则请调用此接口并将子核ID设置为0。

#### 调用示例

```
typedef AscendC::MatmulType<AscendC::TPosition::GM, CubeFormat::ND, half> aType; 
typedef AscendC::MatmulType<AscendC::TPosition::GM, CubeFormat::ND, half> bType; 
typedef AscendC::MatmulType<AscendC::TPosition::GM, CubeFormat::ND, float> cType; 
typedef AscendC::MatmulType<AscendC::TPosition::GM, CubeFormat::ND, float> biasType; 

MatmulImpl<aType, bType, cType, biasType, CFG_NORM> mm;
mm.SetSubBlockIdx(0);  // 子核ID设置为0
```
