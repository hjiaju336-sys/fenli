"""社区功能 — 评分、评论、建议、公告 — 从 server.py 提取"""
import time

from fastapi import APIRouter, Request
from sqlalchemy import text

from db import get_session, check_rate_limit
from middleware import _pid

router = APIRouter()


# ── 评分 API ──
@router.get("/api/ratings/{target_type}/{target_id}")
def get_ratings(target_type: str, target_id: str):
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT AVG(rating), COUNT(*) FROM template_ratings "
            "WHERE target_type=:tt AND target_id=:tid"
        ), {"tt": target_type, "tid": target_id}).fetchone()
        avg = round(float(row[0] or 0), 1)
        cnt = row[1] or 0
        dist = {}
        for r in range(1, 6):
            dist[r] = s.execute(text(
                "SELECT COUNT(*) FROM template_ratings "
                "WHERE target_type=:tt AND target_id=:tid AND rating=:r"
            ), {"tt": target_type, "tid": target_id, "r": r}).fetchone()[0]
        return {"avg_rating": avg, "count": cnt, "distribution": dist}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/ratings/{target_type}/{target_id}")
async def upsert_rating(target_type: str, target_id: str, request: Request):
    pid = _pid(request)
    body = await request.json()
    rating = body.get("rating", 0)
    if not isinstance(rating, int) or rating < 1 or rating > 5:
        return {"error": "rating must be 1-5"}
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        s.execute(text(
            "INSERT INTO template_ratings (target_type, target_id, player_id, rating, created_at) "
            "VALUES (:tt, :tid, :pid, :r, :ca) "
            "ON DUPLICATE KEY UPDATE rating=VALUES(rating), created_at=VALUES(created_at)"
        ), {"tt": target_type, "tid": target_id, "pid": pid, "r": rating, "ca": now})
        s.commit()
        # 同步 avg_rating 到 shared_copies
        if target_type == "copy":
            row = s.execute(text(
                "SELECT AVG(rating), COUNT(*) FROM template_ratings "
                "WHERE target_type='copy' AND target_id=:tid"
            ), {"tid": target_id}).fetchone()
            s.execute(text(
                "UPDATE shared_copies SET avg_rating=:ar, rating_count=:rc WHERE id=:tid"
            ), {"ar": round(float(row[0] or 0), 1), "rc": row[1] or 0, "tid": int(target_id)})
            s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 评论 API ──
