---
name: ttk-aclnn-adapt
description: 把算子仓里的 aclnn 算子适配进 TTK（输入：算子源码目录 + aclnn 接口名 + 用户 golden + 用户 cases.csv + 产物目录），依次完成文档签名提取 → 用户 CSV 转 TTK CSV → 生成 golden.py（spec）→ 冒烟（只验功能）→ 全量跑 → 精度异常修正。只要用户提到新算子接入 TTK、aclnn 算子适配、算子文档转用例、用户 cases.csv 转 TTK CSV、生成 spec.py/golden.py、golden 入参顺序不对、算子冒烟/全量跑，就必须使用此 skill。即使用户只是说"把这个算子接进 TTK"、"帮我把这份 cases.csv 转成 TTK 用例"、"这个算子怎么适配"也应触发。已有用例的正常运行用 ttk-how-run-test；跑挂后的详细排障用 ttk-how-diagnose。
---

# 算子 → TTK ACLNN 适配流水线

输入 **算子源码目录 + aclnn 接口名 + 用户 golden + 用户 cases.csv + 产物目录**，产出一套可直接用 `ttk aclnn` 运行的资产，并跑到能解释每一条精度结果。

本 skill 不绑定任何具体算子或机器路径：下文用 `aclnnXxx` / `<op>` / `<case>` 作占位符，实际值一律从用户输入和 Step 0 的契约表里取。

## 输入与产物

| 变量 | 含义 | 取值来源 |
|------|------|----------|
| `OP_DIR` | 算子源码根目录，含 `docs/` | 用户提供（绝对路径） |
| `API` | `aclnnXxxGetWorkspaceSize` 中的 `aclnnXxx` | 用户提供 |
| `USER_GOLDEN` | 用户提供的 CPU 参考实现（通常是 torch/numpy 函数） | 用户提供 |
| `USER_CASES` | 用户提供的用例 CSV（字段自定） | 用户提供 |
| `WORKDIR` | **用户指定的产物目录**（agent 不自行改路径） | 用户提供（绝对路径） |

所有命令里的 `$WORKDIR`、`$OP_DIR` 都由用户输入展开；**不要**把本次会话用到的路径写死到命令模板里。

产物目录布局（**根下只放两个文件，其余全部进 `debug/`**）：

```
$WORKDIR/
├── golden.py     # 修正后的 golden / TestSpec（唯一的代码产物）
├── cases.csv     # TTK aclnn 用例，末尾追加 pass、note 两列
└── debug/        # 全部中间产物
    ├── contract.md
    ├── signature.txt
    ├── validate.log
    ├── smoke_result.csv / smoke.log
    ├── result.csv / full_run.log
    ├── notes.json
    ├── dump/<case_name>/
    └── log/aclnn/<case_name>/
```

- `pass`：该用例最终精度是否通过（`PASS`/`FAIL`/`SKIP`），由最终结果 CSV 回填；
  结果 CSV 里出现 `FAILURE`、`GOLDEN_FAILURE`、`COMPARE_FAILURE` 等非三态值时，
  `finalize_cases.py` 统一归一为 `FAIL` 并在 stderr 提示原始值；
- `note`：失败/异常的分析结论（如"float32 golden 自身舍入，近零抵消点无法规避"），
  由 agent 写入 `debug/notes.json` 后回填；
- `pass`/`note` 对 TTK 是未知列，运行时会告警并忽略，**不影响 cases.csv 继续可跑**；
- 产物根目录可能被 Python 留下 `__pycache__/`（`--plugin $WORKDIR` 导入产物时生成），
  `finalize_cases.py` 默认会删掉它；跑 ttk 时加 `PYTHONDONTWRITEBYTECODE=1` 可从源头避免。

## 铁律

1. 所有 `python3 -m ttk` 命令**必须在 ops-test-kit 仓库根目录**执行（依赖仓库内相对路径与 C 扩展）。
2. **不修改** `USER_GOLDEN` / `USER_CASES`；转换产物一律写到新的 `WORKDIR`。
3. **Step 0 得到的 aclnn 形参表是唯一签名事实源**：CSV 的张量槽顺序、spec golden 的形参顺序都以它为准，不以用户 CSV 的列顺序或函数外观为准。
4. **不臆造**输出 shape/dtype、属性值、SoC 映射；文档和用户输入都没有时停下来问用户。
5. 精度不通过时**先证伪 golden，再改用例**；不得为了 PASS 静默放宽 tolerance。
6. skill 内的脚本与命令**只使用占位符和用户给的路径**，不假设某一台机器上的目录结构。

