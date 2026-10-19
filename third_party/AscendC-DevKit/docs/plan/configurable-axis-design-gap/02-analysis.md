# 可配置轴算子设计缺口 — 方案分析（L3）

> 选项 / 取舍 / 决策。事实见 `01-problems.md`（P1）。拍板后冻结。

## 决策

**机制 = B（axis-aware addressing）。**

- host TilingFunc 按实际 `dim` 推导 x0/x1 的 GM offset/stride，写入 TilingData；
- kernel CopyIn 按这些描述符用 strided DataCopy 搬 x0/x1 进 UB；
- VF 计算（silu*mul 在寄存器上）**轴无关、不动**；CopyOut 按输出布局。

### 为什么是 B（不是 A/C）

- **A（host transpose）被框架排除**：框架是单-kernel-per-op（已核：codegen 无 aclnn 组合/多 kernel 机制），host transpose 要么 aclnn 组合 `aclnnTranspose`、要么一个 op 多 kernel，**两者 codegen 都产不出**。用户已定 A5 codegen 冻结 → A 需 codegen 改动 → 不可行。"in-kernel transpose"（kernel 内 strided 搬）= B 本身。
- **B 符合框架**：单 kernel，轴处理在数据搬运层（CopyIn），不碰 codegen 的结构能力。
- **B 是 SIMT-native**：kernel 已在用 strided DataCopy（`DataCopyPad`+`srcStride`），A5 SIMD 有 `数据重排/离散与聚合(gather)/索引操作` 原语 → B 是参数化现成机制，非新能力；且 VF 计算不动。
- **B perf ≥ A**：dim=0（失败用例）B 更快（strided/连续读，无 transpose）；dim=-1 持平。
- **不耦合具体算子（§2.1/§2.7）**：做成 general-design 的"轴参算子"通用模式，对 split / reduce-with-axis / concat-dim 等任何轴参算子适用。
- C（收缩+契约）不满足 REQ-03、9/20 fail，排除。

## 修复范围划分（关键：我们的 vs 遗留）

### 我们修（设计 skill 层）

1. **general-design**：识别"轴参算子"——拆分/计算轴是**运行时 dim 属性**（非固定轴）。不再把 SwiGLU 这类简单归为 A01 定轴 elementwise；在轴语义里区分"运行时可选计算轴"与现有静态 `split_axis_priority`（多核切分轴）。
2. **tiling-split / tiling-buffer-kernel**：axis-aware tiling——host 按实际 dim 推导 x0/x1 的 GM 描述符（offset/stride/blockLen/blockCount），写入 TilingData 字段；kernel 伪代码的 CopyIn 按描述符 strided 搬运、VF 与 CopyOut 轴无关。TilingData 设计要新增承载轴描述符的字段。
3. **docgen**：设计文档须写明 axis-aware 寻址（不写死末轴）——与 P5 同源（P5 修 `// BEGIN_TILING_DATA_DEF` 标记时一并处理轴描述符字段的文档化）。

### 遗留（A5 codegen，他人，只记录不修）

- codegen 须按上述设计**产出** axis-aware 的 host TilingFunc（算 stride/offset）+ kernel strided CopyIn 代码。**在 codegen 实现前，设计正确但生成的 kernel 仍只支持 dim=末轴**——即本仓修完设计层，端到端仍要等 A5 codegen 责任人落地才能让 dim≠末轴用例真正通过。
- 归属：A5 codegen（见 `01-problems.md` P3）。本任务结束时在 P1 状态里明写这条遗留 + 指向 codegen 责任人。

## 交付结构：两笔独立提交（已拍板）

开发时两笔一起做（能端到端验证设计正确），但严格独立、任一可单独合入、顺序无关。**核心约束：commit 1 必须加性 + 行为保持——不提交 commit 2 也不影响整体运行。**

**Commit 1（设计 skill，我们的，正常合）** — 加性 + 行为保持：
- 主 kernel 伪代码（dim=末轴路径）**原样不动** → 当前 codegen 产出与今天字节级一致，零回归；
- axis-aware 内容作为**加性附录**（独立段"轴参泛化设计" + TilingData 可选轴描述符字段），当前 codegen **不读** → 忽略 → 行为不变；
- schema 只加可选字段、不加必填、不改名/删字段；
- 轴参识别**只对真有运行时 dim 轴的算子触发**，存量无 dim 轴算子设计不变。
- 净效果：pipeline 照跑、产出与今天一致；axis-aware 设计作为规格"待 codegen 实现"。

**Commit 2（codegen axis-aware 发射，我准备 + 本地验证，合入由 codegen 责任人定）**：
- codegen 读 commit 1 的"轴参泛化设计"附录 + 轴描述符 TilingData 字段 → 产出 axis-aware host TilingFunc（算 stride/offset）+ kernel strided CopyIn。
- 无 commit 1 → 休眠 no-op；有 commit 1 → 激活。
- 本地两笔合一起跑 heavy_llm e2e 验证 dim=0 用例从 diff=173 → pass，作为 commit 2 的合入证据交责任人。

**独立性证明**：commit 1 不依赖 commit 2（当前 codegen 忽略加性内容、产出不变）；commit 2 不依赖 commit 1 已合（无附录则休眠）。任一单独合入安全、顺序无关。

## 验证

- **commit 1**：skill 文档契约 UT（grep 断言"轴参算子"模式落位 + TilingData 承载轴描述符为**可选**字段）非 heavy_llm；**+ 回归守护**（存量无 dim 轴算子设计不变、当前 codegen 产出不变）。
- **commit 2**：heavy_llm e2e（两笔合一起真跑，dim=0 用例 diff→pass）作合入证据，不在 commit 1 的 UT 范围。

## 拍板后产出

L4 `03-impl-axis-aware-design.md`：精确到改哪个 skill 的哪一段、TilingData schema 新增可选字段、按什么顺序、怎么验证（UT + 回归）。