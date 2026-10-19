# UB 工具使用指南

## 工具概览

| 脚本 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `gen_memory_map.py` | 从配置生成地址映射 | buffer_config.json | memory_map.json |
| `ub_analyzer.py` | 核心 UB 解析模块 | ub.dump + memory_map.json | 内部数据结构 |
| `show_by_buffer.py` | 按 buffer 显示 | ub.dump + memory_map.json | 分析报告 |
| `show_by_time.py` | 按时间线显示 | ub.dump + memory_map.json | 分析报告 |
| `merge_logs.py` | 合并 MTE + UB | mte.txt + ub.log | 综合报告 |
| `visualize.py` | 生成交互式甘特图 | merged_report.log | visualization.html |

## 核心配置：地址映射

**使用前必须生成 `memory_map.json`**，定义各 buffer 的地址范围。

### 配置方法

1. **编写 `buffer_config.json`**

   从 kernel 代码的 `InitBuffer` 调用和 TilingData 实际值提取信息：

   ```json
   {
     "buffers": [
       {"name": "xQue_", "num": 2, "size": 120032},
       {"name": "outQue_", "num": 1, "size": 256}
     ]
   }
   ```

   - `name`：buffer 变量名（与 InitBuffer 第一个参数一致）
   - `num`：slot 数量（3 参数形式的第二个参数，2 参数形式默认为 1）
   - `size`：单个 slot 大小（字节，代入 TilingData 实际值）
   - `num == 1` → 保留原名；`num > 1` → 自动拆分为 `name0`, `name1`, ...

2. **运行 `gen_memory_map.py`**

   ```bash
   python gen_memory_map.py buffer_config.json -o memory_map.json
   ```

   脚本自动计算地址，stderr 输出摘要并检查 UB 总用量。

3. **验证**（可选）

   对比 MTE 日志中的地址和 `memory_map.json` 是否一致。

### 配置规则

- buffer 按 `InitBuffer()` 调用顺序连续分配
- 每个 buffer 的 `start` = 前一个 buffer 的 `end`（由 `gen_memory_map.py` 自动计算）
- `num > 1` 时，总大小 = `num * size`
- 248KB UB 边界：总分配不应超过 0x3E000（跟芯片有关）

## show_by_buffer.py

按 buffer 分组显示内存访问情况。

```bash
python show_by_buffer.py <dump_file> -m <memory_map.json> [options]

  -m, --memory-map <file>  地址映射文件（必需）
  -b, --buffer <name>      只显示指定 buffer
  --no-merge               不合并操作
  --time-gap <n>           合并时间间隔阈值 (默认: 10)
  --addr-gap <n>           合并地址间隔阈值 (默认: 32)
  --merge-mte              按 instr_id 合并 MTE
  --mte-focus              MTE 聚焦模式（MTE 详情 + VEC/AIV 聚合摘要）
  --merge-vec-aiv          mte-focus 模式下将 VEC 和 AIV 合并为一行（默认分开）
  -o, --output <file>      输出到文件
```

**合并行为**：
- 默认 VEC（`[VEC]`）和 AIV（`[AIV]`）分开各自独立行显示
- `--merge-vec-aiv` 将 VEC 和 AIV 合并为 `[VEC/AIV]` 一行
- 不同单元类别（VEC/AIV/MTE）互为合并屏障：两个同类操作之间如果出现了另一类操作，不会被合并
- 时间间隔过大的同类操作也会被拆分为独立段

## show_by_time.py

按时间线显示内存访问。

```bash
python show_by_time.py <dump_file> -m <memory_map.json> [options]

  -m, --memory-map <file>  地址映射文件（必需）
  --unit <unit>            过滤执行单元 (MTE_W, MTE_R, VEC_LSU, AIV_SU, ALL)
  -b, --buffer <name>      过滤 buffer
  --time-range <range>     时间范围 (如: 10000-20000)
  --no-merge               不合并操作
  --time-gap <n>           合并时间间隔阈值 (默认: 10)
  --addr-gap <n>           合并地址间隔阈值 (默认: 32)
  --merge-mte              按 instr_id 合并 MTE
  --mte-focus              MTE 聚焦模式
  --merge-vec-aiv          mte-focus 模式下将 VEC 和 AIV 合并为一行
  -t, --mte-timeline <file>  mte_timeline.json 路径（合并 MTE 时间线数据）
  --veccore <name>         目标 veccore (默认: veccore0)
  --limit <n>              最大显示条数
  -o, --output <file>      输出到文件
```

## merge_logs.py

合并 MTE 和 UB 分析结果，生成带越界检查的最终报告。

```bash
python merge_logs.py <mte_timeline.txt> <ub_analysis.log> -o merged_report.log
```

**合并逻辑**：
- MTE_W/MTE_R 记录以 MTE 为准（地址范围更完整，含起止时间戳）
- VEC/AIV 记录保留 UB 分析结果（支持 `[VEC]`、`[AIV]`、`[VEC/AIV]` 三种格式）
- 越界检查：MTE 越界新计算，VEC 越界复用 UB 结果
- 忽略第一次初始化搬运（与业务逻辑无关）
- 支持 MTE 时间范围格式（`start-end`）

## visualize.py

从 merged_report.log 生成自包含交互式甘特图 HTML。

```bash
python visualize.py <merged_report.log> [-o visualization.html]
```

**功能**：
- 甘特图：X 轴时间，Y 轴双层结构（外层 buffer 名，内层 MTE_W/MTE_R/VEC/AIV 通道）
- 交互：鼠标滚轮缩放、拖拽平移、点击折叠/展开 buffer、悬停查看详情
- 过滤：顶部复选框按单元类型过滤
- 无外部依赖，单 HTML 文件直接浏览器打开

## 常见问题

### 1. 地址映射未配置

**症状**：无法识别 buffer，显示 "Unknown buffer"

**解决**：
1. 编写 `buffer_config.json`
2. 运行 `python gen_memory_map.py buffer_config.json -o memory_map.json`
3. 确认命令中加了 `-m memory_map.json` 参数

### 2. 地址映射不一致

**症状**：MTE 地址范围与 TilingData 大小不匹配

**解决**：
1. 检查 `buffer_config.json` 中的 size 值是否正确
2. 检查 InitBuffer 调用顺序是否与 `buffer_config.json` 中的 buffers 顺序一致
3. 对照 MTE 日志验证地址范围

### 3. 越界误报

**症状**：报告越界但实际没有问题

**解决**：
1. 检查 UB 边界设置是否正确（默认 248KB）
2. 检查是否为尾核的特殊处理（可能需要排除）