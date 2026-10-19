---
name: ascendc-sync-incore-tracker
description:
  Use when dynamically locating AscendC intra-core sync deadlocks (SetFlag/WaitFlag) with runnable test cases.
  Triggers when user has pytest/st test cases and needs to verify which exact SetFlag/WaitFlag line causes hang,
  or wants to confirm static analysis conclusions with runtime evidence. Complements ascendc-sync-incore-debug
  (static) by providing dynamic validation. Not for cross-core sync issues.
---

# AscendC 核内同步追踪器

## 概述

本工具用于定位核内同步问题（SetFlag/WaitFlag 导致的死锁）。通过**软件状态追踪**替代硬件同步，程序可正常执行完毕，最后输出错误信息。

**核心优势**：
- 使用 `inline __gm__` 全局变量，无需修改函数签名、调用点或类成员
- 自动过滤关键硬件同步，只追踪软件层面的同步问题
- 注入脚本一键完成所有修改
- 自动适应不同算子目录结构

---

## 核内同步基础知识

在进行追踪调试前，需要理解核内同步的工作原理：

### 同步机制

| API | 作用 | 语义 |
|-----|------|------|
| `SetFlag<HardEvent::XXX>(eid)` | 设置同步标记 | 通知硬件某个操作已完成 |
| `WaitFlag<HardEvent::XXX>(eid)` | 等待同步标记 | 阻塞等待对应 SetFlag 执行 |

### 常见 HardEvent 类型

| 类型 | HardEvent | 说明 |
|------|-----------|------|
| MTE 之间 | MTE2_MTE1, MTE1_MTE2, MTE3_MTE1, MTE1_MTE3, MTE3_MTE2, MTE2_MTE3 | 数据搬运单元之间的同步 |
| MTE 和 V 之间 | MTE2_V, V_MTE2, MTE3_V, V_MTE3, MTE1_V, V_MTE1 | 搬运与向量计算之间的同步 |
| M 和 V 之间 | M_V, V_M | 矩阵与向量计算之间的同步 |
| FIX 相关 | M_FIX, FIX_M, MTE2_FIX, FIX_MTE2, FIX_MTE3, FIX_S | 输出写入相关 |

### 常见同步模式

**正向同步**（生产者→消费者）：
```cpp
// 生产者完成数据搬运
SetFlag<HardEvent::MTE2_V>(event_id);
// ... 其他操作 ...

// 消费者等待数据就绪
WaitFlag<HardEvent::MTE2_V>(event_id);
// 使用数据
```

**反向同步**（PingPong 双缓冲）：
```cpp
// Init: 预先 Set 第一次
SetFlag<HardEvent::MTE2_V>(event_id);

// Loop: Wait → 使用 → Set
for (int i = 0; i < N; i++) {
    WaitFlag<HardEvent::MTE2_V>(event_id);  // 等待上一轮 Set
    // 使用数据 ...
    SetFlag<HardEvent::MTE2_V>(event_id);   // 标记本轮完成
}
```

---

## 动态调试流程 Pipeline ⭐⭐⭐⭐⭐

**关键原则：使用 git worktree 创建独立的调试工作目录，不影响原分支！**

### 前置条件检查

在开始调试前，确认以下条件：

1. **有可运行的测试用例**：
   - 确认 tests/st 目录下有 pytest 文件
   - 测试用例能复现同步问题（程序卡死或结果错误）

2. **已安装编译环境**：
   - CANN 工具链可用
   - Python 环境已配置 torch_npu

3. **了解算子基本信息**：
   - 算子名称（用于 build.sh -n 参数）
   - 算子文件路径

4. **确认芯片型号与空闲卡**（必须先做）：
   ```bash
   npu-smi info
   ```
   - 型号映射：
     - 910B → `ascend910b`
     - 910C → `ascend910_93`
   - 选择无人使用或占用最少的卡，并设置环境变量：
     ```bash
     export ASCEND_DEVICE_ID=<卡号>
     ```
   - 安装路径建议使用 `/tmp` 下的临时目录（例如 `/tmp/omni_ops_install`）

---

### 阶段1：初始化调试环境

**Step 1A**: 使用 git worktree 创建调试工作目录 ⭐

