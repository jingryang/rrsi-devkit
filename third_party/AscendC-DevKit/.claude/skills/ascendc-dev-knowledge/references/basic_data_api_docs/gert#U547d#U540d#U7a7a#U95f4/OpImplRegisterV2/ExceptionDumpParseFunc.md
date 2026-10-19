# ExceptionDumpParseFunc

**页面ID:** atlasopapi_07_00794  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00794.html

---

#### 函数功能

注册一个异常处理函数，在算子发生aic error时，执行用户定义的异常处理逻辑。

#### 函数原型

```
OpImplRegisterV2 &ExceptionDumpParseFunc(ExceptionDumpFunc exception_func)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| 待注册的ExceptionDumpFunc函数。 ExceptionDumpFunc类型定义如下： ``` using ExceptionDumpFunc = void (*)(aclrtExceptionInfo *exception_info, void *reserved); ``` |  |  |

#### 返回值说明

返回算子的OpImplRegisterV2对象本身，该对象新增注册ExceptionDumpFunc函数。

#### 约束说明

无
