# Step 3-5：冒烟、全量跑与精度归因

> 本文的 `$WORKDIR`、`<case>`、`out<k>` 均为占位符；路径和用例名来自用户输入。

## Step 3：冒烟 —— 只验功能，不看精度

冒烟的 gate 是"链路通"，不是"MARE 好看"。精度列是 `PASS`、`FAIL` 还是 `SKIP` 都**不影响冒烟判定**——golden 正常参与比对也没关系。

```shell
mkdir -p "$WORKDIR/debug"
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH="$WORKDIR/debug/dump" python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --plugin "$WORKDIR" \
  -t <最小用例> --dump in,out,golden --dump-format npy \
  -o "$WORKDIR/debug/smoke_result.csv" > "$WORKDIR/debug/smoke.log" 2>&1
```

`PYTHONDONTWRITEBYTECODE=1` 防止 Python 在产物根目录留下 `__pycache__/`（`--plugin $WORKDIR`
会导入产物）。`finalize_cases.py` 收尾时也会兜底清理。

> **退出码语义**：ttk 只要有用例 FAIL 就返回 1，命令本身并没有出错。所以**不要用 `&&`
> 把冒烟和全量跑串起来**——冒烟精度没过也会把后续步骤断掉。每一步单独执行，按结果 CSV 判断。

冒烟只看：

| 检查 | 判据 |
|------|------|
| 设备执行 | 无 ACLNN 报错、用例能跑到 `OnReturning` |
| golden 生成 | 结果/日志无 `GOLDEN_FAILURE`、无 `TypeError` |
| 输出数量 | dump 目录 `golden_*` 文件数 == `output_tensor_indexes` 长度 |
| 输出 shape/dtype | `np.load` 后与 Step 0 推导一致 |
| 数值健全性 | 不是全 0 / 全 NaN |

任一项不满足 → 回 Step 1（CSV/用例问题）或 Step 2（golden 签名/实现问题），不要靠调 tolerance 绕过。

> **可选**：想进一步把执行与 golden 解耦，可加 `--golden-mode Disable`，但不要假设它一定生效——
> 默认 `mixed`/`mix_tolerance`/`cross_check` 判据属于 `PROMOTE_GOLDEN_TOKENS`，worker 会设置
> `golden_mode_override="Promote"`，Disable 被覆盖，golden 仍会生成并比对。要真正 SKIP 需同时
> 指定 `--compare stat_rel_err` 或 `--compare close`。冒烟本身不需要这个开关。

dump 位置与命名（ACLNN）：

```
$WORKDIR/debug/dump/<testcase_name>/     # 经 NPU_DUMP_PATH 重定向
  input_0_<dtype>.npy      # 按 flat 张量槽编号（含输出槽前的输入）
  output_0_<dtype>.npy     # 按输出槽顺序
  golden_0_<dtype>.npy
```

不设 `NPU_DUMP_PATH` 时默认落到仓库根 `dump/`——那会污染测试仓，必须重定向到 `debug/dump`。

用 `ls $WORKDIR/debug/dump/<case>/` 确认真实文件名再加载；`golden_0` 对应 `output_tensor_indexes[0]`。

- **golden 的 dtype 可能不同于 output**：默认判据会触发 Promote，golden 以 float32（甚至 float64）落盘，
  output 按算子声明 dtype（如 float16）落盘。比对时按数值对齐即可。
- **dump 目录不自动清理**：同一用例重跑会叠加新旧文件（不同 dtype 或不同次运行的
  `golden_<k>_*.npy` 并存）。排障前先 `rm -rf $WORKDIR/debug/dump/<case>`，否则会拿旧数据得出错误结论。

## Step 4：全量跑

```shell
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH="$WORKDIR/debug/dump" python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --plugin "$WORKDIR" \
  -o "$WORKDIR/debug/result.csv" --dump-on-fail --dump-format npy \
  > "$WORKDIR/debug/full_run.log" 2>&1
```

- 未传 `--compare`：按 `Spec.tolerance` 逐输出路由，未声明则 `mixed`；
- `--plat` 需要完整平台名（用 `python3 -m ttk info` 查），否则可能不识别；
- 记录：PASS/FAIL 数、失败用例、失败输出槽（`precision_status` 列会带原因）；
- 退出码 1 = 有用例 FAIL（`bridge.py` 在 `ins.fail_count` 非 0 时 `SystemExit(1)`），
  **不是**命令执行失败；一定要看结果 CSV；
