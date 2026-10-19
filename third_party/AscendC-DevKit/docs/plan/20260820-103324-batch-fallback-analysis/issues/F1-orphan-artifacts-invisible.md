# F1: 孤儿产物对框架不可见，契约永远不满足

## 现象

批跑 `20260820-103324-793414` 中，两个算子（rms_norm、add_rms_norm_dynamic_quant）的 agent 把设计/详设产物写进了**孤儿目录**（丢失 `103324-` 前缀），框架完全感知不到这些产物，契约检查永远 unsatisfied，只能靠重试指望 LLM 自觉，直到预算耗尽。

- rms_norm：`general_design.json` 写入 `output/.../20260820-164bbc/artifacts/design/general-design-generator/`（孤儿），正确目录 `20260820-103324-164bbc/...` 下无该文件。
- add_rms_norm_dynamic_quant：tiling 的 6 个产物（`tiling_split/vf_design/buffer_kernel/precision_perf/current_template/decision_log`）全部写入 `output/.../20260820-d8d4d9/artifacts/design/tiling/T1/`（孤儿），正确目录 `20260820-103324-d8d4d9/...` 下只有输入文件。

## 凭什么这么说（证据）

- `_scan_working_dir`（`src/ascendc_devkit/capabilities/agent/_shared.py:274`）只递归扫描注入的 `working_dir`（正确路径），孤儿目录永不进入 artifacts 收集。
- agent transcript 的 Write tool_input.filePath 明确写了孤儿绝对路径（`ascendc-design-generator-02.jsonl` line#15/16/33、`ascendc-design-generator-T1-01.jsonl` 6 处）。
- 孤儿目录无 `.claude/skills` anchor（框架 `_ensure_skills_anchor` 只在正确 cwd 执行），证明孤儿目录是 agent write 时隐式创建，非框架预建。

## 影响

- 契约检查永远 unsatisfied → 重试直到预算耗尽 → stage failed。
- 即使产物内容完全正确，只要位置错了，框架就当"没产出"。

## 根因定位

产物收集的扫描范围是**单一固定目录**，与 agent 实际写盘位置脱节。框架没有任何机制把"wd 之外的产物"纳入视野。