```bash
# 在仓库根目录执行（worktree 放在 .worktree 目录下，保持整洁）
mkdir -p .worktree
git worktree add .worktree/<op_name>-incore-debug-$(date +%Y%m%d%H%M) -b incore-debug-$(date +%Y%m%d%H%M)
# 例如：
git worktree add .worktree/sparse_flash_attention-incore-debug-20260315 -b incore-debug-20260315
```

这会：
- 创建一个独立的工作目录 `.worktree/<op_name>-incore-debug-<timestamp>`
- 同时创建一个新分支 `incore-debug-*`
- 原工作目录不受影响，可以继续在原分支工作
- `.worktree` 目录已在 `.gitignore` 中，不会污染仓库

**Step 1B**: 在调试 worktree 中运行注入脚本 ⭐

```bash
cd .worktree/<op_name>-incore-debug-<timestamp>

# 运行注入脚本（实际修改文件）
python <skill_dir>/scripts/inject_sync_tracker.py <算子目录路径>
```

例如：
```bash
cd .worktree/sparse_flash_attention-incore-debug-20260315
python /mnt/workspace/gitee/omni-ops/.claude/skills/ascendc-sync-incore-tracker/scripts/inject_sync_tracker.py \
    training/ascendc/src/ops-transformer/attention/sparse_flash_attention_grad_enhance
```

脚本会自动完成：
1. 复制 `sync_tracker.h` 到合适目录（优先 `basic_modules/`，否则 `op_kernel/`）
2. 替换所有符合条件的同步调用
3. 添加 `#include` 语句
4. 在 `op.Process()` 后添加 `TrackerPrint()`

**Step 1C**: 在调试 worktree 中编译、安装、运行测试

```bash
# 选择空闲卡并设置设备号（必须先做）
npu-smi info
export ASCEND_DEVICE_ID=<空闲卡号>

cd training/ascendc
bash build.sh -n <op_name> -c <chip_type>  # 例如 bash build.sh -n sparse_flash_attention_grad_enhance -c ascend910b

cd build && ./CANN-*.run --install-path=<install_path> --quiet  # 例如 ./CANN-*.run --install-path=/tmp/omni_ops_install --quiet

source <install_path>/vendors/*/bin/set_env.bash  # 例如 source /tmp/omni_ops_install/vendors/omni_training_custom_ops/bin/set_env.bash

# 只跑一个测试用例（必须遵守，避免一次跑多个用例）
pytest <测试文件>::<测试类>::<单个测试用例> -v -s 2>&1 | tee /tmp/<op_name>_incore_test_$(date +%Y%m%d%H%M).txt
```

**你不需要关注 pytest 的测试精度结果**，因为同步被软件追踪替代，精度测试结果没有意义。

**Step 1D**: 提取并利用分析脚本分析同步日志

```bash
grep "\[SYNC DEBUG\]" /tmp/<op_name>_incore_test_xxx.txt
```

正常情况：
```
[SYNC DEBUG] OK: all sync calls are correct
```

发现错误 - WAIT on UNSET（曾经 SET 过，但已被 WAIT）：
```
[SYNC DEBUG] ERROR: WAIT on UNSET (HE=4 eid=0)
  WAIT at line 828, prev SET at line 800
  => flag was SET then WAITed, need another SET?
```

如果发现了同步错误，可以使用分析脚本快速定位具体代码：

```bash
python <skill_dir>/scripts/analyze_sync_output.py /tmp/<op_name>_incore_test_xxx.txt <算子目录路径>
```

例如：
```bash
python /mnt/workspace/gitee/omni-ops/.claude/skills/ascendc-sync-incore-tracker/scripts/analyze_sync_output.py \
    /tmp/sparse_flash_attention_incore_test_20260315.txt \
    training/ascendc/src/ops-transformer/attention/sparse_flash_attention_grad_enhance
```
阅读脚本输出报告可以获取更多信息
---

### 阶段2：深入分析问题根源（在应用修复前！）

**⚠️ 重要：必须先调用 ascendc-sync-incore-debug skill 进行深入分析！**

**Step 2A**: 提供出错的代码所在的函数，信号以及行号，调用 ascendc-sync-incore-debug skill 进行专业分析 ⭐

