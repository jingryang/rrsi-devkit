# Comment

**页面ID:** atlasascendc_api_07_0975  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0975.html

---

#### 功能说明

设置input/output参数的注释。用于在自动生成算子原型头文件时，同步生成算子原型注释。

基于OpDef算子原型定义，自定义算子工程可以实现如下自动化能力：自动生成图模式场景使用的算子原型定义REG_OP（算子原型头文件），开发者可以使用生成的算子原型进行构图、图编译、图执行等操作。

生成的注释有助于辅助理解算子原型，并可以基于这些注释自动生成算子原型的文档说明。通常情况下，内置CANN算子使用较多。开发者可以按需使用。

#### 函数原型

```
OpParamDef &Comment(const char *comment)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| comment | 输入 | 注释内容。 |

#### 返回值说明

算子参数定义，OpParamDef请参考OpParamDef。

#### 约束说明

无

#### 调用示例

```
class AddCustom : public OpDef {
public:
    explicit AddCustom(const char* name) : OpDef(name)
    {
        this->Input("x")
            .ParamType(REQUIRED)
            .DataType({ge::DT_FLOAT, ge::DT_INT32})
            .FormatList({ge::FORMAT_ND})
            .Comment("Input cmt 1"); // 注释内容
        this->Input("y")
            .ParamType(REQUIRED)
            .Comment("Input cmt 2") // 注释内容
            .DataType({ge::DT_FLOAT, ge::DT_INT32})
            .FormatList({ge::FORMAT_ND});

        this->Output("z")
            .Comment("Output cmt 1") // 注释内容
            .ParamType(REQUIRED)
            .DataType({ge::DT_FLOAT, ge::DT_INT32})
            .FormatList({ge::FORMAT_ND});

        this->SetInferShape(ge::InferShape).SetInferDataType(ge::InferDataType);

        this->AICore()
            .SetTiling(optiling::TilingFunc);
        this->AICore().AddConfig("ascendxxx");

    }
};
```
