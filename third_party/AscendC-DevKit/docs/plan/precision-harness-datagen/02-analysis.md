# precision-debug harness 数据生成层双 bug — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。

## 决策 1（P1）— per-input value_range：恢复透传 vs 加防御 vs 倒退 → **选恢复透传**

- **选项 A 恢复 per-input 透传**：runner serial_cases 把每个 input 自带的 value_range 原样
  透传（loader `_per_input_value_range` 已正确挂载），模板按 per-input list 取 range。
- **选项 B 保留 case 级 + double-zero 防御**：维持 3c250fd3 的 case 级广播，额外检测
  「kernel 输出全 0 且 golden 全 0」告警。
- **选项 C loader 改回 case 级**：让 loader 也压扁成单一 range（倒退 e2e-moe P3e）。
- **选 A 的理由**：根因是 runner 透传丢失（3c250fd3 删了 fb0d552a 的透传），loader 正确
  （apply_adam_w 4 输入异值域 cases_loader UT 11 绿证明）。B 治标——double-zero 防御只能挡
  「全 0」特例，挡不住「部分归零 / range 偏移但非全 0」的更普遍情形，且把数据生成 bug 的
  诊断推到下游（§1.2 可诊断性受损）。C 倒退已修对的 loader，反 §2.5。
- 四把尺子：可维护（恢复「per-input range 一路透传」不变式）、可扩展（任何多输入异值域算子
  自动归位）、可诊断（range 错即 max_diff 大，不被防御吞掉）、架构合理（修复落在 runner
  序列化层，职责正确）。

## 决策 2（P2）— output_dtype：保留猜测 vs 读 proto vs 彻底删 → **选彻底删**

- **选项 A 保留首输入猜测 + 修末尾覆盖 bug**：把循环里的 `if == 'fp16'` 反复覆盖改成
  「只取首输入」一次。
- **选项 B 读 proto output dtype spec**：从 proto.yaml 解析算子级 output dtype 注入。
- **选项 C 彻底删除 output_dtype 猜测**：serial_cases 不带该字段，模板不定义 `_out_dtype`，
  显示 dtype 直接用 runtime `compare_tensors` 返回的 `_sr.dtype`。
- **选 C 的理由**：A 只修了循环 bug，**语义仍错**——首输入 dtype ≠ 输出 dtype
  （argmax fp16→int64、cast 跨 dtype），且 output_dtype 从未参与精度判定（真实阈值用 runtime
  dtype），留着是「错误显示 + 误导维护者」。B 引入 proto output dtype 解析新依赖，但 cases.csv
  无 output dtype 列、proto.yaml 是算子级非 per-case——为「仅显示」引入解析链路属 over-engineering
  （§2.7）。C 最干净：runtime `_sr.dtype` 是事实（compare_tensors 权威返回），无需猜测，显示空
  也比错值好。
- 四把尺子：可维护（消除「输出 dtype 可从输入猜」的错误心智模型）、可扩展（新算子无需关心
  output dtype 字段）、可诊断（显示即 runtime 真值）、架构合理（删除而非打补丁，§1.4 不留兼容）。

## 决策 3（P3 inf/nan）— sentinel 编码 → **选 sentinel**（实现细节，非取舍）

- loader `float()` 已把 csv `-.inf`/`.nan` 转真 float。runner 经 `json.dumps` 序列化 test_cases，
  Python float 的 nan/inf 不合法 JSON（作为生成的 Python 代码执行则 `NameError`）。用字符串
  sentinel（`__INF__`/`__NAN__`/`__NINF__`）编码、模板 `_resolve_vr` 还原回 float。
- 非取舍决策，归 L4。

## 四把尺子总复核（两决策合并）
- **可维护**：恢复 per-input 透传不变式 + 消除 output_dtype 错误心智模型。
- **可扩展**：多输入异值域算子（moe_re_routing / apply_adam_w / clipped_swiglu / 未来）自动归位；
  新算子无需声明 output dtype。
- **可诊断**：range 错 → max_diff 大（不被 double-zero 防御吞）；dtype 显示即 runtime 真值。
- **架构合理**：修复落在 runner 序列化层（职责正确），不动 loader / 不加防御层 / 不引 proto 解析。
