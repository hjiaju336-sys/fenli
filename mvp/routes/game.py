"""游戏核心API — 预设、存档、回滚、调试 — 从 server.py 提取"""
import os
import json
import glob
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import get_session, TagDAO, MemoryDAO, SaveDAO
from middleware import _pid, HOT_INIT, HOOK_SESSION

router = APIRouter()


def _build_save_data(session, pid, recent_messages=None):
    td = TagDAO(session, pid)
    md = MemoryDAO(session, pid)
    data = {"tags": {}, "memories": [], "recent_messages": recent_messages or []}
    for cat in ["world", "map", "rule", "character", "item"]:
        hints = td.hints_by_category().get(cat, [])
        data["tags"][cat] = []
        for h in hints:
            detail = td.get_detail(cat, h["tag_name"])
            data["tags"][cat].append({
                "tag_name": h["tag_name"],
                "tag_hint": h["tag_hint"],
                "tag_detail": detail,
            })
    for m in md.all_hints():
        detail = md.multi_detail([m["memory_id"]]).get(m["memory_id"])
        data["memories"].append({
            "memory_id": m["memory_id"],
            "memory_hint": m["memory_hint"],
            "memory_detail": detail,
        })
    return data


# ── 预设 API ──
@router.get("/api/presets")
def list_presets():
    presets = []
    for f in sorted(glob.glob("presets/*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
                presets.append({
                    "name": data["name"],
                    "rank": data["rank"],
                    "desc": data["desc"],
                    "filename": os.path.basename(f),
                })
        except Exception as e:
            print(f"[Preset] Skip {f}: {e}")
    return {"presets": presets}


@router.post("/api/presets/{filename}/load")
def load_preset(filename: str, request: Request):
    pid = _pid(request)
    if not pid:
        return {"error": "请先登录"}
    path = os.path.join("presets", filename)
    if not os.path.exists(path):
        return {"error": "not found"}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    s = get_session()
    try:
        td = TagDAO(s, pid)
        md = MemoryDAO(s, pid)
        # 清空当前数据
        for t in [
            "world_library", "world_detail_library",
            "map_library", "map_detail_library",
            "rule_library", "rule_detail_library",
            "character_library", "character_detail_library",
            "item_library", "item_detail_library",
        ]:
            s.execute(text(f"DELETE FROM {t} WHERE player_id=:pid"), {"pid": pid})
        # 写入预设
        for tag in data["tags"]:
            td.create(tag["category"], tag["tag_name"], tag["tag_hint"], tag["tag_detail"])
        s.commit()
        # DB 操作成功后才更新 HOT_INIT 缓存（避免状态不一致）
        wb = data.get("world_book") or []
        preset_hooks = data.get("hooks") or []
        HOT_INIT[pid] = (
            [t["tag_name"] for t in td.all_hints()],
            [m["memory_id"] for m in md.all_hints()],
            wb,
            preset_hooks,
        )
        # 重置hook会话（切换副本）
        HOOK_SESSION.pop(pid, None)
        return {"ok": True, "name": data["name"]}
    except Exception as e:
        s.rollback()
        return {"error": f"加载失败: {str(e)[:100]}"}
    finally:
        s.close()


# ── 存档 API ──
@router.get("/api/saves")
def list_saves(request: Request):
    pid = _pid(request)
    s = get_session()
    result = SaveDAO(s, pid).list()
    s.close()
    return {"saves": result}


@router.get("/api/saves/{sid}")
def get_save(sid: int, request: Request):
    pid = _pid(request)
    s = get_session()
    data = SaveDAO(s, pid).get(sid)
    s.close()
    if not data:
        return {"error": "not found"}
    return {"save": data}


@router.post("/api/saves")
async def create_save(request: Request):
    body = await request.json()
    body_size = len(json.dumps(body).encode("utf-8"))
    if body_size > 500 * 1024:  # 500KB
        return {"error": "数据过大，请精简内容"}
    pid = _pid(request)
    s = get_session()
    dao = SaveDAO(s, pid)
    build = _build_save_data(s, pid, body.get("recent_messages"))
    dao.save(
        body.get("slot_name", "存档"),
        body.get("turn_number", 0),
        build,
        body.get("is_auto", False),
    )
    if dao.count() > 10:
        dao.auto_clean(10)
    s.commit()
    s.close()
    return {"ok": True, "count": dao.count()}


@router.delete("/api/saves/{sid}")
def delete_save(sid: int, request: Request):
    pid = _pid(request)
    s = get_session()
    SaveDAO(s, pid).delete(sid)
    s.commit()
    s.close()
    return {"ok": True}


@router.post("/api/saves/upload")
async def upload_save(request: Request):
    body = await request.json()
    pid = _pid(request)
    s = get_session()
    dao = SaveDAO(s, pid)
    save_data = body.get("save_data")
    if not save_data:
        return {"error": "no save_data"}
    dao.save(body.get("slot_name", "导入存档"), body.get("turn_number", 0), save_data, False)
    s.commit()
    s.close()
    return {"ok": True}


# ── 回滚 API ──
@router.post("/api/rollback/{turn_number}")
def rollback_to_turn(turn_number: int, request: Request):
    """回滚到指定turn，删除该turn之后的所有存档和标签变更"""
    pid = _pid(request)
    s = get_session()
    save = s.execute(text(
        "SELECT save_data FROM save_slots WHERE player_id=:pid AND turn_number<=:tn "
        "ORDER BY turn_number DESC LIMIT 1"
    ), {"pid": pid, "tn": turn_number}).fetchone()
    if not save:
        s.close()
        return {"error": "no save found for rollback"}
    # 清空当前标签和记忆
    for t in [
        "world_library", "world_detail_library",
        "map_library", "map_detail_library",
        "rule_library", "rule_detail_library",
        "character_library", "character_detail_library",
        "item_library", "item_detail_library",
        "memory_library", "memory_detail_library",
    ]:
        s.execute(text(f"DELETE FROM {t} WHERE player_id=:pid"), {"pid": pid})
    # 恢复存档数据
    data = json.loads(save[0])
    td = TagDAO(s, pid)
    for cat, tags in data.get("tags", {}).items():
        for tag in tags:
            td.create(cat, tag["tag_name"], tag["tag_hint"], tag["tag_detail"])
    s.commit()
    s.close()
    HOT_INIT.pop(pid, None)
    HOOK_SESSION.pop(pid, None)
    return {"ok": True, "turn": turn_number}


# ── 调试端点 ──
@router.get("/debug/state")
def debug_state(request: Request):
    pid = _pid(request)
    s = get_session()
    td = TagDAO(s, pid)
    md = MemoryDAO(s, pid)
    counts = td.count_by_category()
    mems = md.all_hints()
    pd = {}
    for c in td.hints_by_category().get("character", []):
        d = td.get_detail("character", c["tag_name"])
        if d and isinstance(d, dict) and (d.get("是否玩家") or d.get("is_player")):
            pd = d
            break
    hints = td.hints_by_category()
    result = {
        "player": pd,
        "counts": counts,
        "tags_by_category": {cat: [h["tag_name"] for h in hints.get(cat, [])] for cat in hints},
        "memory_count": len(mems),
    }
    s.close()
    return result


@router.get("/debug/turn-logs")
def debug_turn_logs():
    files = sorted(glob.glob("logs/turn_*.json"), reverse=True)[:10]
    logs = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
                logs.append({
                    "turn_id": d.get("turn_id"),
                    "input": d.get("user_input", "")[:60],
                    "pass1_tokens": d.get("pass1", {}).get("input_tokens", 0),
                    "latency_ms": int(
                        d.get("pass1", {}).get("latency_ms", 0) +
                        d.get("pass2", {}).get("latency_ms", 0)
                    ),
                })
        except Exception as e:
            print(f"[TurnLog] Skip {f}: {e}")
    return {"recent_turns": logs}


@router.get("/debug/last-turn")
def debug_last_turn():
    files = sorted(glob.glob("logs/turn_*.json"))
    if not files:
        return {"error": "no logs yet"}
    try:
        with open(files[-1], encoding="utf-8") as fh:
            data = json.load(fh)
        return {"turn": data}
    except Exception as e:
        return {"error": f"读取日志失败: {str(e)[:100]}"}


@router.get("/debug/turn/{turn_id}")
def debug_turn_by_id(turn_id: int):
    filename = f"logs/turn_{turn_id:04d}.json"
    if not os.path.exists(filename):
        return JSONResponse(status_code=404, content={"error": "turn not found"})
    try:
        with open(filename, encoding="utf-8") as fh:
            data = json.load(fh)
        return {"turn": data}
    except Exception as e:
        return {"error": f"读取日志失败: {str(e)[:100]}"}