- `precision_status` 的正常取值只有 `PASS`/`FAIL`/`SKIP`。出现 `FAILURE`、`GOLDEN_FAILURE`、
  `COMPARE_FAILURE`、`INPUT_GEN_FAILURE` 说明该用例根本没走到精度结论：先查 `full_run.log`
  里的异常栈。设备瞬时错误（典型如 `Runtime API Call rtCtxCreate() Failed:
  ACL_ERROR_RT_DRV_INTERNAL_ERROR`、`aclrtSetDevice() Failed: 507033`、`rtMalloc() Failed:
  ACL_ERROR_RT_MEMORY_ALLOCATION`，多因 HBM 被其它任务占满）清掉旧 dump 后单独 `-t` 复跑即可，
  也可用 `--devices <id>` 换一台空闲设备（`npu-smi info` 看 HBM 占用）；
  **不要**为此改用例或放宽判据；
- 运行日志在仓库根 `log/aclnn/<case>/`，复制到 `$WORKDIR/debug/log/aclnn/` 归档。

多进程并发限制：同一目录不要并行跑两条 ttk（会争抢日志/编译目录），也不要和其它任务抢同一张卡。

## Step 5：精度异常的归因顺序

按 1→4 顺序判断，**不要跳过 1、2 直接调 tolerance**。

### 1. Golden 接线或实现错

- 症状：所有输出/整槽偏离、输出错位、dtype 不符、`GOLDEN_FAILURE`。
- 处置：修 spec 形参顺序、输出列表顺序、dtype；回到 Step 3。

### 2. 用例本身违反约束

- 症状：执行失败、输出 shape 与声明不一致、结果 Inf/NaN。
- 检查文档约束：dtype 是否受支持、维度约束、shape 是否满足 broadcast/后缀关系、range 是否导致溢出。
- 处置：改用例；不要靠插件修正非法输入。

### 3. golden 精度不足导致的"伪失败"

典型形态：

- 只有 **极少数元素** 失败，`golden` 在这些点接近 0（输出由大数相减得到的抵消点）；
- 绝对误差只有几到几十 ULP，但相对误差被放大；
- 同一用例的其它输出（统计量等）全 PASS。

取证三步（必须做，不能靠感觉）：

```shell
# (0) 先删旧 dump，避免新旧文件混读（dump 目录不会自动清理）
rm -rf "$WORKDIR/debug/dump/<case_name>"

# (1) 失败用例复跑，确认可复现、失败槽固定
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH="$WORKDIR/debug/dump" python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --plugin "$WORKDIR" \
  -t <case_name> --compare stat_rel_err --dump-on-fail --dump-format npy \
  -o "$WORKDIR/debug/result_stat.csv" > "$WORKDIR/debug/stat_rel_err.log" 2>&1

# (2) 看失败元素规模与量级（脚本按 stat_rel_err 口径算 mere/mare，
#     并标出“去掉最坏点后 mare 是否骤降”——骤降即单点决定整张用例）
python3 .claude/skills/ttk-aclnn-adapt/scripts/inspect_dump.py \
  "$WORKDIR/debug/dump/<case_name>" --near-zero 1e-5
```

(3) **用 float64 独立参考复算**。读 dump 的输入，按同一数学公式在 float64 下重算，
再分别对"设备输出"和"用户 golden"算同一判据：

```python
import numpy as np

d = "$WORKDIR/debug/dump/<case_name>"
# 输入按张量槽顺序加载；dtype 文件名以 ls 为准
in0 = np.load(f"{d}/input_0_float32.npy").astype(np.float64)
in1 = np.load(f"{d}/input_1_float32.npy").astype(np.float64)
out = np.load(f"{d}/output_<k>_float32.npy").astype(np.float64)
gold = np.load(f"{d}/golden_<k>_float32.npy").astype(np.float64)

# 用 Step 2 的 _compute 同一公式，在 float64 下重算
ref64 = ...                                          # float64 参考

def mare(a, g, floor=2**-23):
    return (np.abs(a - g) / np.maximum(np.abs(g), floor)).max()

print("device vs fp64 :", mare(out, ref64))
print("golden vs fp64 :", mare(gold, ref64))         # golden 自己也不过 → 伪失败
print("device vs golden:", mare(out, gold))
```