## 流水线总览

| Step | 动作 | Gate（不过不进下一步） |
|------|------|------------------------|
| 0 | 读 `$OP_DIR/docs`，抽函数原型 + aclnn 形参表 | 得到有序形参表、张量槽位、输出索引、dtype/shape 约束 |
| 1 | 用户 CSV → TTK CSV | `--validate` 通过，`ttk list` 用例数与用户 CSV 一致 |
| 2 | 生成 `golden.py` | 注册名匹配、golden 形参覆盖全部 aclnn 形参（含输出张量） |
| 3 | 冒烟：只验功能，不看精度 | 最小用例设备执行成功、golden 无异常、输出 shape/dtype 正确 |
| 4 | 全量跑（TTK 默认判据） | 跑完并产出结果 CSV；记录 PASS/FAIL 清单 |
| 5 | 精度异常 → 改 golden / 改用例 → 重跑 | 每个 FAIL 有归因，修正后复跑至收敛 |

---

## Step 0：读文档，抽 aclnn 契约

按优先级阅读（找到为止）：

1. `$OP_DIR/docs/$API.md`（最常见；也可能大小写/命名不同，用 `grep -rl "$API" $OP_DIR/docs` 定位）
2. `$OP_DIR/README.md`、`$OP_DIR/examples/test_aclnn_*.cpp`（真实调用参数顺序）
3. `$OP_DIR/tests/st/aclnn*/executor_*.py` 的 `get_cpp_func_signature_type()`
4. 头文件：`$OP_DIR/op_api/**/aclnn_*.h` 或已安装的 `$ASCEND_HOME_PATH/include/aclnnop/aclnn_*.h`
   —— **TTK 运行期真正解析的是头文件**；源码里有头文件但未安装时，设置 `TTK_OP_API_HEADER_PATH=<头文件所在目录>`。

必须抽出并落成一张契约表：

- 两段式函数原型（`aclnnXxxGetWorkspaceSize` 的完整有序形参）
- 每个形参：名称、C 类型、输入/输出、dtype、format、维度/shape 约束
- 哪些是 `aclTensor*` / `aclTensorList*`（→ CSV 张量槽）、`aclScalar*`（→ `scalar_dtypes`）、C 基本类型（→ `attributes`）
- 输出张量在**张量槽**中的 0-based 索引（→ `output_tensor_indexes`）
- 输出 shape 的推导规则
- dtype 规则（输出是否强制某 dtype、是否必须与输入同 dtype）
- SoC 支持范围、空 Tensor/非连续 Tensor 等约束

快速核对 TTK 实际解析到的签名：

```shell
mkdir -p "$WORKDIR/debug"
python3 .claude/skills/ttk-aclnn-adapt/scripts/dump_aclnn_signature.py <API> \
  > "$WORKDIR/debug/signature.txt"
```

展开方法与契约模板见 `references/step0-signature-extraction.md`。

## Step 1：用户 CSV → TTK CSV

用户 CSV 的列名/结构不固定，先按语义识别列，再逐字段映射到 `ttk aclnn` 的列：

| 用户语义 | TTK 列 | 要点 |
|----------|--------|------|
| 用例名 / case_id | `testcase_name` | 唯一、ASCII；保留原始 id 到 `remark` |
| 算子名 | `api_name` | 填 Step 0 的 `aclnnXxx`，不是用户 CSV 里的 `operator` 列 |
| 输入 shape 列表 | `tensor_view_shapes` | **按 aclnn 张量槽顺序补全输出槽**，不是只抄输入 |
| dtype 列表 | `tensor_dtypes` | 同样补全输出 dtype；混合 dtype 必须逐个写全 |
| attrs | `attributes` | C 基本类型标量按形参名填 |
| value_range | `input_data_ranges` | 按张量槽逐槽对齐；输出槽写 `(None,None)` |
| expected/output（常藏在 note 里） | 校准 `tensor_view_shapes`/`tensor_dtypes` | 与 Step 0 推导结果交叉校验，冲突时停下问用户 |
| note/remark | `remark` | 可截断，保留测试意图 |

