# L1 问题记录：codegen 无确定性 host-offload 契约门（2026-08-14 取证）

> 层级：**L1 / 问题记录**。只陈述客观事实（哪里坏、凭什么这么说），不提方案、不排顺序、不写决策。
> 与 `design-math-claims-verification/` 的 B1（debug `fallback_masked` 未落地）同源但**独立**：那是 debug 侧 host 兜底，本文是 codegen 侧 plugin 把算子核心逻辑放 host 算、且框架无确定性拦截。

---

## 触发事实：moe_re_routing 被判作弊（partial CPU 实现）

- `moe_re_routing` 算子（cann-bench 在线评测 63.24 分）被判定「部分用 CPU 实现算子」。
- 铁证在 plugin 源码 `moe_re_routing_plugin.cpp`：
  - `:101` `auto cpuEtnpr = expertTokenNumPerRank.to(torch::kCPU).contiguous();`（NPU→CPU）
  - `:48-93` `ComputePermuteIdxAndEtnImpl`：host 侧 `std::vector` 前缀和 + 地址映射，重算 4 个正式输出中的 2 个（`permute_token_idx` + `expert_token_num`）
  - `:173-174` `permuteIdx.copy_(hostIdx); expertTokenNum.copy_(hostEtn);`（CPU→NPU 回写）
- NPU kernel `moe_re_routing.h` 是「纯 gather（无 compute）」——只按 host 预置索引搬 token，核心算法（置换索引生成）全在 CPU。

## 与 foreach_norm 的区分（避免同类混淆）

| | foreach_norm | moe_re_routing |
|---|---|---|
| 作弊判定 | **误判**（源码真 NPU，只是缺 CMakeLists 没编进包）| **成立**（源码就把核心计算写 CPU host）|
| 根因 | 脚手架缺失（注册没进包）| codegen 有意把 2/4 输出放 host CPU |
| 约束状态 | 无覆盖（注册缺陷不在反作弊射程）| **有维10 规则，但生成时规则未上线** |

## 问题清单

### H1 codegen 无确定性 host-offload 契约门
- **symptom**：op_plugin 里 `.to(torch::kCPU)`/`.cpu()` + host 算值 + `.copy_()` 回写输出，绕过 aclnn kernel，框架无确定性（机械）拦截，只能靠维10 LLM 自检自觉。
- **evidence**：
  - `grep -rn "kCPU\|\.cpu()\|host 兜底\|plugin 越界" src/ascendc_devkit/` **零命中**（确定性门只覆盖 CMakeLists 缺失 / manifest 契约 / plugin 返回签名，均不覆盖 host-offload）。
  - 维10（`ascendc-op-dev-coding/SKILL.md`）有「③ 含 CPU 兜底路径 → fail」规则，但它是 **LLM 自检**（概率性），且**生成 moe_re_routing 时（Aug 5）规则尚未上线**——`59b12b61`（2026-08-08）才由 unique 同源问题（`at::_unique2` host CPU 兜底）补上。
- **status**: ✅ 已修（本次，见 03-impl.md）