```bash
# 使用 skill 进行标准化的同步分析
# 提供函数路径，出错的信号和行号范围
```

该 skill 会：
1. 列出所有事件 ID 及其 HardEvent 类型
2. 按 HardEvent 类型分组
3. 画出同步流程时序图
4. 生成状态追踪表
5. 验证 SET/WAIT 平衡
6. 输出结构化的分析报告

重要：如果该Skill未检测出问题并且没提供任何修复建议，则根据Step 2B~E流程自己分析一下，否则进行下一个Step 3
**不要急于修复！先理解问题的本质！**

**Step 2B**: 研究同步语义
- 这个 SetFlag/WaitFlag 是用来同步什么操作的？
- Set 之后保证了什么状态？
- Wait 之前需要什么数据就绪？
- **HardEvent 类型的语义是什么？**（如 MTE3_MTE2 = MTE3完成通知MTE2）

**Step 2C**: 分析业务逻辑
- 是否使用了 PingPong 双缓冲模式？
- 是否有循环中的同步？
- Event ID 是否正确复用？

**Step 2D**: 检查同步配对
- Set 和 Wait 的 HardEvent 类型是否一致？
- Event ID 是否匹配？
- 是否存在分支遗漏 Set 或 Wait？

**Step 2E**: 设计修复方案

**⚠️ 绝对禁止的做法**：
- ❌ 机械地在 WAIT 前面随便加一个 SET
- ❌ 在一个 SET 后面再加一个 SET 来"配平"
- ❌ 不理解同步语义就添加同步调用
- ❌ 简单地数 SET/WAIT 数量来平衡

**正确的修复原则**：

1. **理解同步信号的发送时机**：
   - SET 应该在**什么业务操作完成后**发送？
   - 例如 `MTE3_MTE2`：应该在 MTE3 DataCopy（数据搬出）完成后 SET

2. **理解同步信号的等待时机**：
   - WAIT 应该在**什么业务操作之前**等待？
   - 例如 `MTE3_MTE2`：应该在 MTE2 DataCopy（数据搬入）之前 WAIT

3. **参考正确的模式**：
   - 对比同文件中其他正确实现的函数
   - 学习标准的 PingPong 模式结构

常见问题 Pattern：

| 错误类型 | 可能原因 | 正确的修复方案 |
|----------|----------|----------------|
| WAIT 无 SET | 循环内 MTE3 操作后漏 SET | 在 MTE3 DataCopy 完成后添加 SET |
| 重复 SET | 循环逻辑错误 | 检查循环内的 SET/WAIT 顺序 |
| Event ID 不匹配 | PingPong 用了相同 ID | 使用不同的 Event ID |

**关键**：不要简单地"添加缺失的同步"，要理解**为什么**需要这个同步，**什么时候**应该发送信号！

---

### 阶段3：在调试 worktree 验证修复（关键！）

**修复必须在调试 worktree 完成并验证！不完成阶段2的深入分析不能进入阶段3！**

**Step 3A**: 在调试 worktree 应用修复

```bash
# 确认在调试 worktree
pwd  # 应显示 .worktree/<op_name>-incore-debug/...
# 编辑 kernel 文件，应用修复
```

**Step 3B**: 重新编译、安装、运行测试

```bash
cd training/ascendc && bash build.sh -n <op_name> -c ascend910b
cd build && ./CANN-*.run --install-path=/tmp/omni_ops_install --quiet
source /tmp/omni_ops_install/vendors/*/bin/set_env.bash
pytest <测试文件>::<测试类>::<测试用例> -v -s 2>&1 | tee /tmp/fixed_test_log.txt
```

**Step 3C**: 验证修复效果

```bash
grep "\[SYNC DEBUG\]" /tmp/fixed_test_log.txt
```

预期输出：
```
[SYNC DEBUG] OK: all sync calls are correct
```

**如果验证失败**：回到阶段2继续分析，调整修复方案

---

### 阶段4：应用到原仓库并清理

**只有验证通过后才执行此步骤！**

**Step 4A**: 回到原仓库工作目录

```bash
cd <原仓库根目录>  # 例如 cd /mnt/workspace/gitee/omni-ops
```

**Step 4B**: 应用修复到原分支

