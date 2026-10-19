# msaicerr工具功能及约束

**页面ID:** troubleshooting_0099  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/troubleshooting/troubleshooting_0099.html

---

msaicerr工具可用于分析AI Core Error问题、解析Dump文件、转换Dump文件数据类型、检查环境。

1. 该工具仅支持**本地分析使用**，即部署该工具的环境应该和日志所在环境为同一环境（运行环境）。
2. 该工具依赖**python3.7.5或以上版本**，在安装该工具的环境中需提前安装python。
3. 该工具**不支持**在Ascend RC形态下使用。
4. 该工具暂不支持分析以下算子的AI Core Error问题：

  - MatmulAllReduce类算子
  - MatmulAllReduceAddRmsNorm
  - MatmulAllReduceInplaceAddRmsNorm
  - AllGatherMatmul
  - MatmulReduceScatter
  - GroupedMatmulAllReduce
  - MemSet
  - NonMaxSuppressionBucketize
