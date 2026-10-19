# 通过CMake编译

**页面ID:** atlas_ascendc_10_10076  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/programug/Ascendcopdevg/atlas_ascendc_10_10076.html

---

项目中可以使用CMake来更简便地使用毕昇编译器编译Ascend C SIMT算子，生成可执行文件。

以下是CMake脚本的示例及其核心步骤说明：

```
cmake_minimum_required(VERSION 3.16)

# 1、find_package(ASC)是CMake中用于查找和配置Ascend C编译工具链的命令
find_package(ASC)  

# 2、指定项目支持的语言包括ASC和CXX，ASC表示支持使用毕昇编译器对Ascend C编程语言进行编译
project(kernel_samples LANGUAGES ASC CXX)

# 3、使用CMake接口编译可执行文件
add_executable(demo
    add_custom.asc
)
#.....
target_compile_options(demo PRIVATE
    # --npu-arch用于指定NPU的架构版本，dav-后为架构版本号
    # <COMPILE_LANGUAGE:ASC>:表明该编译选项仅对语言ASC生效
    $<$<COMPILE_LANGUAGE:ASC>: --npu-arch=dav-3510>
    # 开启SIMT编程模型的编译功能 
    --enable-simt   
)
```

下文列出了使用CMake编译时默认链接库。

**表1 **默认链接库

| 名称 | 作用描述 |
| --- | --- |
| libascendc_runtime.a | Ascend C算子参数等组装库。 |
| libruntime.so | Runtime运行库。 |
| libprofapi.so | Ascend C算子运行性能数据采集库。 |
| libunified_dlog.so | CANN日志收集库。 |
| libmmpa.so | CANN系统接口库。 |
| libascend_dump.so | CANN维测信息库。 |
| libc_sec.so | CANN安全函数库。 |
| liberror_manager.so | CANN错误信息管理库。 |
| libascendcl.so | acl相关接口库。 |
