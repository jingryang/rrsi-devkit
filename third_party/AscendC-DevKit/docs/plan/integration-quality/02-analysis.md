# P3+P4 分析（追加）

## P3：代码平铺在根目录

### 根因
`kernel_architecture.json` 的 `host_code` / `kernel_code` 不包含 `directory` 字段：
```json
"host_code":   { "files": ["rotary_position_embedding_tiling.h", ...] }  ← 无 directory
"kernel_code": { "files": ["rotary_position_embedding_kernel.h", ...] }  ← 无 directory
```
`_expected_code_files()` 直接返回这些扁平路径 → agent 不知道放哪。

### 选型
**方案 B：在 codegen prompt 中基于 host_code/kernel_code 分类自动注入目录规则。**

理由：不改设计阶段的 schema（透传），不改 kernel_architecture.json 格式。在 codegen 层推断目录：
- `host_code.files` → `op_host/`
- `kernel_code.files` → `op_kernel/`
- 读取现有的 `op_host/` 和 `op_kernel/` 目录确认命名约定存在

## P4：JSON 中间产物污染算子仓

### 根因
`_materialize_inputs()` 第 156-181 行把 design JSONs 直接写入了 `working_dir`（即 `op_dir`），prompt 让 agent 在工作目录写 `changed_files.json` 和 `decision_log.json`。

### 选型
**方案 A：materialize 到 artifacts/staging，prompt 改用 staging 路径。**

`_materialize_inputs()` 写入 `workspace.artifacts / "staging"` 而非 `op_dir`。
Agent `working_dir` 仍为 `op_dir`（代码写这里），但 prompt 中的设计文件路径指向 staging。
`changed_files.json` 和 `decision_log.json` 不再要求写入工作目录——改为写入 staging 目录。