必须显式声明 `output_tensor_indexes`（即使命名能被自动识别）。

**用 Python `csv` 模块生成**，不要手工拼字符串——用户 CSV 里的 JSON/引号/逗号很容易把列冲散。

最终 `$WORKDIR/cases.csv` 在标准列末尾追加两列（Step 5 回填）：

| 追加列 | 内容 |
|--------|------|
| `pass` | 最终精度结论：`PASS` / `FAIL` / `SKIP` |
| `note` | 失败/异常的分析结论；例如"float32 golden 在近零抵消点自身舍入，无法规避" |

这两列对 TTK 是未知列，运行时只告警并忽略，**不破坏用例解析**。

映射细则与逐字段对照示例见 `references/step1-user-csv-to-ttk.md`。

校验（日志写入 `debug/`）：

```shell
mkdir -p "$WORKDIR/debug"
python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --validate > "$WORKDIR/debug/validate.log" 2>&1
python3 -m ttk list -i "$WORKDIR/cases.csv"
```

## Step 2：生成 golden.py

在 `$WORKDIR` 下生成**唯一代码产物** `golden.py`（文件名不以 `_` 开头），显式注册：

```python
__spec__ = {"aclnnXxx": "XxxAclnnTestSpec"}
```

> 用户原始 `USER_GOLDEN` 不改；把修正/适配后的版本写到 `$WORKDIR/golden.py`。
> 中间分析脚本、旧版本备份等一律放 `$WORKDIR/debug/`，不要留在产物根目录。
> 注意 `--plugin $WORKDIR` 会递归扫描所有 `.py`：`debug/` 里的旧版 golden 请存成
> `*.py.bak` 之类的非 `.py` 后缀，且分析脚本不要声明同名 `__spec__`。

ACLNN golden 的调用契约（关键）：

- 参数按 **`aclnnXxxGetWorkspaceSize` 的 C 形参顺序**逐个位置传入，去掉 `workspaceSize`/`executor`；
- **输出张量也作为参数传入**（框架已分配、常量初始化），标量属性同样在位置上；
- golden 的返回值是**输出列表**，顺序与 `output_tensor_indexes` 一致；
- 入参是 CPU 侧 `torch.Tensor`（框架先于设备执行生成）；额外元信息走 `**kwargs`。

用户 golden 通常只接收"输入 + 属性"，因此必须写一层适配：补齐输出形参（或用 `*args` 兜住），再按输出槽顺序返回。通用模板：

```python
import torch

__spec__ = {"aclnnXxx": "XxxAclnnTestSpec"}


def _compute(in0, in1, attr0, attr1):
    """用户 golden 的数学实现（保持原语义；维度/广播规则以 Step 0 契约为准）。"""
    ...


class XxxAclnnTestSpec:
    def golden(in0, in1, attr0, attr1, out0=None, out1=None, **kwargs):
        # 输出形参只为对齐 C 签名，计算不需要它们
        return _compute(in0, in1, attr0, attr1)
```

形参名必须替换为 Step 0 抽出的真实形参名；数量与顺序按 C 签名，输出槽用默认值兜住。

规则、dtype 处理和完整写法见 `references/step2-spec-generation.md`。

## Step 3：冒烟（只验功能，不看精度）

用最小用例确认**链路能跑通**。精度列无论 `PASS`/`FAIL`/`SKIP` 都不作为这一阶段的 gate——golden 正常参与比对也没关系，只看功能：

- 设备执行没有 ACLNN 报错；
- golden 没有 `GOLDEN_FAILURE` / `TypeError`；
- 输出的数量、shape、dtype 与 Step 0 契约一致；
- 输出不是全 0 / 全 NaN。

