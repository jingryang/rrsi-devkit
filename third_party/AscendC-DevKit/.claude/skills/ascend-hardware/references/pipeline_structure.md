# 流水线结构与气泡成因

## 三级流水线

AscendC 的核心执行模型是三级流水线：MTE2（搬入）→ Vector（计算）→ MTE3（搬出）。

### 理想状态：完全重叠

```
Tile:   T0    T1    T2    T3    T4
MTE2: [===] [===] [===] [===] [===]
Vec:        [===] [===] [===] [===] [===]
MTE3:             [===] [===] [===] [===] [===]
```

前提条件：
1. bufferNum = 2（双缓冲），允许搬运和计算同时操作不同的 buffer
2. 各阶段耗时接近，不会出现某阶段空等
3. 同步开销足够小

### 气泡类型与成因

#### 1. MTE2-Vector 气泡（数据搬入瓶颈）

```
MTE2: [=======] [=======] [=======]      ← MTE2 慢
Vec:  [===]     [===]     [===]          ← Vector 等待数据
         ^^^       ^^^        ← 气泡！
```

**成因**: 数据搬运比计算慢（memory-bound 算子）
**表现**: Profiling 中 Vector idle 时间占比高
**优化方向**: 减少数据搬运量、增大 tile 减少搬运次数、优化数据布局

#### 2. Vector-MTE3 气泡（计算瓶颈）

```
MTE2: [===] [===] [===]                  ← MTE2 快
Vec:  [=======] [=======] [=======]      ← Vector 慢
MTE3:           [===]     [===]          ← MTE3 等输出
              ^^^       ^^^   ← 气泡！
```

**成因**: 计算比搬运慢（compute-bound 算子）
**表现**: Profiling 中 MTE idle 时间占比高
**优化方向**: 优化计算效率、使用更高效指令、减少计算冗余

#### 3. 同步气泡（PipeBarrier 导致）

```
MTE2: [===] ||||| [===] ||||| [===]
Vec:        ||||| [===] ||||| [===]
                 ^^^^        ^^^^  ← 强制同步导致的气泡
```

**成因**: 过多或过粗的 PipeBarrier 强制所有流水线同步
**表现**: Profiling 中出现周期性的全局空闲
**优化方向**: 使用细粒度同步（PIPE_V 替代 PIPE_ALL）、减少不必要的同步

#### 4. 单缓冲串行（无流水）

```
MTE2: [===]            [===]            [===]
Vec:        [===]            [===]            [===]
MTE3:             [===]            [===]            [===]
```

**成因**: bufferNum = 1，搬运和计算必须串行
**表现**: 总时间 ≈ MTE2 + Vector + MTE3（无重叠）
**优化方向**: 改为 bufferNum = 2（双缓冲）

## 流水线同步机制

### PipeBarrier

| 同步类型 | 等待范围 | 开销 | 使用场景 |
|---------|---------|------|---------|
| `PipeBarrier<PIPE_V>` | 仅 Vector 指令 | 中 | Vector 指令间有数据依赖 |
| `PipeBarrier<PIPE_ALL>` | 全部流水线 | 高 | 避免使用，除非确实需要全局同步 |
| `PipeBarrier<PIPE_MTE2>` | 仅 MTE2 | 低 | MTE2 指令间依赖 |

### EnQue/DeQue

- 通过队列实现流水线各阶段间的自动同步
- EnQue: 生产者（如 MTE2）将数据放入队列
- DeQue: 消费者（如 Vector）从队列取出数据
- 当队列空时消费者自动等待，队列满时生产者自动等待
- 开销极低，是推荐的同步方式

### 事件同步 (SetFlag/WaitFlag)

- 适用于需要精细控制的跨阶段同步
- 比 PipeBarrier 更灵活，可以只同步特定操作
- 例如: MTE3 写完后 MTE2 才能读同一地址

```cpp
event_t eventID = static_cast<event_t>(GetTPipePtr()->FetchEventID(HardEvent::MTE3_MTE2));
SetFlag<HardEvent::MTE3_MTE2>(eventID);
WaitFlag<HardEvent::MTE3_MTE2>(eventID);
```
