# 通过bisheng命令行编译

**页面ID:** atlas_ascendc_10_10074  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/programug/Ascendcopdevg/atlas_ascendc_10_10074.html

---

毕昇编译器是一款专为AI处理器设计的编译器，支持异构编程扩展，可以将用户编写的昇腾算子代码编译成二进制可执行文件和动态库等形式。毕昇编译器的可执行程序命名为bisheng，支持x86、aarch64等主机系统，并且原生支持设备侧AI Core架构指令集编译。通过使用毕昇编译器，用户可以更加高效地进行针对昇腾AI处理器的编程和开发工作。

#### 入门示例

以下是一个使用毕昇编译器编译的SIMT编程实现的Add算子入门示例。该示例展示了如何编写源文件add.asc以及具体的编译命令。通过这个示例，您可以了解如何使用毕昇编译器进行SIMT算子编译。完整样例请参考[LINK](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/03_simt_api/00_introduction/01_add)。

1. 包含头文件。

在编写算子源文件时，需要包含必要的头文件。

```
// 头文件
#include "acl/acl.h" // 调用核函数相关接口头文件
#include "asc_simt.h" // 核函数内调用SIMT API接口的头文件
```

2. 核函数实现。

核函数入参当前仅支持基础数据类型及其指针类型，核函数具体语法及约束说明参见核函数。

```
__global__ void add_custom(float* x, float* y, float* z, uint64_t total_length)
{
    // Calculate global thread ID
    int32_t idx = blockIdx.x * blockDim.x + threadIdx.x;
    // Maps to the row index of output tensor
    if (idx >= total_length) {
        return;
    }
    z[idx] = x[idx] + y[idx];
}
```

3. Host侧调用函数逻辑，包括内存申请和释放，初始化和去初始化，内核调用符调用核函数等。

```
// Host侧应用程序需要包含的头文件
#include "acl/acl.h"

// 核函数实现
__global__ void add_custom(float* x, float* y, float* z, uint64_t total_length)
{
    ...
}

// 通过<<<...>>>内核调用符调用算子
std::vector<float> add(std::vector<float>& x, std::vector<float>& y)
{
    ...
    // Call kernel funtion with <<<...>>>
    add_custom<<<...>>>(...));
    ...
}

// 计算结果比对
uint32_t verify_result(std::vector<float>& output, std::vector<float>& golden)
{
    ...
}

// 算子验证主程序
int32_t main(int32_t argc, char *argv[])
{
    constexpr uint32_t in_shape = 48 * 256;
    std::vector<float> x(in_shape);
    for (uint32_t i = 0; i < in_shape; i++) {
        x[i] = i * 1.1f;
    }
    std::vector<float> y(in_shape);
    for (uint32_t i = 0; i < in_shape; i++) {
        y[i] = i + 3.4f;
    }
    std::vector<float> golden(in_shape);
    for (uint32_t i = 0; i < in_shape; i++) {
        golden[i] = x[i] + y[i];
    }
    std::vector<float> output = add(x, y);
    return verify_result(output, golden);
}
```

4. 采用如下的编译命令进行编译。

```
bisheng -x asc add.asc -o demo --npu-arch=dav-3510 --enable-simt
```

  - -x asc：-x指定编译语言，asc表示编程语言为Ascend C。
  - -o demo：指定输出文件名为demo。
  - --npu-arch=dav-3510：指定NPU的架构版本为dav-3510。dav-后为NPU架构版本号，各产品型号对应的架构版本号请通过对应关系表进行查询。
  - --enable-simt： SIMT编译的固定选项。

5. 执行可执行文件。

```
./demo
```

#### 程序的编译与执行

通过毕昇编译器可以将算子源文件（以.asc为后缀）编译为当前平台的可执行文件。此外，也支持使用-x asc编译选项编译以.cpp/.c等为后缀的C++/C源文件。

```
# bisheng -x asc [算子源文件] -o [输出产物名称] --npu-arch=[NPU架构版本号] --enable-simt，常见参数顺序与g++保持一致。
# C++源文件
bisheng -x asc add_custom.cpp -o add_custom --npu-arch=dav-xxxx --enable-simt
# 后缀为.asc的算子源文件
bisheng -x asc add_custom.asc -o add_custom --npu-arch=dav-xxxx --enable-simt
```

生成的可执行文件可通过如下方式执行：

```
./add_custom
```

在命令行编译场景下，可以按需链接需要的库文件，编译时会默认链接表1中列出的库文件。
