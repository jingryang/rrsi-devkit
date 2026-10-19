# L3 方案分析 — 轨迹导出工具进工程

> 对应 L1：`01-problems.md`；L2 总纲步骤 27。拍板后冻结。

## D1 平移方式：vendor 到 `scripts/trace_export/`，不进 src 分层

- **选项 A（选定）**：两个 py 原样/微调迁入 `scripts/trace_export/`，新增入口
  `export_trace.py`。理由：工具是**离线运维分析脚本**，不在框架运行时链路上，
  进 src 会凭空引入分层归属问题；stdlib-only、无框架耦合，scripts 即插即用。
- 选项 B（否）：做成 `ascendc-devkit export-trace` CLI 子命令。否决理由：
  用户明确要求 scripts 入口；且该能力不属框架职责，进 CLI 反而扩大框架表面。
- 判据 §1.2 架构合理：修复落在职责正确的位置——运维脚本归 scripts。

## D2 id 解析：镜像 resume_resolver 三态位置规则

- 字符串不可判型（L1-F2），必须按位置三态：
  ① `<root>/<id>/state_snapshot.json` → flat run；
  ② `<root>/<id>/` 下有含 snapshot 的子目录 → batch（过滤非 run 子目录）;
  ③ `<root>/*/<id>/state_snapshot.json` 唯一命中 → nested exec。
- **选项 A（选定）**：脚本内自含实现 + 注释指明规则权威在
  `resume_resolver.py`。理由：resolver 返回 ResumeTarget（面向 resume 语义），
  导出需要的是 run 目录路径列表，复用需改造 resolver 接口——为 15 行规则
  改 L2 应用层不值；规则漂移风险用交叉引用注释缓解。
- 选项 B（否）：重构 resolver 暴露共用原语。过度设计，收益不成比例。

## D3 teacher 元数据：缺省从日志派生，flag 可覆盖

- 用户拍板：teacher=教师模型；用户不设置时**默认与日志记录一致**——即逐记录取
  该 session 自己的 `session.model.id`（实际生成轨迹的模型），而非全局写死常量。
- `--teacher` 显式传入时覆盖全部记录。模型信息缺失时落空串（诚实缺省），
  不回退猜测值（§2.12 宁缺毋滥）。
- 原 DEFAULT_META 写死的 `"glm-5.3"` 常量随之删除（实例数据出代码）；
  owner 等其余 meta 常量用户未要求变更，保持原值。

## D4 批量清单去硬编码：由 id 结构派生

旧 `run_pipeline_batch.sh` 的「算子→db」OPS 数组**不迁入**（§1.12 不耦合实例、
§2.5 唯一通路）：新入口按 id 解析结果枚举 db，算子无关，同类新 run 自动归位。
`run_pipeline.sh` 同理被 `export_trace.py` 取代，一并淘汰。

## D5 输出布局与失败语义

- 输入侧参数命名 `--runs-root`（默认 `output`）：指向含 run/batch 目录的
  **运行数据根**。不用 `--output-root`——从语料导出视角，run 数据与导出语料
  都是某种"输出"，该名无法区分指代（用户实测反馈后更名）；输出侧固定
  `--out`（默认 `<repo>/trace_export/`，入 .gitignore）。
- **导出叶目录扁平命名 `<算子名>_<run_id>`**（用户需求：一眼看出哪个算子、
  何时跑的、可溯源）。算子名从 run 结构化产物派生（§1.12 合规——只读数据
  不按名分支）：codegen_manifest.json `op_name`（CamelCase→snake）→
  op_kernel `<op>_kernel.cpp` 文件名 → `unknown_op` 兜底；run_id 自带运行
  日期时间（ts+uuid），不再重复放导出时间戳——重导出同 run 原地覆盖保持
  幂等（§1.14），导出时间记入 index.json。
- **`<out>/index.json` 机读索引**（§2.10）：每 run 一条
  {operator, run_id, source_run_dir, exported_at, export_dir,
  native_sessions, slow/fast, code_files}，按 run_id upsert，轨迹量大时
  的检索与溯源入口。
- **终版代码随轨迹带出**（用户需求）：每 run 默认拷贝
  `<run>/artifacts/codegen/` → `<out>/.../code/`；缺 artifacts 记 WARN 跳过；
  `--no-code` 可关。
- 每 run 独立处理：无 db 的 run 记 SKIP（claude 后端等合法情形），
  处理异常记 FAIL 不断批；退出码 0 当且仅当 ok≥1 且 fail==0。

## D7 META 全量可配置 + owner 缺省 unknown（用户拍板）

2.0 SFT meta_info 中所有实例侧字段均可配置：teacher / owner /
query_source / category 四个 override（CLI `--*` 与 shell 头部变量各一套），
缺省值 teacher=逐记录取日志模型 id、owner=**unknown**（两侧一致，用户运行前
临时改 shell 变量）、query_source=operator、category=code；language/rounds/
时间戳/session_id 保持自动派生。原写死 owner "00584171" 删除（实例数据出代码）。

## D6 模块化：convert_to_sft 抽可复用函数

`convert_record` 加 teacher 参数、质检 `check_record` 提到模块级、新增
`export_jsonl(records, output_dir, teacher)` 供入口调用；其自身 CLI main 保留
（对 canonical 目录单跑转换的原通路不变，同一实现两个入口不算双通路）。
