# GmAlloc

**页面ID:** atlasascendc_api_07_1207  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_1207.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | √ |

#### 功能说明

进行核函数的CPU侧运行验证时，用于创建共享内存：在/tmp目录下创建一个共享文件，并返回该文件的映射指针。

#### 函数原型

```
void *GmAlloc(size_t size)
```

#### 参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| size | 输入 | 用户想要申请的共享内存大小 |

#### 返回值说明

返回该共享内存空间的首地址。

#### 约束说明

该接口在系统的/tmp目录下生成临时文件，故需要磁盘空间足够才可以正常生成共享内存。

#### 调用示例

```
uint32_t numBlocks = 8;    // 总核数
uint32_t blockLength = 2048;    // 每个核分配的内存大小
size_t len = numBlocks * blockLength * sizeof(uint16_t);    // 共享内存大小
uint8_t* x = (uint8_t*)AscendC::GmAlloc(len);
```
