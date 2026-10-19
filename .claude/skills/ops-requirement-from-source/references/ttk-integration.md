# TTK 适配与测试接入

本文件定义本技能第四步与 `ttk-aclnn-adapt` 的交接契约。TTK 技能位于 ops-test-kit 仓库。

调用方式固定为**按路径读取**：子代理先完整阅读 `<TTK_SKILL>/SKILL.md` 及其 `references/`，再按 Step 0→5 执行。

- `<TTK_SKILL>` 只认 `<TTK_REPO>/.claude/skills/ttk-aclnn-adapt`，即 ops-test-kit 仓库内的版本。
- 不得使用其他位置的同名副本（包括本技能所在仓库 `.claude/skills/` 下的 `ttk-aclnn-adapt`），即使它已注册到技能列表；用 `Skill` 调用会解析到错误版本。
- 调用方式不改变输入契约和产物要求。

## 1. 目录与变量

| 变量 | 值 |
|---|---|
| `TTK_REPO` | ops-test-kit 仓库根目录；环境变量 `OPS_TEST_KIT_ROOT` 优先 |
| `TTK_SKILL` | `<TTK_REPO>/.claude/skills/ttk-aclnn-adapt` |
| `TTK_WORKDIR` | 用户传入；未传入时默认 `<需求文件夹>/ttk/` |
| `OP_DIR` | 本技能的 `PATH` |
| `API` | `aclnnXxx`，由 `op_api` / `op_host` 下 `aclnn*GetWorkspaceSize` 唯一确定 |
| `DOC_PATH` | 本技能选定的接口文档 |
| `USER_GOLDEN` | `<需求文件夹>/golden.py` |
| `USER_CASES` | `<需求文件夹>/cases.csv` |
| `CHIP` | 所选芯片种类 |

`TTK_REPO` 定位顺序：用户显式参数 → `OPS_TEST_KIT_ROOT` → 从 `PATH` 逐级向上查找同级 `ops-test-kit/ttk/__init__.py` → 询问用户。找不到时不执行，不得猜测路径。

TTK 产物目录：

```text
<TTK_WORKDIR>/
├── golden.py              # TTK TestSpec 包装层（不等于需求包 golden.py）
├── cases.csv              # TTK 用例（七列 + pass/note）
└── debug/
    ├── contract.md        # Step 0 契约表
    ├── signature.txt
    ├── validate.log
    ├── smoke_result.csv / smoke.log
    ├── result.csv / full_run.log
    ├── notes.json
    ├── handoff.json       # 本技能要求的交接文件
    ├── dump/<case_name>/
    └── log/aclnn/<case_name>/
```

需求包 `cases.csv` 与 `TTK_WORKDIR/cases.csv` 是两份资产：前者始终保持七列，后者末尾追加 `pass`/`note`，只作验证证据。

## 2. 环境预检

执行前逐条确认，任一失败即整体跳过并在 `design.md` 记录“未执行”：

```bash
test -f <TTK_SKILL>/SKILL.md
cd <TTK_REPO> && python3 -m ttk info        # 需识别到与 CHIP 匹配的设备
```

- 无设备、无 CANN 环境、`ttk info` 报错 → 跳过，**不启用** `--backend npusim`，不反复重试，不改用其他芯片。
- 一次运行只允许一条 `python3 -m ttk` 命令，禁止并行。
- 所有命令必须 `cd <TTK_REPO>` 后执行。

## 3. 子代理 prompt 模板

```text
你负责把一个 CANN 算子接入 TTK aclnn 通路并跑出精度结论。

先完整阅读并遵循 <TTK_SKILL>/SKILL.md 及其 references/（step0~step3-5 各文件），
再按该 skill 的 Step 0→5 执行。不得使用其他位置的同名副本。

输入：
  OP_DIR=<PATH>
  API=<aclnnXxx>
  DOC_PATH=<我们选定的接口文档>
  USER_GOLDEN=<需求文件夹>/golden.py
  USER_CASES=<需求文件夹>/cases.csv
  WORKDIR=<TTK_WORKDIR>
  CHIP=<芯片种类>

执行 TTK skill 的 Step 0→5，并遵守：
1. 所有 python3 -m ttk 命令在 <TTK_REPO> 根目录执行，且不并行。
2. 不修改 USER_GOLDEN / USER_CASES；产物全部写入 WORKDIR。
3. Step 0 的 aclnn 形参表是唯一签名事实源；不臆造输出 shape/dtype、属性值、平台名，有歧义时停下报告。
4. 精度失败先证伪 golden，再考虑用例；不得静默放宽 tolerance。
5. 最后写 <WORKDIR>/debug/handoff.json。

产物只放在 <WORKDIR> 下：golden.py、cases.csv、debug/**。
```

## 4. handoff.json 契约

它的唯一作用：让第五步做回流时**不必自己翻日志和 dump**，直接知道“这次跑没跑、没跑为什么、哪些用例失败、每个失败该怪谁”。

```json
{
  "status": "executed",
  "skip_reason": "",
  "failures": [
    {"case_id": 12, "attribution": "false_failure",
     "detail": "y 槽近零抵消点，去掉最坏点后 3.5e-3"}
  ],
  "leftovers": []
}
```

| 字段 | 作用 |
|---|---|
| `status` | 区分“真跑过”和“环境不具备而跳过”，第五步据此决定走回流还是纯静态检查 |
| `skip_reason` | 跳过原因，写进 `design.md` 的“未执行”说明 |
| `failures` | 只登记 FAIL 用例。`case_id` 定位用例，`attribution` 决定第五步的动作（修 golden / 改用例 / 豁免 / 记缺陷 / 记环境），`detail` 给出判定依据 |
| `leftovers` | 未解决项、需用户决策项，以及 TTK 无法表达的用例构造 |

