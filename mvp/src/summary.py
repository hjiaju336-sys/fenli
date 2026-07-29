"""
后台总结 AI — 每 N 轮压缩上下文为记忆，异步不阻塞
"""

from ai_provider import AIProvider, create_provider, get_default_model

SUMMARY_PROMPT = """你是无限流规则怪谈游戏的记忆压缩员。将最近对话压缩为高密度记忆条目。

输入：最近N轮对话

输出格式（严格JSON，无其他文本）：
{
  "memories": [
    {
      "memory_id": "r{编号}",
      "memory_hint": "关键信息摘要（10-20字）",
      "memory_detail": {"内容": "简明记忆（50-150字）。格式：[事件]→[结果]。只记录事实，不抒情。"}
    }
  ]
}

压缩规则：
1. 只记录新信息：新地点发现/新角色登场/规则触发及后果/关键物品获取/状态重大变化
2. 不重复已有记忆的内容（检查记忆索引中的hint，避免重复记录同一事件）
3. 编号从最新记忆顺延
4. 每轮对话产出1-3条记忆即可，宁少勿滥
5. 保留人名/地名/物品名等专有名词，方便后续关键词匹配召回"""


async def run_summary(api_key: str, recent_rounds: list[dict], last_memory_id: str = "r0") -> list[dict]:
    """执行总结，返回新记忆列表 [{memory_id, memory_hint, memory_detail}]"""
    if not recent_rounds or len(recent_rounds) < 2:
        return []

    provider = create_provider(api_key)
    model = get_default_model(api_key, "small")

    # 格式化对话上下文
    ctx_lines = []
    for msg in recent_rounds[-20:]:  # 最多20条
        role = "玩家" if msg["role"] == "user" else "剧情"
        ctx_lines.append(f"{role}: {msg['content'][:300]}")
    ctx_text = "\n---\n".join(ctx_lines)

    last_num = int(last_memory_id[1:]) if last_memory_id.startswith("r") else 0
    prompt = f"最近对话：\n{ctx_text}\n\n当前最新记忆编号：r{last_num}，新记忆从r{last_num+1}开始。\n请输出JSON。"

    try:
        result = await provider.chat(model=model, system=SUMMARY_PROMPT,
                                     messages=[{"role": "user", "content": prompt}],
                                     max_tokens=2048, temperature=0.5)
        import json
        text = result.text.strip()
        if text.startswith("```"): text = text.split("\n", 1)[1].rstrip("```")
        data = json.loads(text)
        memories = data.get("memories", [])
        await provider.close()
        return memories
    except Exception as e:
        print(f"[Summary] Error: {e}")
        await provider.close()
        return []
