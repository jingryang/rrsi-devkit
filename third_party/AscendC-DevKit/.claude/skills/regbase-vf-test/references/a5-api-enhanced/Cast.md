# Cast

**页面ID:** atlasascendc_api_07_0398  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0398.html

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

数据类型精度转换，将U类型的源操作数根据指定的转换模式，转换成T类型的目的操作数类型。

#### 函数原型

```
template <typename T = DefaultType, typename U = DefaultType, const CastTrait& trait = castTrait, typename S, typename V>
__simd_callee__ inline void Cast(S& dstReg, V& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数数据类型。 |
| U | 源操作数数据类型。 |
| trait | 类型转换模式结构体。 包括RegLayout、SatMode、MaskMergeMode、RoundMode。 使能SatMode生效需与SetCtrlSpr(ISASI)配合使用。 |
| S | srcReg类型，例如RegTensor<float>，由编译器自动推导，用户不需要填写。 |
| V | dstReg类型，例如RegTensor<int32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 Atlas 350 加速卡支持的数据类型参考表3、表4、表5、表6。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 Atlas 350 加速卡支持的数据类型参考表3、表4、表5、表6。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 注意：数据类型转换的mask会按照输入和输出类型中sizeof(dtype)较大的来筛选。 |

**表3 **浮点转整数

| src dtype | dst dtype | mode | round mode | sat mode | layout mode |
| --- | --- | --- | --- | --- | --- |
| half | int4x2_t | MaskMergeMode::ZEROING | RoundMode::CAST_RINT, RoundMode::CAST_ROUND, RoundMode::CAST_FLOOR, RoundMode::CAST_CEIL, RoundMode::CAST_TRUNC | SatMode::NO_SAT SatMode::SAT | RegLayout::ZERO, RegLayout::ONE, RegLayout::TWO, RegLayout::THREE |
| float | int16_t | RegLayout::ZERO RegLayout::ONE |  |  |  |
| half | int8_t |  |  |  |  |
| half | uint8_t |  |  |  |  |
| float | int64_t |  |  |  |  |
| float | int32_t | RegLayout::UNKNOWN |  |  |  |
| half | int16_t |  |  |  |  |
| half | int32_t | SatMode::UNKNOWN | RegLayout::ZERO RegLayout::ONE |  |  |

**表4 **浮点转浮点

| src dtype | dst dtype | mode | round mode | sat mode | layout mode |
| --- | --- | --- | --- | --- | --- |
| half | float | MaskMergeMode::ZEROING | RoundMode::UNKNOWN | SatMode::UNKNOWN | RegLayout::ZERO RegLayout::ONE |
| bfloat16_t | float |  |  |  |  |
| hifloat8_t | half |  |  |  |  |
| float | bfloat16_t | RoundMode::CAST_RINT, RoundMode::CAST_ROUND, RoundMode::CAST_FLOOR, RoundMode::CAST_CEIL, RoundMode::CAST_TRUNC | SatMode::NO_SAT SatMode::SAT |  |  |
| float | half | RoundMode::CAST_ODD， RoundMode::CAST_RINT, RoundMode::CAST_ROUND, RoundMode::CAST_FLOOR RoundMode::CAST_CEIL, RoundMode::CAST_TRUNC |  |  |  |
| half | hifloat8_t | RoundMode::CAST_ROUND, RoundMode::CAST_HYBRID |  |  |  |
| float | hifloat8_t | RegLayout::ZERO, RegLayout::ONE, RegLayout::TWO, RegLayout::THREE |  |  |  |
| float | fp8_e5m2_t | RoundMode::CAST_RINT |  |  |  |
| float | fp8_e4m3fn_t |  |  |  |  |
| hifloat8_t | float | RoundMode::UNKNOWN | SatMode::UNKNOWN |  |  |
| fp8_e4m3fn_t | float |  |  |  |  |
| fp8_e5m2_t | float |  |  |  |  |
| bfloat16_t | fp4x2_e2m1_t | RoundMode::CAST_RINT, RoundMode::CAST_ROUND, RoundMode::CAST_FLOOR, RoundMode::CAST_CEIL, RoundMode::CAST_TRUNC | RegLayout::UNKNOWN |  |  |
| bfloat16_t | fp4x2_e1m2_t |  |  |  |  |
| fp4x2_e2m1_t | bfloat16_t | RoundMode::UNKNOWN |  |  |  |
| fp4x2_e1m2_t | bfloat16_t |  |  |  |  |
| bfloat16_t | half | RoundMode::CAST_RINT, RoundMode::CAST_ROUND, RoundMode::CAST_FLOOR, RoundMode::CAST_CEIL, RoundMode::CAST_TRUNC | SatMode::NO_SAT SatMode::SAT |  |  |
| half | bfloat16_t | SatMode::UNKNOWN |  |  |  |
| bfloat16_t | fp8_e8m0_t | RoundMode::UNKNOWN | RegLayout::ZERO RegLayout::ONE |  |  |
| fp8_e8m0_t | bfloat16_t |  |  |  |  |

**表5 **整数转浮点

| src dtype | dst dtype | mode | round mode | layout mode |
| --- | --- | --- | --- | --- |
| int4x2_t | half | MaskMergeMode::ZEROING | RoundMode::UNKNOWN | RegLayout::ZERO, RegLayout::ONE, RegLayout::TWO, RegLayout::THREE |
| int4x2_t | bfloat16_t |  |  |  |
| uint8_t | half | RegLayout::ZERO RegLayout::ONE |  |  |
| int8_t | half |  |  |  |
| int16_t | float |  |  |  |
| int64_t | float | RoundMode::CAST_RINT, RoundMode::CAST_ROUND, RoundMode::CAST_FLOOR, RoundMode::CAST_CEIL, RoundMode::CAST_TRUNC |  |  |
| int16_t | half | RegLayout::UNKNOWN |  |  |
| int32_t | float |  |  |  |

**表6 **整数转整数

| src dtype | dst dtype | mode | sat mode | layout mode |
| --- | --- | --- | --- | --- |
| uint32_t | uint8_t | MaskMergeMode::ZEROING | SatMode::NO_SAT SatMode::SAT | RegLayout::ZERO, RegLayout::ONE, RegLayout::TWO, RegLayout::THREE |
| int32_t | uint8_t |  |  |  |
| uint16_t | uint8_t | RegLayout::ZERO RegLayout::ONE |  |  |
| int16_t | uint8_t |  |  |  |
| uint32_t | uint16_t |  |  |  |
| uint32_t | int16_t |  |  |  |
| int32_t | uint16_t |  |  |  |
| int32_t | int16_t |  |  |  |
| uint8_t | uint16_t | RoundMode::UNKNOWN |  |  |
| int8_t | int16_t |  |  |  |
| uint16_t | uint32_t |  |  |  |
| int16_t | uint32_t |  |  |  |
| int16_t | int32_t |  |  |  |
| int32_t | int64_t |  |  |  |
| uint8_t | uint32_t | RegLayout::ZERO, RegLayout::ONE, RegLayout::TWO, RegLayout::THREE |  |  |
| int8_t | int32_t |  |  |  |
| int16_t | int4x2_t |  |  |  |
| int4x2_t | int16_t |  |  |  |
| int64_t | int32_t | SatMode::NO_SAT SatMode::SAT | RegLayout::ZERO RegLayout::ONE |  |

**表7 **浮点转整数转换规则

| 转换模式 | 转换规则介绍 |
| --- | --- |
| CAST_RINT | 就近舍入，距离相同时向偶数进位。 举例： 输入3.3，输出3 输入5.9，输出6 输入5.5，输出6，因为6是偶数，5是奇数，所以向6舍入 输入4.5，输出4，4是偶数 输入-2.4，输出2 输入-3.6，输出-4 |
| CAST_ROUND | 就近舍入，距离相同时向远离0的数值进位。 举例： 输入3.3，输出3 输入5.9，输出6 输入5.5，输出6，因为6相比5，距离0更远，所以向6舍入 输入-2.4，输出2 输入-3.6，输出-4 输入-6.5，输出-7， 因为-7相比-6，距离0更远 |
| CAST_FLOOR | 向负无穷方向舍入。 举例： 输入3.2，输出3 输入7.9，输出7 输入-4.6，输出-5 输入-3.1，输出-4 相比输入，输出更接近负无穷 |
| CAST_CEIL | 向正无穷方向舍入。 举例： 输入3.2，输出4 输入7.9，输出8 输入-4.6，输出-4 输入-3.1，输出-3 相比输入，输出更接近正无穷 |
| CAST_TRUNC | 向0方向舍入。 举例： 输入3.2，输出3 输入7.9，输出7 输入-4.6，输出-4 输入-3.1，输出-3 相比输入，输出更接近0 |

**表8 **浮点转浮点转换规则

| src dtype | dst dtype | 舍入规则 |
| --- | --- | --- |
| float | half | **CAST_ODD**，向奇数方向舍入。 half有尾数位10bit，float有尾数位23bit，float转half舍弃精度13bit，float16最低位标记为黄色y，float舍弃精度标记为红色 float +/-a.xxxxxxxxx00000100000000，如果y bit位为0偶数，则进位，得到half a.xxxxxxxxx1 float +/-a.xxxxxxxxx11000100000000，如果y bit位为1奇数，则不进位，得到half a.xxxxxxxxx1 **举例** 输入float 123.23333，二进制为 sign:0, exponent:10000101, mantissa:11101100111011101110111 float_exponet = 0b10000101 = 133 half_exponet - 15 = 133 - 127 half_exponet  = 21 = 0b10101 float_mantissa 第14位为1奇数，所以不进位，舍弃后面13位 11101100111011101110111 得到half_mantissa = 1110110011 所以half二进制为 sign:0, exponent:10101, mantissa:1110110011 half = 123.2 |
| float | bfloat16_t | float 二进制规则为 sign:1bit,exponent:8bit mantissa:23bit bfloat16_t二进制规则为 sign:1bit,exponent:8bit,mantissa:7bit **CAST_RINT****：**就近舍入，距离相等时向偶数进位 举例 1、float32_mantissa:00100000010000010000000 舍弃精度小于0b1000000000000000，等效于0, 0.5），则不进位 得到bfloat16_mantissa:0010000 2、float32_mantissa:00110001000000000000000 舍弃精度等于0b1000000000000000，bf16最低位为偶数时不进位 得到bfloat16_mantissa:0011000 3、float32_mantissa:00110011000000000000000 舍弃精度等于0b1000000000000000，bf16最低位为奇数时进位 得到bfloat16_mantissa:0011010 4、float32_mantissa:00100001010000010000000 舍弃精度大于0b1000000000000000，等效于(0.5, 1），则进位 得到bfloat16_mantissa:0010001 **CAST_ROUND****：**就近舍入，距离相等时向远离0方向进位 举例 1、float32_mantissa:00100000010000010000000 舍弃精度小于0b1000000000000000，等效于[0, 0.5），则不进位 得到bfloat16_mantissa:0010000 2、float32_mantissa:00110001000000000000000 舍弃精度等于0b1000000000000000，进位后离0越远，所以进位 得到bfloat16_mantissa:0011001 3、float32_mantissa:00100001010000010000000 舍弃精度大于0b1000000000000000，等效于(0.5, 1），则进位 得到bfloat16_mantissa:0010001 **CAST_FLOOR****：**向负无穷方向舍入 1、float32_mantissa:00100000010000010000000，float32值正数时不进位，得到bfloat16_mantissa:0010000 2、float32_mantissa:00110001000000000000000 float32 值负数时进位，得到bfloat16_mantissa:0011001 **CAST_CEIL****：**向正无穷方向舍入 1、float32_mantissa:00100000010000010000000，float32值正数时进位，得到bfloat16_mantissa:0010001 2、float32_mantissa:00110001000000000000000 float32 值负数时不进位，得到bfloat16_mantissa:0011000 **CAST_TRUNC****：**向0方向舍入 1、float32_mantissa:00100000010000010000000，都不进位，直接舍弃红色精度，得到bfloat16_mantissa:001000 **完整举例****：**输入float32 205.75，二进制为 sign:0, exponent:10000110, mantissa:10011011100000000000000 CAST_RINT模式 float32_mantissa = 0b10011011100000000000000 舍弃精度大于0b1000000000000000，等效于(0.5, 1），则进位 得到bfloat16_mantinssa = 0b1001110 所以bfloat16二进制为 sign:0, exponent:10000110, mantissa:1001110 bfloat16 = 206 |
| bfloat16_t | half | bfloat16_t二进制规则为 sign:1bit,exponent:8bit,mantissa:7bit float16二进制规则为 sign:1bit,exponent:5bit,mantissa:10bit 尾数位相差3位 当bfloat16_exponent = exponent-127 >= -14时 因为bfloat16精度低，float16精度高，所以bfloat16到float16精度不变 **例1**：bfloat16_mantissa = 0b1011000 -> float16_maintissa = 0b1011000000, 二进制位不发生进位，只需要再低位补3个0 当bfloat16_exponent = exponent-127 < -14时 **例2**：当exponent = 108， bfloat16_exponent = exponent-127 = -19< -14时，因为float16_exponent = exponent - 14 最小为-14，无法表示，所以指数需要+5保持和float16_exponent相等，同时尾数位需要除以2的5次方，因为bf16计算公式 = s * (2^(e-127))*(man) = s * (2^(e-127+5))*(man*2^(-5)),指数位乘以一个数，尾数位需要除以相同大小的数，保证最终值不变。假设bfloat16_mantissa = 0b1011011 bfloat16 mantissa计算公式为 1+ man/128, 用例二进制表示为 0b1.1011011，指数位乘以2的5次方时，尾数要除以2的5次，小数点向左移动5位，所以bfloat16_mantissa = 0b0.000011011011，尾数为12位，因为float16只有10bit尾数位，所以在以下CAST模式中需要舍弃最低2位，并根据舍入模式决定是否舍入，当前例子的舍弃精度中间值为0b10 **CAST_RINT****：**就近舍入，距离相等时向偶数进位 当bfloat16_mantissa尾数小于等于10位时，不需要舍入； 当bfloat16_mantissa尾数大于10位时，类似**例2**的例子 1）被舍弃的精度小于舍弃精度中间值时，不进位， 例bfloat16_mantissa = 0b0.00001101100xxx 0xxx < 1000 输出float16_mantissa = 0b0.0000110110 2）被舍弃的精度大于舍弃精度中间值时，进位 例bfloat16_mantissa = 0b0.00001101100xxx 1x1x > 1000 输出float16_mantissa = 0b0.0000110111 3) 被舍弃的精度等于舍弃精度中间值时，第10位为偶数时不进位 例bfloat16_mantissa = 0b0.00001101100xxx 0 % 2 == 0 输出float16_mantissa = 0b0.0000110110 4) 被舍弃的精度等于舍弃精度中间值时，第10位为奇数时进位 例bfloat16_mantissa = 0b0.00001100010xxx 1 % 2 == 1 输出float16_mantissa = 0b0.0000110001 **CAST_ROUND****：**就近舍入，距离相等时向远离0方向进位 当bfloat16_mantissa尾数小于等于10位时，不需要进位； 当bfloat16_mantissa尾数大于10位时，类似**例2**的例子 1）被舍弃的精度小于舍弃精度中间值时，不进位， 例bfloat16_mantissa = 0b0.00001101100xxx 0xxx < 1000 输出float16_mantissa = 0b0.0000110110 2）被舍弃的精度大于舍弃精度中间值时，进位 例bfloat16_mantissa = 0b0.00001101100xxx 1x1x > 1000 输出float16_mantissa = 0b0.0000110111 3) 被舍弃的精度等于舍弃精度中间值时，进位远离0，所以进位 例bfloat16_mantissa = 0b0.00001101100xxx 输出float16_mantissa = 0b0.0000110111 **CAST_FLOOR****：**向负无穷方向舍入 当bfloat16_mantissa尾数小于等于10位时，不需要进位； 当bfloat16_mantissa尾数大于10位时，类似**例2**的例子 1）符号位S为0，既正数时不舍入， 例bfloat16_mantissa = 0b0.00001101100xxx 输出float16_mantissa = 0b0.0000110110 2）符号位S为1，既负数时舍入 例bfloat16_mantissa = 0b0.00001101100xxx 输出float16_mantissa = 0b0.0000110111 **CAST_CEIL****：**向正无穷方向舍入 当bfloat16_mantissa尾数小于等于10位时，不需要舍入； 当bfloat16_mantissa尾数大于10位时，类似**例2**的例子 1）符号位S为0，既正数时舍入， 例bfloat16_mantissa = 0b0.00001101100xxx 输出float16_mantissa = 0b0.0000110111 2）符号位S为1，既负数时不舍入 例bfloat16_mantissa = 0b0.00001101100xxx 输出float16_mantissa = 0b0.0000110110 **CAST_TRUNC****：**向0方向舍入 当bfloat16_mantissa尾数小于等于10位时，不需要舍入； 当bfloat16_mantissa尾数大于10位时，类似**例2**的例子 1）直接舍弃多余精度，不舍入 例bfloat16_mantissa = 0b0.00001101100xxx 输出float16_mantissa = 0b0.0000110110 **完整举例**： 输入bfloat16为2.90573e-06，二进制为 sign:0, exponent:01101100, mantissa:1000011 bfloat16_exponent = 108-127 = -19 < -14，float16_exponent最小为-14，所以bfloat16_exponent += 5，bfloat16_mantissa 小数点左移 5位，1.1000011 -> 0.000011000011 CAST_RINT模式 舍弃精度11大于舍弃精度中间值10，所以进位 bfloat16_mantissa = 0.0000110001 最终float16二进制为 sign:0, exponent: 00000, mantissa = 0000110001 按照计算公式十进制表示为 float16=0.00000293 |
| half | bfloat16_t | half二进制规则为 sign:1bit,exponent:5bit,mantissa:10bit bfloat16_t二进制规则为 sign:1bit,exponent:8bit,mantissa:7bit **CAST_RINT：**就近舍入，距离相同时向偶数舍入 1）当舍弃精度小于舍弃精度中间值100时，不舍入 例half_mantinssa = 0111010011 输出bfloat16_mantissa = 0111010 2）当舍弃精度大于舍弃精度中间值100时，舍入 例half_mantinssa = 0111010111 输出bfloat16_mantissa = 0111011 3）当舍入精度等于舍弃精度中间值100时，bfloat16最低位为偶数，不舍入 例half_mantinssa = 0111010100 输出bfloat16_mantissa = 0111010 4）当舍入精度等于舍弃精度中间值100时，bfloat16最低位为奇数， 舍入 例half_mantinssa = 0111010100 输出bfloat16_mantissa = 0111011 **CAST_ROUND：**就近舍入，距离相同时远离0舍入 1）当舍弃精度小于舍弃精度中间值100时，不舍入 例half_mantinssa = 0111010011 输出bfloat16_mantissa = 0111010 2）当舍弃精度大于舍弃精度中间值100时，舍入 例half_mantinssa = 0111010111 输出bfloat16_mantissa = 0111011 3）当舍入精度等于舍弃精度中间值100时，进位远离0，所以舍入 例half_mantinssa = 0111010100 输出bfloat16_mantissa = 0111011 **CAST_FLOOR：**向负无穷方向舍入 1）当输入值为正数时，不舍入 例half_mantinssa = 0111010011 输出bfloat16_mantissa = 0111010 2）当输入值为负数时，舍入 例half_mantinssa = 0111010011 输出bfloat16_mantissa = 0111011 **CAST_CEIL：**向正无穷方向舍入 1）当输入值为正数时，舍入 例half_mantinssa = 0111010011 输出bfloat16_mantissa = 0111011 2）当输入值为负数时，不舍入 例half_mantinssa = 0111010011 输出bfloat16_mantissa = 0111010 **CAST_TRUNC：**向0方向舍入 直接舍弃多余精度 例half_mantinssa = 0111010011 输出bfloat16_mantissa = 0111010 **完整举例：** 输入half 0.131 二进制为sign:0, exponent:01100, mantissa:0000110001 half_exponent = 12-15 = bfloat16_exp - 127 bfloat16_exp = 124 = 0b1111100 CAST_ROUND模式下 half_mantissa = 0000110001 舍弃精度小于舍弃中间精度100，不进位，所以得到 bfloat16_mantissa = 0000110 所以bfloat16二进制为 sign:0, exponent:1111100, mantissa: 0000110 按照计算公式十进制表示为 bfloat16=0.130859 |
| float | fp8_e4m3fn_t | float 二进制规则为 sign:1bit,exponent:8bit mantissa:23bit fp8_e4m3fn_t二进制规则为 sign:1bit,exponent:4bit,mantissa:3bit 需要舍弃20bit，舍弃精度中间值为0b10000000000000000000 **CAST_RINT：**就近舍入，距离相同时向偶数舍入 1）当舍弃精度小于舍弃精度中间值时，不舍入 例float_mantinssa = 01100100110000000000000 输出fp8_e4m3fn_t_mantissa = 011 2）当舍弃精度大于舍弃精度中间值时，舍入 例float_mantinssa= 01110100110000000000000 输出fp8_e4m3fn_t_mantissa  = 100 3）当舍入精度等于舍弃精度中间值时，fp8_e4m3fn_t最低位为偶数，不舍入 例float_mantinssa= 01010000000000000000000 输出fp8_e4m3fn_t_mantissa = 010 4）当舍入精度等于舍弃精度中间值时，fp8_e4m3fn_t最低位为奇数， 舍入 例float_mantinssa= 01110000000000000000000 输出fp8_e4m3fn_t_mantissa = 100 **完整例子：** 输入float 1.233 二进制为 sign:0, exponent:01111111, mantissa:00111011101001011110010 float_exponent = 127-127 = fp8_e4m3fn_t_exp - 7 fp8_e4m3fn_t_exp = 7 = 0b0111 CAST_RINT模式下 float_mantissa = 00111011101001011110010 舍弃精度大于舍弃中间精度，进位，所以得到 fp8_e4m3fn_t_mantissa = 010 所以fp8_e4m3fn_t二进制为 sign:0, exponent:0111, mantissa: 010 按照计算公式十进制表示为 fp8_e4m3fn_t=1.25 |
| float | fp8_e5m2_t | float 二进制规则为 sign:1bit,exponent:8bit mantissa:23bit fp8_e5m2_t二进制规则为 sign:1bit,exponent:5bit,mantissa:2bit 需要舍弃21bit，舍弃精度中间值为0b100000000000000000000 **CAST_RINT：**就近舍入，距离相同时向偶数舍入 1）当舍弃精度小于舍弃精度中间值时，不舍入 例float_mantinssa = 01000100110000000000000 输出fp8_e5m2_t_mantissa = 01 2）当舍弃精度大于舍弃精度中间值时，舍入 例float_mantinssa= 01101001100000000000000 输出fp8_e5m2_t_mantissa  = 10 3）当舍入精度等于舍弃精度中间值时，fp8_e5m2_t最低位为偶数，不舍入 例float_mantinssa= 00100000000000000000000 输出fp8_e5m2_t_mantissa = 00 4）当舍入精度等于舍弃精度中间值时，fp8_e5m2_t最低位为奇数， 舍入 例float_mantinssa= 0110000000000000000000 输出fp8_e5m2_t_mantissa = 10 **完整例子：** 输入float32 1.233 二进制为 sign:0, exponent:01111111, mantissa:00111011101001011110010 float_exponent = 127-127 = fp8_e5m2_t_exp - 15 fp8_e5m2_t_exp = 15 = 0b01111 CAST_RINT模式下 float_mantissa = 00111011101001011110010 舍弃精度大于舍弃中间精度，进位，所以得到 fp8_e5m2_t_mantissa = 01 所以fp8_e5m2_t二进制为 sign:0, exponent:01111, mantissa: 01 按照计算公式十进制表示为 fp8_e5m2_t=1.25 |
| bfloat16_t | fp4x2_e2m1_t | bfloat16二进制规则为 sign:1bit,exponent:8bit,mantissa:7bit fp4x2_e2m1_t二进制规则为 sign:1bit,exponent:2bit,mantissa:1bit 尾数位相差6位 当bfloat16_exponent = exponent-127 < 0时 **例1**：当exponent = 124， bfloat16_exponent = exponent-127 = -3 < 0时，因为float4_e2m1_exponent = exponent - 1 最小为0，无法表示，所以指数需要+3保持和float4_e2m1_exponent相等，同时尾数位需要除以2的3次方，因为bf16计算公式 = s * (2^(e-127))*(man) = s * (2^(e-127+3))*(man*2^(-3)),指数位乘以一个数，尾数位需要除以相同大小的数，保证最终值不变。假设bfloat16_mantissa = 0b1011011 bfloat16 mantissa计算公式为 1+ man/128, 用例二进制表示为 0b1.1011011，指数位乘以2的3次方时，尾数要除以2的3次，小数点向左移动3位，所以bfloat16_mantissa = 0b0.0011011011，因为float4_e2m1只有1bit尾数位，所以在以下CAST模式中需要舍弃最低9位，并根据舍入模式决定是否舍入，当前例子的舍弃精度中间值为0b100000000 **CAST_RINT****：**就近舍入，距离相等时向偶数进位 1）被舍弃的精度小于舍弃精度中间值时，不进位， 例bfloat16_mantissa = 0b0.0000110xxx 000110xxx < 舍弃精度中间值 输出float4_e2m1_mantissa = 0b0.0 2）被舍弃的精度大于舍弃精度中间值时，进位 例bfloat16_mantissa = 0b0.0100110xxx 100110xxx > 舍弃精度中间值 输出float4_e2m1_mantissa = 0b0.1 3) 被舍弃的精度等于舍弃精度中间值时，第1位为偶数时不进位 例bfloat16_mantissa = 0b0.0100000xxx 0 % 2 == 0 输出float4_e2m1_mantissa = 0b0.0 4) 被舍弃的精度等于舍弃精度中间值时，第1位为奇数时进位 例bfloat16_mantissa = 0b0.1100000xxx 1 % 2 == 1 输出float4_e2m1_mantissa = 0b0.1 **CAST_ROUND****：**就近舍入，距离相等时向远离0方向进位 1）被舍弃的精度小于舍弃精度中间值时，不进位， 例bfloat16_mantissa = 0b0.0000110xxx 000110xxx < 舍弃精度中间值 输出float4_e2m1_mantissa = 0b0.0 2）被舍弃的精度大于舍弃精度中间值时，进位 例bfloat16_mantissa = 0b0.0100110xxx 100110xxx > 舍弃精度中间值 输出float4_e2m1_mantissa = 0b0.1 3) 被舍弃的精度等于舍弃精度中间值时，进位远离0，所以进位 例bfloat16_mantissa = 0b0.0100000xxx 输出float4_e2m1_mantissa = 0b0.1 **CAST_FLOOR****：**向负无穷方向舍入 1）输入值正数时，不进位， 例bfloat16_mantissa = 0b0.0000110xxx 输出float4_e2m1_mantissa = 0b0.0 2）输入值负数时，进位 例bfloat16_mantissa = 0b0.0100110xxx 输出float4_e2m1_mantissa = 0b0.1 **CAST_CEIL****：**向正无穷方向舍入 1）输入值正数时，进位， 例bfloat16_mantissa = 0b0.0000110xxx 输出float4_e2m1_mantissa = 0b0.1 2）输入值负数时，不进位 例bfloat16_mantissa = 0b0.0100110xxx 输出float4_e2m1_mantissa = 0b0.0 **CAST_TRUNC****：**向0方向舍入 1）直接舍弃多余精度，不进位 例bfloat16_mantissa = 0b0.0100110xxx 输出float4_e2m1_mantissa = 0b0.0 **完整举例**： 输入bfloat16为0.761719，二进制为 sign:0, exponent:01111110, mantissa:1000011 bfloat16_exponent = 126-127 = -1 < 0，float16_exponent最小为0，所以bfloat16_exponent += 1，bfloat16_mantissa 小数点左移 1位，1.1000011 -> 0.11000011 CAST_RINT模式 舍弃精度1000011大于舍弃精度中间值1000000，所以进位 float4_e2m1_mantissa = 0.1 最终float4_e2m1二进制为 sign:0, exponent: 00, mantissa = 1 按照计算公式十进制表示为 float4_e2m1=0.5 |
| bfloat16_t | fp4x2_e1m2_t | bfloat16二进制规则为 sign:1bit,exponent:8bit,mantissa:7bit fp4x2_e1m2_t二进制规则为 sign:1bit,exponent:1bit,mantissa:2bit 尾数位相差5位 当bfloat16_exponent = exponent-127 < 0时，bfloat16_mantissa需要发生位移 **例1**：当exponent = 124， bfloat16_exponent = exponent-127 = -3 < 0时，因为float4_e1m2_exponent = exponent - 1 最小为0，无法表示，所以指数需要+3保持和float4_e2m1_exponent相等，同时尾数位需要除以2的3次方，因为bf16计算公式 = s * (2^(e-127))*(man) = s * (2^(e-127+3))*(man*2^(-3)),指数位乘以一个数，尾数位需要除以相同大小的数，保证最终值不变。假设bfloat16_mantissa = 0b1011011 bfloat16 mantissa计算公式为 1+ man/128, 用例二进制表示为 0b1.1011011，指数位乘以2的3次方时，尾数要除以2的3次，小数点向左移动3位，所以bfloat16_mantissa = 0b0.0011011011，因为float4_e2m1只有2bit尾数位，所以在以下CAST模式中需要舍弃最低8位，并根据舍入模式决定是否舍入，当前例子的舍弃精度中间值为0b10000000 **CAST_RINT****：**就近舍入，距离相等时向偶数进位 1）被舍弃的精度小于舍弃精度中间值时，不进位， 例bfloat16_mantissa = 0b0.0000011xxx 00011xxx < 舍弃精度中间值 输出float4_e1m2_mantissa = 0b0.00 2）被舍弃的精度大于舍弃精度中间值时，进位 例bfloat16_mantissa = 0b0.0010011xxx 10011xxx > 舍弃精度中间值 输出float4_e1m2_mantissa = 0b0.01 3) 被舍弃的精度等于舍弃精度中间值时，第2位为偶数时不进位 例bfloat16_mantissa = 0b0.0010000xxx 0 % 2 == 0 输出float4_e1m2_mantissa = 0b0.00 4) 被舍弃的精度等于舍弃精度中间值时，第2位为奇数时进位 例bfloat16_mantissa = 0b0.0110000xxx 1 % 2 == 1 输出float4_e1m2_mantissa = 0b0.10 **CAST_ROUND****：**就近舍入，距离相等时向远离0方向进位 1）被舍弃的精度小于舍弃精度中间值时，不进位， 例bfloat16_mantissa = 0b0.0000110xxx 00110xxx < 舍弃精度中间值 输出float4_e1m2_mantissa = 0b0.00 2）被舍弃的精度大于舍弃精度中间值时，进位 例bfloat16_mantissa = 0b0.0010110xxx 10110xxx > 舍弃精度中间值 输出float4_e1m2_mantissa = 0b0.01 3) 被舍弃的精度等于舍弃精度中间值时，进位远离0，所以进位 例bfloat16_mantissa = 0b0.0010000xxx 输出float4_e1m2_mantissa = 0b0.01 **CAST_FLOOR****：**向负无穷方向舍入 1）输入值正数时，不进位， 例bfloat16_mantissa = 0b0.0000110xxx 输出float4_e1m2_mantissa = 0b0.00 2）输入值负数时，进位 例bfloat16_mantissa = 0b0.00100110xxx 输出float4_e1m2_mantissa = 0b0.01 **CAST_CEIL****：**向正无穷方向舍入 1）输入值正数时，进位， 例bfloat16_mantissa = 0b0.0000110xxx 输出float4_e1m2_mantissa = 0b0.01 2）输入值负数时，不进位 例bfloat16_mantissa = 0b0.0010110xxx 输出float4_e1m2_mantissa = 0b0.00 **CAST_TRUNC****：**向0方向舍入 1）直接舍弃多余精度，不进位 例bfloat16_mantissa = 0b0.0010110xxx 输出float4_e1m2_mantissa = 0b0.00 **完整举例**： 输入bfloat16为0.761719，二进制为 sign:0, exponent:01111110, mantissa:1000011 bfloat16_exponent = 126-127 = -1 < 0，float16_exponent最小为0，所以bfloat16_exponent += 1，bfloat16_mantissa 小数点左移 1位，1.1000011 -> 0.11000011 CAST_RINT模式 舍弃精度000011小于舍弃精度中间值100000，所以不进位 float4_e2m1_mantissa = 0.11 最终float4_e2m1二进制为 sign:0, exponent: 0, mantissa = 11 按照计算公式十进制表示为 float4_e2m1=0.75 |
| float | hifloat8_t | 参考[表9。 |

**表9 **float to hifloat8_t类型转换规则

| VCVTFF:F322HiF8 |
| --- |
| *tmp*2[31 : 0] = *f32_src_data*[*i*][31 : 0]; *Ev* = *tmp*2[30 : 23] - 8'*b*01111111, *thr* = *tmp*2[13 : 0]; if (*Ev* == 128 && *tmp*2[22 : 0] != 23'*b*0) then *tmp*3[7 : 0] = *HiF8**NAN*(8'*b*10000000); else if ((*Ev* == 128 && *tmp*2[22 : 0] == 23'*b*0) \|\| (*Ev* > 15)) then *tmp*3[7 : 0] = (*tmp*2[31] == 1'*b*0) ? *HiF8+INF *(8'*b*01101111) : *HiF8-INF* (8'*b*11101111); else if (*Ev* < -23) then *tmp*3[7 : 0] = *HiF*8*ZERO* (8'*b*00000000); else if (*Ev* == -23) then if ((Half To Away Round) \|\| (Hybrid Round && {1’*b*1, *tmp*2[22 : 10]} >= *thr*)) then *tmp*3[7 : 0] = (*tmp*2[31] == 1'*b*0) ? 8'*b*00000001 : 8'*b*10000001; // min subnormal else *tmp*3[7 : 0] = *HiF8ZERO* (8'*b*00000000); end if else if (*Ev* == 0) then *M* = *tmp*2[22 : 20], *T* *A_bit* = *tmp*2[19], *frac* = *tmp*2[19 : 6]; else if (*Ev* == ±1) then *M* = *tmp*2[22 : 20], *T* *A_bit* = *tmp*2[19], *frac* = *tmp*2[19 : 6]; else if (*Ev* == ±[2, 3]) then *M* = *tmp*2[22 : 20], *T* *A_bit* = *tmp*2[19], *frac* = *tmp*2[19:6]; else if (*Ev* == ±[4, 7]) then *M* = *tmp*2[22 : 21], *T* *A_bit* = *tmp*2[20], *frac* = *tmp*2[20 : 7]; else if (*Ev* == ±[8, 15]) then *M* = *tmp*2[22], *T* *A_bit* = *tmp*2[21], *frac* = *tmp*2[21 : 8]; else if (*Ev* == [-16, -22]) then *M* = *Ev* + 23, *T* *A_bit* = *tmp*2[22], *frac* = *tmp*2[22 : 9]; // subnormal end if if (*Ev* == ±[0, 3]) then if (*T* *A_bit* == 1’*b*1) then *M_tmp* = *M* + 1, *Ev* = *Ev* + *carry* *of* *M_tmp*, *M* = (*carry of M_tmp*) ? 0 : *M_tmp*; end if else if (*Ev* == ±[4, 15]) then if (HALF To Away Round && *T* *A_bit* == 1’*b*1) \|\| (Hybrid Round && *frac* >= *thr*) then *M_tmp* = *M* + 1, *Ev* = *Ev* + *carry* *of* *M_tmp*, *M* = (*carry of M_tmp*) ? 0 : *M_tmp*; end if else if (*Ev* == [-16, -22]) then if ((Half To Away Round) && *T* *A_bit* == 1'*b*1) \|\| ((Hybrid Round && *frac* >= *thr*) then *M*_*tmp* = *Ev* + 23, *Ev* = *Ev* + 1, M = (*Ev* == -15) ? 0 : *M_tmp*; end if end if encode {*tmp*3[31], *Ev*, *M*} to *tmp*3[7 : 0] following HiF encoding rule; end if *result*[*i*][7 : 0] = *saturation*(*tmp*3[7 : 0]) according to control bit; |

**表10 **half to hifloat8_t类型转换规则

| VCVTFF: F162HiF8 |
| --- |
| *tmp*2[15 : 0] = *f16_src_data*[*i*][15 : 0]; *Ev* = *tmp*2[14 : 10] - 5'*b*01111, *thr* = {*tmp*2[0], 1’b1}; if (*Ev* == 16 && *tmp*2[9 : 0] != 10'*b*0) then *tmp*3[7 : 0] = *HiF8NAN*(8'*b*10000000); else if (*Ev* == 16 && *tmp*2[9:0] == 10'*b*0) && (*Ev* > 15) then *tmp*3[7 : 0] = (*tmp*2[31] == 1'*b*0) ? *HiF8+INF*(8'*b*01101111) : *HiF8-INF*(8'*b*11101111); else if (*Ev* < -23) then *tmp*3[7 : 0] = *HiF8ZERO*(8'*b*00000000); else if (*Ev* == -23) then if ((Half To Away Round) \|\| (Hybrid Round && {1’*b*1, *tmp*2[9]} >= *thr*)) then *tmp*3[7 : 0] = (*tmp*2[31] == 1'*b*0) ? 8'*b*00000001 : 8'*b*10000001; // min subnormal else *tmp*3[7 : 0] = *HiF8ZERO*(8'*b*00000000); end if else if (*Ev* == 0) then *M* = *tmp*2[9 : 7], *T* *A_bit* = *tmp*2[6], *frac* = *tmp*2[6 : 5]; else if (*Ev* == ±1) then *M* = *tmp*2[9 : 7], *T* *A_bit* = *tmp*2[6], *frac* = *tmp*2[6 : 5]; else if (*Ev* == ±[2, 3]) then *M* = *tmp*2[9 : 7], *T* *A_bit* = *tmp*2[6], *frac* = *tmp*2[6 : 5]; else if (*Ev* == ±[4, 7]) then *M* = *tmp*2[9 : 8], *T* *A_bit* = *tmp*2[7], *frac* = *tmp*2[7 : 6]; else if (*Ev* == ±[8, 15]) then *M* = *tmp*2[9], *T* *A_bit* = *tmp*2[8], *frac* = *tmp*2[8 : 7]; else if (*Ev* == [-16, -22]) then *M* = *Ev* + 23, *T* *A_bit* = *tmp*2[9], *frac* = *tmp*2[9 : 8]; // subnormal end if if (*Ev* == ±[0, 3]) then if (T *A_bit* == 1’*b*1) then *M_tmp* = *M* + 1, *Ev* = *Ev* + *carry* *of* *M_tmp*, *M* = (*carry of M_tmp*) ? 0 : *M_tmp*; end if else if (*Ev* == ±[4, 15]) then if (HALF To Away Round && *T* *A_bit* == 1’*b*1) \|\| (Hybrid Round && *frac* >= *thr*) then *M_tmp* = M + 1, *Ev* = *Ev* + *carry* *of* *M_tmp*, *M* = (*carry of M_tmp*) ? 0 : *M_tmp*; end if else if (*Ev* == [-16, -22]) then if ((Half To Away Round) && *T* *A_bit* == 1'*b*1) \|\| ((Hybrid Round && *frac* >= *thr*) then *M*_*tmp* = *Ev* + 23, *Ev* = *Ev* + 1, M = (*Ev* == -15) ? 0 : *M_tmp*; end if end if encode {*tmp3*[31], *Ev*, *M*} to *tmp*3[7 : 0] following HiF encoding rule; end if *result*[*i*][7 : 0] = *saturation*(*tmp*3[7 : 0]) according to control bit; |

#### 约束说明

- 该指令需配合SetCtrlSpr(ISASI) 指令使用，通过设置寄存器的值控制Cast的饱和和非饱和模式。
- 浮点数转整数：

  - 非饱和模式：输入数据超过输出类型最值时，结果被截断为目标格式的数据宽度，例如输入half值为257, 输出uint8_t值为1，输入为+/-inf，则返回输出类型的对应最值，输入nan时，返回0。
  - 饱和模式：输入数据超过输出类型最值时，返回输出类型的对应最值，例如输入half值为257, 输出uint8值为255，输入half值为-inf，输出uint8_t值为0，输入nan时，返回0。

- 浮点数转浮点数：

  - 当前浮点数转浮点数支持饱和模式和非饱和模式，非饱和模式下，输入数据为nan时，输出为nan，输入+/-inf时，输出为+/-inf；饱和模式下，输入为nan时，输出为0，输入数据超过输出类型最值时，返回输出类型的对应最值。
  - 当输出类型float32时，只支持不饱和模式。
  - 当输出类型为fp8_e4m3fn_t时，由于fp8_e4m3fn_t没有inf表示格式，所以输出为nan。
  - 当输出类型为fp8_e5m2_t/fp8_e4m3fn_t时，输入nan，默认输出为0。
  - 对于bfloat16 to float4类型，输入bfloat16 inf或超出fp4x2_e2m1_t/fp4x2_e1m2_t数据最值范围时，会返回对应符号的fp4x2_e2m1_t/fp4x2_e1m2_t最值；输入nan时，fp4x2_e2m1_t/fp4x2_e1m2_t输出0。
  - 对于bfloat16_t到fp4x2_e2m1_t/fp4x2_e1m2_t数据类型的转换，指令会以每2个元素为一对进行读写，mask有效位以偶数位为准，例如 10 00 00 00 10 10 00 10 等效于11 11 00 00 10 10 00 11。

![](images/atlasascendc_api_07_0398_img_001.png)

  - 对于fp8_e8m0_t类型：

输入bfloat16_t +/-inf或绝对值超出fp8_e8m0_t类型最值，则返回fp8_e8m0_t最大值0b11111110；

输入bfloat16_t nan 输出fp8_e8m0_t nan = 0b11111111。

- 整数转整数

不饱和模式：输入数据会截断为目标数据格式，例如，输入int32_t值为256, 输出uint8_t值为0

饱和模式：输入数据超出目标数据范围，会饱和为目标数据最值

对于窄数据类型例如int16_t(2Byte)转宽数据类型uint32_t(4Byte),只支持饱和模式，输入负数会被饱和成0

#### 调用示例

```
__simd_vf__ inline void CastVF(__ubuf__ int16_t* dstAddr, __ubuf__ float* srcAddr, uint32_t count, uint32_t srcRepeatSize, uint32_t dstRepeatSize, uint16_t repeatTimes)
{
    // castTrait 类变量时需要加static
    static constexpr AscendC::Reg::CastTrait castTrait = 
    {AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::NO_SAT,AscendC::Reg::MaskMergeMode::ZEROING,AscendC::RoundMode::CAST_RINT};

   

    AscendC::Reg::RegTensor<float> srcReg;
    AscendC::Reg::RegTensor<int16_t> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * srcRepeatSize);
        mask = AscendC::Reg::UpdateMask<float>(count);
        AscendC::Reg::Cast<int16_t, float, castTrait>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * dstRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Cast 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Cast 调用次数**: 10
