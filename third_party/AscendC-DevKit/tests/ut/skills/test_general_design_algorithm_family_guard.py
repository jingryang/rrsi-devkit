"""概设排序模式库「排序算法族」知识契约守护（§3 UT）。

实证：排序/去重类算子的设计若只继承"比较排序 + 归并"单一心智模型，会把值域分桶
迭代（LSD radix）与 presence bitmap 排除在选项空间外，押注晦涩硬件排序原语并最终
在精度闭环失败（设备黑盒崩溃）。本守护防止算法族知识被删回单一路径；
「算法族选型正确性」由 heavy_llm ST（真实设计/编码/精度闭环）覆盖。
"""

from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parents[3] / ".claude" / "skills"
_PATTERN = _SKILLS / "ascendc-op-general-design" / "references" / "patterns" / "atomic" / "H01_select-sort.md"


@pytest.fixture(scope="module")
def sort_pattern():
    assert _PATTERN.exists(), f"模式文件缺失：{_PATTERN}"
    return _PATTERN.read_text(encoding="utf-8")


@pytest.mark.parametrize("needle", [
    "### 3.5 排序算法族选型",                # 算法族选型节存在
    "LSD 值域分桶迭代",                       # radix 范式
    "presence bitmap",                        # bitmap 范式
    "值域分桶视角",                           # 双视角（非单一"选择维需归并"）
    "需完整有序输出时走值域分桶迭代或 presence bitmap",  # 核心修正落点
    "每趟独立可验证",                         # radix 可验证性
])
def test_pattern_has_algorithm_family(sort_pattern, needle):
    assert needle in sort_pattern, f"排序模式库缺算法族/修正内容：{needle!r}"
