# 下游消费链路与接入方式

本文只讲**产物放哪、被谁读、怎么接进产线**。设计取舍与来龙去脉见仓内设计说明，
不在本文展开。

## 1. 五文件被谁读

| 消费者 | 读什么 | 性质 |
|---|---|---|
| eval runner 的 `read_category()` | `proto.yaml` → `operator.category` | **唯一的程序化读取点**：作为 `{category}` 注入 prompt 上下文（非按类选模板）|
| 算子发现 | 遍历 `<root>/level*/<op>/` | 路径约定 |
| 工作目录准备 | 把算子目录下**所有文件平铺复制**到 `operators/<op>/` | 文件名即契约 |
| architect / design-reviewer / developer / reviewer | 把五文件当 **prompt 上下文**读 | LLM 语义消费 |
| 精度比对 harness | `proto.yaml` → `precision_thresholds`，整数/索引输出默认精确相等，浮点输出阈值 `0` 触发 bit-exact | 程序化 |

两条硬性结论：

1. **`desc.md` 是下游认的 spec 文件名**，不是 `spec.md`、不是 `<op>.md`。
2. **没有 `cases.yaml` / `desc.md` 的强 schema 校验器**，畸形产物不会被拒绝，
   只会静默拉低成功率 —— 所以校验必须在生成侧做完。

## 2. 产物放哪

```
operators/<op_snake_case>/
├── desc.md
├── cases.yaml
├── cases.csv
├── proto.yaml
└── golden.py
```

五文件**平铺**，不要建子目录 —— 下游是按平铺复制取用的。
按难度分层归档时用 `<root>/level{1,2,3}/<op>/`，`difficulty` 必须与层级一致。

## 3. 接进产线：替换「需求生成」阶段

产线原本让 root 自己读模板现写需求（且通常只产出一个 spec md，没有 cases/proto/golden），
这有三个问题：**root 上下文膨胀、验收判据不可控、无校验时点**。

改成两段式：

```
Stage 0  ops-preinput-gen   算子名 → operators/<op>/{五文件}   ← 可并行 / 可缓存 / 16 道门
Stage 1  ops-direct-invoke  读 AGENTS.md，Step 1-7 开发
```

root 的 prompt 相应简化为单阶段：

```
算子需求文件已就绪于 operators/{operator_name}/（desc.md / cases.yaml / cases.csv /
proto.yaml / golden.py，五文件已通过前置校验）。
请读取 AGENTS.md，按其 Step 1-7 工作流完成算子开发。
验收标准：cases.yaml 全部 20 个用例通过；禁止 CPU 计算，必须运行在 NPU 上。
```

> 末两句硬判据前移到需求侧，是提升下游成功率的有效做法：把「过哪 20 个用例」
> 变成生成侧可控的输入，而不是下游临场决定。

### 拆成独立 Stage 的收益

1. **可并行** —— 算子之间互不依赖，一算子一 subagent；留在 root 则与开发串行
2. **可缓存** —— 五文件是纯函数式产物（算子名 → 文件），一次生成可反复复用
3. **可校验** —— 独立 Stage 才有明确时点跑 `--run-golden` 全绿门
4. **判据可控** —— cases.yaml 由生成侧按覆盖矩阵产出

### 批量跑法

```bash
# 单算子
python3 scripts/resolve_semantics.py <op>                 # 取权威语义事实
#   …（据事实写五文件）…
python3 scripts/gen_cases_csv.py       operators/<op>     # 派生 CSV
python3 scripts/validate_preinput.py --run-golden operators/<op>

# 批量校验既有产物
python3 scripts/validate_preinput.py operators/*/
```

产线批量建议用 `ops-preinput-generator` subagent，一算子一实例并行，
每个实例跑完自己的校验门再返回，失败的单独重试。

## 4. 接入注意

- 若下游按别的路径找 spec（如 `demands/<op>.md`），需同步改成
  `operators/<op>/desc.md`，或放一份同内容副本过渡。
- `category` 作为上下文注入下游 prompt；写错或写空会让下游 LLM 拿到错误的算子归类、静默拉低质量。
  `read_category()` 是五文件里**唯一**被程序读取的字段，由 G4 门提醒归类一致性（不在 13 类内 → WARN）。。
- `baseline_kernels` 由下游 profiling 回填到 `note` 尾部，生成侧不写；
  回填时应**同时写 yaml 与 csv**，否则两边漂移。
