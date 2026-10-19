# L4 实施方案 — 判死前取证 + 杀工具不杀会话

> 对应 L3 冻结方案（D1 主修复 + D2 防御层）。

## 改动 1：runtime_config 工具容忍界（可配置）

- `_DEFAULT_OPENCODE_TOOL_GRACE_S = 1800.0`；`opencode_timeouts()` 增
  `tool_grace_s` 键（`timeouts.opencode_tool_grace_s`，0=禁用杀工具只复位，
  负值 ConfigError 加载期拒绝）；
- dispatcher 三处 `build_agent_backend(...)` 透传 `tool_grace_s=`。

## 改动 2：backend 判死单点加取证（opencode_backend.py）

- `__init__` 增 `tool_grace_s: float = 1800.0` → `self._tool_grace_s`；
- `_probe_running_tool(session_id)`：只读 sqlite（`mode=ro` + 1s 超时）查本
  spawn db（`<workspace>/.opencode_home/data/opencode/opencode.db`）该 session
  最新 tool part（近 20 条内 type==tool 的最新者），返回
  `{status, command, output_tail(200), started_ms}`；无 db/无 part/查询失败
  → None（退化现行行为）；
- `_kill_running_tool_subtree(proc, command)`：限定 **serve 后裔树**（/proc
  ppid 图 BFS），命令的特异 token（含路径或 ≥12 字符）匹配后裔 cmdline，
  SIGKILL 匹配者；根（serve 本身）永不匹配；无特异 token/无匹配 → False；
- `_pretrip_tool_evidence(...) -> "alive"|"killed"|"trip"`：三分支决策表
  （alive=running 未超界→复位 turn_ts/last_event_ts+节流透部分输出一行
  `agent_stream`；killed=超界且匹配→杀工具+复位+warn；trip=无证据/超界无
  匹配（serve 楔死检出）→现行 kill-serve）；
- 看门狗 `_post_message_watched`：turn_stall 门与 keepalive 门 trip 前各经
  取证（`!= "trip"` → `continue` 重新武装）；**hard cap 不受门控**；
- **§P9 让位公式删除**（`max(turn_stall_s, keepalive_idle_s)` 的 tool-block
  分支）——probe 取代（§2.5）；类方法 `_classify_smoke_phase` 无关本步，
  但同理保持单点（见 step-96）。

## 改动 3：D2 防御层（opencode bash 工具超时）

- 实施期查证结论：**未启用**——本批 db 实证 kill-3 的 bash 605s 无工具层
  终止，opencode 版本的 bash 超时行为未获得文档保证；D1 已自足（探活+杀
  工具），不为此改外部件配置（§1.7）。

## 验证（UT `tests/ut/capabilities/test_step97_pretrip_evidence.py` 16 例）

- probe：running/completed/部分输出/无 db/无 session/无 workspace；
- 判定三分支 + grace=0 只复位 + 超界无匹配 trip（楔死检出）；
- 看门狗集成：kill-3 形态存活 / 无证据判死保持 / hard cap 不受门控 /
  超界杀工具后存活且 serve 不死 / keepalive 失明同样门控；
- 杀工具真实 syscall：后裔命中 SIGKILL（根永不匹配）/ 父死无匹配 / 无特异
  token 不猜；
- 配置面：默认 1800 / raw 覆盖 / 0 / 负值拒绝。

## 不做清单

1. 不为取证开第二条判死通路（单点收口在 `_post_message_watched`，§1.15）；
2. 不做 opencode 版本升级/替换（D2 查证后放弃，§1.7）；
3. skill 验证纪律（timeout 包装）不作为主修复（L3 否决记录）。

## as-built（2026-08-27）

- 全部按改动 1/2 落地；D2 记录为「查证后不启用」。
- P117 套件同步重写：§P9 两条旧测试（静态让位界）改为 probe 语义
  （tool 期静默无 running 证据 → model-silence 界直接判死）。
- 全量 UT 3736 绿。**有效性最终验证属下批真实跑**（§3.11 诚实记录）：
  观测点 = 四杀形态复发率（running 误杀应为 0）、杀工具事件、部分输出透出。

## 勘误（2026-08-28）— UT fixture 竞态

`test_kill_running_tool_subtree_kills_descendant_match` Popen 后零等待即扫描
/proc——bash fork+`exec -a` 改名需要时间，负载高时扫描跑在 fork 之前 → 假失败
（隔离 6/6 红，当日全量两轮绿后复现）。被测逻辑无缺陷（生产调用点在工具已
运行 grace 秒后才扫描）。修复 = fixture 有界等待（≤10s 轮询至改名子进程出现
在父直系后裔，再断言杀）；5 连跑绿。