PASS/SKIP 的逐条状态不从 handoff 读，直接看 `<WORKDIR>/cases.csv` 的 `pass` 列，避免同一事实存两份。

## 5. 门禁

由子代理自检，不额外落脚本：

- Step 0：形参表、张量槽和输出索引齐备，与 `design.md` 一致。
- Step 1：`--validate` 通过，`ttk list` 为 20 条。
- Step 2：包装层注册名等于 `API`，形参覆盖全部 aclnn 形参（含输出张量）。
- Step 3：最小用例冒烟成功，无 `GOLDEN_FAILURE`。
- Step 4：产出 `debug/result.csv`。
- Step 5：`pass`/`note` 已回填，FAIL 已给归因，`handoff.json` 已写。

## 6. 已知格式差异与处理

| 差异 | 处理 |
|---|---|
| `tensor_view_shapes` / `tensor_dtypes` 必须覆盖输入+输出槽 | 输出槽由 `proto.yaml` outputs 与 shape 规则推导，并与 Step 0 推导交叉校验；冲突时停止问用户 |
| `note` 为非结构化一句话 | 不解析字段；其中的“显式值列表 / 非连续视图 / 特殊值”等描述按第 6 章规则落成 TTK 构造 |
| 显式值列表与 TTK `input_data_ranges` 第 3 项起“必现值混入”语义不同 | 需要精确逐值序列时用 `customize_inputs`；做不到则记入 `case_data_gaps`，不得近似替代 |
| NaN 无法写入 `input_data_ranges`（`ast.literal_eval` 不认 `nan`） | 含 NaN 的用例走 `customize_inputs`，或记入 `case_data_gaps`；Inf 用 `1e309` / `-1e309` |
| 非连续视图用例 | 落成 `tensor_view_strides` / `tensor_view_offsets` / `tensor_storage_shapes`；字段细节允许读同仓 `ttk-how-write-case/references/aclnn-case.md` |
| `seed` 固定为 `case_id` | TTK 只有全局 `--seed`，按 `(seed, testcase_name)` 派生；不能满足时记入 `case_data_gaps` |
| `soc_series` 与 A5/A3 无通用映射 | 用 `ttk info` 的实际平台名核对；拿不准留空并记录 |
| `--plugin` 递归扫描 `.py` | 固定 `--plugin "$WORKDIR"`，不得指向需求文件夹根目录 |

## 7. 命令模板

```bash
cd <TTK_REPO>
mkdir -p <TTK_WORKDIR>/debug

# Step 0 签名核对
python3 <TTK_SKILL>/scripts/dump_aclnn_signature.py <API> > <TTK_WORKDIR>/debug/signature.txt

# Step 1 校验
python3 -m ttk aclnn -i <TTK_WORKDIR>/cases.csv --validate > <TTK_WORKDIR>/debug/validate.log 2>&1
python3 -m ttk list -i <TTK_WORKDIR>/cases.csv

# Step 3 冒烟（单独执行，不要用 && 串联）
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH=<TTK_WORKDIR>/debug/dump python3 -m ttk aclnn \
  -i <TTK_WORKDIR>/cases.csv --plugin <TTK_WORKDIR> -t <最小用例> \
  --dump in,out,golden --dump-format npy \
  -o <TTK_WORKDIR>/debug/smoke_result.csv > <TTK_WORKDIR>/debug/smoke.log 2>&1

# Step 4 全量
PYTHONDONTWRITEBYTECODE=1 NPU_DUMP_PATH=<TTK_WORKDIR>/debug/dump python3 -m ttk aclnn \
  -i <TTK_WORKDIR>/cases.csv --plugin <TTK_WORKDIR> \
  -o <TTK_WORKDIR>/debug/result.csv --dump-on-fail --dump-format npy \
  > <TTK_WORKDIR>/debug/full_run.log 2>&1

# Step 5 回填
python3 <TTK_SKILL>/scripts/finalize_cases.py \
  --cases <TTK_WORKDIR>/cases.csv --result <TTK_WORKDIR>/debug/result.csv \
  --notes <TTK_WORKDIR>/debug/notes.json
```

- ttk 退出码 1 表示“有用例 FAIL”，不是命令失败；必须打开结果 CSV 判断。
- 运行日志默认写到 `<TTK_REPO>/log/aclnn/<case>/`，需复制到 `debug/log/aclnn/` 归档。

## 8. 回灌到需求包

| 归因 | 需求包动作 | 禁止 |
|---|---|---|
| `golden` | 修 `<需求文件夹>/golden.py` + `desc.md` 第 5 节代码块 + 必要时的 `proto.yaml` | 复制 TestSpec 包装层 |
| `case` | 修 `cases.yaml` → 重派生 `cases.csv`，仍 20 条 | 增删用例凑数 |
| `false_failure` | 只在 `design.md` 覆盖表标“豁免”并记录证据 | 改 value_range / 放宽 tolerance / 删用例 |
| `operator_defect` | 保留 FAIL，记录复现与 ULP | 改判 PASS |
| `environment` | 记录错误与复跑结论 | 据此改用例 |

golden 或用例被修正后，最多再跑两轮第四步→第五步；仍不收敛的失败写入 `design.md` 遗留事项。

只有 `result.csv` 中真实出现的 case 才能在覆盖映射表标为“已运行验证”；`false_failure` 标记为“已运行验证（豁免）”。
