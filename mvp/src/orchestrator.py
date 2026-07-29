"""
AI 编排器 — 关键词召回 + 硬同步 + Pass2叙事生成
"""
import time, asyncio
from db import TagDAO, MemoryDAO
from ai_provider import AIProvider, create_provider
from hard_sync import format_pass2_context
from pass2 import run_pass2
from worldbook import scan_and_inject


class TurnError(Exception):
    def __init__(self, stage, error_type, detail, log=None):
        self.stage = stage; self.error_type = error_type; self.detail = detail
        self.log = log or {}
        super().__init__(f"[{stage}] {error_type}: {detail}")


def _keyword_recall(user_input: str, all_tags: list[dict], all_memories: list[dict],
                    hot_tag_names: list[str]) -> tuple:
    """关键词匹配召回——不用AI，100%可靠"""
    keywords = set(user_input.lower().split())
    # 添加N-gram以匹配多字词
    for i in range(len(user_input) - 1):
        keywords.add(user_input[i:i+2].lower())
        if i < len(user_input) - 2:
            keywords.add(user_input[i:i+3].lower())

    fetch_tags, keep_tags, drop_tags = [], list(hot_tag_names), []
    fetch_mems, keep_mems = [], []

    for tag in all_tags:
        text = (tag.get('tag_name', '') + ' ' + tag.get('tag_hint', '')).lower()
        if any(kw in text for kw in keywords):
            if tag['tag_name'] not in hot_tag_names:
                fetch_tags.append(tag['tag_name'])
            else:
                keep_tags.append(tag['tag_name'])

    for mem in all_memories:
        text = (mem.get('memory_id', '') + ' ' + mem.get('memory_hint', '')).lower()
        if any(kw in text for kw in keywords):
            fetch_mems.append(mem['memory_id'])

    return (keep_tags[:20], fetch_tags[:15], drop_tags, keep_mems[:5], fetch_mems[:10])


async def process_turn_async(
    api_key_small, user_input, tag_dao, mem_dao,
    hot_tag_names, hot_memory_ids, recent_context=None,
    player_id="u001", max_retries=2,
    model_small=None, model_large=None,
    api_key_large=None,
    world_book=None,
    hooks=None,
    inject_texts=None,
) -> dict:
    if not api_key_large:
        api_key_large = api_key_small
    provider = create_provider(api_key_large)
    log = {
        "turn_id": int(time.time()), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "player_id": player_id, "user_input": user_input,
        "pass1": {}, "hard_sync": {}, "pass2": {},
        "persistence": {"created": 0, "updated": 0, "dropped": 0},
        "errors": [],
    }

    all_tags = tag_dao.all_hints()
    all_memories = mem_dao.all_hints()

    # Step 1: 关键词召回（不用AI）
    t0 = time.time()
    keep_tags, fetch_tags, drop_tags, keep_mems, fetch_mems = _keyword_recall(
        user_input, all_tags, all_memories, hot_tag_names)
    log["pass1"] = {
        "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
        "output": {"keepTags": keep_tags, "fetchTags": fetch_tags,
                   "dropTags": drop_tags, "keepMemories": keep_mems,
                   "fetchMemories": fetch_mems, "dropMemories": []},
        "raw_output": "keyword_recall"
    }

    # Step 2: 硬同步
    t_sync = time.time()
    fetch_by_cat = {}
    for tn in fetch_tags:
        cat = next((t["category"] for t in all_tags if t["tag_name"] == tn), "character")
        fetch_by_cat.setdefault(cat, []).append(tn)
    tag_details = {}
    for cat, tns in fetch_by_cat.items():
        tag_details.update(tag_dao.multi_detail(cat, tns))
    memory_details = mem_dao.multi_detail(fetch_mems)
    tag_hints = {t["tag_name"]: t for t in all_tags if t["tag_name"] in set(keep_tags + fetch_tags)}
    world_context = format_pass2_context(tag_details, memory_details, tag_hints)
    log["hard_sync"] = {
        "fetched_tags": fetch_tags, "fetched_memories": fetch_mems,
        "tag_details_count": len(tag_details),
        "latency_ms": (time.time() - t_sync) * 1000,
    }

    # Step 3: 世界书注入
    wb_injection = scan_and_inject(world_book or [], user_input, recent_context) if world_book else ""
    if wb_injection:
        world_context = wb_injection + "\n" + world_context

    # 注入上轮hook的inject文本
    if inject_texts:
        inject_block = "\n".join(f"【系统注入】{t}" for t in inject_texts)
        world_context = inject_block + "\n" + world_context

    # Step 4: Pass2 叙事生成
    last_error = None
    for attempt in range(max_retries):
        try:
            pass2_result = await run_pass2(
                provider, api_key_large, user_input, world_context, model_large, recent_context, hooks)
            log["pass2"] = {
                "input_tokens": pass2_result["input_tokens"],
                "output_tokens": pass2_result["output_tokens"],
                "latency_ms": pass2_result["latency_ms"],
                "narrative": pass2_result["narrative"],
                "data_ops": pass2_result["data_ops"],
                "ai_triggers": pass2_result.get("ai_triggers", []),
            }

            # 持久化 data_ops（如果有）
            data_ops = pass2_result.get("data_ops", {})
            if not isinstance(data_ops, dict):
                data_ops = {}
            for item in data_ops.get("create", []):
                tn = item.get("tag_name", "")
                cat = item.get("category", "character")
                if tn and tag_dao.exists(cat, tn):
                    tag_dao.update(cat, tn, item.get("tag_detail", {}))
                    log["persistence"]["updated"] += 1
                elif tn:
                    tag_dao.create(cat, tn, item.get("tag_hint", ""), item.get("tag_detail", {}))
                    log["persistence"]["created"] += 1

            for item in data_ops.get("update", []):
                tn = item.get("tag_name", "")
                if tn:
                    cat = next((t["category"] for t in all_tags if t["tag_name"] == tn), "character")
                    tag_dao.update(cat, tn, item.get("tag_detail", {}))
                    log["persistence"]["updated"] += 1

            log["persistence"]["dropped"] = len(data_ops.get("drop", []))
            log["final_state"] = {
                "sync": {
                    "keepTags": keep_tags, "addTags": fetch_tags,
                    "dropTags": drop_tags, "keepMemories": keep_mems,
                    "addMemories": fetch_mems, "dropMemories": [],
                }
            }

            await provider.close()
            return log

        except Exception as e:
            last_error = e
            import traceback
            log["errors"].append({"attempt": attempt + 1, "error": str(e),
                                  "traceback": traceback.format_exc()[:500]})
            if attempt < max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))

    await provider.close()
    raise TurnError("orchestrator", "MAX_RETRIES",
                    f"Retries exhausted: {last_error}", log=log)
