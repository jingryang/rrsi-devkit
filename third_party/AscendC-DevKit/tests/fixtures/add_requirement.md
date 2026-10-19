# Add 算子需求

## 基本定义
- **算子名**: add
- **算子类型**: 逐元素二元运算
- **公式**: y = x1 + x2

## 输入
- x1: Tensor(float16/float32), shape 任意, format ND
- x2: Tensor(float16/float32), shape 与 x1 广播兼容, format ND

## 输出
- y: Tensor(float16/float32), shape 为广播后的结果, format ND

## 约束
- 无属性参数
- 支持广播
- 精度目标: 相对误差 < 1e-3
