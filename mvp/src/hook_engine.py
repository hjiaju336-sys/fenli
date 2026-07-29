"""
Hook 触发器检查引擎 — 检测hook条件并返回触发的效果列表
"""


def _match_keyword(text: str, words: list[str]) -> bool:
    """检查文本中是否包含任一关键词"""
    if not text or not words:
        return False
    text_lower = text.lower()
    for w in words:
        kw = w.strip().lower()
        if not kw:
            continue  # 跳过空白关键词，避免空字符串匹配一切
        if kw in text_lower:
            return True
    return False


def _check_state_condition(condition: dict, turn_context: dict) -> bool:
    """检查单个状态条件是否满足"""
    field = condition.get("field", "")
    op = condition.get("op", "")
    value = condition.get("value")

    if field == "hp":
        if op == "lte":
            return turn_context.get("player_hp", 100) <= value
        elif op == "gte":
            return turn_context.get("player_hp", 100) >= value
        elif op == "eq":
            return turn_context.get("player_hp", 100) == value

    elif field == "sanity":
        if op == "lte":
            return turn_context.get("player_sanity", 100) <= value
        elif op == "gte":
            return turn_context.get("player_sanity", 100) >= value
        elif op == "eq":
            return turn_context.get("player_sanity", 100) == value

    elif field == "turns":
        if op == "gte":
            return turn_context.get("turns", 0) >= value

    elif field == "has_item":
        return value in turn_context.get("items", [])

    elif field == "has_tag":
        return value in turn_context.get("tags", [])

    elif field == "mem_count":
        if op == "gte":
            return turn_context.get("mem_count", 0) >= value

    elif field == "npc_fav":
        # value is npc_name; threshold extracted from op (gte/lte)
        npc_favs = turn_context.get("npc_favs", {})
        fav_val = npc_favs.get(value, 0)
        threshold = condition.get("threshold", 0)
        if op == "gte":
            return fav_val >= threshold
        elif op == "lte":
            return fav_val <= threshold

    elif field == "visited_map":
        return value in turn_context.get("visited_maps", [])

    elif field == "rule_triggered":
        return value in turn_context.get("triggered_rules", [])

    elif field == "rule_broken":
        return value in turn_context.get("broken_rules", [])

    return False


def _has_ach_effect(effects: list[dict]) -> bool:
    """检查效果列表中是否包含成就类效果（ach_*）"""
    if not isinstance(effects, list):
        return False
    return any(
        isinstance(eff, dict) and eff.get("type", "").startswith("ach_")
        for eff in effects
    )


def check_hooks(hooks: list[dict], turn_context: dict, triggered_ids: set) -> list[dict]:
    """
    检查所有hook，返回本轮触发的效果列表（按priority降序排列）。

    turn_context = {
        "ai_reply": str,           # 本轮AI回复文本
        "new_tags": list[str],     # 本轮新发现的标签名
        "player_hp": int,
        "player_sanity": int,
        "turns": int,
        "items": list[str],        # 玩家持有物品名列表
        "tags": list[str],         # 当前所有标签名列表
        "mem_count": int,
        "npc_favs": dict,          # {npc_name: fav_value, ...}
        "visited_maps": list[str],
        "triggered_rules": list[str],
        "broken_rules": list[str],
        "ai_triggers": list[str],  # AI 在 ---HOOKS--- 中输出的触发标识列表
    }

    Returns:
        list[dict]: 触发的效果列表（已展开所有hook的所有effects），按priority降序排列
    """
    all_effects = []

    if not hooks:
        return all_effects

    for hook in hooks:
        if not isinstance(hook, dict):
            continue

        hook_id = hook.get("id", "")
        trigger = hook.get("trigger", {})
        if not isinstance(trigger, dict) or not trigger:
            continue

        # once 检查：once 默认 false（可重复触发）
        # 成就类效果（ach_*）内部强制 once: true
        effects_list = hook.get("effects", [])
        is_once = hook.get("once", False) or _has_ach_effect(effects_list)
        if is_once and hook_id and hook_id in triggered_ids:
            continue

        triggered = False

        if trigger.get("type") == "ai_trigger":
            # AI 主动标识：检查 hook.id（或 trigger.id）是否在 ai_triggers 列表中
            trigger_id = trigger.get("id") or hook_id
            ai_triggers = turn_context.get("ai_triggers", [])
            if isinstance(ai_triggers, list) and trigger_id in ai_triggers:
                triggered = True

        elif trigger.get("type") == "keyword":
            source = trigger.get("source", "both")
            words = trigger.get("words", [])
            if not words:
                continue
            ai_reply = turn_context.get("ai_reply", "")
            new_tags = turn_context.get("new_tags", [])
            new_tags_text = " ".join(new_tags) if new_tags else ""

            if source == "ai_reply":
                triggered = _match_keyword(ai_reply, words)
            elif source == "new_tags":
                triggered = _match_keyword(new_tags_text, words)
            else:  # both
                triggered = _match_keyword(ai_reply, words) or _match_keyword(new_tags_text, words)

        elif trigger.get("type") == "state":
            conditions = trigger.get("conditions", [])
            logic = trigger.get("logic", "and")
            if not conditions:
                continue

            results = [_check_state_condition(cond, turn_context) for cond in conditions]

            if logic == "and":
                triggered = all(results)
            else:  # or
                triggered = any(results)

        if triggered:
            priority = hook.get("priority", 0)
            if isinstance(effects_list, list):
                for eff in effects_list:
                    if isinstance(eff, dict):
                        eff_copy = dict(eff)
                        eff_copy["_priority"] = priority
                        eff_copy["_hook_id"] = hook_id
                        all_effects.append(eff_copy)

    # 按priority降序排列
    all_effects.sort(key=lambda e: e.get("_priority", 0), reverse=True)

    return all_effects


def extract_ending_type(effects: list[dict]) -> str:
    """从效果列表中提取结局类型（ending_card效果）"""
    for eff in effects:
        if eff.get("type") == "ending_card":
            return eff.get("params", {}).get("title", "ending")
    return ""


def extract_achievements(effects: list[dict]) -> list[dict]:
    """从效果列表中提取成就（ach_*效果）"""
    achievements = []
    for eff in effects:
        etype = eff.get("type", "")
        if etype.startswith("ach_"):
            achievements.append({
                "achievement_key": eff.get("_hook_id", ""),
                "achievement_name": eff.get("params", {}).get("name", ""),
                "icon": eff.get("params", {}).get("icon", ""),
                "scenario_name": eff.get("params", {}).get("scenario_name", ""),
            })
    return achievements
