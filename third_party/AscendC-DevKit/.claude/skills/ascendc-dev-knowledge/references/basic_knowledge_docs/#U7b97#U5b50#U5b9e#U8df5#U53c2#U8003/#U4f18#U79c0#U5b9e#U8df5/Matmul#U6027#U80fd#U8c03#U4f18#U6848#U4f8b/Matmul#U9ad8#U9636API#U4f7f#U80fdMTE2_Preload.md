# Matmul高阶API使能MTE2 Preload

**页面ID:** atlas_ascendc_best_practices_10_10007  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/programug/Ascendcopdevg/atlas_ascendc_best_practices_10_10007.html

---

#### 案例介绍

本案例呈现了在矩阵乘算子场景中，使用Matmul高阶API进行矩阵乘法计算，使能MTE2 Preload对算子性能的提升效果**。**通过MatmulConfig中的doMTE2Preload参数开启矩阵M或N方向的预加载功能，预加载即在MTE2间隙提前加载A矩阵/B矩阵数据，开启预加载功能后，可以减少MTE2间隙，提升算子性能。doMTE2Preload参数的详细介绍请参考MatmulConfig。

- 使能MTE2 Preload的适用场景 

MTE2流水间隙较大，且M或N数值较大时。

- 使能MTE2 Preload的约束条件 

  - 仅在使用MDL模板和SpecialMDL模板时，MTE2 Preload有效。
  - 开启M或N方向预加载功能时，需保证K方向数据全载，且M或N方向开启DoubleBuffer。
  - K方向数据全载的条件是singleK <= baseK * stepK。
  - M方向开启DoubleBuffer的条件是depthA1 = stepM * stepK * 2。
  - N方向开启DoubleBuffer的条件是depthB1 = stepN * stepK * 2。

本案例的算子规格如下：

**表1 **算子规格

| 输入 | Shape | Data type | Format |
| --- | --- | --- | --- |
| a | 128, 512 | float16 | ND |
| b | 512, 24576 | float16 | ND |

当前案例使用的AI处理器共24个核，算子中使能高阶API Matmul的纯Cube模式。使用MDL模板，Tiling参数如下：

- 原始shape：M=128, N= 24576, K=512。
- 单核shape：singleCoreM=128，singleCoreN=1024，singleCoreK=512。
- 基本块shape：baseM=128，baseN=128，baseK=64。
- L1缓存相关Tiling参数：stepM=1，stepN=1，stepKa=8，stepKb=8，depthA1=8，depthB1=16。

#### 获取性能数据

使用msProf工具获取算子仿真流水图和上板Profiling数据，重点分析Cube，Fixpipe的流水情况。

#### 分析主要瓶颈点

- 优化前的流水图如下，M和K方向全载，因此A矩阵只搬运一次。由于N较大，B矩阵会搬运多次，可以看到单次MTE2间存在间隙。![](images/atlas_ascendc_best_practices_10_10007_img_001.png)
- 优化前的Profiling数据如下，aic_time平均耗时30.88us。![](images/atlas_ascendc_best_practices_10_10007_img_002.png)

#### 设计优化方案

使能MTE2 Preload功能：在创建Matmul对象时，开启doMTE2Preload开关。使能MTE2 Preload的完整样例请参考[M方向预加载Matmul算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/00_matrix/matmul_preload)。具体步骤如下：

1. 配置MDL模板参数，将其中的doMTE2Preload参数设置为2，使能N方向Preload功能。

```
// preloadMode = 2
static constexpr MatmulConfig MM_CFG = GetMDLConfig(false, false, preloadMode);
```

2. 基于自定义MatmulConfig模板参数，创建Matmul对象。

```
AscendC::Matmul<AscendC::MatmulType<AscendC::TPosition::GM, CubeFormat::ND, aType>,
    AscendC::MatmulType<AscendC::TPosition::GM, CubeFormat::ND, bType>,
    AscendC::MatmulType<AscendC::TPosition::GM, CubeFormat::ND, cType>,
    AscendC::MatmulType<AscendC::TPosition::GM, CubeFormat::ND, biasType>, MM_CFG> matmulObj;
```

#### 验证优化方案性能收益

- 优化后的流水图如下，Tiling参数不变，可以看到，下一次计算使用的B矩阵数据提前加载，MTE2间的间隙缩短。![](images/atlas_ascendc_best_practices_10_10007_img_003.png)
- 优化后的Profiling数据如下，aic_time平均耗时28.50us，较优化前的30.88us有所下降。![](images/atlas_ascendc_best_practices_10_10007_img_004.png)

#### 总结

当MTE2流水间隙较大，且M或N数值较大时，可以考虑使能MTE2 Preload功能，提前加载A矩阵或B矩阵数据。
