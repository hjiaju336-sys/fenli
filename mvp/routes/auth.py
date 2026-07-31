"""登录注册 — 从 server.py 提取"""
import time
import bcrypt
import uuid

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import text

from db import get_session, check_rate_limit
from auth import create_token

router = APIRouter()


def _hash(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _verify(pw, hash_val):
    return bcrypt.checkpw(pw.encode(), hash_val.encode())


@router.post("/api/auth/register")
def register(req: dict, request: Request):
    # 速率限制
    client_ip = request.client.host
    if not check_rate_limit(f"register_ip:{client_ip}", 3, 3600):
        return {"error": "注册过于频繁，请稍后再试"}
    if not check_rate_limit("register_global", 10, 60):
        return {"error": "系统繁忙，请稍后再试"}
    s = get_session()
    pid = f"u{uuid.uuid4().hex[:8]}"
    try:
        un = (req.get("username") or "").strip()
        pw = (req.get("password") or "").strip()
    except Exception:
        return {"error": "请提供用户名和密码"}
    if not un or not pw:
        return {"error": "请提供用户名和密码"}
    try:
        s.execute(text(
            "INSERT INTO users (player_id,username,password_hash,created_at) "
            "VALUES (:pid,:un,:pw,:ca)"
        ), {
            "pid": pid, "un": un, "pw": _hash(pw),
            "ca": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        # 注册赠送积分
        bonus_row = s.execute(text(
            "SELECT value FROM system_config WHERE key_name='register_bonus'"
        )).fetchone()
        bonus = int(bonus_row[0]) if bonus_row else 200
        s.execute(text(
            "INSERT INTO point_accounts (player_id, balance, total_earned, total_spent, "
            "sign_in_streak, created_at) VALUES (:pid, :bal, :te, 0, 0, :ca)"
        ), {"pid": pid, "bal": bonus, "te": bonus, "ca": time.strftime("%Y-%m-%d")})
        s.commit()
        return {"token": create_token(pid, un), "player_id": pid, "username": un}
    except Exception as e:
        err_msg = str(e)
        if "Duplicate" in err_msg or "UNIQUE" in err_msg.upper():
            return {"error": "用户名已存在"}
        return {"error": f"注册失败: {err_msg[:100]}"}
    finally:
        s.close()


@router.post("/api/auth/login")
def login(req: dict, request: Request):
    # 登录速率限制
    client_ip = request.client.host
    if not check_rate_limit(f"login:{client_ip}", 20, 60):
        return {"error": "登录过于频繁，请稍后再试"}
    try:
        un = (req.get("username") or "").strip()
        pw = (req.get("password") or "").strip()
    except Exception:
        return {"error": "请提供用户名和密码"}
    if not un or not pw:
        return {"error": "请提供用户名和密码"}
    s = get_session()
    row = s.execute(text(
        "SELECT player_id,username,password_hash,is_banned FROM users WHERE username=:un"
    ), {"un": un}).fetchone()
    if row and _verify(pw, row[2]):
        if row[3]:
            s.close()
            raise HTTPException(status_code=403, detail="账号已被封禁")
        return {"token": create_token(row[0], row[1]), "player_id": row[0], "username": row[1]}
    s.close()
    return {"error": "用户名或密码错误"}
