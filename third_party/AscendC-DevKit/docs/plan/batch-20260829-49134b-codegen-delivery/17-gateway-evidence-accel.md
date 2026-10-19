# P16 修复——静默判死分型：阳性网关错误证据立即 trip + 残差界降 180s（step-115）

> L1：`01-problems.md` P16（+14s 错误证据实测 + 裁决史 + 用户裁定）。
> L3/L4 合并（单文件小步）。

## L3 方案分析（2026-09-02 冻结）

**定性**：可观测性缺陷 + 参数裁定。判死动作本身正确（P131 实证：判死后
backoff-resume 立即重采样成功），缺陷在「何时判死」只认静默时长，不认已
可查证的阳性错误证据。

**结构**：判死条件从一维（时长）变三维分型——

| 证据形态 | 判定 | 动作 |
|---|---|---|
| 阳性上游错误（app log 新鲜 `stream error`）+ chars 静止 | **网关已死** | 立即 trip（`gateway_stream_error`） |
| db 工具 running（step-97 既有） | 活着 | re-arm 不杀 |
| 无任何证据 | 未知 | **时长兜底 180s**（用户裁定；P9 误杀风险知悉接受，配置可回调） |

**为何不是单纯缩短时长**：P9 实证 120s 系统性误杀 pangu 无增量静默深推理
（trip→resume→trip 死亡螺旋，整算子 exit 65）。证据分型后，时长界只剩
「无证据」类——恰是活深推理保护区；但用户裁定 180s 并接受风险，配置面
`timeouts.opencode_turn_stall_s` 保留回调能力，trip 打标供后续校准。

**误差分析（证据 trip 的误杀面）**：单次瞬态错误被 opencode 内部重试自愈、
chars 尚未恢复流动时，可能早杀一刀。三重收窄：① 错误行必须**晚于静默起点**
（新鲜度）；② trip 前再核 chars 仍静止；③ **≥2 条复发判据**（2026-09-02
用户质询「30s 前置的实际价值/误杀面」后收紧）——坏窗口错误持续复发（实测
6-12s/轮），瞬态错误单发自愈后不复现，「复发」是比静默时长更强的判据
（§1.10 证据优先于时长代理）；单发瞬态 + 首 token 迟到（>probe_s，本网关
首 part 实测 ~9s）不再可能误杀。慢循环坏窗口（每轮上游 300s 才报错）凑不
齐 2 条，由 180s 时长界兜底——分工正确。残余竞态（双发 flap 后自愈）代价 =
一次 resume（会话保留），有界；对照收益 10 倍（600s→<1min/死尝试）。
静默前置与 ≥2 复发**正交互补**（2026-09-02 用户质询「IO 经济实际意义」
后澄清）：前置防 flappy-alive（输出 burst 间隙连出 2 条瞬态错误的活会话，
既往 L1 实证 14 错误期间完成 74 步），≥2 防单发瞬态+首 token 迟到——
「静默中持续报错」= 死亡签名，两条件各贡献一半。IO 经济是伪理由
（尾读成本可忽略），已从设计中剔除（15s 节流删除）。「≥2」是正确性
判据不做旋钮（§1.14）。

**边界**：
- 信号源 = 本 spawn scratch home 的 app log（§1.7 无忧，step-97 先例同目录 db）。
- 只在 opencode backend 实现（sdk 侧无此形态，单点 §1.15）。
- 证据 trip **不**再走 db 工具探针：工具执行期无活跃流、不会产生新鲜
  `stream error`，两证据源天然不相交。
- 与 keepalive/硬顶共存：证据 trip 是提前出口，不改其余看门狗语义。

## L4 实施

1. `runtime_config.py`：
   - `_DEFAULT_OPENCODE_TURN_STALL_S` 600.0→**180.0**（注释记 2026-09-02
     用户裁定 + 风险知悉 + 证据分型后的残差语义 + 回调旋钮）；
   - `opencode_timeouts()` 增 `gateway_error_probe_s`（默认 30.0：chars
     静止超过该值才开始探证据；**0=禁用证据腿**——本键的真实运维价值是
     新杀路径的逃生口，数值调节价值边际。探针随 poll 直读不设节流——
     尾 64KB 页缓存读成本可忽略，IO 动机的节流复杂度不值[2026-09-02
     用户质询后简化]）。
2. `opencode_backend.py`：
   - 构造参数 `gateway_error_probe_s`（dispatcher 三构造点随
     `opencode_timeouts()` 注入）；
   - `_gateway_error_evidence(log_path, since_epoch)`：读 app log 尾部
     （≤64KB），解析 `timestamp=…Z level=ERROR` 且 `message="stream error"`
     行，返回晚于 since 的**全部**错误时刻列表（空 = 无证据）；
   - `_post_message_watched` 看门狗循环：chars 静止 > probe_s → 每 poll 直读
     探证据（无节流——15s 节流已删，与上 L3 注一致）；**≥2 条**新鲜错误（复发
     判据）且 chars 仍静止 → trip，
     reason 带 `gateway_stream_error` + 错误条数/最新时刻/静默时长；abort
     kind 同名；
   - app log 路径：spawn 内由 scratch home 拼出，传入 watched POST。
3. trip 打标：evidence-trip 与 duration-trip 的 reason/abort kind 天然可区分
   （`gateway_stream_error` vs `no_turn_progress`），批日志可汇总校准。
4. UT（`tests/ut/capabilities/test_opencode_backend.py` 扩展）：
   - 新鲜错误 + chars 静止 → 证据 trip（kind 正确、早于时长界）；
   - 错误早于静默起点（陈旧）→ 不 trip；
   - 无错误行 → 时长界兜底（小 bound 注入验证 duration trip 仍工作）；
   - chars 恢复流动 → 不 trip；
   - **单发瞬态错误（无复发）→ 不 trip**（≥2 判据的边界用例，防误杀
     「瞬态自愈 + 首 token 迟到」的活会话）；
   - probe_s=0 → 禁用证据路径；
   - `opencode_timeouts()` 新键默认/0/非法值三态。
5. 既有测试更新：pin 600 默认值或依赖 600 语义的用例随契约更新（如有）。

## 验证

- 全量 UT（--quick）；受影响 ST（看门狗族 + 4 个 codegen staging 文件）
  重跑；下批真实跑判据：坏窗口死尝试 <1min 出局、`gateway_stream_error`
  事件可见、无证据 trip 的分布可汇总（校准 180 是否需回调）。
