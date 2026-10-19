# Init

**页面ID:** atlasascendc_api_07_0111  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0111.html

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

用于内存和同步流水事件EventID的初始化。

#### 函数原型

```
__aicore__ inline void Init()
```

#### 约束说明

重复申请释放tpipe，要与Destroy接口成对使用，tpipe如果要重复申请需要先Destroy释放后再Init。

#### 调用示例

```
// 实例化一个浮点型的自定义算子对象
KernelInit<float> op;
uint32_t srcSize = 128;

// 第一次执行流程：使用pipeIn管道
AscendC::TPipe pipeIn;
pipeIn.Init();  // 初始化pipeIn管道资源
op.Init(x, z, srcSize, &pipeIn);
op.Process();
pipeIn.Destroy();  // 销毁pipeIn管道资源

// 第二次执行流程：复用算子对象，但更换为pipeCast管道
AscendC::TPipe pipeCast;
pipeCast.Init();  // 初始化pipeCast管道资源
op.Init(x, z, srcSize, &pipeCast);
op.Process();
pipeCast.Destroy();  // 销毁pipeCast管道资源
```
