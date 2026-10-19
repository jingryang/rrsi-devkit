# VF 编排合成器

## 输入

- `vf_count`（来自 SKILL.md 步骤 1 决策树输出）
- `has_dependency`（VF 间有依赖→依赖链约束顺序，无依赖→独立顺序任意）

## 编排模板

与 `vf_archetypes.md` 的 5 模式对齐。**CopyIn (mte2) 和 CopyOut (mte3) 是外层搬运，不计入 VF。**

```python
def compose_vf_layout(vf_count, has_dependency, base_pattern):
    if vf_count == 1:
        return single_vf_layout(base_pattern)
    elif has_dependency:
        return sequential_vf_layout(vf_count, base_pattern)
    else:
        return independent_vf_layout(vf_count, base_pattern)


def single_vf_layout(base):
    """模式 1/2：单 VF。外层 CopyIn/CopyOut 独立。"""
    return {
        'copy_in': [{'id': 'copy_in', 'engine': 'mte2', 'api': 'DataCopyPad'}],
        'vfs': [{
            'vf_id': 'vf_0',
            'stages': ['load(UB→Reg)', 'compute', 'store(Reg→UB)']
        }],
        'copy_out': [{'id': 'copy_out', 'engine': 'mte3', 'api': 'DataCopyPad'}],
    }


def sequential_vf_layout(vf_count, base):
    """模式 3/4：多 VF 串行（VF 间有数据依赖）。VF 间同 V 引擎顺序执行，无显式同步。"""
    vfs = []
    for i in range(vf_count):
        vfs.append({
            'vf_id': f'vf_{i}',
            'stages': ['load(UB→Reg)', 'compute', 'store(Reg→UB)'],
        })
    return {
        'copy_in': [{'id': 'copy_in', 'engine': 'mte2'}],
        'vfs': vfs,
        'copy_out': [{'id': 'copy_out', 'engine': 'mte3'}],
        # 仅跨引擎边界需 sync: [copy_in→vf_0, vf_{N-1}→copy_out]
        'sync_count': 2,
    }


def independent_vf_layout(vf_count, base):
    """模式 5：多 VF 独立（VF 间无依赖）+ M 路 CopyIn。VF 间同 V 引擎顺序执行，顺序无约束。"""
    vfs = []
    for i in range(vf_count):
        vfs.append({
            'vf_id': f'vf_{i}',
            'stages': ['load(UB→Reg)', 'compute', 'store(Reg→UB)'],
        })
    return {
        'copy_in': [
            {'id': 'copy_in_a', 'engine': 'mte2', 'note': 'M 路并行发出，无同步'},
            {'id': 'copy_in_b', 'engine': 'mte2', 'note': 'M 路并行发出，无同步'},
        ],
        'vfs': vfs,
        'vfs_independent': True,  # data_flow 无 VF→VF 边，顺序无约束
        'copy_out': [{'id': 'copy_out', 'engine': 'mte3'}],
    }
```

## Stage 列表推导

```python
def derive_stage_list(vf_count, has_dependency):
    """根据 VF 数和依赖关系推导编排。"""
    if vf_count == 1:
        return 'pattern_1_or_2', single_vf_layout(None)
    elif has_dependency:
        return f'pattern_3_or_4 (N={vf_count})', sequential_vf_layout(vf_count, None)
    else:
        return f'pattern_5 (N={vf_count})', independent_vf_layout(vf_count, None)
```

## 输出

```yaml
vf_layout:
  copy_in: [...]      # 外层 mte2 搬运（不计入 VF 数）
  vfs:                # __VEC_SCOPE__ 块列表
    - vf_id: vf_0
      stages: [load(UB→Reg), compute, store(Reg→UB)]
    - vf_id: vf_1
      stages: [load(UB→Reg), compute, store(Reg→UB)]
      # 同 V 引擎顺序执行，无显式同步
  copy_out: [...]     # 外层 mte3 搬运（不计入 VF 数）
  # sync_points 仅跨引擎边界（TQue EnQue/DeQue）: [copy_in→vf_0, vf_1→copy_out]
```

## 异常处理

- vf_count > 4 → 模式 4 推广，标记为需要人工确认
- 与基础范式 layout 冲突 → 优先 user-corrected 标注
