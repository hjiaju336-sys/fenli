"""鉴权 + 限频 + 全局共享状态 — 从 server.py 提取"""
import os
import hashlib as _hl

from fastapi import Request, HTTPException
from sqlalchemy import text

from auth import verify_token
from db import get_session, check_rate_limit  # noqa: F401  (re-export for other modules)

# ── 全局共享状态 ────────────────────────────────────────
HOT_INIT = {}
HOOK_SESSION = {}  # pid -> {triggered_ids: set, pending: [...], turn_count: int}
_WS_CONNECTIONS = {}  # client_ip -> list of WebSocket connections

# ── 兑换码密钥 ──────────────────────────────────────────
XCHG_SECRET = os.environ.get("XCHG_SECRET", "fenli_xchg_secret").encode()


def _pid(request: Request) -> str:
    """从请求中提取 player_id，同时检查封禁状态"""
    # Check Authorization header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        data = verify_token(auth[7:])
        if data:
            s = get_session()
            row = s.execute(text(
                "SELECT is_banned FROM users WHERE player_id=:pid"
            ), {"pid": data["pid"]}).fetchone()
            s.close()
            if row and row[0]:
                raise HTTPException(status_code=403, detail="账号已被封禁")
            return data["pid"]
    # Also check X-Token header for compatibility
    xtoken = request.headers.get("X-Token", "")
    if xtoken:
        data = verify_token(xtoken)
        if data:
            s = get_session()
            row = s.execute(text(
                "SELECT is_banned FROM users WHERE player_id=:pid"
            ), {"pid": data["pid"]}).fetchone()
            s.close()
            if row and row[0]:
                raise HTTPException(status_code=403, detail="账号已被封禁")
            return data["pid"]
    raise HTTPException(status_code=401, detail="Invalid or missing authentication token")


def _admin_pid(request: Request):
    """验证管理员身份，返回 (player_id, None) 或 (None, error_dict)"""
    pid = _pid(request)
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT is_admin FROM users WHERE player_id=:pid"
        ), {"pid": pid}).fetchone()
        if not row or not row[0]:
            return None, {"error": "需要管理员权限"}
        return pid, None
    finally:
        s.close()
