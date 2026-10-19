# MTE 分析工具指南

## 一键分析

```bash
cd <技能目录>/scripts/MTE/

python run_mte_analysis.py <mte_log.dump路径> <veccore> [--output-dir <dir>] [--no-detail]
```

| 参数 | 说明 | 必填 | 默认值 |
|------|------|------|--------|
| mte_log.dump | MTE 日志文件路径 | 是 | - |
| veccore | `veccore0` 或 `veccore1` | 是 | - |
| --output-dir | 输出目录 | 否 | 当前目录 |
| --no-detail | 紧凑模式（记录多时推荐） | 否 | - |

**产出文件**：

| 文件 | 内容 |
|------|------|
| `mte_analysis.json` | 去重后的搬运记录（Stage 1） |
| `mte_timeline.json` | 按 veccore 分组的时间线（Stage 2） |
| `mte_timeline_<veccore>.txt` | 可读报告，最终输出（Stage 3） |

> **⚠️ 禁止直接读取 `.dump` 日志原文**，必须通过脚本处理后读取输出文件。

---

## 数据说明

### 搬运方向

| 方向 | 说明 | 源地址类型 | 目标地址类型 |
|------|------|-----------|-------------|
| GM -> UB | 全局内存搬运到统一缓冲区 | GM 地址 | UB 偏移 |
| UB -> GM | 统一缓冲区搬运到全局内存 | UB 偏移 | GM 地址 |

### 地址格式

| 格式 | 说明 | 示例 |
|------|------|------|
| `0x9000xxxxx` | GM（Global Memory）地址 | `0x900022c028` |
| `0x0` ~ `0x3E000` | UB（Unified Buffer）偏移 | `0x3c680` |

### 关键字段

| 字段 | 说明 |
|------|------|
| timestamp | 指令开始时间戳 |
| end_timestamp | 指令结束时间戳（从 `mte retire: instr_id` 事件提取） |
| instr_id | 指令 ID |
| burst_length | 单次 burst 长度（字节） |
| burst_count | burst 次数 |
| src_stride | 源地址步进（字节） |
| dst_stride | 目标地址步进（字节） |
| data_type | 数据类型（B8/B16/B32/B64） |

### 时间戳说明

MTE 指令的起止时间通过 `instr_id` 关联：
- **开始时间**：从 `MOV_SRC_TO_DST_ALIGNv2 ... id: N` 行提取
- **结束时间**：从 `mte retire: instr_id: N` 行提取

输出格式为 `start-end`（如 `10204-10207`），单时间戳时显示为 `10204`。

### 去重机制

- 按 `req_id` 对 UBWIF/UBRIF 记录去重，同一 `req_id` 的 `send_req`/`recv_rsp`/`record_map_3` 是同一次搬运的不同阶段，只保留一条
- BRIF 按 `(port, address, size_bytes)` 去重

---

## 越界检查

默认 UB 边界为 248KB (`0x3E000`)，不同芯片可能不同，以实际硬件规格为准。

越界判断：搬运目标地址范围（`start_offset + total_size`）超过 UB 边界即为越界。MTE 日志中的地址范围比 UB 日志更完整，越界检查以 MTE 数据为准。

---

## 与 UB 分析配合

MTE 日志提供完整的地址范围和起止时间戳，UB 日志提供详细的内存访问记录。两者结合：

1. 先用 MTE 分析确定地址范围和时间线
2. 再用 UB 分析检查实际访问
3. 用 `merge_logs.py` 合并结果（MTE 起止时间戳会体现在合并报告中）
4. 可选：用 `visualize.py` 生成交互式甘特图

---

## 子脚本独立用法

三个子脚本仍可独立调用，详细参数和输出格式见 `detail/MTE_Timeline_Tools.md`。

| 脚本 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `analyze_mte_transfers.py` | 解析 mte_log.dump | mte_log.dump | mte_analysis.json |
| `process_mte_timeline.py` | 生成时间线 | mte_analysis.json | mte_timeline.json |
| `show_timeline.py` | 展示可读时间线 | mte_timeline.json | 文本输出 |
