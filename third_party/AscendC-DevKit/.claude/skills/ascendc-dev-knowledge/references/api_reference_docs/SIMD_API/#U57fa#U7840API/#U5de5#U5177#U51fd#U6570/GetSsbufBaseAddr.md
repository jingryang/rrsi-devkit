# GetSsbufBaseAddr

**页面ID:** atlasascendc_api_07_00266  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00266.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

该接口用于获取SSBuffer的基地址。

#### 函数原型

```
__aicore__ inline __ssbuf__ void*  GetSsbufBaseAddr()
```

#### 参数说明

无

#### 返回值说明

返回指向SSBuffer基地址的指针。

#### 约束说明

- SSBuffer中存在脏数据，读取时数据时不保证全为0。
- AIC和AIV启动不同的任务时，不能访问SSBuffer。
- 访问超过最末端的地址存在异常。每个核在非MIX模式下运行时，可以独立占用1KB的空间（AIC，AIV0，AIV1各占据1KB）；或者在Mix模式下运行时共享整个3KB的空间(AIC:AIV = 1:2)。目前ssbuf的大小为3KB。
- 只支持通过读写指令32B,64B 的对齐访问。

#### 调用示例

```
__ssbuf__ void* ssbuf = GetSsbufBaseAddr(); // NPU域中返回(void*) 0 ,CPU域中返回CPU模拟分配的地址
AscendC::printf("Ssbuf基地址指针： %p\n", ssbuf ); // %p为打印指针格式符，NPU环境中，将特殊的 0 指针值显示为 nil
AscendC::PRINTF("Ssbuf基地址指针： %p\n", ssbuf ); //输出为nil
```
