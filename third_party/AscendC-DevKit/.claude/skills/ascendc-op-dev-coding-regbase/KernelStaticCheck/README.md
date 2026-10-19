# KernelStaticCheck

AscendC / RegBase 算子内核源码静态检查工具。

用于在 NPU 编译/运行之前，对算子内核源码进行轻量级正则预检，尽早发现常见的
RegBase 编程规范问题。支持命令行批量扫描和 Python 库接口两种使用方式。

---

## 目录结构

```text
KernelStaticCheck/
├── __init__.py          # 库入口，导出公共 API
├── __main__.py          # 支持 python3 -m KernelStaticCheck
├── check_kernel.py      # 独立入口脚本，支持 python3 check_kernel.py ...
├── cli.py               # 命令行入口实现
├── checker.py           # 静态检查核心实现
└── tests/               # pytest 测试集
```

---

## 功能简介

KernelStaticCheck 会扫描 AscendC 算子源码中的 `__simd_vf__` / `__simd_callee__`
函数，检查其是否符合 RegBase 矢量函数编程规范，从而避免把明显不符合规范的代码
带入后续昂贵的 `ccec` 编译阶段。

支持扫描单文件、多文件、目录；支持递归扫描子目录；支持自动探测 kernel 入口名；
支持文本 / JSON 两种报告输出；支持通过退出码在 CI 流水线中集成。

---

## 检查规则

| 检查项 | 说明 |
|--------|------|
| `simd_vf_modifiers` | `__simd_vf__` / `__simd_callee__` 函数是否带 `inline` 关键字 |
| `simd_vf_ubuf_access` | SIMD 函数体内是否用 `ptr[i]` 直接访问 `__ubuf__` |
| `simd_vf_no_gm` | SIMD 函数体内/参数是否出现 GM/HBM 访问（`GM_ADDR`、`__gm__`、`GlobalTensor`、`SetGlobalBuffer`） |
| `hardware_loop_var_type` | SIMD 函数 `for` 循环变量是否为 `uint16_t` |
| `hardware_loop_branch` | SIMD 函数 `for` 循环体内是否包含运行时 `if/else` 或三目运算符 `?:`（`if constexpr` 除外） |
| `hardware_loop_var_mutation` | `UpdateMask<T>(var)` 的参数是否在循环体内被重新赋值/修改 |
| `vf_function_level_branch` | SIMD 函数在循环体外是否包含运行时分支 |

> 这些检查基于正则实现，属于快速预检，不能替代 `ccec` 编译检查。复杂场景下可能
> 存在误报或漏报，需要结合人工判断。

---

## 命令行使用

提供了两种命令行调用方式：独立脚本方式与模块方式，功能完全一致。

### 方式一：直接运行独立脚本（推荐）

```bash
# $SKILL_ROOT = ascendc-op-dev-coding-regbase skill 目录（SKILL.md 注入）
python3 "$SKILL_ROOT/KernelStaticCheck/check_kernel.py" /path/to/op_kernel
```

也可以给脚本加上执行权限后直接运行：

```bash
chmod +x "$SKILL_ROOT/KernelStaticCheck/check_kernel.py"
"$SKILL_ROOT/KernelStaticCheck/check_kernel.py" /path/to/op_kernel
```

### 方式二：通过模块方式运行

```bash
cd "$SKILL_ROOT/KernelStaticCheck"
python3 -m KernelStaticCheck /path/to/op_kernel
```

### 扫描单个文件

```bash
python3 "$SKILL_ROOT/KernelStaticCheck/check_kernel.py" /path/to/softmax_kernel.cpp --kernel-name softmax
```

### 递归扫描目录

```bash
python3 "$SKILL_ROOT/KernelStaticCheck/check_kernel.py" /path/to/op_kernel --recursive
```

会自动搜索 `.cpp` / `.h` / `.hpp` / `.cc` / `.cxx` / `.c` 文件，并尝试从每个文件中的
`extern "C" __global__ __aicore__ void <name>` 自动推断 kernel 入口名。

### 输出 JSON 报告

```bash
python3 KernelStaticCheck/check_kernel.py /path/to/op_kernel --format json
```

### 常用参数

| 参数 | 说明 |
|------|------|
| `paths` | 一个或多个文件/目录路径 |
| `-k, --kernel-name` | 强制指定所有文件的 kernel 入口名（默认自动探测） |
| `-r, --recursive` | 递归扫描子目录（默认开启） |
| `--no-recursive` | 不递归扫描 |
| `-f, --format` | 输出格式：`text` / `json` |
| `--strict` | 发现失败时返回非零退出码（默认） |
| `--no-strict` | 即使发现失败也返回 0 |
| `-q, --quiet` | 不输出报告，仅设置退出码 |

### 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 所有扫描文件均通过检查 |
| 1 | 至少一个文件失败，或扫描过程中发生错误 |

---

## 库接口使用

```python
from KernelStaticCheck import check_regbase_source, RegBaseChecker

source = '''
template <typename T>
__simd_vf__ inline void BadVf(__ubuf__ T* dst, __ubuf__ T* src, uint32_t n)
{
}
'''

# 方式 1：直接调用并抛出异常（默认）
try:
    check_regbase_source(source, "bad_kernel")
except RuntimeError as exc:
    print(exc)

# 方式 2：仅获取报告，不抛异常
report = check_regbase_source(source, "bad_kernel", raise_on_failure=False)
if not report.passed:
    for failure in report.failures:
        print(failure.name, failure.message)

# 方式 3：直接操作 Checker
checker = RegBaseChecker(source, "bad_kernel")
report = checker.run_all()
print(report)
```

---

## 测试

```bash
cd "$SKILL_ROOT/KernelStaticCheck"
python3 -m pytest tests -v
```

当前测试集包含 109 个用例，覆盖全部检查规则、边界场景、命令行入口及独立脚本入口。

---

## 工作原理

1. **源码预处理**：读取源码后，先剔除 C/C++ 字符串字面量和注释，避免它们被误识别为代码。
2. **函数定位**：通过正则匹配 `__simd_vf__` / `__simd_callee__` 函数定义。
3. **函数体提取**：使用基于大括号配对的简单解析器提取函数体，支持嵌套结构。
4. **规则检查**：在每个函数体 / 循环体内应用对应的正则规则，生成检查报告。
5. **报告聚合**：把所有规则的检查结果聚合为 `StaticCheckReport`，支持文本和 JSON 输出。

---

## 注意事项

- 本工具适合在 CI 或本地作为前置检查使用，不能替代 `ccec` 编译器。
- 对于 `__aicore__` 中的普通循环、非 SIMD 函数等，不会触发 RegBase 专用规则。
- 变量声明初始化（如 `uint32_t remaining = dimSize;`）不会被误判为对
  `UpdateMask` 参数的 Mutation。

---

## 许可

与 `ops-test-kit` 仓库保持一致，详见根目录 `LICENSE` 与 `THIRD_PARTY_NOTICES`。
