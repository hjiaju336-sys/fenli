"""WebSocket handler — 从 server.py 提取拆分"""
import os
import json
import asyncio
import time

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import text

from db import get_session, TagDAO, MemoryDAO
from auth import verify_token
from orchestrator import process_turn_async as process_turn, TurnError
from hook_engine import check_hooks, extract_ending_type, extract_achievements
from logger import print_turn_summary
from summary import run_summary
from middleware import HOT_INIT, HOOK_SESSION, _WS_CONNECTIONS, check_rate_limit


# ═══════════════════════════════════════════════════════════
#  helper functions
# ═══════════════════════════════════════════════════════════

def _ensure_hook_session(pid):
    """确保hook会话状态已初始化"""
    if pid not in HOOK_SESSION:
        HOOK_SESSION[pid] = {"triggered_ids": set(), "pending": [], "turn_count": 0}


def _favor_from_attitude(attitude: str) -> int:
    """将态度字符串映射为数值好感度"""
    if not attitude:
        return 50
    a = attitude.strip().lower()
    if a in ("敌对", "hostile", "仇视"):
        return 5
    elif a in ("冷淡", "cold", "疏远"):
        return 20
    elif a in ("中立", "neutral"):
        return 50
    elif a in ("友好", "friendly", "善意"):
        return 75
    elif a in ("亲密", "close", "信赖"):
        return 90
    return 50


def _build_turn_context(pid, narrative, fetch_tags, hot_tags, hot_memories,
                        session_obj, data_ops, ai_triggers=None):
    """构建hook检查所需的turn_context"""
    _ensure_hook_session(pid)
    hs = HOOK_SESSION[pid]
    hs["turn_count"] += 1

    td = TagDAO(session_obj, pid)
    player_detail = {}
    for c in td.hints_by_category().get("character", []):
        d = td.get_detail("character", c["tag_name"])
        if d and isinstance(d, dict) and (d.get("是否玩家") or d.get("is_player")):
            player_detail = d
            break

    player_hp = 100
    player_sanity = 80
    try:
        player_hp = int(player_detail.get("血量", 100))
    except (ValueError, TypeError):
        pass
    try:
        player_sanity = int(player_detail.get("理智", 80))
    except (ValueError, TypeError):
        pass

    items = player_detail.get("持有物品", [])
    if isinstance(items, str):
        items = [items]

    visited_maps = []
    for t in hot_tags:
        for cat_hint in td.hints_by_category().get("map", []):
            if cat_hint["tag_name"] == t:
                visited_maps.append(t)
                break

    npc_favs = {}
    for c in td.hints_by_category().get("character", []):
        d = td.get_detail("character", c["tag_name"])
        if d and isinstance(d, dict) and not (d.get("是否玩家") or d.get("is_player")):
            fav_raw = d.get("好感度")
            if fav_raw is not None:
                try:
                    npc_favs[c["tag_name"]] = int(fav_raw)
                except (ValueError, TypeError):
                    npc_favs[c["tag_name"]] = _favor_from_attitude(
                        d.get("态度", d.get("对玩家的态度", "")))
            else:
                npc_favs[c["tag_name"]] = _favor_from_attitude(
                    d.get("态度", d.get("对玩家的态度", "")))

    triggered_rules = []
    broken_rules = []
    if isinstance(data_ops, dict):
        for op_type in ("create", "update"):
            for item in data_ops.get(op_type, []):
                if isinstance(item, dict) and item.get("category") == "rule":
                    detail = item.get("tag_detail", {})
                    if isinstance(detail, dict):
                        disc = detail.get("发现程度", "")
                        if disc == "已触发":
                            triggered_rules.append(item.get("tag_name", ""))
                        elif disc == "已违反":
                            broken_rules.append(item.get("tag_name", ""))

    return {
        "ai_reply": narrative or "",
        "new_tags": fetch_tags or [],
        "player_hp": player_hp,
        "player_sanity": player_sanity,
        "turns": hs["turn_count"],
        "items": items,
        "tags": hot_tags or [],
        "mem_count": len(hot_memories) if hot_memories else 0,
        "npc_favs": npc_favs,
        "visited_maps": visited_maps,
        "triggered_rules": triggered_rules,
        "broken_rules": broken_rules,
        "ai_triggers": ai_triggers or [],
    }


