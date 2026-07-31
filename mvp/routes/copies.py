"""云端副本API — 从 server.py 提取"""
import json

from fastapi import APIRouter, Request
from sqlalchemy import text

from db import get_session, CloudDAO, TagDAO
from middleware import _pid, HOT_INIT, HOOK_SESSION

router = APIRouter()


@router.get("/api/copies")
def list_copies():
    s = get_session()
    result = CloudDAO(s).list_all()
    s.close()
    return {"copies": result}


@router.get("/api/copies/{cid}")
def get_copy(cid: int):
    s = get_session()
    dao = CloudDAO(s)
    data = dao.get(cid)
    dao.download_count(cid)
    s.commit()
    s.close()
    if not data:
        return {"error": "not found"}
    return data


@router.post("/api/copies/upload")
async def upload_copy(request: Request):
    body = await request.json()
    body_size = len(json.dumps(body).encode("utf-8"))
    if body_size > 500 * 1024:  # 500KB
        return {"error": "数据过大，请精简内容"}
    pid = _pid(request)
    s = get_session()
    CloudDAO(s).upload(
        pid,
        body.get("title", ""),
        body.get("desc", ""),
        body.get("tags", ""),
        body.get("save_data", {}),
    )
    s.commit()
    s.close()
    return {"ok": True}


@router.post("/api/copies/{cid}/load")
async def load_copy(cid: int, request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        dao = CloudDAO(s)
        data = dao.get(cid)
        if not data:
            return {"error": "not found"}
        # 清空+写入用户数据
        td = TagDAO(s, pid)
        for t in [
            "world_library", "world_detail_library",
            "map_library", "map_detail_library",
            "rule_library", "rule_detail_library",
            "character_library", "character_detail_library",
            "item_library", "item_detail_library",
        ]:
            s.execute(text(f"DELETE FROM {t} WHERE player_id=:pid"), {"pid": pid})
        for tag in data.get("tags", []):
            td.create(
                tag.get("category", "character"),
                tag["tag_name"],
                tag.get("tag_hint", ""),
                tag.get("tag_detail", {}),
            )
        s.commit()
        # DB 操作成功后才更新 HOT_INIT 缓存（避免状态不一致）
        wb = data.get("world_book") or []
        preset_hooks = data.get("hooks") or []
        HOT_INIT[pid] = ([t["tag_name"] for t in td.all_hints()], [], wb, preset_hooks)
        # 重置hook会话（切换副本）
        HOOK_SESSION.pop(pid, None)
        return {"ok": True}
    except Exception as e:
        s.rollback()
        return {"error": f"加载失败: {str(e)[:100]}"}
    finally:
        s.close()


@router.delete("/api/copies/{cid}")
def delete_copy(cid: int, request: Request):
    pid = _pid(request)
    s = get_session()
    CloudDAO(s).delete(cid, pid)
    s.commit()
    s.close()
    return {"ok": True}
