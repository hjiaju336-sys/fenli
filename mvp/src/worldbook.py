"""
世界书 (World Book) — 关键词触发→动态注入 Prompt

参考 SillyTavern World Info 设计，适配本项目的标签式数据结构。
世界书条目与模板绑定，存储在 save_data / shared_copies 的 world_book 字段中。
"""

import re


def scan_and_inject(
    world_book: list[dict],
    user_input: str,
    recent_context: list[dict] = None,
    max_tokens: int = 800,
) -> str:
    """
    扫描最近上下文和用户输入，匹配世界书条目的关键词，返回注入文本。

    Args:
        world_book: 世界书条目列表，每条格式:
            {
              "id": "wb1",
              "keys": ["关键词1", "关键词2"],      # 触发关键词（必需）
              "content": "注入的提示词内容",          # 注入文本（必需）
              "priority": 100,                      # 优先级，越大越靠后（更靠近底部，AI关注度更高）
              "enabled": true,                      # 是否启用
              "constant": false,                    # true=常驻（蓝灯），不检查关键词
              "secondary_keys": ["次要关键词"],       # 可选：AND逻辑的次要关键词
              "logic": "AND_ANY"                    # AND_ANY | AND_ALL | NOT_ANY，默认AND_ANY
            }
        user_input: 当前用户输入
        recent_context: 最近对话上下文 [{"role":"user/assistant","content":"..."}]
        max_tokens: 注入内容的最大token数（粗略估计，1 token ≈ 2字符）

    Returns:
        格式化的世界书注入文本，无匹配时返回空字符串
    """
    if not world_book:
        return ""

    # 构建扫描文本：用户输入 + 最近N轮上下文
    scan_text = user_input or ""
    if recent_context:
        ctx_parts = []
        for msg in recent_context[-6:]:  # 只扫描最近3轮
            ctx_parts.append(msg.get("content", "")[:500])
        scan_text += "\n" + "\n".join(ctx_parts)

    # 收集匹配条目
    matched = []
    for entry in world_book:
        if not entry.get("enabled", True):
            continue

        # 常驻条目（蓝灯）——始终注入
        if entry.get("constant"):
            matched.append(entry)
            continue

        # 关键词匹配
        keys = entry.get("keys") or []
        if not keys:
            continue  # 无关键词且非常驻 = 永不触发

        if _match_entry(entry, scan_text):
            matched.append(entry)

    if not matched:
        return ""

    # 按 priority 排序（priority 大的靠后）
    matched.sort(key=lambda e: e.get("priority", 100))

    # 组装注入文本，控制总长度
    parts = []
    total_chars = 0
    char_limit = max_tokens * 2  # 粗略：1 token ≈ 2字符

    for entry in matched:
        content = entry.get("content") or ""
        if not content:
            continue
        # 截断过长的条目
        if len(content) > 400:
            content = content[:400] + "..."
        entry_text = f"[世界设定] {content}"
        if total_chars + len(entry_text) > char_limit:
            break
        parts.append(entry_text)
        total_chars += len(entry_text)

    if not parts:
        return ""

    return "## 额外世界设定\n" + "\n".join(parts) + "\n"


def _match_entry(entry: dict, scan_text: str) -> bool:
    """检查条目的关键词是否匹配扫描文本"""
    keys = entry.get("keys") or []
    secondary = entry.get("secondary_keys") or []
    logic = entry.get("logic", "AND_ANY")

    # 检查主要关键词
    primary_matched = False
    for key in keys:
        key = str(key).strip()
        if not key:
            continue
        # 支持正则表达式：以 / 开头和结尾
        if key.startswith("/") and key.endswith("/"):
            try:
                pat = key[1:-1]
                if re.search(pat, scan_text, re.IGNORECASE):
                    primary_matched = True
                    break
            except re.error:
                pass
        else:
            if key.lower() in scan_text.lower():
                primary_matched = True
                break

    if not primary_matched:
        return False

    # 无次要关键词 → 直接通过
    if not secondary:
        return True

    # 检查次要关键词
    sec_matched_count = 0
    sec_total = 0
    for sk in secondary:
        sk = str(sk).strip()
        if not sk:
            continue
        sec_total += 1
        if sk.lower() in scan_text.lower():
            sec_matched_count += 1

    if logic == "AND_ALL":
        return sec_total > 0 and sec_matched_count >= sec_total
    elif logic == "NOT_ANY":
        return sec_matched_count == 0
    else:  # AND_ANY（默认）
        return sec_total == 0 or sec_matched_count > 0
