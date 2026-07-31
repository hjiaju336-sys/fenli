"""积分系统 — 用户资料、签到、积分历史、兑换 — 从 server.py 提取"""
import time

from fastapi import APIRouter, Request
from sqlalchemy import text

from db import get_session
from middleware import _pid

router = APIRouter()


@router.get("/api/user/profile")
def user_profile(request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        user = s.execute(text(
            "SELECT player_id, username, created_at, is_admin, avatar_url "
            "FROM users WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()
        if not user:
            return {"error": "user not found"}
        pts = s.execute(text(
            "SELECT balance, total_earned, total_spent, sign_in_streak, last_sign_in_date "
            "FROM point_accounts WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()
        if not pts:
            # 自动为已有用户创建积分账户
            today = time.strftime("%Y-%m-%d")
            s.execute(text(
                "INSERT INTO point_accounts "
                "(player_id, balance, total_earned, total_spent, sign_in_streak, "
                "last_sign_in_date, created_at) "
                "VALUES (:pid, 99999, 99999, 0, 0, '', :ca)"
            ), {"pid": pid, "ca": today})
            s.commit()
            pts = s.execute(text(
                "SELECT balance, total_earned, total_spent, sign_in_streak, last_sign_in_date "
                "FROM point_accounts WHERE player_id=:pid"
            ), {"pid": pid}).fetchone()
        # 获取今日是否已签到
        today_str = time.strftime("%Y-%m-%d")
        signed_in_today = bool(pts and pts[4] == today_str)
        # 统计
        play_count = s.execute(text(
            "SELECT COUNT(*) FROM point_transactions WHERE player_id=:pid AND reason='游戏'"
        ), {"pid": pid}).fetchone()[0]
        clear_count = s.execute(text(
            "SELECT COUNT(*) FROM point_transactions WHERE player_id=:pid AND reason='通关'"
        ), {"pid": pid}).fetchone()[0]
        template_count = s.execute(text(
            "SELECT COUNT(*) FROM shared_copies WHERE uploader_id=:pid"
        ), {"pid": pid}).fetchone()[0]
        # 成就列表
        ach_rows = s.execute(text(
            "SELECT achievement_key, achievement_name, icon, scenario_name, unlocked_at "
            "FROM player_achievements WHERE player_id=:pid ORDER BY unlocked_at DESC"
        ), {"pid": pid}).fetchall()
        achievements = [{
            "key": r[0], "name": r[1], "icon": r[2],
            "scenario_name": r[3], "unlocked_at": r[4],
        } for r in ach_rows]
        return {
            "player_id": user[0], "username": user[1], "created_at": user[2],
            "is_admin": bool(user[3]), "avatar_url": user[4] or "",
            "points": pts[0] if pts else 0, "total_earned": pts[1] if pts else 0,
            "total_spent": pts[2] if pts else 0, "sign_in_streak": pts[3] if pts else 0,
            "last_sign_in_date": pts[4] if pts else "",
            "signed_in_today": signed_in_today,
            "play_count": play_count, "clear_count": clear_count,
            "template_count": template_count, "achievements": achievements,
        }
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.put("/api/user/profile")
async def update_profile(request: Request):
    pid = _pid(request)
    body = await request.json()
    avatar_url = body.get("avatar_url", None)
    s = get_session()
    try:
        if avatar_url is not None:
            s.execute(text(
                "UPDATE users SET avatar_url=:av WHERE player_id=:pid"
            ), {"av": avatar_url, "pid": pid})
            s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/user/sign-in")
def user_sign_in(request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        today = time.strftime("%Y-%m-%d")
        # 确保积分账户存在
        existing = s.execute(text(
            "SELECT 1 FROM point_accounts WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()
        if not existing:
            s.execute(text(
                "INSERT INTO point_accounts "
                "(player_id, balance, total_earned, total_spent, sign_in_streak, created_at) "
                "VALUES (:pid, 99999, 99999, 0, 0, :ca)"
            ), {"pid": pid, "ca": today})
        # 检查今日是否已签到
        row = s.execute(text(
            "SELECT last_sign_in_date, sign_in_streak FROM point_accounts WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()
        if row and row[0] == today:
            return {"error": "already signed in today", "streak": row[1]}
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        streak = row[1] if row else 0
        if row and row[0] == yesterday:
            streak += 1
        else:
            streak = 1
        bonus = min(50 + streak * 10, 100)
        s.execute(text(
            "UPDATE point_accounts SET balance=balance+:bonus, "
            "total_earned=total_earned+:bonus, "
            "sign_in_streak=:st, last_sign_in_date=:td WHERE player_id=:pid"
        ), {"bonus": bonus, "st": streak, "td": today, "pid": pid})
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        s.execute(text(
            "INSERT INTO point_transactions (player_id, amount, reason, ref_id, created_at) "
            "VALUES (:pid, :amt, :rs, :ref, :ca)"
        ), {"pid": pid, "amt": bonus, "rs": "签到", "ref": today, "ca": now})
        s.commit()
        return {"ok": True, "bonus": bonus, "streak": streak}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.get("/api/user/point-history")
def point_history(request: Request, page: int = 1, size: int = 20):
    pid = _pid(request)
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text(
            "SELECT COUNT(*) FROM point_transactions WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, amount, reason, ref_id, created_at FROM point_transactions "
            "WHERE player_id=:pid ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {"pid": pid, "lim": size, "off": offset})
        txns = [{
            "id": r[0], "amount": r[1], "reason": r[2],
            "ref_id": r[3], "created_at": r[4],
        } for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"transactions": txns, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()


@router.post("/api/points/exchange")
async def exchange_points(request: Request):
    pid = _pid(request)
    body = await request.json()
    code = (body.get("code", "") or "").strip()
    if not code:
        return {"error": "code is required"}
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT points, is_used FROM exchange_codes WHERE code=:cd"
        ), {"cd": code}).fetchone()
        if not row:
            return {"error": "invalid code"}
        if row[1]:
            return {"error": "code already used"}
        pts = row[0]
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        # 标记兑换码已使用
        s.execute(text(
            "UPDATE exchange_codes SET is_used=1, used_by=:pid, used_at=:ca WHERE code=:cd"
        ), {"pid": pid, "ca": now, "cd": code})
        # 确保积分账户存在
        acc = s.execute(text(
            "SELECT 1 FROM point_accounts WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()
        if not acc:
            s.execute(text(
                "INSERT INTO point_accounts "
                "(player_id, balance, total_earned, total_spent, sign_in_streak, created_at) "
                "VALUES (:pid, 0, 0, 0, 0, :ca)"
            ), {"pid": pid, "ca": now})
        # 充值积分
        s.execute(text(
            "UPDATE point_accounts SET balance=balance+:pts, "
            "total_earned=total_earned+:pts WHERE player_id=:pid"
        ), {"pts": pts, "pid": pid})
        # 记录流水
        s.execute(text(
            "INSERT INTO point_transactions (player_id, amount, reason, ref_id, created_at) "
            "VALUES (:pid, :amt, :rs, :ref, :ca)"
        ), {"pid": pid, "amt": pts, "rs": "兑换码", "ref": code, "ca": now})
        s.commit()
        return {"ok": True, "points": pts}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()
