"""
AI-2 输出校验层

校验 data_ops 的格式完整性，不校验游戏语义（后端不知道什么是怪物/规则/理智）
"""

from models import Category


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_data_ops(data_ops: dict, existing_tags: set[str]) -> None:
    """校验 data_ops。抛出 ValidationError 如果校验失败。"""

    errors = []
    ops = data_ops if isinstance(data_ops, dict) else {}

    # ── create 校验 ──
    for i, item in enumerate(ops.get("create", [])):
        prefix = f"create[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: 必须是对象")
            continue

        tag_name = item.get("tag_name", "")
        if not tag_name or not isinstance(tag_name, str):
            errors.append(f"{prefix}.tag_name: 非空字符串")

        category = item.get("category", "")
        if category not in [c.value for c in Category]:
            errors.append(f"{prefix}.category: 无效枚举值 '{category}'")

        tag_hint = item.get("tag_hint", "")
        if not tag_hint or not isinstance(tag_hint, str):
            errors.append(f"{prefix}.tag_hint: 非空字符串")

        tag_detail = item.get("tag_detail")
        if not tag_detail or not isinstance(tag_detail, dict):
            errors.append(f"{prefix}.tag_detail: 非空对象")

        # 检查批次内重复
        for j in range(i + 1, len(ops.get("create", []))):
            if ops["create"][j].get("tag_name") == tag_name:
                errors.append(f"{prefix}.tag_name: 与create[{j}].tag_name重复")

    # ── update 校验 ──
    for i, item in enumerate(ops.get("update", [])):
        prefix = f"update[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: 必须是对象")
            continue

        tag_name = item.get("tag_name", "")
        if not tag_name or not isinstance(tag_name, str):
            errors.append(f"{prefix}.tag_name: 非空字符串")

        if tag_name and tag_name not in existing_tags:
            errors.append(f"{prefix}.tag_name: '{tag_name}'不存在于标签库中")

        tag_detail = item.get("tag_detail")
        if not tag_detail or not isinstance(tag_detail, dict):
            errors.append(f"{prefix}.tag_detail: 非空对象")

    # ── drop 校验 ──
    for i, item in enumerate(ops.get("drop", [])):
        prefix = f"drop[{i}]"
        if not isinstance(item, str):
            errors.append(f"{prefix}: 必须是字符串")

    if errors:
        raise ValidationError(errors)
