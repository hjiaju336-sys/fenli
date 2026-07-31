"""健康检查端点"""
from fastapi import APIRouter
import time
import os
from db import get_session
from sqlalchemy import text

router = APIRouter()
_START_TIME = time.time()


@router.get("/api/health")
def health():
    db_ok = True
    try:
        s = get_session()
        s.execute(text("SELECT 1"))
        s.close()
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "version": "v0.8.0",
        "uptime": int(time.time() - _START_TIME),
        "db": "ok" if db_ok else "error"
    }
