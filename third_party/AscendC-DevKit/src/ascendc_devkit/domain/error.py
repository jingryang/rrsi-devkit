"""L4 Domain — agent error-type classification (single source).

``error_type`` 是 AgentResult 携带的领域值（infra / infra_transient / None=logic）。
本模块是「error_type 值分类」的单一来源（KNOWN 清零 step-4）：纯字符串分类、无
SDK 依赖，dispatcher(L2) 与各 L3 stage 都该经 L4 读它，而非 import L5
capabilities（L2→L5 违矩阵）。capabilities/agent/_shared re-export 本模块保持
L5 内部消费方兼容。

§1.1 层矩阵：L2/L3/L5 → L4 均合法；本模块不 import 任何上层。
"""

INFRA_ERROR_TYPES = ("infra", "infra_transient")


def is_infra_error_type(error_type: str | None) -> bool:
    """``error_type`` 是否属 infra 类（永久 ``infra`` 或瞬时 ``infra_transient``）。

    供下游（requirement/design/codegen/dispatcher 的 last_error 传播与 halt 诊断）
    判定「这是 infra 而非 logic」——二者都非 logic、都该走 infra 语义。与
    ``is_infra_failure``（面向 AgentResult，还看 aborted）互补：这个只看 error_type
    值本身，供持有 ``ErrorFeedback`` 等无 aborted 字段的消费方用。
    """
    return error_type in INFRA_ERROR_TYPES
