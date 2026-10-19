# OpDef 渲染幻觉 + 多芯片交付 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发：run `20260722-022209-e08f46` 的 `Exp_详细设计说明书.md` §2.3 算子信息库。

## P1 — docgen §2.3 渲染出虚构 CANN OpDef API（已修）
docgen 渲染的 OpDef 用了一套**不存在的 API**：`desc.MutatableInputDesc("x")` /
`desc.OutputAttrMapping(&y,{0})` / `desc.Attr("base", ge::DT_FLOAT, ScalarValueType::SINGLE_FLOAT, -1.0f)` /
`this->AICore().AddConfig(<SOC_VERSION_FROM_CHIP_TRANSLATION>)`（占位串、缺 `OpAICoreConfig` 对象），
且缺 `#include "register/op_def_registry.h"` 与 `OP_ADD`、构造写错为 `Exp() : OpDef("Exp")`。
凭什么：对照 cann-bench 真实 `examples/aclnn_launch_example/csrc/ops/exp/op_host/exp_def.cpp`（同算子
Exp/base/scale/shift），真实 API 是 builder 链 `this->Input("x").ParamType(REQUIRED).DataType({...})...AutoContiguous()`、
`this->Attr("base").Float(-1.0f)`、`OpAICoreConfig cfg; ...; AddConfig("ascend950", cfg)`、`OP_ADD(Exp);`。
根因：渲染知识（builder 链 / dtype 串→`ge::DT_*` / `OpAICoreConfig`+`AddConfig` / `OP_ADD`）谁都没显式
给——知识库有 API refs 但无"逻辑 spec→C++"映射规程；docgen §2.3 模板仅占位注释；无下游门（docgen 自述
产物面向人、validate 不查 OpDef）。修法见 `04-impl.md`。

## P2 — OpDef 仅渲染单芯片 AddConfig，多芯片交付暂不支持（**开放，低优先级**）
当前 OpDef 的 `AddConfig` 只为**本次运行的目标芯片**渲染一个（chip 来自 `hw_params.json`/`meta.json`
的 `chip_code`，经 `to_soc_version()`）。凭什么：CLI `--design-target-chip` 单值 + design JSON 按设计
chip-agnostic（chip 走 state/meta/hw_params 通道，不进 design_spec）；流水线 per-chip，单次一个
AddConfig 是当前正确形态。要做（未来）：入口声明**交付芯片集**（多值）→ OpDef 多 `AddConfig`（每芯片
一个 `OpAICoreConfig`）→ codegen 多芯片编译矩阵。本轮**不做**，仅记录。