若 `golden vs fp64` 的 mare 与 `device vs golden` 同量级，说明**用户 golden 自身**在
抵消点就是主要误差源，不是算子缺陷。

进一步按"**设备输出 vs fp64**"区分两类，处置完全不同：

| 判据 | 结论 | 处置 |
|------|------|------|
| `device vs fp64` **通过**，`golden vs fp64` 失败 | golden 精度不足 | 把 golden 内部提升到 float64 再 cast 回输出 dtype |
| `device vs fp64` **也失败**，且 worst 点与 `device vs golden` 同属近零抵消 | 判据在抵消点失效（伪失败） | **不要改 golden**：device 本身是低精度，换 fp64 golden 也救不了；改用绝对误差感知的判据（TTK 默认 `mix_tolerance`）、调整输入范围避开抵消点，或经用户确认后标注豁免 |
| `device vs fp64` 在非抵消点显著大于 `golden vs fp64` | 真实算子缺陷 | 保留 FAIL，附最小复现与数据上报 |

> 常见误区：看到"golden 是 float32"就把它改成 float64。若设备输出本身也是 float32，
> 抵消点的相对误差仍然存在——这只改变了 golden，不会让结论更接近算子真实精度。

结论必须落到 `$WORKDIR/debug/notes.json`（case → 一句话结论），最终回填到 `cases.csv` 的
`note` 列；例如："失败为 float32 golden 在近零抵消点的自身舍入，无法规避"。

### 4. 真实算子缺陷

保持 `FAIL`，不要删用例、不要加豁免。整理：用例名、shape/dtype、失败槽、失败元素数、典型值与 ULP。

## 复跑

ACLNN 不支持 `--rerun`（那是 Kernel/GEIR 的结果 CSV 重跑）。ACLNN 复跑用 `-t`：

```shell
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH="$WORKDIR/debug/dump" python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --plugin "$WORKDIR" \
  -t <case_a>,<case_b> --dump-on-fail --dump-format npy \
  -o "$WORKDIR/debug/result_rerun.csv" > "$WORKDIR/debug/rerun.log" 2>&1
```

## 回填 cases.csv（pass / note）

最终结果确定后：

1. 把逐用例分析写成 `$WORKDIR/debug/notes.json`：

```json
{
  "<case_name>": "失败为 float32 golden 在近零抵消点的自身舍入，无法规避",
  "default": ""
}
```

2. 用结果 CSV 回填：

```shell
python3 .claude/skills/ttk-aclnn-adapt/scripts/finalize_cases.py \
  --cases "$WORKDIR/cases.csv" \
  --result "$WORKDIR/debug/result.csv" \
  --notes "$WORKDIR/debug/notes.json"
```

- `pass` 取 `precision_status`；`FAILURE`/`GOLDEN_FAILURE`/`COMPARE_FAILURE` 等非三态值
  归一为 `FAIL`，stderr 打印原始值；
- `note` 优先取 `notes.json`，否则保留原值；运行期失败的用例若没写 notes，
  自动填 `精度比对未完成：precision_status=...（见 debug/full_run.log）`；
- 脚本同时删除产物根目录的 `__pycache__/`；
- 两列对 TTK 是未知列，只告警不报错，交付后的 `cases.csv` 仍可直接重跑。

## 常见判据提示

| 判据 | 特点 | 适用 |
|------|------|------|
| `mixed`（默认） | 逐元素 `|a-g| <= atol + rtol*|g|` + 通过率 + 绝对误差上限 | 浮点常规 |
| `stat_rel_err` | 统计相对误差：fp32 阈值 `2^-13`，FAIL 条件为 `mere >= th` 或 `mare >= 10*th`；rel_err 分母下限（噪声地板）按 dtype：fp32 `2^-23`、fp16 `2^-11`、bf16 `2^-8` | 统计类输出；近零点多时 mare 会被单点放大 |
| `close` | `np.allclose`，读 CSV `precision_tolerances`/`absolute_precision` | 需要显式 rtol/atol |
| `cosine` | 向量余弦 | 整体趋势 |

判据选择属于测试策略，最终由用户确认；agent 只负责给证据和建议。