- **不要复制 TrackerSet/TrackerWait 代码！**
- 将调试版本的修复转换为真正的 SetFlag/WaitFlag 版本
- 例如：
  ```cpp
  // 调试 worktree 中验证过的修复（Tracker 版本）
  TrackerSet(HE_MTE2_V, event_id, __LINE__);

  // 应用到原仓库（真实 API 版本）
  SetFlag<HardEvent::MTE2_V>(event_id);
  ```

**Step 4C**: 删除调试 worktree 和分支

```bash
# 删除 worktree
git worktree remove --force .worktree/<op_name>-incore-debug-<timestamp>

# 删除调试分支
git branch -D incore-debug-*

# 如果 .worktree 目录为空，可以删除
rmdir .worktree 2>/dev/null || true
```

**Step 4D**: 生成调试报告，格式应该美观并且结构化

报告应包含：
- 问题描述（发现了什么同步问题）
- 根本原因（为什么会出现这个问题）
- 信号语义分析（这个同步的作用，应该在什么业务时机发送）
- 修复方案（如何修复，为什么这样修复是正确的）
- 验证结果（修复前后的对比）

---

## 常见问题

### Q: 头文件放在哪个目录？

A: 脚本会自动选择：
- 如果算子有 `basic_modules/` 目录，放在 `basic_modules/`
- 否则放在 `op_kernel/`

不要在两个目录都放，会导致编译冲突。

### Q: 多核是否会竞争？

A: 不会。`__gm__` 全局变量每个核独立拥有自己的实例，追踪函数内部检查 `GetBlockIdx() == 0`，只有 block 0 会写入。

### Q: 行号准确吗？

A: 是的，使用 `__LINE__` 宏在编译时自动插入当前行号。

### Q: 为什么精度测试失败？

A: 因为同步被软件追踪替代，没有真正等待硬件完成。这是正常现象，关注 `[SYNC DEBUG]` 输出即可。

### Q: git worktree 相关命令？

```bash
# 查看所有 worktree
git worktree list

# 创建调试 worktree（放在 .worktree 目录下）
mkdir -p .worktree
git worktree add .worktree/<name>-incore-debug -b incore-debug-xxx

# 删除调试 worktree
git worktree remove .worktree/<name>-incore-debug

# 清理已删除的 worktree 引用
git worktree prune
```

---

## 常见错误（避免！）

**错误1**：在原仓库而不是调试 worktree 工作
- 结果：污染原分支，难以回滚
- **正确做法**：使用 `git worktree add .worktree/<name>` 创建独立调试目录

**错误2**：没有深入分析就直接添加 Set/Wait ⚠️ **严重错误！**
- 结果：可能引入新的同步问题或破坏流水线性能
- **典型错误**：
  - 看到"WAIT 无 SET"就简单在前面加一个 Set
  - 在一个 SET 后面再加一个 SET 来"配平"
  - 不理解 HardEvent 语义就随便加同步
- **正确做法**：
  - **必须先调用 ascendc-sync-incore-debug skill 进行专业分析**
  - 理解同步信号的发送时机（什么业务操作完成后 SET）
  - 理解同步信号的等待时机（什么业务操作前 WAIT）
  - 分析不清楚就不要乱改，宁可保留问题也不要引入新问题

**错误3**：修复后没有重新运行验证
- 结果：不确定修复是否正确，可能遗漏问题

**错误4**：将 TrackerSet/TrackerWait 代码应用到原仓库
- 结果：代码逻辑不正确，精度测试必然失败

**错误5**：跳过阶段2直接进入阶段3
- 结果：机械地修复，没有理解业务逻辑，修复不正确

**错误6**：忘记清理调试 worktree
- 结果：磁盘空间浪费，worktree 列表混乱

**正确做法**：
1. 使用 git worktree 创建独立调试目录（放在 `.worktree/` 下）
2. **调用 ascendc-sync-incore-debug skill 深入分析同步语义和业务逻辑**
3. 理解信号的发送时机和等待时机，**不要机械地配平 SET/WAIT 数量**
4. 在调试 worktree 验证修复
5. 验证通过后回到原仓库应用修复（用真实 API）
6. 清理调试 worktree: `git worktree remove .worktree/<name>-incore-debug`