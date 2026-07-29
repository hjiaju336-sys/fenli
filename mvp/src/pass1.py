"""
Pass 1: AI-1 标签召回

输入: 用户输入 + 上下文 + 全部标签hint + 全部记忆hint + 当前热区
输出: keepTags / fetchTags / dropTags / keepMemories / fetchMemories / dropMemories
"""

import json
from ai_provider import AIProvider, resolve_model

PASS1_SYSTEM_PROMPT = """你是记忆检索员。根据玩家输入，从标签库中精准召回相关标签和记忆。

## 输出（纯JSON）
{"keepTags":[],"fetchTags":[],"dropTags":[],"keepMemories":[],"fetchMemories":[],"dropMemories":[]}

## 规则
- keepTags: 当前场景仍需使用的标签
- fetchTags: 需加载详情的标签（首次出现或状态可能变化）
- dropTags: 仅放入已死亡/离开/销毁的实体
- keepMemories: 与当前剧情直接相关的记忆ID（记忆可能很多，只选最相关的3-8条）
- fetchMemories: 玩家行动触发回忆→匹配记忆hint中的关键词
- 当前副本、玩家位置地图、身上物品、附近角色必须keep或fetch"""


def _format_tags_compact(tags: list[dict]) -> str:
    """紧凑格式：一条标签一行，省 token"""
    lines = []
    for tag in tags:
        lines.append(f"[{tag['category']}] {tag['tag_name']} | {tag['tag_hint']}")
    return "\n".join(str(x) for x in lines if x is not None)


def _format_memories_compact(memories: list[dict]) -> str:
    lines = []
    for m in memories:
        lines.append(f"[memory] {m['memory_id']} | {m['memory_hint']}")
    return "\n".join(str(x) for x in lines if x is not None)


def build_pass1_prompt(
    user_input: str,
    hot_tag_names: list[str],
    all_tags: list[dict],
    all_memories: list[dict],
    recent_context: list[dict] = None,
) -> str:
    """构造 AI-1 的完整 prompt"""
    parts = []

    # 玩家输入
    parts.append(f"--- 玩家输入 ---\n{user_input}")

    # 近期上下文（最近N轮）
    if recent_context:
        ctx_lines = []
        for msg in recent_context[-4:]:  # 最近2轮
            role = "玩家" if msg["role"] == "user" else "剧情"
            ctx_lines.append(f"{role}: {msg['content'][:150]}")
        parts.append(f"--- 近期上下文 ---\n" + "\n".join(str(x) for x in ctx_lines if x is not None))

    # 当前热区
    parts.append(f"--- 当前热区标签 ---\n" + (", ".join(n for n in hot_tag_names if n is not None) if hot_tag_names else "(空)"))

    # 全部标签（紧凑格式）
    parts.append(f"--- 标签库索引 ---\n{_format_tags_compact(all_tags)}")

    # 全部记忆
    if all_memories:
        parts.append(f"--- 记忆索引 ---\n{_format_memories_compact(all_memories)}")

    parts.append("---\n请输出JSON，只输出JSON。")
    return "\n\n".join(str(x) for x in parts if x is not None)


async def run_pass1(
    provider: AIProvider,
    api_key: str,
    user_input: str,
    hot_tag_names: list[str],
    all_tags: list[dict],
    all_memories: list[dict],
    recent_context: list[dict] = None,
    model_name: str = None,
) -> dict:
    """执行 Pass 1，返回 {keepTags, fetchTags, dropTags, keepMemories, fetchMemories, dropMemories, tokens, latency}"""

    model = resolve_model(api_key, model_name, "small")
    prompt = build_pass1_prompt(user_input, hot_tag_names, all_tags, all_memories, recent_context)

    result = await provider.chat(
        model=model,
        system=PASS1_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048,
        temperature=0.3,  # 低温度，稳定输出
    )

    # 解析 JSON —— 处理 AI 可能包裹 ```json ```
    text = result.text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # v4模型返回reasoning而非JSON→返回空结果，不崩溃
        return {"keepTags": [], "fetchTags": [], "dropTags": [], "keepMemories": [], "fetchMemories": [], "dropMemories": [], "input_tokens": result.input_tokens, "output_tokens": result.output_tokens, "latency_ms": result.latency_ms, "raw_output": text[:200]}

    return {
        "keepTags": parsed.get("keepTags", []),
        "fetchTags": parsed.get("fetchTags", []),
        "dropTags": parsed.get("dropTags", []),
        "keepMemories": parsed.get("keepMemories", []),
        "fetchMemories": parsed.get("fetchMemories", []),
        "dropMemories": parsed.get("dropMemories", []),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "latency_ms": result.latency_ms,
        "raw_output": result.text,
    }
