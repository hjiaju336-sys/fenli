"""
硬同步: Pass 1 输出的 fetch 标签 → 确定性 SQL 查询详情 → 格式化为 AI-2 上下文
"""

from db import TagDAO, MemoryDAO


def _sj(seq, sep=", "):
    """安全join — 过滤None，所有元素转str"""
    return sep.join(str(x) for x in seq if x is not None)


def fetch_details(
    tag_dao: TagDAO,
    mem_dao: MemoryDAO,
    fetch_tags: list[str],
    fetch_memories: list[str],
) -> dict:
    """批量查询详情，返回 {tag_details: dict, memory_details: dict}"""
    tag_details = tag_dao.get_multi_tag_details(fetch_tags)
    memory_details = mem_dao.get_multi_details(fetch_memories)
    return {
        "tag_details": tag_details,
        "memory_details": memory_details,
    }


def _format_section(title: str, items: list[str]) -> str:
    """格式化一个段落"""
    if not items:
        return ""
    return f"--- {title} ---\n" + _sj((f"- {item}" for item in items), "\n")


def _safe_str(x):
    """安全转字符串"""
    if x is None: return ''
    if isinstance(x, (list, dict)): return str(x)[:200]
    return str(x)[:500]

def _fmt_tag(tag_name, detail, hint):
    """格式化单个标签——全防御，任何异常返回空字符串"""
    try:
        if not isinstance(detail, dict): return ""
        category = hint.get("category", "unknown") if isinstance(hint, dict) else "unknown"
        if category == "world":
            return f"【{tag_name}】\n  表面介绍: {detail.get('表面介绍') or ''}\n  隐藏真相: {detail.get('隐藏真相') or ''}\n  通关条件: {detail.get('通关条件') or ''}"
        elif category == "map":
            return f"【{tag_name}】({detail.get('所属副本') or ''})\n  表面描述: {detail.get('表面描述') or ''}\n  隐藏信息: {detail.get('隐藏信息') or ''}\n  连接: {_sj(detail.get('相连区域') or []) or '无'}\n  危险等级: {detail.get('危险等级',0)}/5"
        elif category == "rule":
            sr_lines = []
            for sr in (detail.get("细则列表") or detail.get("sub_rules") or []):
                if isinstance(sr, str): sr = {"名称": sr}
                if not isinstance(sr, dict): continue
                raw_t = sr.get("触发条件") or sr.get("triggers") or []
                triggers = [raw_t] if isinstance(raw_t, str) else [f"{t.get('类型','')}={t.get('值','')}" if isinstance(t,dict) else str(t) for t in raw_t]
                sr_lines.append(f"  [{sr.get('名称','?')}] 优先级={sr.get('优先级',5)}\n    条文: {sr.get('条文内容','')}\n    触发: {_sj(triggers)}\n    后果: {sr.get('触发后果','无')}")
            return f"【{tag_name}】\n" + _sj(sr_lines, "\n")
        elif category == "character":
            is_player = detail.get("是否玩家") or detail.get("is_player", False)
            label = "玩家" if is_player else (detail.get('角色类型') or 'NPC')
            lines = [f"【{tag_name}】{label} | 位于: {detail.get('当前位置') or '未知'}",
                     f"  血量: {detail.get('血量','?')} | 理智: {detail.get('理智','?')}",
                     f"  外貌: {detail.get('外貌') or ''}",
                     f"  持有物品: {_sj(detail.get('持有物品') or detail.get('items') or []) or '无'}"]
            if not is_player:
                for k in ['行为逻辑','当前意图','说话风格']:
                    v = detail.get(k, '')
                    if v: lines.append(f"  {k}: {v}")
                att = detail.get('对玩家的态度')
                if isinstance(att, dict):
                    lines.append(f"  对玩家态度: {att.get('态度描述','')} (好感{att.get('好感度','?')}/100 信任{att.get('信任度','?')}/100)")
                rels = detail.get('对其他角色的态度')
                if isinstance(rels, dict):
                    for rn, rd in rels.items():
                        lines.append(f"  对[{rn}]的态度: {rd}")
            return _sj(lines, "\n")
        elif category == "item":
            return f"【{tag_name}】{detail.get('物品类型','')}\n  描述: {detail.get('表面描述','')}\n  效果: {detail.get('效果','')}"
    except Exception:
        return f"【{tag_name}】[格式化错误]"
    return ""

def format_pass2_context(tag_details, memory_details, tag_hints):
    """将查到的详情格式化为 AI-2 的结构化上下文"""
    try:
        worlds, maps_list, rules, characters, items, memories_text = [], [], [], [], [], []
        for tn, detail in (tag_details or {}).items():
            if not isinstance(detail, dict): continue
            hint = (tag_hints or {}).get(tn, {})
            cat = hint.get("category", "unknown") if isinstance(hint, dict) else "unknown"
            formatted = _fmt_tag(tn, detail, hint)
            if not formatted: continue
            if cat == "world": worlds.append(formatted)
            elif cat == "map": maps_list.append(formatted)
            elif cat == "rule": rules.append(formatted)
            elif cat == "character": characters.append(formatted)
            elif cat == "item": items.append(formatted)
        for mid, md in (memory_details or {}).items():
            if isinstance(md, dict): memories_text.append(f"【{mid}】{md.get('content','')}")
        parts = []
        if worlds: parts.append(f"--- 当前副本 ---\n{worlds[0]}")
        if maps_list: parts.append(f"--- 地图 ---\n" + _sj(maps_list, "\n\n"))
        if rules: parts.append(f"--- 生效规则 ---\n" + _sj(rules, "\n"))
        if characters: parts.append(f"--- 角色 ---\n" + _sj(characters, "\n\n"))
        if items: parts.append(f"--- 物品 ---\n" + _sj(items, "\n\n"))
        if memories_text: parts.append(f"--- 相关记忆 ---\n" + _sj(memories_text, "\n"))
        return _sj(parts, "\n\n") or "(空)"
    except Exception as e:
        return f"--- 世界状态格式化出错: {e} ---"


def _format_extras(detail: dict) -> str:
    """格式化 extras 附加字段"""
    extras = detail.get("extras", {})
    if not extras:
        return ""
    lines = []
    for k, v in extras.items():
        if isinstance(v, (list, dict)):
            v = str(v)
        lines.append(f"  {k}: {v}")
    return "\n" + _sj(lines, "\n")
