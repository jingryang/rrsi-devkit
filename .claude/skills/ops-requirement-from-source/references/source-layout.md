# 源码布局与文档版本选择

## 1. 标准布局

```text
PATH/
├── docs/                      # 接口文档，可能有多份/多版本
├── op_kernel/                 # device 侧 kernel；可能含 arch22/、arch35/ 等
├── op_host/                   # host 侧：def、infershape、tiling、config
│   └── op_api/                # 部分算子把 aclnn 实现放在这里
├── op_api/                    # 另一部分算子直接放在算子根目录
├── op_graph/                  # 算子原型 <op>_proto.h
├── examples/                  # test_aclnn_*.cpp
├── tests/
│   ├── assets/golden.py       # golden 常见位置
│   ├── st/<api_name>/         # atk_*.json + executor_*.py
│   ├── st/arch35/             # ttk_*.csv
│   └── ut/                    # 不适合作为需求来源，仅辅助
└── torch_extension/           # torch 接入层，可辅助确认参数名
```

所有位置都是默认值，不是硬性要求。目录名不同但语义等价时按实际结构识别，在 `design.md 记录替换关系。

## 2. 算子名推导与校验

1. `ops_snake` = `basename(realpath(PATH))`，例如 `deep_norm`。
2. `ops_pascal` 默认由 `ops_snake` 按 `_` 分段首字母大写得到：`deep_norm → DeepNorm`。
3. 用 `op_host/*_def.cpp` 中 `class Xxx : public OpDef` 与 `OP_ADD(Xxx)` 校验。
4. `ops_pascal` 与目录名不一致时以源码为准，例如目录 `add_rms_norm_quant_v2` 注册 `AddRmsNormQuantV2`；在 `design.md` 记录差异。

## 3. 文档候选与匹配

### 3.1 候选收集

`PATH/docs`（及用户指定路径）下所有 `*.md`，按文件名归类：

| 文件名模式 | 含义 | 默认优先级 |
|---|---|---|
| `aclnn<OpsPascal>.md` | 单接口 aclnn 文档 | 1 |
| `aclnn<A>&aclnn<B>.md` | 多入口组合文档 | 2 |
| `aclnn<OpsPascal>V<N>.md` | 其他版本号 | 按版本与接口调用关系决定 |
| `ascendir<OpsPascal>[V<N>].md` | IR/图模式接口文档 | 3 |
| `torchapi_<ops_snake>.md` | torch 接入说明 | 4（仅补参数语义） |
| `*FusionPass*.md`、`*Pass.md` | 融合 pass 文档 | 排除 |
| `README.md`、`*Welford*`、专题分析 | 背景/算法说明 | 排除（可辅助理解） |

### 3.2 版本选择步骤

1. **精确匹配**：`aclnn<OpsPascal>.md` 存在且接口功能与 op def 一致 → 采用。
2. **源码接口反向确认**：读取 `op_api/aclnn_*.h` 或 `op_host/**/aclnn_*.h`，取得实际 `aclnnXxxGetWorkspaceSize` 名称；文档中同名接口的章节才算有效。
3. **tests/examples 反向确认**：`tests/st/*/executor_*.py` 的 `get_cpp_func_signature_type`、`examples/test_aclnn_*.cpp` 中的调用名。
4. **版本后缀确认**：op def 中 `.Version(N)`、`CLIPPED_SWIGLU_VERSION_TWO` 之类常量；V2 属性只出现在 V2 接口。
5. **目录名与文档版本不一致**：以接口名映射为准。例：`quant_batch_matmul_v4` 目录对应 `aclnnQuantMatmulV5.md` 与 `aclnn_quant_matmul_v5.h`，此时采用 V5 文档并在 `design.md` 记录映射。
6. **多入口组合文档**：只提取与 `ops_pascal` 对应的入口章节；inplace/weightNz 等变体不作为主接口，除非用户指定。
7. 仍有多个候选且无法由上述证据区分 → 一次性询问用户，列出候选与各自差异。

### 3.3 文档必须提取的字段

- 功能说明与计算公式；
- `aclnnXxxGetWorkspaceSize` 完整参数表：张量、标量、属性，必选/可选，输出槽；
- 输入/输出 dtype、format、shape 约束与广播规则；
- 属性默认值与取值范围；
- 所选芯片种类的支持行与不支持行；
- 精度标准与容差；
- 是否有多个输出、输出 dtype 与输入不同的情况。

## 4. aclnn 接口位置回退

```text
PATH/op_api/
PATH/op_host/op_api/
PATH/op_host/                      # 少数算子直接平铺
```

命中多个 `aclnn_*.h` 时，按“文件名与 `ops_snake` 最接近”的规则选择；无匹配时读取所有头文件中的 `GetWorkspaceSize` 签名，选择参数与文档一致的接口，并记录。

## 5. tests 解析

| 文件 | 用途 |
|---|---|
| `tests/assets/golden.py` | 首选 golden；可能包含 kernel/aclnn 两套入口与 `__golden__` 注册表 |
| `tests/**/golden*.py` | 备用 golden |
| `tests/st/**/ttk_*.csv` | 已有用例矩阵：`input_shapes`、`input_dtypes`、`attributes`、`input_data_ranges`、`soc_series` |
| `tests/st/**/atk_*.json` | 已有用例：`inputs[].dtype/shape/range_values`、attr 取值 |
| `tests/st/**/executor_*.py` | 实际 golden 与 `get_cpp_func_signature_type`，可确认输出顺序 |
| `tests/ut/**` | 分支/边界线索，不作为需求语义来源 |

用例合并时保留 `soc_series`/`chips` 信息：只保留与所选芯片种类一致的条目（默认 `("Ascend950",)` 等 A5 标识）。其他芯片条目直接排除，不做转换；`soc_series` 为空的条目按所属目录与 dtype/shape 合法性判断，无法确认时排除。

## 6. 芯片种类与范围限制

`芯片种类` 参数（默认 `A5`）决定允许读取和引用的源码范围：

| 芯片种类 | 产品/SoC | arch 目录 | config 目录 | 文档支持行 | `soc_series` |
|---|---|---|---|---|---|
| `A5`（默认） | Ascend 950（950PR/950DT）、3510 | `arch35` | `ascend950`、`ascend350` | Ascend 950PR&950DT 系列 | `Ascend950` 等 |
| `A3` | Atlas A3 910B/910C | `arch22` | `ascend910b`、`ascend910_93` | Atlas A3 系列 | `Ascend910B`、`Ascend910_93` 等 |
| `A3,A5` | 两者 | 两者 | 两者 | 两者 | 两者 |

规则：

1. 未指定时一律按 `A5` 执行，不得自行扩大到 A3 或其他芯片。
2. 只读取所选芯片的 arch 目录、config 目录、`AddConfig("<soc>")` 分支和文档支持行；共享的公共头文件可以读，但只采纳对所选芯片生效的分支。
3. `ascend960*`、`ascend310p`、`kirin*`、`__NPU_ARCH__ == 3003/3113` 等未列入所选范围的分支一律记录为范围外，不进入需求、golden、cases、desc。
4. 所选芯片在 `op_host/*_def.cpp`、`op_kernel/`、`op_host/config/` 中完全没有对应实现或配置时，停止并报告缺口；不得自动降级到其他芯片。
5. `A3,A5` 时两条路径分别分析，在 `design.md` 分节记录，芯片差异写进 `desc.md` 与 `design.md`；用例 `note` 只描述用例特征，不写芯片种类。
