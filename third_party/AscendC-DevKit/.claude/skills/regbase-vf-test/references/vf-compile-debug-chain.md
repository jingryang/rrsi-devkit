# VF 单测编译/执行链路解剖与失败排查（regbase-vf-test）

> **定位**：`ascendc-vf-test-agent` 编写 VF 后"编译 + 运行 + 失败排查"的**链路地图与快速排查**。
> 目的是让 agent 遇到编译/运行问题时**按图索骥、一次定位**，而不是 `inspect.getsource`
> 逆向 `ttk` 的 `CceManualCompile` 源码去猜编译参数——后者是历史上 VF 单测 agent 最耗时的
> 空转点（一次 argmax 归约 VF 单测为此多花上百轮）。
>
> 数据来源：`$SKILL_ROOT/SingleOperatorLaunch/source_module.py`（本 Skill 封装的编译执行器，
> 随仓可读，**以它为准**，无需逆向 ttk）。

## 1. 链路全貌（谁调谁）

```
test_{vf}.py
  └─ SourceModule(source, ..., kernel_meta=...)          # pycuda 风格入口
       └─ _compile_kernel(kernel_path, platform, core_type, ...)
            ├─ 写 .cce → 生成 kernel_meta JSON（blockDim/magic/coreType/workspace）
            ├─ CceManualCompile._compile_cce(.cce, .i, platform, core_type, extra_compile_options)
            └─ CceManualCompile._ld("<name>.o", [<name>.i, <name>_meta.i])
       └─ _KernelFunction.__call__(...)  → 拷贝 HBM → 运行 → 回读 → 精度比对
```

- **arch / 编译参数**：由 ttk 内部 `CceManualCompile` 根据 `platform`（soc_version 字符串）自动
  映射（`_get_arch_for_ccec`）。**agent 不要自己写死 arch、不要改 `_compile_cce` 参数**——传对
  `platform`/`core_type` 即可。
- **include 路径**：`_get_ascend_include_paths()` 从 `$ASCEND_HOME_PATH` 自动拼出
  `asc/include/{basic_api,adv_api,reg_compute,simt_api,utils,...}`。找不到头文件先查
  `$ASCEND_HOME_PATH` 是否就绪，不要手工拼绝对路径。
- **platform 探测**：`_auto_detect_platform()`（`get_ascend_full_soc_version` → DeviceInfo）；
  探测失败时**显式传 `platform`** 或用 `asys` 取 soc 名。
- **kernel_meta（编译产物目录）**：默认落在"调用脚本所在目录"，且每次 fresh-build 清旧产物。
  测试脚本应**显式** `SourceModule(..., kernel_meta=<脚本目录>/kernel_meta)`，禁止依赖 cwd 下的
  kernel_meta（cwd 与脚本目录可能不一致且无法清理）。

## 2. 编译失败快速排查表

| 现象 | 根因 | 对策 |
|------|------|------|
| `Do not know how to split the result of this operator` | `__simd_vf__` 未 `inline` / RegTensor 数量超限 | 检查 VF 是否 `__simd_vf__ inline`；寄存器（RegTensor≤32 / MaskReg≤8） |
| `no matching function for call to 'Xxx'` | 该 dtype 不支持该 API（如 `PairReduceElem` 仅 half/float 且仅 SUM） | 查 `references/a5-api-enhanced/{Xxx}.md` 的 dtype 支持表；不支持则换 API 或换实现 |
| `static_assert ... const` 拒绝 | `__ubuf__ const T*` 被 `LoadAlign` 等 static_assert 拒 | VF 形参去 const（函数体内不写输入） |
| 头文件找不到 / `No such file` | `ASCEND_HOME_PATH` 未设或 arch 子目录错 | 确认环境 `ASCEND_HOME_PATH`；确认 aarch64/x86 子目录 |
| 改了源码仍跑旧结果 | kernel_meta 未清理（陈旧二进制） | 显式指定 kernel_meta 并在重跑前清理该目录 |
| platform 探测失败 | 无 `asys` / DeviceInfo 失败 | 显式传 `platform` 字符串 |

## 3. 查 SDK API 签名/支持范围（比逆向源码更快的路径）

优先级：`references/vf-instructions/` → `references/a5-api-enhanced/` → `ascendc-dev-knowledge` →
**SDK 头文件**。

- 声明（签名/默认参数）：`$ASCEND_HOME_PATH/<arch>-linux/asc/include/basic_api/reg_compute/*.h`
- 实现（模板展开/重载）：`$ASCEND_HOME_PATH/<arch>-linux/asc/impl/basic_api/reg_compute/*.h`
- 只在上述文档都查不到时才下钻头文件，且只 `grep` 具体函数名/模板签名；**不要**
  `inspect.getsource(CceManualCompile)` 逆向 ttk 去推编译参数（那是编译链路内部，见 §1）。

## 4. 运行/精度失败快速排查

- **OOB/越界**：`diagnostics.py` 提供 OOB 检测；先跑最小 shape 定位是搬运还是计算越界。
- **精度失败**：先核对"计算序是否与 golden 逐序一致"（fp32 不结合）、尾块 mask、dtype 往返
  Cast；再对照对应 `vf_experiences` 条目坑位。
- **环境错误**：`DeviceInfo` 显示 Health=CRITICAL 时按 `error_type=ENV` 上报，不继续重试。

## 5. 使用纪律

- 编译失败 → 先查本表 + 按 `error_type`（COMPILE/PREC/ENV）分类返回，**不无限重试**（MAX_RETRY=3）。
- 遇到"某 API 某 dtype 支持与否"查不到时，按 `knowledge_policy.md` 的"信息遗漏处理"暴露，
  不静默假设支持。
