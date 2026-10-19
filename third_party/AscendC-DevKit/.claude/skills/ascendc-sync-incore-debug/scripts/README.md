# In-core Sync TopN Analyzer

`analyze_incore_sync_topn.py` 用于静态扫描 AscendC 核内同步（`SetFlag/WaitFlag`），输出 **TopN 可疑函数**，并在每个函数下给出可疑信号与错误类型。

## 1. 适用场景

- 程序卡死（hang/timeout），但不知道哪个函数可能有同步问题
- 先做快速静态收敛，再做定向动态验证
- 需要给 agent/skill 一个可执行的“下一步排查列表”

## 2. 快速使用

在仓库根目录执行：

```bash
python3 training/ascendc/src/ops-transformer/attention/sparse_flash_attention_grad_enhance/scripts/analyze_incore_sync_topn.py <input> --topn 10
```

`<input>` 可以是单文件或目录。

常用参数：

- `--topn N`：输出前 N 个函数（默认 10）
- `--md-out <path>`：输出 markdown 报告（推荐）
- `--json-out <path>`：输出 json 报告（给工具链用）
- `--include-lifecycle`：包含生命周期函数（默认会过滤 `AllocEventID/FreeEventID/...`）

示例（SFAG）：

```bash
python3 training/ascendc/src/ops-transformer/attention/sparse_flash_attention_grad_enhance/scripts/analyze_incore_sync_topn.py \
  training/ascendc/src/ops-transformer/attention/sparse_flash_attention_grad_enhance \
  --topn 12 \
  --md-out /tmp/sfag_incore_sync_topn.md
```

## 3. 输出怎么看（详细）

### 3.1 函数级行（Top Functions）

示例：

```text
01. score=219 | ops=36 | hard(wait_unset=1, double_set=0) | risk(entry_wait=0, imbalance=2)
```

字段说明：

- `score`：函数总风险分。由每个信号的风险分累加，再加函数级补偿项（例如 loop mismatch boost）。
- `ops`：函数内识别到的核内同步操作数（`SetFlag/WaitFlag`，含宏形式）。
- `hard(...)`：硬错误计数（确定性强，优先级最高）。
- `hard(wait_unset=K)`：该函数内发生 `UNSET -> Wait` 的次数（等待未被设置的信号）。
- `hard(double_set=K)`：该函数内发生 `SET -> SET` 且中间无 `Wait` 消费的次数。
- `risk(...)`：风险提示计数（启发式，不一定是最终 bug）。
- `risk(entry_wait=K)`：函数入口附近出现 Wait 的次数，可能依赖跨函数契约。
- `risk(imbalance=K)`：同一信号 `Set`/`Wait` 数量不平衡的次数。

### 3.2 信号级行（suspicious_signals）

示例（markdown 报告）：

```text
- `MTE2->V::foo_flag + SHIFT` score=97 (hard_wait_unset=0, hard_double_set=1, entry_wait=0, imbalance=1)
  - issue_types: `DOUBLE_SET, SET_WAIT_IMBALANCE, LOCAL_UNPAIRED_SIGNAL`
```

字段说明：

- `HardEvent::event_expr`：信号键。`HardEvent` 表示方向（如 `MTE2->V`），`event_expr` 是事件表达式。
- `score`：该信号风险分，函数总分主要由它们构成。
- `hard_wait_unset`：该信号上的 `UNSET -> Wait` 次数。
- `hard_double_set`：该信号上的 `SET -> SET` 次数。
- `entry_wait`：该信号在函数入口处 Wait 的命中次数。
- `imbalance`：该信号 `Set/Wait` 数量差异计数。
- `issue_types`：该信号触发的具体规则标签（用于定位“为什么高分”）。

说明：

- 终端打印还会展示 `loop_mismatch` 计数；markdown 当前不单独打印该字段，但会体现在 `issue_types` 与 `score` 中。

### 3.3 issue_types 含义

- `WAIT_ON_UNSET`：出现 `UNSET -> Wait`，高风险硬错误。
- `DOUBLE_SET`：连续 `SET -> SET`（未消费），高风险硬错误。
- `LOOP_DEPTH_MISMATCH`：`Wait` 与 `Set` 处于不同循环深度，高风险。
- `LOOP_WAIT_SET_SCOPE_MISMATCH`：`Wait` 在循环内而 `Set` 仅在循环外，高风险。
- `LOOP_WAIT_OUTSIDE_SET_INSIDE`：`Wait` 在循环外而 `Set` 在循环内，高风险。
- `LOOP_WAIT_SET_COUNT_MISMATCH`：循环中 `Wait/Set` 次数不一致。
- `SET_WAIT_IMBALANCE`：同信号 `Set/Wait` 总次数不平衡。
- `LOCAL_UNPAIRED_SIGNAL`：函数里存在配对链，但该信号是单边（更像回归缺失）。
- `ENTRY_WAIT_UNKNOWN`：入口 Wait，可能合法也可能依赖外部契约。
- `SPLIT_CONTRACT`：单边契约，可能是跨函数分工。
- `CONFIRM_NEEDED`：存在 loop mismatch 但相关操作在 `if` 分支内，已降权，需人工确认。

## 4. 推荐排查流程（给 agent/skill）

1. 先按 `score` 看 Top3 函数。
2. 在 Top3 内优先看包含以下类型的信号：
   - `WAIT_ON_UNSET`
   - `DOUBLE_SET`
   - 任意 `LOOP_*`
   - `LOCAL_UNPAIRED_SIGNAL`
3. 对每个高优先级函数做定向动态验证（不要全量替换）：
   - 先 `bypass` 验证：是否由该函数导致 hang
   - 再 `trace` 验证：定位函数内第一阻塞点
4. 如果只出现 `ENTRY_WAIT_UNKNOWN/SPLIT_CONTRACT`，先当“候选”，不要直接定性。

## 5. 注意事项

- 这是静态启发式工具，不是最终根因证明器。
- 当前对 `if` 保护的 loop mismatch 使用降权（`score *= 0.4`）并打 `CONFIRM_NEEDED`。
- 宏/模板/跨函数契约会带来误报，必须结合动态验证。
- 结果用于“排查优先级排序”，不是直接生成修复代码。