- **参数模式**: `T3_A3_M1_TYPEfloat_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: float）
- **语义（待补充）**: 在 MX 浮点量化（FP8）非尾轴优化路径中，先用 castTraitZero/castTraitOne 将 BF16/FP16 指数最大值拆位升精度到 FP32 求尺度，再用 castTraitFp32ToBf16 回转 BF16，最后用 castTrait32to8 把 FP32 中间结果量化成 FP8 输出。

**片段 1** (行 486-504):

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    Reg::DataCopy(maxExpAddr, expMax, pnumMask);
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
    expOffset /= DIGIT_TWO;
    maskNum = expOffset;
    mask = Reg::UpdateMask<uint16_t>(maskNum);
    Reg::DataCopyUnAlignPre(u0, maxExpAddr + expOffset);
    Reg::DataCopyUnAlign(exp, u0, maxExpAddr + expOffset);
    Reg::Max(expMax, expMax, exp, mask);
}
maskNum = static_cast<uint32_t>(dataLen);
mask = Reg::CreateMask<uint32_t>();
maskNum = static_cast<uint32_t>(dataLen);
// 求scale
Reg::Interleave(expMax, tmp16RegTensor, expMax, tmp16RegTensor);
Reg::Cast<float, T, castTraitZero>((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<T>&)expMax, mask);

Reg::Compare<uint32_t, CMPMODE::LT>(infMask, maxFP32RegTensor, absMaskFP32RegTensor, mask);
Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, maxFP32RegTensor, fp32ZeroRegTensor, mask);
```