def _process_delayed_effects(pid):
    """处理延迟效果：递减remaining_turns，返回到期的效果列表"""
    _ensure_hook_session(pid)
    hs = HOOK_SESSION[pid]
    ready_effects = []
    still_pending = []
    for entry in hs["pending"]:
        entry["remaining_turns"] -= 1
        if entry["remaining_turns"] <= 0:
            for eff in entry.get("effects", []):
                eff["_delayed_ready"] = True
                ready_effects.append(eff)
        else:
            still_pending.append(entry)
    hs["pending"] = still_pending
    return ready_effects


def get_initial_state(pid="u001"):
    if pid not in HOT_INIT:
        s = get_session()
        tags = TagDAO(s, pid).all_hints()
        mems = MemoryDAO(s, pid).all_hints()
        HOT_INIT[pid] = ([t["tag_name"] for t in tags],
                         [m["memory_id"] for m in mems], [], [])
        s.close()
    wb = HOT_INIT[pid][2] if len(HOT_INIT[pid]) > 2 else []
    hooks = HOT_INIT[pid][3] if len(HOT_INIT[pid]) > 3 else []
    return HOT_INIT[pid][0][:], HOT_INIT[pid][1][:], wb, hooks


async def _do_summary(api_key, ctx, last_mid, session, pid="u001"):
    try:
        mems = await run_summary(api_key, ctx, last_mid)
        md = MemoryDAO(session, pid)
        for m in mems:
            md.create(m["memory_id"], m["memory_hint"], m["memory_detail"])
        session.commit()
        print(f"[Summary] Created {len(mems)} memories")
    except Exception as e:
        print(f"[Summary] Failed: {e}")


# ═══════════════════════════════════════════════════════════
#  WebSocket handler 拆分函数
# ═══════════════════════════════════════════════════════════

async def ws_authenticate(ws: WebSocket, token: str):
    """鉴权+封禁检查+连接数限制。返回 (pid, session) 或 (None, None)"""
    data = verify_token(token) if token else None
    pid = data["pid"] if data else None

    if not pid:
        await ws.send_json({"type": "error", "message": "请先登录"})
        await ws.close()
        return None, None

    # 检查封禁状态
    s = get_session()
    banned_row = s.execute(text(
        "SELECT is_banned FROM users WHERE player_id=:pid"), {"pid": pid}).fetchone()
    if banned_row and banned_row[0]:
        await ws.send_json({"type": "error", "message": "账号已被封禁"})
        await ws.close()
        s.close()
        return None, None

    # 检查并发连接数
    client_ip = ws.client.host
    ip_connections = [c for c in _WS_CONNECTIONS.get(client_ip, [])
                      if not c.client_state.DISCONNECTED]
    if len(ip_connections) >= 5:
        await ws.send_json({"type": "error", "message": "连接数过多，请稍后再试"})
        await ws.close()
        s.close()
        return None, None

    # 注册连接
    if client_ip not in _WS_CONNECTIONS:
        _WS_CONNECTIONS[client_ip] = []
    _WS_CONNECTIONS[client_ip].append(ws)

    return pid, s


async def ws_init_state(ws: WebSocket, pid: str, session):
    """构建初始状态，发送 init_state 消息。返回 (ctx, hot_tags, hot_memories, world_book, hooks)"""
    # 新用户自动初始化血月医院预设
    td_init = TagDAO(session, pid)
    if len(td_init.all_hints()) == 0:
        preset_path = os.path.join("presets", "血月医院.json")
        if os.path.exists(preset_path):
            with open(preset_path, encoding="utf-8") as f:
                preset = json.load(f)
            for tag in preset["tags"]:
                td_init.create(tag["category"], tag["tag_name"],
                               tag["tag_hint"], tag["tag_detail"])
            session.commit()

    hot_tags, hot_memories, world_book, hooks = get_initial_state(pid)
    ctx = []

    # Find player and world intro
    pd = {}
    world_intro = ""
    world_name = ""
    world_desc = ""
    for c in TagDAO(session, pid).hints_by_category().get("character", []):
        d = TagDAO(session, pid).get_detail("character", c["tag_name"])
        if d and isinstance(d, dict) and (d.get("是否玩家") or d.get("is_player")):
            pd = d
            break
    worlds = TagDAO(session, pid).hints_by_category().get("world", [])
    opening_monologue = ""
    if worlds:
        wn = worlds[0]["tag_name"]
        wd = TagDAO(session, pid).get_detail("world", wn)
        if wd and isinstance(wd, dict):
            world_intro = wd.get("表面介绍") or wd.get("surface_intro", "")
            world_name = wn
            world_desc = (wd.get("通关条件") or wd.get("clear_condition", ""))[:30]
            opening_monologue = wd.get("开场白") or wd.get("opening_monologue", "")

    # 构建分类标签数据
    all_tags_cat = {}
    hints_by_cat = TagDAO(session, pid).hints_by_category()
    for cat, hints in hints_by_cat.items():
        all_tags_cat[cat] = []
        for h in hints:
            detail = TagDAO(session, pid).get_detail(cat, h["tag_name"])
            all_tags_cat[cat].append({
                "tag_name": h["tag_name"], "tag_hint": h["tag_hint"],
                "tag_detail": detail or {},
            })

    await ws.send_json({
        "type": "init_state", "hotTags": hot_tags, "hotMemories": hot_memories,
        "player_detail": pd, "world_intro": world_intro,
        "world_name": world_name, "world_desc": world_desc,
        "opening_monologue": opening_monologue,
        "all_tags_by_category": all_tags_cat,
        "world_book": world_book, "hooks": hooks,
    })

    # 将开场白加入ctx
    if opening_monologue:
        ctx.append({"role": "assistant", "content": opening_monologue})

    return ctx, hot_tags, hot_memories, world_book, hooks


