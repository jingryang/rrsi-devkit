# ReadGmByPassDCache(ISASI)

**页面ID:** atlasascendc_api_07_00090  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00090.html

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

不经过DCache从GM地址上读数据。

当多核操作GM地址时，如果数据无法对齐到Cache Line，经过DCache的方式下，由于按照Cache Line大小进行读写，会导致多核数据随机覆盖的问题。此时，可以采用不经过DCache直接读写GM地址的方式，从而避免上述随机覆盖的问题。

#### 函数原型

```
template <typename T>
__aicore__ inline T ReadGmByPassDCache(__gm__ T* addr)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t、uint8_t、int16_t、uint16_t、int32_t、uint32_t、int64_t、uint64_t。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 含义 |
| --- | --- | --- |
| addr | 输入 | 源GM地址。 |

#### 返回值说明

源GM地址上的数据。

#### 约束说明

连续使用（Polling）该接口，用于进行多核同步，会造成Bus被长期占用，导致其他核无法访问该GM，导致多核读同一GM出现卡死现状，若需要Polling，建议在该使用接口间，增加Nop指令，指令量建议为800个，一般为需要同步的核数 * 200。

#### 调用示例

```
__gm__ int32_t* addr = srcGlobal.GetPhyAddr();
int32_t value = ReadGmByPassDCache(addr);

// 通过Scalar读写相同GM时，需要让读操作，空出总线，避免长时占用
int target = -1;
while (target != 0) {
     target = ReadGmByPassDCache(addr);
     Nop<800>();
}
```