**片段 2** (行 528-546):

```cpp

Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, invMaxRegTensor, infMask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, fp32ZeroRegTensor, zeroMask);
Reg::Pack(tmp16RegTensor, extractExpRegTensor);
Reg::Pack(outZero, tmp16RegTensor);
// 搬出mxScale
Reg::DataCopyUnAlign(mxScaleAddr, outZero, u1, dataLen);
Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);

// 求1/scale
Reg::ShiftLefts(extractExpRegTensor, extractExpRegTensor, FP32_SHR_NUM, mask);
Reg::Sub(extractExpRegTensor, scaleBias, extractExpRegTensor, mask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, nan, infMask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, fp32ZeroRegTensor, zeroMask);

Reg::Cast<bfloat16_t, float, castTraitFp32ToBf16>((Reg::RegTensor<bfloat16_t>&)reversedShareExpRegTensor,
                                                  (Reg::RegTensor<float>&)extractExpRegTensor, mask);
Reg::DeInterleave(reversedShareExpRegTensor, tmp16RegTensor, reversedShareExpRegTensor, tmp16RegTensor);
auto scaleAddr = maxExpAddr;
```

**片段 3** (行 560-583):

```cpp
// 求data value
for (uint16_t i = 0; i <= static_cast<uint16_t>(regLoop - 1); i++) {
    this->template LoadData<RoundMode::UNKNOWN, roundMode, true>(xAddr, i * dataLenSingleLoop, x, pnumMask);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<float, T, castTraitZero>(yZero, x, pnumMask);
        Reg::Cast<float, T, castTraitOne>(yOne, x, pnumMask);
        Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, mask);
        Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, mask);
    } else if constexpr (IsSame<T, bfloat16_t>::value) {
        Reg::Mul(xBF16RegTensor, x, (Reg::RegTensor<bfloat16_t>&)reversedShareExpRegTensor, pnumMask);
        Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, xBF16RegTensor, mask);
        Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, xBF16RegTensor, mask);
    }
    Reg::Cast<U, float, castTrait32to8>(yZeroFP8, yZero, mask);
    Reg::Cast<U, float, castTrait32to8>(yOneFP8, yOne, mask);
    // 寄存器复用
    Reg::Pack(tmp16RegTensor, (Reg::RegTensor<uint32_t>&)yZeroFP8);
    Reg::Pack(exp, (Reg::RegTensor<uint32_t>&)yOneFP8);
    Reg::Interleave(tmp16RegTensor, exp, tmp16RegTensor, exp);
    Reg::Pack(outZero, tmp16RegTensor);
    auto addr0 = yAddr + i * dataLenSingleLoop;
    Reg::DataCopyUnAlign(addr0, outZero, u1, dataLenSingleLoop);
    Reg::DataCopyUnAlignPost(addr0, u1, 0);
}
```