async def ws_process_turn(ws, pid, session, d, ctx, hot_tags, hot_memories, world_book, hooks):
    """处理单个回合：参数提取、AI处理、流式输出、状态更新。
    返回 (ctx, hot_tags, hot_memories) 或 None"""
    ak1 = d.get("apiKey1", "")
    ak2 = d.get("apiKey2", "")
    ui = d.get("userInput", "")
    model_small = d.get("modelSmall", "")
    model_large = d.get("modelLarge", "")
    n_value = int(d.get("nValue", 5) or 5)
    my_wb = d.get("myWorldBook", [])

    if not ak1 or not ui:
        await ws.send_json({"type": "error", "message": "API Key or input missing"})
        return None
    if not ak2:
        ak2 = ak1
    if not model_large:
        model_large = model_small

    # 对话速率限制
    if not check_rate_limit(f"turn:{pid}", 6, 60):
        await ws.send_json({
            "type": "error",
            "message": "请稍后再试（每分钟最多6轮对话）",
        })
        return None

    # 积分检查
    pts_row = session.execute(text(
        "SELECT balance FROM point_accounts WHERE player_id=:pid"
    ), {"pid": pid}).fetchone()
    if pts_row and pts_row[0] < 5:
        await ws.send_json({
            "type": "error",
            "message": "积分不足（需要5积分/轮）。请签到或兑换积分。当前余额: " + str(pts_row[0]),
        })
        return None

    try:
        # 合并玩家自管世界书与模板世界书
        merged_wb = list(world_book) if world_book else []
        if my_wb:
            existing_ids = {e.get("id") for e in merged_wb if e.get("id")}
            for entry in my_wb:
                eid = entry.get("id")
                if eid and eid in existing_ids:
                    for i, e in enumerate(merged_wb):
                        if e.get("id") == eid:
                            merged_wb[i] = entry
                            break
                else:
                    merged_wb.append(entry)

        td = TagDAO(session, pid)
        md = MemoryDAO(session, pid)

        # 消费上一轮的inject队列
        _ensure_hook_session(pid)
        hs = HOOK_SESSION[pid]
        inj_texts = hs.get("inject_queue", [])
        if inj_texts:
            hs["inject_queue"] = []

        log = await process_turn(
            api_key_small=ak1, api_key_large=ak2,
            user_input=ui, tag_dao=td, mem_dao=md,
            hot_tag_names=hot_tags, hot_memory_ids=hot_memories,
            recent_context=ctx,
            model_small=model_small, model_large=model_large,
            world_book=merged_wb, hooks=hooks, inject_texts=inj_texts,
        )

        narrative = log["pass2"]["narrative"]
        for i in range(0, len(narrative), 10):
            await ws.send_json({
                "type": "narrative_chunk",
                "text": narrative[i:i + 10],
            })
            await asyncio.sleep(0.03)

        session.commit()
        sync = log["final_state"]["sync"]
        hot_tags_new = [t for t in (sync["keepTags"] + sync["addTags"])
                        if t not in set(sync["dropTags"])]
        hot_memories_new = [m for m in (sync["keepMemories"] + sync["addMemories"])
                            if m not in set(sync["dropMemories"])]
        ctx.append({"role": "user", "content": ui})
        ctx.append({"role": "assistant", "content": narrative})
        ctx_new = ctx[-(n_value * 2):]

        # Hook检查 + 效果发送 + 积分扣减
        await ws_check_hooks_and_send(
            ws, pid, session, log, hooks, ctx_new, n_value, ak1,
            hot_tags_new, hot_memories_new,
        )

        return ctx_new, hot_tags_new, hot_memories_new
    except TurnError as te:
        await ws.send_json({"type": "error", "message": str(te)[:1200]})
        return None
    except Exception as e:
        import traceback as _tb
        _tblines = _tb.format_exc().split("\n")[-5:]
        _detail = str(e)[:200] + " | " + " <- ".join(
            [l.strip() for l in _tblines if l.strip()])
        print(f"[WS ERROR] {_detail}")
        await ws.send_json({
            "type": "error",
            "message": "AI调用失败: " + _detail[:500],
        })
        return None