```shell
mkdir -p "$WORKDIR/debug"
# 正常跑最小用例，同时落 dump 方便检查
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH="$WORKDIR/debug/dump" python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --plugin "$WORKDIR" \
  -t <最小的用例名> --dump in,out,golden --dump-format npy \
  -o "$WORKDIR/debug/smoke_result.csv" > "$WORKDIR/debug/smoke.log" 2>&1
# 日志默认写仓库根 log/，复制进 debug/
mkdir -p "$WORKDIR/debug/log/aclnn"
cp -r log/aclnn/<最小的用例名> "$WORKDIR/debug/log/aclnn/"
```

> **ttk 的退出码是"有用例 FAIL 就返回 1"**，不是"命令本身出错"。所以别用 `&&` 串
> 冒烟和全量跑——冒烟精度没过也会把后续命令断掉。各步单独执行，按结果 CSV 判断。

也可以加 `--golden-mode Disable` 把执行与 golden 解耦，但**不要依赖它一定生效**：默认 `mixed`/`mix_tolerance`/`cross_check` 判据会触发 Promote override，Disable 会被覆盖、golden 仍会生成并比对。这不影响冒烟结论，因为冒烟本来就不看精度。

出现 `GOLDEN_FAILURE`、`TypeError`、输出数量/形状不对 → **修 `golden.py` 的入参顺序或内部实现**，而不是改用例。

冒烟功能检查项与 dump 文件命名见 `references/step3-5-run-and-triage.md`。

## Step 4：全量跑（TTK 默认判据）

```shell
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH="$WORKDIR/debug/dump" python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --plugin "$WORKDIR" \
  -o "$WORKDIR/debug/result.csv" --dump-on-fail --dump-format npy \
  > "$WORKDIR/debug/full_run.log" 2>&1
# 复制本次运行涉及的用例日志
mkdir -p "$WORKDIR/debug/log/aclnn"
cp -r log/aclnn/<case_a> log/aclnn/<case_b> "$WORKDIR/debug/log/aclnn/"
```

- 不传 `--compare`：按 Spec.tolerance 路由，未声明时用 TTK 默认 `mixed`。
- 不要把结果写到产物根目录；结果 CSV、日志、dump 全部落在 `debug/`。
- 退出码 1 表示**有用例 FAIL**，不是执行失败——务必打开 `result.csv` 逐条看 `precision_status`。
- 若 `precision_status` 是 `FAILURE`/`GOLDEN_FAILURE` 这类非三态值（不是精度结论），
  先看 `full_run.log`：常见是设备瞬时错误（如 `rtCtxCreate() ACL_ERROR_RT_DRV_INTERNAL_ERROR`、
  `rtMalloc() ACL_ERROR_RT_MEMORY_ALLOCATION`，多因 HBM 被其它任务占满），
  清掉该用例旧 dump 后单独 `-t` 复跑，或用 `--devices <id>` 换空闲设备（`npu-smi info` 看占用），
  不要据此改成例或放宽 tolerance。
- 不要在这一步顺手放宽 tolerance；先把失败分门别类。
- 记录结果：`PASS/FAIL` 数量、失败用例名、失败的输出槽。

## Step 5：精度异常 → 改 golden / 改用例，再重跑

排障前先**清掉该用例的旧 dump**：dump 目录不会自动清理，重跑会叠加新旧文件（例如不同 dtype 或不同次运行的 `golden_<k>_*.npy` 并存），直接分析会拿到上一次运行的数据。

```shell
rm -rf "$WORKDIR/debug/dump/<case_name>"
```

按以下顺序归因（详见 `references/step3-5-run-and-triage.md`）：

1. **Golden 接线/实现错误**：全部输出或某一槽大幅偏离、输出错位、dtype 不对 → 修 `golden.py`，回到 Step 3。
2. **用例数据错误**：shape/dtype/属性违反 Step 0 约束（如维度关系不满足、shape 后缀/broadcast 不匹配、dtype 不在支持列表、范围导致 Inf/NaN）→ 改 `cases.csv`。
3. **Golden 精度不足的伪失败**：只有极少数近零元素失败（输出 `≈0` 的抵消点），且用更高精度参考复算后用户 golden 本身也过不了同一判据 → 归为伪失败；处理方式与用户确认（换判据/调范围/标注豁免），不要谎报算子缺陷。
4. **真实算子缺陷**：非抵消点、可复现、误差远超 ULP → 保留 FAIL，整理复现用例与数据上报。