**要点**: castTraitZero 与 castTraitOne 配对使用，对应 RegLayout::ZERO/ONE，分别取相邻元素偶/奇位，常与 Interleave 配合实现 16bit→32bit 拆位升精度；castTrait32to8 用于 FP32→FP8 量化，mask 按源/目的 sizeof 较大者筛选；模板参数 <DST,SRC,trait>，dstReg/srcReg 常需 (Reg::RegTensor<DST>&) 强转。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Cast 调用次数**: 16
- **参数模式**: `T3_A3_M0_TYPEbfloat16+float`（实参 3 个，类型: bfloat16, float）
- **语义（待补充）**: 在分组 MX 量化非尾轴 FP8 路径中，用 castTraitHalf2Float 将 BF16 指数最大值升精度到 FP32 做尺度计算，再用 castTraitZero/castTraitOne 把 BF16 输入拆位成 FP32 乘 scale，half/bfloat16_t 经 if constexpr 分支选择不同 trait。

**片段 1** (行 565-582):

```cpp
for (uint16_t j = 0; j <= static_cast<uint16_t>(blockCountLoop); j++) {
    Reg::LoadAlign(xRegTensor0, xAddr + j * dataLen + i * vfNum32);
    Reg::LoadAlign(xRegTensor1,
                   xAddr + (static_cast<uint16_t>(blockCount) - j - 1) * dataLen + i * vfNum32);
    Reg::And(expMaxRegTensor0, (Reg::RegTensor<uint16_t>&)xRegTensor0, absMaskBF16Reg, p0);
    Reg::And(expMaxRegTensor1, (Reg::RegTensor<uint16_t>&)xRegTensor1, absMaskBF16Reg, p0);
    Reg::Max(expMaxRegTensor, expMaxRegTensor0, expMaxRegTensor1, p0);
    Reg::Max(expMaxreShareExpFP16YOneRegTensor, expMaxRegTensor, expMaxreShareExpFP16YOneRegTensor, p0);
}
// 2. BF16→FP32
Reg::Interleave(expMaxreShareExpFP16YOneRegTensor, fullZeroReg, expMaxreShareExpFP16YOneRegTensor,
                fullZeroReg);
Reg::Cast<float, T, castTraitHalf2Float>((Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor,
                                         (Reg::RegTensor<T>&)expMaxreShareExpFP16YOneRegTensor,
                                         preMaskScale);
// 3. Inf/Zero校验
Reg::CompareScalar<uint32_t, CMPMODE::LT>(infMask, expMaxAndAddOneFP32RegTensor, MAX_EXP_FOR_FP32,
                                          preMaskScale);
```