async def ws_check_hooks_and_send(ws, pid, session, log, hooks, ctx, n_value, ak1,
                                  hot_tags, hot_memories):
    """Hook检查 + 效果发送 + 成就/结局 + turn_complete + 积分扣减"""
    _pass1_output = (log.get("pass1") or {}).get("output") or {}
    fetch_tags = _pass1_output.get("fetchTags", [])
    if not isinstance(fetch_tags, list):
        fetch_tags = []
    _ops = log.get("pass2", {}).get("data_ops", {})
    if not isinstance(_ops, dict):
        _ops = {}
    ai_triggers = log.get("pass2", {}).get("ai_triggers", [])
    narrative = log["pass2"]["narrative"]

    turn_ctx = _build_turn_context(
        pid, narrative, fetch_tags, hot_tags, hot_memories,
        session, _ops, ai_triggers,
    )

    # 处理延迟效果
    delayed_effects = _process_delayed_effects(pid)
    if delayed_effects:
        print(f"[Hook] {len(delayed_effects)} delayed effects now active for player {pid}")

    # 检查当前轮hooks
    _ensure_hook_session(pid)
    hs = HOOK_SESSION[pid]
    triggered_effects = check_hooks(hooks, turn_ctx, hs["triggered_ids"])

    # 合并延迟效果
    all_hook_effects = delayed_effects + triggered_effects

    # 记录触发hook_id
    for eff in triggered_effects:
        hid = eff.get("_hook_id", "")
        if hid:
            hs["triggered_ids"].add(hid)
            print(f"[Hook] Triggered: {hid} (type={eff.get('type', '')})")

    # 分离即时效果和延迟效果
    immediate_effects = []
    for eff in all_hook_effects:
        hook_id = eff.get("_hook_id", "")
        if eff.get("_delayed_ready"):
            del eff["_delayed_ready"]
            immediate_effects.append(eff)
            continue
        delay = 0
        for hook in hooks:
            if hook.get("id") == hook_id:
                delay = hook.get("delay_turns", 0)
                break
        if delay > 0:
            existing_pending = [
                pe for pe in hs["pending"]
                if pe.get("hook_id") == hook_id
            ]
            if not existing_pending:
                hs["pending"].append({
                    "hook_id": hook_id,
                    "effects": [eff],
                    "remaining_turns": delay,
                })
        else:
            immediate_effects.append(eff)

    # 分离inject效果
    inject_texts = []
    frontend_effects = []
    for eff in immediate_effects:
        if eff.get("type") == "inject":
            txt = (eff.get("params") or {}).get("text", "")
            if txt:
                inject_texts.append(txt)
        else:
            frontend_effects.append(eff)

    if inject_texts:
        if "inject_queue" not in hs:
            hs["inject_queue"] = []
        hs["inject_queue"].extend(inject_texts)

    # 发送hook_effects
    if frontend_effects:
        clean_effects = []
        _internal_keys = {"type", "params", "_priority", "_hook_id", "_delayed_ready"}
        for eff in frontend_effects:
            ce = {
                "type": eff.get("type", ""),
                "params": eff.get("params", {}),
            }
            for k in list(eff.keys()):
                if k not in _internal_keys:
                    ce[k] = eff[k]
            clean_effects.append(ce)
        await ws.send_json({
            "type": "hook_effects",
            "effects": clean_effects,
        })

    # 处理成就
    achievements_list = extract_achievements(immediate_effects)
    for ach in achievements_list:
        try:
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            session.execute(text(
                "INSERT IGNORE INTO player_achievements "
                "(player_id, achievement_key, achievement_name, icon, "
                "scenario_name, unlocked_at) "
                "VALUES (:pid, :ak, :an, :ic, :sn, :ua)"
            ), {
                "pid": pid, "ak": ach["achievement_key"],
                "an": ach["achievement_name"],
                "ic": ach["icon"], "sn": ach["scenario_name"],
                "ua": now_str,
            })
            session.commit()
        except Exception as e:
            print(f"[Achievement] Write failed: {e}")

    # 检查ending
    hook_ending = extract_ending_type(immediate_effects)

    # 获取更新后的玩家详情
    s2 = get_session()
    pd = {}
    for c in TagDAO(s2, pid).hints_by_category().get("character", []):
        d = TagDAO(s2, pid).get_detail("character", c["tag_name"])
        if d and isinstance(d, dict) and (d.get("是否玩家") or d.get("is_player")):
            pd = d
            break
    s2.close()

    p = log.get("persistence", {}) or {}
    ending_type = hook_ending if hook_ending else (
        _ops.get("ending_type", "none") if _ops else "none"
    )

    # 构建分类标签数据
    all_tags_cat = {}
    hints_by_cat = TagDAO(session, pid).hints_by_category()
    for cat, hints in hints_by_cat.items():
        all_tags_cat[cat] = []
        for h in hints:
            detail = TagDAO(session, pid).get_detail(cat, h["tag_name"])
            all_tags_cat[cat].append({
                "tag_name": h["tag_name"], "tag_hint": h["tag_hint"],
                "tag_detail": detail or {},
            })

    raw_pass2 = log["pass2"].get("raw_output", "")
    await ws.send_json({
        "type": "turn_complete", "hotTags": hot_tags,
        "hotMemories": hot_memories,
        "pass1_tokens": log["pass1"].get("input_tokens", 0) +
                        log["pass1"].get("output_tokens", 0),
        "pass2_tokens": log["pass2"].get("input_tokens", 0) +
                        log["pass2"].get("output_tokens", 0),
        "latency_ms": int(log["pass1"].get("latency_ms", 0) +
                          log["pass2"].get("latency_ms", 0)),
        "player_detail": pd,
        "created": p.get("created", 0),
        "updated": p.get("updated", 0),
        "dropped": p.get("dropped", 0),
        "ending_type": ending_type,
        "all_tags_by_category": all_tags_cat,
        "raw_output_pass2": raw_pass2[:500] if raw_pass2 else "",
    })

    print_turn_summary(log)

    # 积分消耗
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        session.execute(text(
            "UPDATE point_accounts SET balance=GREATEST(balance-5,0), "
            "total_spent=total_spent+5 WHERE player_id=:pid"
        ), {"pid": pid})
        session.execute(text(
            "INSERT INTO point_transactions "
            "(player_id, amount, reason, ref_id, created_at) "
            "VALUES (:pid, -5, '游戏', :ref, :ca)"
        ), {"pid": pid, "ref": f"turn_{int(time.time())}", "ca": now})
        session.commit()
    except Exception as e:
        print(f"[Points] Deduction failed: {e}")

    # 后台总结
    if len(ctx) >= n_value * 2 and len(ctx) % (n_value * 2) == 0:
        last_mid = hot_memories[-1] if hot_memories else "r0"
        asyncio.create_task(
            _do_summary(ak1, ctx, last_mid, session, pid))


# ═══════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════

async def ws_handler(ws: WebSocket):
    """WebSocket 主入口"""
    token = ws.query_params.get("token", "")
    await ws.accept()

    pid, session = await ws_authenticate(ws, token)
    if pid is None:
        return

    ctx, hot_tags, hot_memories, world_book, hooks = await ws_init_state(ws, pid, session)

    try:
        while True:
            d = await ws.receive_json()
            if d.get("type") == "cancel":
                await ws.send_json({"type": "cancelled"})
                continue
            if d.get("type") != "user_turn":
                continue

            result = await ws_process_turn(
                ws, pid, session, d, ctx, hot_tags, hot_memories, world_book, hooks,
            )
            if result:
                ctx, hot_tags, hot_memories = result
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        session.close()
