# L1 问题/需求记录 — 轨迹导出工具进工程（一键导出）

## R1 需求：轨迹导出一键化

轨迹导出工具 PanguTraceProcess 位于工程外他人 home 目录
（`/home/x00584171/tools/PanguTraceProcess`），批量使用需手工编辑脚本内写死的
「算子名<TAB>db路径」映射清单（实例数据硬编码，§1.12），且跨目录使用不便。
要求把该能力收进本工程：在 `scripts/` 新增导出脚本，参数为 output 下的
**run id（session）或 batch id**——传 run id 导出该次运行的全部轨迹，
传 batch id 导出该批下所有 run 的轨迹数据。

## R2 术语与对象界定

- 「session id」= DevKit 的 **run_id / execution_id**（output 下含
  `state_snapshot.json` 的目录名），不是 opencode 原生 `ses_*` 会话 id；
- 一个 run 目录的 `opencode.db` 内含**多个**原生会话（每次 agent spawn 一条），
  现工具语义 = 全部导出、每条一个 SFT 记录。

## F1 事实：db/config 布局固定

每个 opencode 后端的 run 目录固定有唯一
`.opencode_home/data/opencode/opencode.db` 与 `.opencode_home/opencode-config.json`
（`opencode_backend.py` `_cfg_scratch_dir`：所有 spawn 隔离到 run 目录同一 scratch）。
工具 `find_config()` 的三级向上推导恰好命中该布局；已对真实 db 验证可跑通。

## F2 事实：id 歧义只能按位置判

batch_id 与 execution_id 字符串同为 ts+uuid 格式，字符串不可判型；
`application/resume_resolver.py` 已实现三态位置判定
（flat run / batch / nested exec）。batch 目录下还混有非 run 子目录
（如 `cann_bench`、zip 包），须以 `state_snapshot.json` 存在性过滤。

## F3 事实：工具零依赖可平移

两个 py 只用 stdlib（sqlite3/json/argparse/pathlib/html/datetime/re），
Python ≥3.11 满足；WAL 模式下 sqlite `mode=ro` 可在 run 存活时只读访问。