复跑失败用例（ACLNN 不支持 `--rerun`）：

```shell
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH="$WORKDIR/debug/dump" python3 -m ttk aclnn -i "$WORKDIR/cases.csv" --plugin "$WORKDIR" \
  -t <case_a>,<case_b> --dump-on-fail --dump-format npy \
  -o "$WORKDIR/debug/result_rerun.csv" > "$WORKDIR/debug/rerun.log" 2>&1
```

### 回填 cases.csv 的 pass / note 列

最终跑完后，把结论写回产物用例（agent 先把分析结论写成 `debug/notes.json`）：

```json
{
  "<case_name>": "失败为 float32 golden 在近零抵消点的自身舍入，无法规避",
  "default": ""
}
```

```shell
python3 .claude/skills/ttk-aclnn-adapt/scripts/finalize_cases.py \
  --cases "$WORKDIR/cases.csv" \
  --result "$WORKDIR/debug/result.csv" \
  --notes "$WORKDIR/debug/notes.json"
```

- `pass` 取结果 CSV 的 `precision_status`；`FAILURE`/`GOLDEN_FAILURE`/`COMPARE_FAILURE`
  等运行期失败归一为 `FAIL`（stderr 会打印原始值，原因写进 note）；
- `note` 取 `notes.json` 的逐用例结论（没有则保留 cases.csv 原值；若该用例是运行期失败
  且没写 notes，自动填 `精度比对未完成：precision_status=...`）；
- 脚本同时删除产物根目录的 `__pycache__/`（加 `--keep-pycache` 可保留）；
- 两列是 TTK 未知列，后续再跑只告警、不影响解析。

伪失败的取证三步法（近零抵消）、dump 分析与判据选择见 `references/step3-5-run-and-triage.md`。

## 完成检查清单

- [ ] 契约表与 aclnn 头文件解析结果一致（张量槽数、输出索引、标量属性）
- [ ] `$WORKDIR/cases.csv` 的 `--validate` 通过，用例数与用户 CSV 一致
- [ ] `$WORKDIR/golden.py` 注册名 == `api_name`，golden 形参覆盖全部 C 形参（含输出张量）
- [ ] 冒烟用例执行成功、golden 无异常、输出 shape/dtype 符合文档
- [ ] 全量结果每个 FAIL 都已归因（golden / 用例 / 伪失败 / 算子缺陷）
- [ ] `cases.csv` 的 `pass`/`note` 两列已回填，note 写清可解释的失败原因
- [ ] 产物根目录只有 `golden.py` 和 `cases.csv`（无 `__pycache__/`、无结果/日志/dump）；
      其余全部在 `debug/`
- [ ] 分析 dump 前已清理旧文件（`rm -rf $WORKDIR/debug/dump/<case>`，dump 目录不会自动清理）
- [ ] 未修改用户原始 golden 与 cases.csv
- [ ] skill 内没有残留某一台机器/某个算子的硬编码路径

## 脚本

| 资源 | 用途 |
|------|------|
| `references/step0-signature-extraction.md` | 文档/头文件抽取方法与契约模板 |
| `references/step1-user-csv-to-ttk.md` | 字段映射与 CSV 生成 |
| `references/step2-spec-generation.md` | golden 适配层与 dtype 规则 |
| `references/step3-5-run-and-triage.md` | 冒烟、全量与精度归因 |
| `scripts/dump_aclnn_signature.py` | 打印 TTK 解析到的 aclnn 签名（张量槽/标量/属性） |
| `scripts/inspect_dump.py` | 分析 dump：按 stat_rel_err 口径算 mere/mare、定位近零主导点 |
| `scripts/finalize_cases.py` | 用最终结果回填 `cases.csv` 的 `pass`/`note` 两列 |

## 相关 Skill

- 用例字段细节 → `ttk-how-write-case`
- TestSpec 字段与 tolerance 语义 → `ttk-how-write-plugin`
- 运行参数与环境 → `ttk-how-run-test`
- 失败排障与精度调试 → `ttk-how-diagnose`