**片段 2** (行 625-644):

```cpp
        reversedShareExpRegTensorFP32Zero, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor,
        p0);
    Reg::Cast<float, bfloat16_t, castTraitOne>(
        reversedShareExpRegTensorFP32One, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor,
        p0);
}
for (uint16_t j = 0; j < static_cast<uint16_t>(blockCount); j++) {
    Reg::LoadAlign(xRegTensor, xAddr + j * dataLen + i * vfNum32);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<float, T, castTraitZero>(yZero, xRegTensor, p0);
        Reg::Cast<float, T, castTraitOne>(yOne, xRegTensor, p0);
        Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, maskAll);
        Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, maskAll);
    } else {
        Reg::Mul(valueRegTensor, xRegTensor, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor,
                 p0);
        Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, valueRegTensor, maskAll);
        Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, valueRegTensor, maskAll);
    }
    Reg::Interleave(yZero, yOne, yZero, yOne);
```

**要点**: castTraitHalf2Float 对应 BF16→FP32 升精度，模板参数 <float, T(bfloat16_t), castTraitHalf2Float>，M0 模式第三参仍传 pred mask 变量；分组场景按 blockCount 循环 LoadAlign 成对载入，Cast 紧跟 Load 做类型抬升便于后续 CompareScalar 做 Inf/Zero 校验；half/bfloat16_t 用 if constexpr 分支选择不同 trait。

### 实例 3：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Cast 调用次数**: 14
- **参数模式**: `T3_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在 SwiGLU 反向 MX 量化（双轴）中，用 CAST_X_TO_FP32_ZERO/ONE 把 half 输入拆位升精度到 FP32 并乘 scale，再用 CAST_32_TO_80/82/81/83 四个 trait 把 FP32 量化结果分四段转成 FP8（y1Dtype），最后累加合并。

**片段 1** (行 924-924):

```cpp
for (uint16_t j = 0; j < batchCount; j++) {
```

**片段 2** (行 1007-1033):

```cpp
if constexpr (IsSameType<xDtype, half>::value) {
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x0ZeroFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x0OneFP32, regA, maskAll);
    Reg::Cast<float, bfloat16_t, CAST_X_TO_FP32_ZERO>(
        scaleForMulFP32, (Reg::RegTensor<bfloat16_t>&)scaleForMulFP16, maskAll);
    Reg::Mul(x0ZeroFP32, x0ZeroFP32, scaleForMulFP32, maskAll);
    Reg::Mul(x0OneFP32, x0OneFP32, scaleForMulFP32, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x1ZeroFP32, regB, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x1OneFP32, regB, maskAll);
    Reg::Mul(x1ZeroFP32, x1ZeroFP32, scaleForMulFP32, maskAll);
    Reg::Mul(x1OneFP32, x1OneFP32, scaleForMulFP32, maskAll);
} else {
    Reg::Mul(regA, regA, (Reg::RegTensor<xDtype>&)scaleForMulFP16, maskAll);
    Reg::Mul(regB, regB, (Reg::RegTensor<xDtype>&)scaleForMulFP16, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x0ZeroFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x0OneFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x1ZeroFP32, regB, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x1OneFP32, regB, maskAll);
}
AscendC::Reg::Cast<y1Dtype, float, CAST_32_TO_80>(fp8Part0, x0ZeroFP32, maskAll);
AscendC::Reg::Cast<y1Dtype, float, CAST_32_TO_82>(fp8Part1, x0OneFP32, maskAll);
AscendC::Reg::Cast<y1Dtype, float, CAST_32_TO_81>(fp8Part2, x1ZeroFP32, maskAll);
AscendC::Reg::Cast<y1Dtype, float, CAST_32_TO_83>(fp8Part3, x1OneFP32, maskAll);
AscendC::Reg::Add((Reg::RegTensor<uint8_t>&)fp8Part0, (Reg::RegTensor<uint8_t>&)fp8Part0,
                       (Reg::RegTensor<uint8_t>&)fp8Part1, maskAllB8);
AscendC::Reg::Add((Reg::RegTensor<uint8_t>&)fp8Part0, (Reg::RegTensor<uint8_t>&)fp8Part0,
                       (Reg::RegTensor<uint8_t>&)fp8Part2, maskAllB8);
```

**要点**: CAST_32_TO_80/81/82/83 是 FP32→FP8 的分段量化 trait，分别对应不同位段，需配合 Add 累加还原完整 FP8 结果；Reg 命名空间下 trait 常量用大写宏形式（CAST_X_TO_FP32_ZERO），Reg 命名空间下用 castTrait 小写结构体，二者不可混用；maskAll 用于全量元素，half 与 bfloat16_t 走不同分支但都先升 FP32 再量化。

### 实例 4：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Cast 调用次数**: 16
- **参数模式**: `T3_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义（待补充）**: 在动态量化（MoE 全载入）算子中，先用 castTraitB16ToB32 把 BF16 输入升精度到 FP32 做乘 smooth 与 abs/max 归约，再按输出类型用不同 trait 链把 FP32 量化结果转成 int8_t/hifloat8/fp8/int4 等目标类型。

**片段 1** (行 333-344):

```cpp
for (uint16_t j = 0; j < vfLoop; j++) {
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, xAddr + multiRow * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, smoothAddr + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
    AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
    AscendC::Reg::Abs(vreg6, vreg3, preg0);
    AscendC::Reg::Max(vreg7, vreg6, vreg7, preg1);
}
```

**片段 2** (行 354-378):

```cpp
for (uint16_t j = 0; j < vfLoop - 1; j++) {
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, xAddr + multiRow * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, smoothAddr + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
    AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
    AscendC::Reg::Max(vreg7, vreg3, vreg7, preg1);
    AscendC::Reg::Min(vregMinX, vreg3, vregMinX, preg1);
}
AscendC::Reg::ReduceMax(vregReduceMaxX, vreg7, preg1);
AscendC::Reg::ReduceMin(vregReduceMinX, vregMinX, preg1);

preg4 = AscendC::Reg::UpdateMask<float>(tailNum);
AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
    vreg1, xAddr + multiRow * rowCount + (vfLoop - 1) * VL);
AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg4);
AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
    vreg2, smoothAddr + (vfLoop - 1) * VL);
AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg4);
AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg4);
AscendC::Reg::Max(vreg7, vreg3, vreg7, preg4);
AscendC::Reg::Min(vregMinX, vreg3, vregMinX, preg4);
```

**片段 3** (行 410-429):

```cpp
    AscendC::Reg::Div(vreg16, vreg3, vreg10, preg2);
} else if constexpr (isSymmetrical == false) {
    AscendC::Reg::Div(vregXDivScale, vreg3, vreg10, preg2);
    AscendC::Reg::Add(vreg16, vregXDivScale, vregDupOffset, preg2);
}
if constexpr (IsSameType<yDtype, int8_t>::value) {
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vreg17, vreg16, preg2);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vreg18, vreg17, preg2);
    AscendC::Reg::Cast<yDtype, half, castTraitF16ToI8>(vreg19, vreg18, preg2);
} else if constexpr (IsSameType<yDtype, hifloat8_t>::value) {
    AscendC::Reg::Cast<yDtype, float, castTraitF32toh8>(vreg19, vreg16, preg2);
} else if constexpr (IsSameType<yDtype, fp8_e4m3fn_t>::value || IsSameType<yDtype, fp8_e5m2_t>::value) {
    AscendC::Reg::Cast<yDtype, float, castTraitF32tofp8>(vreg19, vreg16, preg2);
} else if constexpr (IsSameType<yDtype, int4b_t>::value) {
    AscendC::Reg::RegTensor<uint16_t> vreg20;
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vreg17, vreg16, preg2);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vreg18, vreg17, preg2);
    AscendC::Reg::Pack(vreg20, (AscendC::Reg::RegTensor<uint32_t>&)vreg18);
    AscendC::Reg::Cast<int4x2_t, half, castTraitF16ToI8>(
        (AscendC::Reg::RegTensor<int4x2_t>&)vreg19, (AscendC::Reg::RegTensor<half>&)vreg20,
```

**要点**: FP32→int8_t 不能一步完成，需 castTraitF32ToI16→castTraitI16ToF16→castTraitF16ToI8 三级 Cast 链；int4b_t 输出还需 Pack 重排后再 Cast<int4x2_t, half, castTraitF16ToI8>；castTraitB16ToB32 用于 BF16→FP32，与 castTraitHalf2Float 同向但对应不同源类型/布局约定。

