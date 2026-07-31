"""
MVP 服务器 — FastAPI + WebSocket + MySQL
启动: docker-compose up -d mysql && python server.py
"""

import sys, os, pathlib
sys.path.insert(0, "src")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ws_handler import ws_handler
from ddl.migrations import _ensure_user_table, _ensure_phase3_tables, _ensure_hook_tables
from routes.auth import router as auth_router
from routes.game import router as game_router
from routes.copies import router as copies_router
from routes.community import router as community_router
from routes.admin import router as admin_router
from routes.points import router as points_router
from routes.upload import router as upload_router

app = FastAPI(title="Infinite Flow MVP")

# 注册 HTTP 路由
app.include_router(auth_router)
app.include_router(game_router)
app.include_router(copies_router)
app.include_router(community_router)
app.include_router(admin_router)
app.include_router(points_router)
app.include_router(upload_router)

# 注册 WebSocket
app.websocket("/ws")(ws_handler)


# ── 静态文件预加载 ──
_STATIC_DIR = pathlib.Path(__file__).parent / "static"
_STATIC_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
_MOBILE_HTML = (_STATIC_DIR / "m.html").read_text(encoding="utf-8") \
    if (_STATIC_DIR / "m.html").exists() else _STATIC_HTML


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    ua = request.headers.get("user-agent", "").lower()
    is_mobile = any(t in ua for t in ["mobile", "android", "iphone", "ipad", "webos"])
    html = _MOBILE_HTML if is_mobile else _STATIC_HTML
    return HTMLResponse(html, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache", "Expires": "0",
    })


@app.get("/m.html", response_class=HTMLResponse)
async def mobile():
    return HTMLResponse(_MOBILE_HTML, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache", "Expires": "0",
    })


# ── 静态文件 ──
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    from db import init_db

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8777"))
    print(f"\n=== Infinite Flow MVP (MySQL) ===\n    http://{host}:{port}\n")
    init_db()
    _ensure_user_table()
    _ensure_phase3_tables()
    _ensure_hook_tables()
    os.makedirs("logs", exist_ok=True)
    os.makedirs("static/uploads", exist_ok=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
