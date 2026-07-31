"""管理面板 — 用户管理、兑换码、评论审核、举报、建议、公告、系统统计、配置 — 从 server.py 提取"""
import time
import hashlib as _hl
import hmac
import base64

from fastapi import APIRouter, Request
from sqlalchemy import text

from db import get_session
from middleware import _pid, _admin_pid, XCHG_SECRET

router = APIRouter()


# ── 审核接口 ──────────────
@router.post("/api/review/template")
async def review_template(request: Request):
    return {"approved": True}


@router.post("/api/review/comment")
async def review_comment(request: Request):
    return {"approved": True}


# ── 用户管理 ──
@router.get("/api/admin/users")
def admin_users(request: Request, search: str = "", page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        offset = (page - 1) * size
        where = ""
        params = {}
        if search:
            where = " AND (u.username LIKE :s OR u.player_id LIKE :s)"
            params["s"] = f"%{search}%"
        total = s.execute(text(
            f"SELECT COUNT(*) FROM users u WHERE 1=1{where}"
        ), params).fetchone()[0]
        rows = s.execute(text(
            f"SELECT u.player_id, u.username, u.created_at, u.is_admin, u.avatar_url, "
            f"u.is_banned, COALESCE(p.balance,0) "
            f"FROM users u LEFT JOIN point_accounts p ON u.player_id=p.player_id "
            f"WHERE 1=1{where} ORDER BY u.created_at DESC LIMIT :lim OFFSET :off"
        ), {**params, "lim": size, "off": offset})
        users = [{
            "player_id": r[0], "username": r[1], "created_at": r[2],
            "is_admin": bool(r[3]), "avatar_url": r[4] or "",
            "is_banned": bool(r[5]), "points": r[6],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"users": users, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.get("/api/admin/users/{target_pid}")
def admin_user_detail(target_pid: str, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        user = s.execute(text(
            "SELECT player_id, username, created_at, is_admin, avatar_url "
            "FROM users WHERE player_id=:pid"
        ), {"pid": target_pid}).fetchone()
        if not user:
            return {"error": "用户不存在"}
        pts = s.execute(text(
            "SELECT balance, total_earned, total_spent, sign_in_streak, last_sign_in_date "
            "FROM point_accounts WHERE player_id=:pid"
        ), {"pid": target_pid}).fetchone()
        comment_cnt = s.execute(text(
            "SELECT COUNT(*) FROM template_comments WHERE player_id=:pid"
        ), {"pid": target_pid}).fetchone()[0]
        copy_cnt = s.execute(text(
            "SELECT COUNT(*) FROM shared_copies WHERE uploader_id=:pid"
        ), {"pid": target_pid}).fetchone()[0]
        return {
            "player_id": user[0], "username": user[1], "created_at": user[2],
            "is_admin": bool(user[3]), "avatar_url": user[4] or "",
            "points": {
                "balance": pts[0] if pts else 0,
                "total_earned": pts[1] if pts else 0,
                "total_spent": pts[2] if pts else 0,
                "sign_in_streak": pts[3] if pts else 0,
            },
            "comment_count": comment_cnt, "copy_count": copy_cnt,
        }
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.put("/api/admin/users/{target_pid}")
async def admin_update_user(target_pid: str, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    body = await request.json()
    s = get_session()
    try:
        if "balance" in body or "points" in body:
            val = int(body.get("balance") or body.get("points", 0))
            s.execute(text(
                "UPDATE point_accounts SET balance=:bal WHERE player_id=:pid"
            ), {"bal": val, "pid": target_pid})
        if "is_admin" in body:
            s.execute(text(
                "UPDATE users SET is_admin=:adm WHERE player_id=:pid"
            ), {"adm": 1 if body["is_admin"] else 0, "pid": target_pid})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/admin/users/{target_pid}/ban")
def admin_toggle_ban(target_pid: str, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT is_banned FROM users WHERE player_id=:pid"
        ), {"pid": target_pid}).fetchone()
        if not row:
            return {"error": "用户不存在"}
        new_val = 0 if row[0] else 1
        s.execute(text(
            "UPDATE users SET is_banned=:v WHERE player_id=:pid"
        ), {"v": new_val, "pid": target_pid})
        s.commit()
        return {"ok": True, "is_banned": bool(new_val)}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 兑换码管理 ──
@router.post("/api/admin/exchange-codes")
async def admin_gen_codes(request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    body = await request.json()
    count = int(body.get("count", 1))
    points = int(body.get("points", 100))
    batch_id = (body.get("batch_id", "") or "").strip() or f"batch_{int(time.time())}"
    if count > 1000:
        count = 1000
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        codes = []
        for i in range(count):
            code_raw = hmac.new(
                XCHG_SECRET, f"{batch_id}:{i}:{time.time()}".encode(), _hl.sha256
            ).digest()
            code_b32 = base64.b32encode(code_raw).decode().rstrip("=").upper()[:12]
            while len(code_b32) < 12:
                code_b32 += "A"
            code = f"FL-{code_b32[:4]}-{code_b32[4:8]}-{code_b32[8:12]}"
            s.execute(text(
                "INSERT INTO exchange_codes (code, points, batch_id, created_by, created_at) "
                "VALUES (:cd, :pts, :bid, :pid, :ca)"
            ), {"cd": code, "pts": points, "bid": batch_id, "pid": pid, "ca": now})
            codes.append(code)
        s.commit()
        return {"ok": True, "batch_id": batch_id, "count": count, "codes": codes}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.get("/api/admin/exchange-codes")
def admin_list_codes(request: Request, batch_id: str = "", page: int = 1, size: int = 50):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        offset = (page - 1) * size
        where = "WHERE 1=1"
        params = {}
        if batch_id:
            where += " AND batch_id=:bid"
            params["bid"] = batch_id
        total = s.execute(text(
            f"SELECT COUNT(*) FROM exchange_codes {where}"
        ), params).fetchone()[0]
        rows = s.execute(text(
            f"SELECT code, points, batch_id, created_by, used_by, is_used, used_at, created_at "
            f"FROM exchange_codes {where} ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {**params, "lim": size, "off": offset})
        items = [{
            "code": r[0], "points": r[1], "batch_id": r[2], "created_by": r[3],
            "used_by": r[4], "is_used": bool(r[5]), "used_at": r[6], "created_at": r[7],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"codes": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 评论管理 ──
@router.get("/api/admin/comments")
def admin_comments(request: Request, status: str = "all", page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        offset = (page - 1) * size
        where = "WHERE 1=1"
        params = {}
        if status == "approved":
            where += " AND is_approved=1"
        elif status == "reported":
            where += " AND id IN (SELECT comment_id FROM comment_reports WHERE is_resolved=0)"
        elif status == "pending":
            where += " AND is_approved=0"
        total = s.execute(text(
            f"SELECT COUNT(*) FROM template_comments {where}"
        ), params).fetchone()[0]
        rows = s.execute(text(
            f"SELECT id, target_type, target_id, player_id, username, content, parent_id, "
            f"likes, is_approved, created_at FROM template_comments {where} "
            f"ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {**params, "lim": size, "off": offset})
        items = [{
            "id": r[0], "target_type": r[1], "target_id": r[2], "player_id": r[3],
            "username": r[4], "content": r[5], "parent_id": r[6], "likes": r[7],
            "is_approved": bool(r[8]), "created_at": r[9],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"comments": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.delete("/api/admin/comments/{comment_id}")
def admin_delete_comment(comment_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        s.execute(text("DELETE FROM template_comments WHERE id=:id"), {"id": comment_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/admin/comments/{comment_id}/approve")
def admin_approve_comment(comment_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        s.execute(text(
            "UPDATE template_comments SET is_approved=1 WHERE id=:id"
        ), {"id": comment_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 举报管理 ──
@router.get("/api/admin/reports")
def admin_reports(request: Request, page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text("SELECT COUNT(*) FROM comment_reports")).fetchone()[0]
        rows = s.execute(text(
            "SELECT r.id, r.comment_id, r.reporter_id, r.reason, r.is_resolved, "
            "r.resolved_by, r.created_at, c.content "
            "FROM comment_reports r LEFT JOIN template_comments c ON r.comment_id=c.id "
            "ORDER BY r.created_at DESC LIMIT :lim OFFSET :off"
        ), {"lim": size, "off": offset})
        items = [{
            "id": r[0], "comment_id": r[1], "reporter_id": r[2], "reason": r[3],
            "is_resolved": bool(r[4]), "resolved_by": r[5], "created_at": r[6],
            "comment_content": r[7],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"reports": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.put("/api/admin/reports/{report_id}")
async def admin_resolve_report(report_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    body = await request.json()
    s = get_session()
    try:
        s.execute(text(
            "UPDATE comment_reports SET is_resolved=:ir, resolved_by=:rb WHERE id=:id"
        ), {
            "ir": 1 if body.get("is_resolved", True) else 0,
            "rb": body.get("resolved_by", pid),
            "id": report_id,
        })
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 模板管理 ──
@router.delete("/api/admin/templates/{target_type}/{target_id}")
def admin_delete_template(target_type: str, target_id: str, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        if target_type == "copy":
            s.execute(text(
                "DELETE FROM shared_copies WHERE id=:id"
            ), {"id": int(target_id)})
        elif target_type == "preset":
            # 预设删除文件
            pass
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 建议管理 ──
@router.get("/api/admin/suggestions")
def admin_suggestions(request: Request, page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text("SELECT COUNT(*) FROM suggestions")).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, player_id, username, category, content, status, admin_reply, created_at "
            "FROM suggestions ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {"lim": size, "off": offset})
        items = [{
            "id": r[0], "player_id": r[1], "username": r[2], "category": r[3],
            "content": r[4], "status": r[5], "admin_reply": r[6], "created_at": r[7],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"suggestions": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.put("/api/admin/suggestions/{suggestion_id}")
async def admin_update_suggestion(suggestion_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    body = await request.json()
    s = get_session()
    try:
        if "status" in body:
            s.execute(text(
                "UPDATE suggestions SET status=:st WHERE id=:id"
            ), {"st": body["status"], "id": suggestion_id})
        if "admin_reply" in body:
            s.execute(text(
                "UPDATE suggestions SET admin_reply=:rp WHERE id=:id"
            ), {"rp": body["admin_reply"], "id": suggestion_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 公告管理 ──
@router.post("/api/admin/announcements")
async def admin_create_announcement(request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    body = await request.json()
    content = (body.get("content", "") or "").strip()
    if not content:
        return {"error": "content is required"}
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        s.execute(text(
            "INSERT INTO system_announcements (content, created_by, created_at) "
            "VALUES (:ct, :pid, :ca)"
        ), {"ct": content, "pid": pid, "ca": now})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.put("/api/admin/announcements/{announcement_id}")
async def admin_update_announcement(announcement_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    body = await request.json()
    s = get_session()
    try:
        if "content" in body:
            s.execute(text(
                "UPDATE system_announcements SET content=:ct WHERE id=:id"
            ), {"ct": body["content"], "id": announcement_id})
        if "is_active" in body:
            s.execute(text(
                "UPDATE system_announcements SET is_active=:ia WHERE id=:id"
            ), {"ia": 1 if body["is_active"] else 0, "id": announcement_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.get("/api/admin/announcements")
def admin_all_announcements(request: Request, page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text(
            "SELECT COUNT(*) FROM system_announcements"
        )).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, content, created_by, is_active, created_at "
            "FROM system_announcements ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {"lim": size, "off": offset})
        items = [{
            "id": r[0], "content": r[1], "created_by": r[2],
            "is_active": bool(r[3]), "created_at": r[4],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"announcements": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 系统统计 ──
@router.get("/api/admin/stats")
def admin_stats(request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        total_users = s.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
        total_templates = s.execute(text("SELECT COUNT(*) FROM shared_copies")).fetchone()[0]
        total_comments = s.execute(text("SELECT COUNT(*) FROM template_comments")).fetchone()[0]
        total_points = s.execute(text(
            "SELECT COALESCE(SUM(amount),0) FROM point_transactions WHERE amount>0"
        )).fetchone()[0]
        total_spent = s.execute(text(
            "SELECT COALESCE(SUM(ABS(amount)),0) FROM point_transactions WHERE amount<0"
        )).fetchone()[0]
        today = time.strftime("%Y-%m-%d")
        today_active = s.execute(text(
            "SELECT COUNT(DISTINCT player_id) FROM point_transactions WHERE created_at LIKE :td"
        ), {"td": f"{today}%"}).fetchone()[0]
        thirty_days_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * 30))
        active_30d = s.execute(text(
            "SELECT COUNT(DISTINCT player_id) FROM point_transactions WHERE created_at >= :td"
        ), {"td": thirty_days_ago}).fetchone()[0]
        return {
            "total_users": total_users, "total_templates": total_templates,
            "total_comments": total_comments,
            "total_points_issued": total_points, "total_points_consumed": total_spent,
            "today_active": today_active, "active_users_30d": active_30d,
        }
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


# ── 系统配置管理 ──
@router.get("/api/admin/config")
def admin_get_config(request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    s = get_session()
    try:
        rows = s.execute(text("SELECT key_name, value FROM system_config")).fetchall()
        config = {row[0]: row[1] for row in rows}
        defaults = {
            "register_bonus": "200",
            "turn_cost": "5",
            "sign_in_max": "100",
            "rate_limit_user_per_min": "6",
            "rate_limit_ws_per_ip": "5",
            "rate_limit_register_per_hour": "3",
            "save_max_size_kb": "500",
            "ws_idle_timeout_min": "5",
        }
        for k, v in defaults.items():
            if k not in config:
                config[k] = v
                s.execute(text(
                    "INSERT INTO system_config (key_name, value, updated_at) "
                    "VALUES (:k,:v,:t) ON DUPLICATE KEY UPDATE key_name=key_name"
                ), {"k": k, "v": v, "t": time.strftime("%Y-%m-%d %H:%M:%S")})
        s.commit()
        return {"config": config}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.put("/api/admin/config")
async def admin_update_config(request: Request):
    pid, err = _admin_pid(request)
    if err:
        return err
    body = await request.json()
    s = get_session()
    try:
        for k, v in body.items():
            s.execute(text(
                "INSERT INTO system_config (key_name, value, updated_at) "
                "VALUES (:k,:v,:t) ON DUPLICATE KEY UPDATE value=:v, updated_at=:t"
            ), {"k": k, "v": str(v), "t": time.strftime("%Y-%m-%d %H:%M:%S")})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()