### 实例 5：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Cast 调用次数**: 36
- **参数模式**: `T3_A3_M1_TYPEfloat_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: float）
- **语义（待补充）**: 在动态块量化单行 kernel 中，Div 求 scale 后按 OUT_TYPE 用 constexpr 分支选择不同 Cast trait 把 FP32 量化值转成 hifloat8/int8/fp8：hifloat8 用 castTrait32toh8Zero，fp8 用 castTrait32tofp8，int8 用三级 Cast 链。

**片段 1** (行 379-392):

```cpp
if constexpr (IsSameType<OUT_TYPE, hifloat8_t>::value) {
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32toh8Zero>(vReg15, vReg13,
                                                                  defaultMaskReg);
} else if constexpr (IsSameType<OUT_TYPE, int8_t>::value) {
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vReg19, vReg13, defaultMaskReg);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vReg20, vReg19, defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, half, castTraitF16ToI8>(vReg15, vReg20, defaultMaskReg);
} else {
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32tofp8>(vReg15, vReg13, defaultMaskReg);
}

AscendC::Reg::DataCopy<OUT_TYPE, AscendC::Reg::StoreDist::DIST_PACK4_B32>(
    outLocal + rowIdx * colSizeAlign + colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL,
    vReg15, inputMaskReg);
```

**片段 2** (行 508-527):

```cpp
AscendC::Reg::Div<float, &mode>(vReg14, vReg12, vReg8, defaultMaskReg);

if constexpr (IsSameType<OUT_TYPE, hifloat8_t>::value) {
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32toh8Zero>(vReg15, vReg13,
                                                                  defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32toh8Zero>(vReg16, vReg14,
                                                                  defaultMaskReg);
} else if constexpr (IsSameType<OUT_TYPE, int8_t>::value) {
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vReg19, vReg13, defaultMaskReg);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vReg20, vReg19, defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, half, castTraitF16ToI8>(vReg15, vReg20, defaultMaskReg);
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vReg19, vReg14, defaultMaskReg);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vReg20, vReg19, defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, half, castTraitF16ToI8>(vReg16, vReg20, defaultMaskReg);
} else {
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32tofp8>(vReg15, vReg13, defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32tofp8>(vReg16, vReg14, defaultMaskReg);
}

AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::LOWEST>(maskReg2, inputMaskReg);
```

**片段 3** (行 585-604):

```cpp
AscendC::Reg::Interleave(vReg11, vReg12, vReg9, vReg10);
AscendC::Reg::Div<float, &mode>(vReg13, vReg11, vReg8, defaultMaskReg);
AscendC::Reg::Div<float, &mode>(vReg14, vReg12, vReg8, defaultMaskReg);

if constexpr (IsSameType<OUT_TYPE, hifloat8_t>::value) {
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32toh8Zero>(vReg15, vReg13, defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32toh8Zero>(vReg16, vReg14, defaultMaskReg);
} else if constexpr (IsSameType<OUT_TYPE, int8_t>::value) {
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vReg19, vReg13, defaultMaskReg);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vReg20, vReg19, defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, half, castTraitF16ToI8>(vReg15, vReg20, defaultMaskReg);
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vReg19, vReg14, defaultMaskReg);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vReg20, vReg19, defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, half, castTraitF16ToI8>(vReg16, vReg20, defaultMaskReg);
} else {
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32tofp8>(vReg15, vReg13, defaultMaskReg);
    AscendC::Reg::Cast<OUT_TYPE, float, castTrait32tofp8>(vReg16, vReg14, defaultMaskReg);
}

AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::LOWEST>(maskReg2, inputMaskReg);
```

**要点**: castTrait32toh8Zero 对应 FP32→hifloat8_t 的 ZERO 布局，与 castTrait32tofp8 是并行的 FP8/hifloat8 量化路径；int8 路径需 F32ToI16→I16ToF16→F16ToI8 三级，每级都传 defaultMaskReg；mask 用 defaultMaskReg（全 1），Div 与 Cast 共用同一 mask。

### 实例 6：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub, UnPack
- **Cast 调用次数**: 1
- **参数模式**: `T3_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义（待补充）**: 在 SwiGLU MX 量化（双轴）的尺度计算中，对 -1 轴 ReduceMax 后的 absMax 用 UnPack 拆位，再用 CAST_X_TO_FP32_ZERO 把拆出的半位升精度到 FP32，以便做指数/尾数比较确定 scale。

（行 996-1014）

```cpp
// Absolute value (CLUB)
Reg::And(x0Abs, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
Reg::And(x1Abs, (Reg::RegTensor<uint16_t>&)x1, absMask, maskAll);

// -1 axis: max of pair + reduce
Reg::Max(absMaxDim1, x0Abs, x1Abs, maskAll);
Reg::ReduceMaxWithDataBlock(absMaxDim1, absMaxDim1, maskAll); // -1轴 指数位计算结束 8个int16的数

// -2 axis: accumulate column-wise max
Reg::Max(absMax1Dim2, absMax1Dim2, x0Abs, maskAll); // -2轴最大值
Reg::Max(absMax2Dim2, absMax2Dim2, x1Abs, maskAll); // -2轴最大值

// ---- -1 axis CLUB scale: ZERO half (even positions after ReduceMax) ----
Reg::UnPack((AscendC::Reg::RegTensor<uint32_t>&)absMaxDim1Unpack,
                 (AscendC::Reg::RegTensor<uint16_t>&)absMaxDim1);
Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>((Reg::RegTensor<float>&)max32, absMaxDim1Unpack,
                                                   maskAll);

Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32, expMaskReg, maskAll32);
```

**要点**: UnPack 拆位后紧跟 Cast 升精度，是 16bit→32bit 的常见拆位升精度套路（替代 Interleave）；CAST_X_TO_FP32_ZERO 对应 RegLayout::ZERO 取偶数位，与 CAST_X_TO_FP32_ONE 配对取奇数位；模板参数 <float, xDtype, trait>，xDtype 由上层模板传入，trait 随源类型选择。

### 实例 7：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Cast 调用次数**: 1
- **参数模式**: `T3_A3_M1_TYPEbfloat16+float_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: float, bfloat16）
- **语义（待补充）**: 在 flat 量化高精度 v2 路径中，用 castTraitHalf2Float 把 BF16 最大值升精度到 FP32，再通过 ShiftRights/And 拆指数和尾数，按 FP32 规则确定 fp4 scale 并 Pack 回 BF16 输出。

（行 500-539）

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    preMaskScale = AscendC::Reg::UpdateMask<uint32_t>(scaleNum);
    AscendC::Reg::LoadAlign<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                 AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16, srcPtr, vfLen32);

    AscendC::Reg::Cast<float, bfloat16_t, castTraitHalf2Float>(
        (AscendC::Reg::RegTensor<float>&)max32, (AscendC::Reg::RegTensor<bfloat16_t>&)max16,
        preMaskScale);
    AscendC::Reg::Compare<uint32_t, AscendC::CMPMODE::LT>(cmpResult, max32, expMask, preMaskScale);
    AscendC::Reg::Compare<uint32_t, AscendC::CMPMODE::NE>(zeroMask, max32, zeroRegTensor32, preMaskScale);

    AscendC::Reg::Mul((AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)max32, invMax, preMaskScale);
    AscendC::Reg::ShiftRights(exp32, max32, SHR_NUM_FOR_FP32, preMaskScale);
    AscendC::Reg::And(man32, max32, manMaskFP32, preMaskScale);

    AscendC::Reg::CompareScalar<uint32_t, AscendC::CMPMODE::GT>(p0, exp32, NUMBER_ZERO, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, AscendC::CMPMODE::LT>(p1, exp32, NUMBER_TWO_FIVE_FOUR,
                                                                     preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, AscendC::CMPMODE::GT>(p2, man32, NUMBER_ZERO, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p1, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p2, preMaskScale);

    AscendC::Reg::Adds(expAddOne32, exp32, 1, preMaskScale);
    AscendC::Reg::Select(extractExp, expAddOne32, exp32, p0);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, fp4NanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(expOut, extractExp);

    AscendC::Reg::StoreAlign<uint16_t, AscendC::Reg::StoreDist::DIST_PACK_B16>(
        dstPtr + i * SCALE_STORE_STRIDE, expOut, dataMaskB16Half);

    AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
    AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(recExpOut, halfScale);

    AscendC::Reg::StoreAlign<uint16_t>(dst2Ptr + i * vfLen32, recExpOut, dataMaskB16Half);
}
```

**要点**: castTraitHalf2Float 是 BF16→FP32 升精度，模板参数 <float, bfloat16_t, castTraitHalf2Float>，第三参传 preMaskScale（UpdateMask 生成的部分掩码）；升精度后用 CompareScalar 对指数/尾数做多阈值判断，Select 决定是否 +1 进位，是 MX/flat 量化求 scale 的通用模式；来源类型 __simd_vf__（老式 VF 上下文），与 Reg 的 __VEC_SCOPE__ 写法并存。

### 实例 8：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Cast 调用次数**: 3
- **参数模式**: `T3_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义（待补充）**: 在复数取模算子中，对 complex32 输入用 castTraitZero/castTraitOne 把 BF16/FP16 实部和虚部拆位升精度到 FP32，做平方和开方后用 castTrait32to16 把 FP32 结果回转成原始 T 类型输出。

（行 103-160）

```cpp
if constexpr (std::is_same<U, complex32>::value) {
    preg2 = AscendC::Reg::CreateMask<uint16_t, AscendC::Reg::MaskPattern::ALL>();
    Reg::LoadAlign(vSrcReg0, srcAddr + i * vflen * 2);
    Reg::Cast<float, T, castTraitZero>(vA, vSrcReg0, preg2);
    Reg::Cast<float, T, castTraitOne>(vB, vSrcReg0, preg2);
    Reg::Mul(vA1Sq, vA, vA, preg);
    Reg::Mul(vB1Sq, vB, vB, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);
    Reg::Cast<T, float, castTrait32to16>(vResult, vS, preg);
    Reg::StoreAlign<T, Reg::StoreDist::DIST_PACK_B32>(dstAddr + i * vflen, vResult, preg);
} else {
    Reg::LoadAlign<T, Reg::LoadDist::DIST_DINTLV_B32>(vSrcReg0, vSrcReg1, srcAddr + i * vflen * 2);
    Reg::Abs(vAbsSrcReg0, vSrcReg0, preg);
    Reg::Abs(vAbsSrcReg1, vSrcReg1, preg);
    Reg::Compare<float, CMPMODE::GT>(preg2, vAbsSrcReg1, vAbsSrcReg0, preg);
    Reg::Select<float>(vA, vAbsSrcReg1, vAbsSrcReg0, preg2);
    Reg::Select<float>(vB, vAbsSrcReg0, vAbsSrcReg1, preg2);

    // 0的处理
    Reg::Compare<uint32_t, CMPMODE::EQ>(preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero,
                                        preg);

    // subnormal处理
    Reg::Compare<uint32_t, CMPMODE::LT>(preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA,
                                        vMinNormalFloat, preg);
    Reg::Mul(vAS, vA, vSCALE_UP, preg);
    Reg::Mul(vBS, vB, vSCALE_UP, preg);
    Reg::Select(vA, vAS, vA, preg3);
    Reg::Select(vB, vBS, vB, preg3);
    // 提取A的指数因子（对vAForExp操作）
    Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
    Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0,
             preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0,
             preg);

    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA1, vExpBias,
             preg);
    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB1, vExpBias,
             preg);

    // 计算归化值
    Reg::Mul(vA1Sq, vA1, vA1, preg);
    Reg::Mul(vB1Sq, vB1, vB1, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);

    Reg::Mul(vResult, vS, (AscendC::Reg::RegTensor<float>&)vA0, preg);
    Reg::Mul(vResultS, vResult, vSCALE_DOWN, preg);
    Reg::Select(vResult, vResultS, vResult, preg3);

    // 0的处理
    Reg::Select(vResult, vA, vResult, preg4);

    Reg::StoreAlign(dstAddr + i * vflen, vResult, preg);
}
```

**要点**: castTraitZero/castTraitOne 配对拆位是 16bit→32bit 升精度的标准做法，Zero 取偶位、One 取奇位；castTrait32to16 反向把 FP32→half/BF16，与 castTraitZero/One 方向相反，用于把高精度中间结果压回原类型；complex32 路径用 CreateMask<ALL> 全量 mask，非 complex32 走另一分支用算法性归一化（无 Cast）。

### 实例 9：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Cast 调用次数**: 3
- **参数模式**: `T3_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义（待补充）**: 在复数取绝对值算子中，对 complex32 输入用 castTraitZero/castTraitOne 将 BF16 实虚部拆位升精度到 FP32，求 sqrt(re²+im²) 后用 castTrait32to16 回转成 T 类型输出。