@router.post("/api/comments/like/{comment_id}")
def toggle_like(comment_id: int, request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT 1 FROM comment_likes WHERE comment_id=:cid AND player_id=:pid"
        ), {"cid": comment_id, "pid": pid}).fetchone()
        if row:
            s.execute(text(
                "DELETE FROM comment_likes WHERE comment_id=:cid AND player_id=:pid"
            ), {"cid": comment_id, "pid": pid})
            s.execute(text(
                "UPDATE template_comments SET likes=GREATEST(likes-1,0) WHERE id=:cid"
            ), {"cid": comment_id})
        else:
            s.execute(text(
                "INSERT INTO comment_likes (comment_id, player_id) VALUES (:cid, :pid)"
            ), {"cid": comment_id, "pid": pid})
            s.execute(text(
                "UPDATE template_comments SET likes=likes+1 WHERE id=:cid"
            ), {"cid": comment_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/comments/report/{comment_id}")
async def report_comment(comment_id: int, request: Request):
    pid = _pid(request)
    body = await request.json()
    reason = (body.get("reason", "") or "").strip()
    if not reason:
        return {"error": "reason is required"}
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        s.execute(text(
            "INSERT INTO comment_reports (comment_id, reporter_id, reason, created_at) "
            "VALUES (:cid, :pid, :rs, :ca)"
        ), {"cid": comment_id, "pid": pid, "rs": reason, "ca": now})
        s.commit()
        return {"ok": True}
    except Exception as e:
        err_msg = str(e)
        if "Duplicate" in err_msg or "duplicate" in err_msg.lower():
            return {"error": "您已经举报过该评论"}
        return {"error": err_msg[:200]}
    finally:
        s.close()


@router.get("/api/comments/{target_type}/{target_id}")
def get_comments(
    target_type: str, target_id: str, request: Request,
    page: int = 1, size: int = 20, sort: str = "time",
):
    s = get_session()
    try:
        order = "created_at DESC" if sort == "time" else "likes DESC"
        offset = (page - 1) * size
        total = s.execute(text(
            "SELECT COUNT(*) FROM template_comments "
            "WHERE target_type=:tt AND target_id=:tid AND is_approved=1"
        ), {"tt": target_type, "tid": target_id}).fetchone()[0]
        rows = s.execute(text(
            f"SELECT id, player_id, username, content, parent_id, likes, created_at "
            f"FROM template_comments WHERE target_type=:tt AND target_id=:tid "
            f"AND is_approved=1 ORDER BY {order} LIMIT :lim OFFSET :off"
        ), {"tt": target_type, "tid": target_id, "lim": size, "off": offset})
        comments = [{
            "id": r[0], "player_id": r[1], "username": r[2], "content": r[3],
            "parent_id": r[4], "likes": r[5], "created_at": r[6],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"comments": comments, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/comments/{target_type}/{target_id}")
async def create_comment(target_type: str, target_id: str, request: Request):
    pid = _pid(request)
    if not check_rate_limit(f"comment:{pid}", 10, 3600):
        return {"error": "评论过于频繁，请稍后再试"}
    body = await request.json()
    content = (body.get("content", "") or "").strip()
    if not content:
        return {"error": "content is required"}
    parent_id = body.get("parent_id", None)
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        user_row = s.execute(text(
            "SELECT username FROM users WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()
        username = user_row[0] if user_row else "anonymous"
        s.execute(text(
            "INSERT INTO template_comments "
            "(target_type, target_id, player_id, username, content, parent_id, created_at) "
            "VALUES (:tt, :tid, :pid, :un, :ct, :pi, :ca)"
        ), {
            "tt": target_type, "tid": target_id, "pid": pid, "un": username,
            "ct": content, "pi": parent_id, "ca": now,
        })
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.delete("/api/comments/{target_type}/{target_id}/{comment_id}")
def delete_comment(target_type: str, target_id: str, comment_id: int, request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT player_id FROM template_comments WHERE id=:id"
        ), {"id": comment_id}).fetchone()
        if not row:
            return {"error": "comment not found"}
        if row[0] != pid:
            return {"error": "can only delete your own comment"}
        s.execute(text("DELETE FROM template_comments WHERE id=:id"), {"id": comment_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 建议 API ──
@router.post("/api/suggestions")
async def create_suggestion(request: Request):
    pid = _pid(request)
    if not check_rate_limit(f"suggestion:{pid}", 5, 86400):
        return {"error": "建议提交过于频繁，请明天再试"}
    body = await request.json()
    category = (body.get("category", "") or "").strip()
    content = (body.get("content", "") or "").strip()
    if not content:
        return {"error": "content is required"}
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        user_row = s.execute(text(
            "SELECT username FROM users WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()
        username = user_row[0] if user_row else "anonymous"
        s.execute(text(
            "INSERT INTO suggestions (player_id, username, category, content, created_at) "
            "VALUES (:pid, :un, :cat, :ct, :ca)"
        ), {"pid": pid, "un": username, "cat": category, "ct": content, "ca": now})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.get("/api/suggestions/my")
def my_suggestions(request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        rows = s.execute(text(
            "SELECT id, category, content, status, admin_reply, created_at FROM suggestions "
            "WHERE player_id=:pid ORDER BY created_at DESC"
        ), {"pid": pid})
        items = [{
            "id": r[0], "category": r[1], "content": r[2], "status": r[3],
            "admin_reply": r[4], "created_at": r[5],
        } for r in rows]
        return {"suggestions": items}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 公告 API ──
@router.get("/api/announcements")
def latest_announcement():
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT id, content, created_by, created_at FROM system_announcements "
            "WHERE is_active=1 ORDER BY created_at DESC LIMIT 1"
        )).fetchone()
        if not row:
            return {"announcement": None}
        return {"announcement": {
            "id": row[0], "content": row[1],
            "created_by": row[2], "created_at": row[3],
        }}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.get("/api/announcements/list")
def announcement_list(page: int = 1, size: int = 20):
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text(
            "SELECT COUNT(*) FROM system_announcements WHERE is_active=1"
        )).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, content, created_by, created_at FROM system_announcements "
            "WHERE is_active=1 ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {"lim": size, "off": offset})
        items = [{
            "id": r[0], "content": r[1], "created_by": r[2], "created_at": r[3],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"announcements": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()