（行 103-156）

```cpp
if constexpr (std::is_same<U, complex32>::value) {
    preg2 = AscendC::Reg::CreateMask<uint16_t, AscendC::Reg::MaskPattern::ALL>();
    Reg::LoadAlign(vSrcReg0, srcAddr + i * vflen * 2);
    Reg::Cast<float, T, castTraitZero>(vA, vSrcReg0, preg2);
    Reg::Cast<float, T, castTraitOne>(vB, vSrcReg0, preg2);
    Reg::Mul(vA1Sq, vA, vA, preg);
    Reg::Mul(vB1Sq, vB, vB, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);
    Reg::Cast<T, float, castTrait32to16>(vResult, vS, preg);
    Reg::StoreAlign<T, Reg::StoreDist::DIST_PACK_B32>(dstAddr + i * vflen, vResult, preg);
} else {
    Reg::LoadAlign<T, Reg::LoadDist::DIST_DINTLV_B32>(vSrcReg0, vSrcReg1, srcAddr + i * vflen * 2);
    Reg::Abs(vAbsSrcReg0, vSrcReg0, preg);
    Reg::Abs(vAbsSrcReg1, vSrcReg1, preg);
    Reg::Compare<float, CMPMODE::GT>(preg2, vAbsSrcReg1, vAbsSrcReg0, preg);
    Reg::Select<float>(vA, vAbsSrcReg1, vAbsSrcReg0, preg2);
    Reg::Select<float>(vB, vAbsSrcReg0, vAbsSrcReg1, preg2);

    // 0的处理
    Reg::Compare<uint32_t, CMPMODE::EQ>(
        preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero, preg);

    // subnormal处理
    Reg::Compare<uint32_t, CMPMODE::LT>(
        preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA, vMinNormalFloat, preg);
    Reg::Mul(vAS, vA, vSCALE_UP, preg);
    Reg::Mul(vBS, vB, vSCALE_UP, preg);
    Reg::Select(vA, vAS, vA, preg3);
    Reg::Select(vB, vBS, vB, preg3);
    // 提取A的指数因子（对vAForExp操作）
    Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
    Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0, preg);

    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA1, vExpBias, preg);
    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB1, vExpBias, preg);

    // 计算归化值
    Reg::Mul(vA1Sq, vA1, vA1, preg);
    Reg::Mul(vB1Sq, vB1, vB1, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);

    Reg::Mul(vResult, vS, (AscendC::Reg::RegTensor<float>&)vA0, preg);
    Reg::Mul(vResultS, vResult, vSCALE_DOWN, preg);
    Reg::Select(vResult, vResultS, vResult, preg3);

    // 0的处理
    Reg::Select(vResult, vA, vResult, preg4);

    Reg::StoreAlign(dstAddr + i * vflen, vResult, preg);
}
```

**要点**: 与 complex_abs 共用 castTraitZero/One + castTrait32to16 的拆位升精度+回转模式，区别在算子语义（取绝对值 vs 取模）和文件；castTrait32to16 是 FP32→16bit 的统称 trait，按 T 自动落到 half 或 bfloat16_t；complex32 分支用 CreateMask<ALL>，非 complex32 分支走纯算术归一化路径。

### 实例 10：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Cast 调用次数**: 4
- **参数模式**: `T3_A3_M1_TYPEfloat+int32_t_MASKmask`（实参 3 个，含 mask/mode: mask，类型: int32_t, float）
- **语义（待补充）**: 在仿量化（per-channel）算子中，用 kCastFp32ToInt32Floor 把浮点 zero-point/scaled 值向下取整为 int32_t，再用 kCastInt32ToFp32 转回 FP32 实现 floor 语义，确保 nudged_zp 与 TF 对齐。

**片段 1** (行 408-428):

```cpp
AscendC::Reg::Div<float, &kDivMode>(vregInvScaleSafe, vregQRange, vregDiffSaved, mask);

// 2.4 zp_from_min = qMin - min / scaleSafe
//     用 0-ULP Div：min/scaleSafe 在 zfm 落到 N+0.5 半整数边界时极易抖动 1 ULP，
//     与 floor(zfm+0.5) 叠加会让 nudged_zp 偏离 TF。
AscendC::Reg::Div<float, &kDivMode>(vregZpFromMin, vregMin, vregScaleSafe, mask);
AscendC::Reg::Muls<float>(vregZpFromMin, vregZpFromMin, -1.0f, mask);
AscendC::Reg::Adds<float>(vregZpFromMin, vregZpFromMin, qMin, mask);

// 2.5 nudged_zp = floor(clip(zp_from_min, qMin, qMax) + 0.5)
AscendC::Reg::Maxs<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(vregZpClipped, vregZpFromMin, qMin,
                                                                       mask);
AscendC::Reg::Mins<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(vregZpClipped, vregZpClipped, qMax,
                                                                       mask);
AscendC::Reg::Adds<float>(vregZpClipped, vregZpClipped, 0.5f, mask);
AscendC::Reg::Cast<int32_t, float, kCastFp32ToInt32Floor>(vregZpInt, vregZpClipped, mask);
AscendC::Reg::Cast<float, int32_t, kCastInt32ToFp32>(vregNudgedZp, vregZpInt, mask);

// 2.6 nudged_min = (qMin - nudged_zp) * scaleSafe
//     nudged_max = (qMax - nudged_zp) * scaleSafe
AscendC::Reg::Muls<float>(vregNudgedMin, vregNudgedZp, -1.0f, mask);
```

**片段 2** (行 436-455):

```cpp
// -----------------------------------------------------------------
// 阶段 3：主公式
// -----------------------------------------------------------------
// clip：clamped = min(max(x, nudgedMin), nudgedMax)
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregClamped, vregX, vregNudgedMax, mask);
AscendC::Reg::Max<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregClamped, vregClamped, vregNudgedMin,
                                                               mask);
// shift = clamped - nudgedMin
AscendC::Reg::Sub<float>(vregShift, vregClamped, vregNudgedMin, mask);
// scaled = shift * invScaleSafe + 0.5
//        与 TF 一致：使用独立计算的 inv_scale = qRange/(max-min)，
//        而非 shift/scale（二次舍入误差）
AscendC::Reg::Mul<float>(vregScaled, vregShift, vregInvScaleSafe, mask);
AscendC::Reg::Adds<float>(vregScaled, vregScaled, 0.5f, mask);
// floor 语义：fp32 → int32 (CAST_FLOOR) → fp32 (UNKNOWN)
AscendC::Reg::Cast<int32_t, float, kCastFp32ToInt32Floor>(vregFlrInt, vregScaled, mask);
AscendC::Reg::Cast<float, int32_t, kCastInt32ToFp32>(vregFloored, vregFlrInt, mask);
// out = floored * scaleSafe + nudgedMin
AscendC::Reg::Mul<float>(vregOut, vregFloored, vregScaleSafe, mask);
AscendC::Reg::Add<float>(vregOut, vregOut, vregNudgedMin, mask);
```

**要点**: kCastFp32ToInt32Floor 对应浮点→整数的 CAST_FLOOR 舍入，配合 kCastInt32ToFp32 反向转回即实现 floor(x) 语义；这是浮点转整数（表3/表7）类 Cast 的典型用法，mask 按 sizeof(float)=4 筛选；两次 Cast 成对出现（int32↔float），中间不修改 int32 值，纯做舍入语义对齐。

### 实例 11：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Cast 调用次数**: 4
- **参数模式**: `T3_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义（待补充）**: 在 SwiGLU MX 量化非末轴尺度计算中，用 CAST_ZERO/CAST_ONE 把 BF16/FP16 绝对值最大值拆位升精度到 FP32，分别处理偶/奇位得到 maxFP32_0/maxFP32_1，再做指数尾数分离求 scale。

**片段 1** (行 310-338):

```cpp
for (uint16_t i = 0; i < blockCount; i++) {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
        x0, x1, xAddr, 256);
    Reg::And(absMax0, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
    Reg::And(absMax1, (Reg::RegTensor<uint16_t>&)x1, absMask, maskAll);
    Reg::Max(absMax1Dim2, absMax1Dim2, absMax0, maskAll);
    Reg::Max(absMax2Dim2, absMax2Dim2, absMax1, maskAll);
}

// process absMax1Dim2
Reg::Cast<float, T, CAST_ZERO>((Reg::RegTensor<float>&)maxFP32_0,
                                    (Reg::RegTensor<T>&)absMax1Dim2, maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_0, (Reg::RegTensor<float>&)maxFP32_0,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_0, maxFP32_0, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_0, maxFP32_0, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_0, EXP_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_0, ZERO_FOR_ALL, p0);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32_0, SPECIAL_EXP_THRESHOLD_FP32, p1);
Reg::MaskOr(p0, p0, p1, maskFP32);
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(manFP32_0, maxFP32_0, expFP32_0, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);
Reg::Cast<float, T, CAST_ONE>((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<T>&)absMax1Dim2,
                                   maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1,
              (Reg::RegTensor<float>&)invMax, maskFP32);
```

**片段 2** (行 360-378):

```cpp
Reg::Cast<float, T, CAST_ZERO>((Reg::RegTensor<float>&)maxFP32_0,
                                    (Reg::RegTensor<T>&)absMax2Dim2, maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_0, (Reg::RegTensor<float>&)maxFP32_0,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_0, maxFP32_0, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_0, maxFP32_0, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_0, EXP_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_0, ZERO_FOR_ALL, p0);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32_0, SPECIAL_EXP_THRESHOLD_FP32, p1);
Reg::MaskOr(p0, p0, p1, maskFP32);
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(manFP32_0, maxFP32_0, expFP32_0, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);
Reg::Cast<float, T, CAST_ONE>((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<T>&)absMax2Dim2,
                                   maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1,
              (Reg::RegTensor<float>&)invMax, maskFP32);
```

**要点**: CAST_ZERO/CAST_ONE 是 Reg 风格的 16bit→32bit 拆位 trait，与 Reg 风格 castTraitZero/One 等价，按命名空间选用；两个 Cast 分别取偶/奇位得到两份 FP32，配合 Mul(invMax)/ShiftRights/And 拆指数尾数；模板参数 <float, T, CAST_ZERO>，T 为 half/bfloat16_t，trait 随源类型确定。

### 实例 12：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Cast 调用次数**: 1
- **参数模式**: `T3_A3_M1_TYPEfloat_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: float）
- **语义（待补充）**: 在 add_rms_norm + MX 量化的尺度计算中，用 castTraitHalf2Float 把 BF16 最大值升精度到 FP32，再做指数/尾数分离确定 MX scale 并 Pack 回 BF16 输出。

（行 461-495）

```cpp
for (uint16_t i = 0; i < loopNumScale4NV; i++) {
    AscendC::Reg::LoadAlign<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                 AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16, maxExpAddr, VL_F32);
    AscendC::Reg::Cast<float, T_X, castTraitHalf2Float>(
        (AscendC::Reg::RegTensor<float>&)max32, (AscendC::Reg::RegTensor<T_X>&)max16, preMaskScale);
    AscendC::Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32, expMask, preMaskScale);
    AscendC::Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32, zeroRegTensor32, preMaskScale);
    AscendC::Reg::Mul((AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)invMax, preMaskScale);
    AscendC::Reg::ShiftRights(exp32, max32, SHR_NUM_FOR_FP32, preMaskScale);
    AscendC::Reg::And(man32, max32, manMaskFP32, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32, CUBLAS_ZERO_FOR_ALL, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, exp32, CUBLAS_EXP254, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, CUBLAS_ZERO_FOR_ALL, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p1, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p2, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, exp32, CUBLAS_ZERO_FOR_ALL, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, CUBLAS_HALF_FOR_MAN, preMaskScale);
    AscendC::Reg::MaskAnd(p1, p1, p2, preMaskScale);
    AscendC::Reg::MaskOr(p0, p0, p1, preMaskScale);
    AscendC::Reg::Adds(expAddOne32, exp32, 1, preMaskScale);
    AscendC::Reg::Select(extractExp, expAddOne32, exp32, p0);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, fp8NanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(expOut, extractExp);
    AscendC::Reg::StoreAlign<uint16_t, AscendC::Reg::StoreDist::DIST_PACK_B16>(
        mxScaleLocalAddr + i * ThirtyTwo, expOut, maskHalf);
    AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
    AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(recExpOut, halfScale);
    AscendC::Reg::StoreAlign<uint16_t>(halfScaleLocalAddr + i * VL_F32, recExpOut, maskHalf);
}
```

**要点**: castTraitHalf2Float 用于 BF16→FP32 升精度，与 flat_quant/rms_norm 共用同一 MX scale 求取范式；第三参 preMaskScale 是 UpdateMask 生成的部分元素掩码，处理非整 VF 的尾段；升精度后用 CompareScalar 多阈值判断 + Select 决定进位，是 MX scale 提取的固定流程。

### 实例 13：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Cast 调用次数**: 1
- **参数模式**: `T3_A3_M1_TYPEfloat_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: float）
- **语义（待补充）**: 在 RMSNorm + MX 量化的尺度计算中，用 castTraitHalf2Float 把 BF16 最大值升精度到 FP32，按 MX scale 提取范式做指数尾数分离并 Pack 回 BF16，用 DataCopy（带 PostModeUpdate）写回。

（行 419-463）

```cpp
for (uint16_t i = 0; i < loopNumScale4NV; i++) {
    AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16, maxExpAddr, VL_FP32);

    AscendC::Reg::Cast<float, T1, castTraitHalf2Float>(
        (AscendC::Reg::RegTensor<float>&)max32, (AscendC::Reg::RegTensor<T1>&)max16, preMaskScale);
    AscendC::Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32, expMask, preMaskScale);
    AscendC::Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32, zeroRegTensor32, preMaskScale);

    AscendC::Reg::Mul((AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)invMax, preMaskScale);
    AscendC::Reg::ShiftRights(exp32, max32, SHR_NUM_FOR_FP32, preMaskScale);
    AscendC::Reg::And(man32, max32, manMaskFP32, preMaskScale);

    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32, zeroForAll, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, exp32, Exp254, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, zeroForAll, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p1, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p2, preMaskScale);

    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, exp32, zeroForAll, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, halfForMan, preMaskScale);
    AscendC::Reg::MaskAnd(p1, p1, p2, preMaskScale);
    AscendC::Reg::MaskOr(p0, p0, p1, preMaskScale);

    AscendC::Reg::Adds(expAddOne32, exp32, 1, preMaskScale);
    AscendC::Reg::Select(extractExp, expAddOne32, exp32, p0);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, fp8NanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(expOut, extractExp);

    AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::StoreDist::DIST_PACK_B16>(mxScaleLocalAddr, expOut,
                                                                             VL_FP32 / NUM_TWO, maskHalf);

    AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
    AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(recExpOut, halfScale);

    AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        halfScaleLocalAddr, recExpOut, VL_FP32, maskHalf);
}
```

**要点**: 与 add_rms_norm 共用 castTraitHalf2Float 升精度 + 指数尾数分离范式，差异在存储用 DataCopy（POST_MODE_UPDATE 自增地址）；castTraitHalf2Float 模板 <float, T1, castTraitHalf2Float>，T1 为 bfloat16_t，第三参 preMaskScale 处理尾段；无 CastTrait/RegLayout 成员（仅 1 次 Cast），其余为 CompareScalar/Select/MaskAnd/MaskOr 组合做 scale 提取。

### 实例 14：dynamic_mx_quant::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **Cast 调用次数**: 2
- **参数模式**: `T3_A3_M1_TYPEbfloat16+float+half_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: bfloat16, float, half）
- **语义（待补充）**: 在 MX 量化尾轴 FP8 路径中，对 half 输入用 castTraitHalf2Bf16 转成 BF16 以统一指数位提取，配合 And/Compare 做 INF/NAN 校验后 ReduceMax 求指数最大值并 StoreUnAlign 写出。

（行 458-477）

```cpp
for (uint16_t i = 0; i < loopNum2VF; i++) {
    Reg::LoadAlign<half, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(x0, x1, xLocalAddr,
                                                                                             VF_LEN_16_DOUBLE);
    Reg::And(xExpSelect0, (Reg::RegTensor<uint16_t>&)x0, invalidMaskFP16, Mask);
    Reg::And(xExpSelect1, (Reg::RegTensor<uint16_t>&)x1, invalidMaskFP16, Mask);
    Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask0, xExpSelect0, invalidMaskFP16, Mask);
    Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask1, xExpSelect1, invalidMaskFP16, Mask);
    Reg::Cast<bfloat16_t, half, castTraitHalf2Bf16>(x0BF16, x0, Mask);
    Reg::Cast<bfloat16_t, half, castTraitHalf2Bf16>(x1BF16, x1, Mask);
    Reg::And(xExpExtract0, (Reg::RegTensor<uint16_t>&)x0BF16, expMaskBF16, Mask);
    Reg::And(xExpExtract1, (Reg::RegTensor<uint16_t>&)x1BF16, expMaskBF16, Mask);
    Reg::Select<uint16_t>(xExpExtract0, xExpExtract0, expMaskBF16, invalidDataMask0);
    Reg::Select<uint16_t>(xExpExtract1, xExpExtract1, expMaskBF16, invalidDataMask1);

    Reg::Max(xMaxExp, xExpExtract0, xExpExtract1, Mask);
    Reg::ReduceMaxWithDataBlock(xMaxExp, xMaxExp, Mask);

    Reg::StoreUnAlign<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(maxExpAddr, xMaxExp, ureg,
                                                                    ELEMENT_AFTER_REDUCE_);
}
```

**要点**: castTraitHalf2Bf16 用于 half→bfloat16_t 转换（16bit→16bit 但指数位宽不同），便于用 BF16 的 expMask 提取指数；模板参数 <bfloat16_t, half, castTraitHalf2Bf16>，三种类型同时出现在签名（half 源、bfloat16_t 目的、float 中间）；mask 用 Mask（变量名），LoadAlign 用 DIST_DINTLV_B16 成对载入 x0/x1。

### 实例 15：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, And, Compare, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreDist, Sub
- **Cast 调用次数**: 2
- **参数模式**: `T3_A3_M1_TYPEbfloat16+float_MASKmask`（实参 3 个，含 mask/mode: mask，类型: bfloat16, float）
- **语义（待补充）**: 在双轴 MX 量化中，对 half 输入先用 castTraitHalf2BF16Rint（四舍五入）转成 BF16 再取绝对值，与 OCP 的 CAST_TRUNC 截断不同，需对 INF/NAN 做替换保护。

（行 953-972）

```cpp
if constexpr (IsSameType<xDtype, half>::value) {
    // FP16输入: 先检查INF/NAN，再转BF16(RINT)，取绝对值，INF/NAN替换为BF16 INF
    Reg::And(expOnly, (Reg::RegTensor<uint16_t>&)x0, expMaskFP16, maskAll);
    Reg::Compare<uint16_t, CMPMODE::NE>(infNanDataMask0, expOnly, expMaskFP16, maskAll);
    Reg::And(expOnly, (Reg::RegTensor<uint16_t>&)x1, expMaskFP16, maskAll);
    Reg::Compare<uint16_t, CMPMODE::NE>(infNanDataMask1, expOnly, expMaskFP16, maskAll);
    // 转BF16 (使用CAST_RINT四舍五入，不同于OCP的CAST_TRUNC截断)
    Reg::Cast<bfloat16_t, xDtype, castTraitHalf2BF16Rint>(x0BF16, x0, maskAll);
    Reg::Cast<bfloat16_t, xDtype, castTraitHalf2BF16Rint>(x1BF16, x1, maskAll);
    // 取绝对值
    Reg::And(absVal0, (Reg::RegTensor<uint16_t>&)x0BF16, absMask, maskAll);
    Reg::And(absVal1, (Reg::RegTensor<uint16_t>&)x1BF16, absMask, maskAll);
    // INF/NAN位置替换为BF16的INF (0x7f80)
    Reg::Select<uint16_t>(absVal0, absVal0, expMaskBF16, infNanDataMask0);
    Reg::Select<uint16_t>(absVal1, absVal1, expMaskBF16, infNanDataMask1);
} else {
    // BF16输入: 直接取绝对值
    Reg::And(absVal0, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
    Reg::And(absVal1, (Reg::RegTensor<uint16_t>&)x1, absMask, maskAll);
}
```

**要点**: castTraitHalf2BF16Rint 对应 half→bfloat16_t 的 CAST_RINT 舍入模式，与 castTraitHalf2Bf16（默认截断）区别在舍入策略；转换前先用 And+Compare 检测 INF/NAN，转换后用 Select 把 INF/NAN 位置替换为 BF16 INF，避免舍入破坏特殊值；half 走 Cast 转换路径，bfloat16_t 输入直接 And 取绝对值，分支由 if constexpr(IsSameType<xDtype,half>) 选择。

### Cast 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, CastTrait, Compare | BF16/FP16→FP32 拆位升精度求 MX scale，FP32→BF16 回转，FP32→FP8 量化输出 | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, CastTrait, Compare | BF16→FP32 升精度求指数最大值，castTraitZero/One 拆位升精度乘 scale | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange | CAST_X_TO_FP32_ZERO/ONE 拆位升精度，CAST_32_TO_80~83 分段 FP32→FP8 量化 | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, adds, CreateMask | castTraitB16ToB32 升精度做归约，FP32→int8/fp8/hifloat8 多类型量化链 | __aicore__ |
| dynamic_block_quant | And, CastTrait, CompareScalar, CreateMask | Div 求 scale 后 castTrait32toh8Zero/castTrait32tofp8/三级链把 FP32→hifloat8/fp8/int8 | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, And, Compare, CompareScalar | UnPack 拆位 + CAST_X_TO_FP32_ZERO 升精度求尺度 | __VEC_SCOPE__ |
| flat_quant | Adds, And, CastTrait, Compare | castTraitHalf2Float 升精度，FP32 指数尾数分离求 fp4 scale | __simd_vf__ |
| complex_abs | Abs, Add, CastTrait, Compare | castTraitZero/One 拆位升精度求 sqrt(re²+im²)，castTrait32to16 回转 | __aicore__ |
| abs | Abs, Add, CastTrait, Compare | castTraitZero/One 拆位升精度求复数绝对值，castTrait32to16 回转 | __aicore__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, adds, Compares | kCastFp32ToInt32Floor + kCastInt32ToFp32 成对实现 floor 语义 | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Compare, CompareScalar | CAST_ZERO/CAST_ONE 拆位升精度求指数尾数 | __aicore__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Compare, CompareScalar | castTraitHalf2Float 升精度做 MX scale 指数尾数分离 | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Compare, CompareScalar | castTraitHalf2Float 升精度 + DataCopy 写回 MX scale | __aicore__ |
| dynamic_mx_quant | And, CastTrait, Compare, CreateMask | castTraitHalf2Bf16 把 half 转 BF16 统一指数位提取 | __VEC_SCOPE__ |
| dynamic_mx_quant_with_dual_axis | Add, And, Compare, CreateMask | castTraitHalf2BF16Rint 四舍五入 half→BF16，INF/NAN 替换保护 | __VEC_SCOPE__ |

