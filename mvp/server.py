"""
MVP 服务器 — FastAPI + WebSocket + MySQL
启动: docker-compose up -d mysql && python server.py
"""

import sys, os, json, asyncio, pathlib, time, hmac, base64  # asyncio required for sleep/create_task in WS handler
sys.path.insert(0, "src")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from db import init_db, get_session, TagDAO, MemoryDAO, SaveDAO, CloudDAO, _ensure_hook_tables, check_rate_limit
from sqlalchemy import text
from orchestrator import process_turn_async as process_turn, TurnError
from logger import print_turn_summary
from summary import run_summary
from hook_engine import check_hooks, extract_ending_type, extract_achievements
from pydantic import BaseModel
from auth import create_token, verify_token

app = FastAPI(title="Infinite Flow MVP")

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

# ── 用户表（简易）──
import hashlib as _hl
def _hash(pw): return _hl.sha256(pw.encode()).hexdigest()

def _ensure_user_table():
    s = get_session()
    s.execute(text("CREATE TABLE IF NOT EXISTS users (player_id VARCHAR(255) PRIMARY KEY, username VARCHAR(255) UNIQUE, password_hash VARCHAR(255), created_at VARCHAR(50))"))
    # 仅在 ADMIN_PASSWORD 环境变量存在时创建管理员
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if admin_pw:
        existing = s.execute(text("SELECT 1 FROM users WHERE username='admin'")).fetchone()
        if not existing:
            s.execute(text("INSERT INTO users (player_id,username,password_hash,created_at,is_admin) VALUES (:pid,:un,:pw,:ca,1)"),
                      {"pid":"u001","un":"admin","pw":_hash(admin_pw),"ca":"2026-01-01"})
    s.commit(); s.close()

def _ensure_phase3_tables():
    s = get_session()
    # 积分账户
    s.execute(text("""CREATE TABLE IF NOT EXISTS point_accounts (
        player_id VARCHAR(255) PRIMARY KEY,
        balance INT DEFAULT 0,
        total_earned INT DEFAULT 0,
        total_spent INT DEFAULT 0,
        sign_in_streak INT DEFAULT 0,
        last_sign_in_date VARCHAR(20),
        created_at VARCHAR(50)
    )"""))
    # 积分流水
    s.execute(text("""CREATE TABLE IF NOT EXISTS point_transactions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        player_id VARCHAR(255),
        amount INT,
        reason VARCHAR(100),
        ref_id VARCHAR(255),
        created_at VARCHAR(50)
    )"""))
    # 兑换码
    s.execute(text("""CREATE TABLE IF NOT EXISTS exchange_codes (
        code VARCHAR(64) PRIMARY KEY,
        points INT,
        batch_id VARCHAR(64),
        created_by VARCHAR(255),
        used_by VARCHAR(255) DEFAULT NULL,
        used_at VARCHAR(50) DEFAULT NULL,
        is_used TINYINT DEFAULT 0,
        created_at VARCHAR(50)
    )"""))
    # 模板评分
    s.execute(text("""CREATE TABLE IF NOT EXISTS template_ratings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        target_type VARCHAR(32),
        target_id VARCHAR(255),
        player_id VARCHAR(255),
        rating TINYINT,
        created_at VARCHAR(50),
        UNIQUE KEY uk_rate (target_type, target_id, player_id)
    )"""))
    # 模板评论
    s.execute(text("""CREATE TABLE IF NOT EXISTS template_comments (
        id INT AUTO_INCREMENT PRIMARY KEY,
        target_type VARCHAR(32),
        target_id VARCHAR(255),
        player_id VARCHAR(255),
        username VARCHAR(255),
        content TEXT,
        parent_id INT DEFAULT NULL,
        likes INT DEFAULT 0,
        is_approved TINYINT DEFAULT 1,
        created_at VARCHAR(50)
    )"""))
    # 评论点赞
    s.execute(text("""CREATE TABLE IF NOT EXISTS comment_likes (
        comment_id INT,
        player_id VARCHAR(255),
        PRIMARY KEY (comment_id, player_id)
    )"""))
    # 评论举报
    s.execute(text("""CREATE TABLE IF NOT EXISTS comment_reports (
        id INT AUTO_INCREMENT PRIMARY KEY,
        comment_id INT,
        reporter_id VARCHAR(255),
        reason VARCHAR(500),
        is_resolved TINYINT DEFAULT 0,
        resolved_by VARCHAR(255),
        created_at VARCHAR(50)
    )"""))
    # 玩家建议
    s.execute(text("""CREATE TABLE IF NOT EXISTS suggestions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        player_id VARCHAR(255),
        username VARCHAR(255),
        category VARCHAR(50),
        content TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        admin_reply TEXT,
        created_at VARCHAR(50)
    )"""))
    # 系统公告
    s.execute(text("""CREATE TABLE IF NOT EXISTS system_announcements (
        id INT AUTO_INCREMENT PRIMARY KEY,
        content TEXT,
        created_by VARCHAR(255),
        is_active TINYINT DEFAULT 1,
        created_at VARCHAR(50)
    )"""))
    # 系统配置
    s.execute(text("""CREATE TABLE IF NOT EXISTS system_config (
        key_name VARCHAR(100) PRIMARY KEY,
        value VARCHAR(500),
        updated_at VARCHAR(50)
    )"""))
    # 默认系统配置（注册赠送积分）
    existing = s.execute(text("SELECT 1 FROM system_config WHERE key_name='register_bonus'")).fetchone()
    if not existing:
        s.execute(text("INSERT INTO system_config (key_name,value,updated_at) VALUES (:k,:v,:u)"),
                  {"k":"register_bonus","v":"200","u":"2026-01-01"})
    # ALTER users 表加字段
    for col, typ in [("is_admin", "TINYINT DEFAULT 0"), ("avatar_url", "VARCHAR(500)"), ("is_banned", "TINYINT DEFAULT 0")]:
        try:
            s.execute(text(f"ALTER TABLE users ADD COLUMN {col} {typ}"))
        except Exception as e:
            print(f"[Phase3] ALTER users.{col} skipped: {e}")
    # ALTER comment_reports 加唯一约束
    try:
        s.execute(text("ALTER TABLE comment_reports ADD UNIQUE KEY uk_report (comment_id, reporter_id)"))
    except Exception as e:
        print(f"[Phase3] ALTER comment_reports.uk_report skipped: {e}")
    # 创建 shared_copies 表（如果不存在）
    s.execute(text("""CREATE TABLE IF NOT EXISTS shared_copies (
        id INT AUTO_INCREMENT PRIMARY KEY,
        uploader_id VARCHAR(255),
        title VARCHAR(255),
        description TEXT,
        tags TEXT,
        save_data TEXT,
        downloads INT DEFAULT 0,
        created_at VARCHAR(50),
        cover_image VARCHAR(500),
        opening_monologue TEXT,
        avg_rating FLOAT DEFAULT 0,
        rating_count INT DEFAULT 0,
        play_count INT DEFAULT 0
    )"""))
    # ALTER shared_copies 表加字段
    for col, typ in [("cover_image", "VARCHAR(500)"), ("opening_monologue", "TEXT"),
                      ("avg_rating", "FLOAT DEFAULT 0"), ("rating_count", "INT DEFAULT 0"), ("play_count", "INT DEFAULT 0")]:
        try:
            s.execute(text(f"ALTER TABLE shared_copies ADD COLUMN {col} {typ}"))
        except Exception as e:
            print(f"[Phase3] ALTER shared_copies.{col} skipped: {e}")
    s.commit(); s.close()

def _admin_pid(request: Request):
    """验证管理员身份，返回 (player_id, None) 或 (None, error_dict)"""
    pid = _pid(request)
    s = get_session()
    try:
        row = s.execute(text("SELECT is_admin FROM users WHERE player_id=:pid"), {"pid": pid}).fetchone()
        if not row or not row[0]:
            return None, {"error": "需要管理员权限"}
        return pid, None
    finally:
        s.close()

# ── 鉴权 API ──
@app.post("/api/auth/register")
def register(req: dict, request: Request):
    # 速率限制
    client_ip = request.client.host
    if not check_rate_limit(f"register_ip:{client_ip}", 3, 3600):
        return {"error": "注册过于频繁，请稍后再试"}
    if not check_rate_limit("register_global", 10, 60):
        return {"error": "系统繁忙，请稍后再试"}
    s = get_session()
    import uuid
    pid = f"u{uuid.uuid4().hex[:8]}"
    try:
        un = (req.get("username") or "").strip()
        pw = (req.get("password") or "").strip()
    except Exception:
        return {"error": "请提供用户名和密码"}
    if not un or not pw:
        return {"error": "请提供用户名和密码"}
    try:
        s.execute(text("INSERT INTO users (player_id,username,password_hash,created_at) VALUES (:pid,:un,:pw,:ca)"),
                  {"pid":pid,"un":un,"pw":_hash(pw),"ca":time.strftime("%Y-%m-%d %H:%M:%S")})
        # 注册赠送积分
        bonus_row = s.execute(text("SELECT value FROM system_config WHERE key_name='register_bonus'")).fetchone()
        bonus = int(bonus_row[0]) if bonus_row else 200
        s.execute(text("INSERT INTO point_accounts (player_id, balance, total_earned, total_spent, sign_in_streak, created_at) VALUES (:pid, :bal, :te, 0, 0, :ca)"),
                  {"pid":pid,"bal":bonus,"te":bonus,"ca":time.strftime("%Y-%m-%d")})
        s.commit()
        return {"token": create_token(pid, un), "player_id": pid, "username": un}
    except Exception as e:
        err_msg = str(e)
        if "Duplicate" in err_msg or "UNIQUE" in err_msg.upper():
            return {"error": "用户名已存在"}
        return {"error": f"注册失败: {err_msg[:100]}"}
    finally: s.close()

@app.post("/api/auth/login")
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
    row = s.execute(text("SELECT player_id,username,is_banned FROM users WHERE username=:un AND password_hash=:pw"),
                    {"un":un,"pw":_hash(pw)}).fetchone()
    if row:
        if row[2]:
            s.close()
            raise HTTPException(status_code=403, detail="账号已被封禁")
        return {"token": create_token(row[0], row[1]), "player_id": row[0], "username": row[1]}
    s.close()
    return {"error": "用户名或密码错误"}

_STATIC_DIR = pathlib.Path(__file__).parent / "static"
_STATIC_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
_MOBILE_HTML = (_STATIC_DIR / "m.html").read_text(encoding="utf-8") if (_STATIC_DIR / "m.html").exists() else _STATIC_HTML

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    ua = request.headers.get("user-agent", "").lower()
    is_mobile = any(t in ua for t in ["mobile", "android", "iphone", "ipad", "webos"])
    html = _MOBILE_HTML if is_mobile else _STATIC_HTML
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})

@app.get("/m.html", response_class=HTMLResponse)
async def mobile():
    return HTMLResponse(_MOBILE_HTML, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})

HOT_INIT = {}
HOOK_SESSION = {}  # pid -> {triggered_ids: set, pending: [...], turn_count: int}
_WS_CONNECTIONS = {}  # client_ip -> list of WebSocket connections

def get_initial_state(pid="u001"):
    if pid not in HOT_INIT:
        s = get_session()
        tags = TagDAO(s, pid).all_hints()
        mems = MemoryDAO(s, pid).all_hints()
        HOT_INIT[pid] = ([t["tag_name"] for t in tags], [m["memory_id"] for m in mems], [], [])
        s.close()
    wb = HOT_INIT[pid][2] if len(HOT_INIT[pid]) > 2 else []
    hooks = HOT_INIT[pid][3] if len(HOT_INIT[pid]) > 3 else []
    return HOT_INIT[pid][0][:], HOT_INIT[pid][1][:], wb, hooks

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

def _build_turn_context(pid, narrative, fetch_tags, hot_tags, hot_memories, session_obj, data_ops,
                        ai_triggers=None):
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
                    npc_favs[c["tag_name"]] = _favor_from_attitude(d.get("态度", d.get("对玩家的态度", "")))
            else:
                npc_favs[c["tag_name"]] = _favor_from_attitude(d.get("态度", d.get("对玩家的态度", "")))

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
                eff["_delayed_ready"] = True  # 标记为延迟到期效果，跳过再次延迟检查
                ready_effects.append(eff)
        else:
            still_pending.append(entry)
    hs["pending"] = still_pending
    return ready_effects

@app.websocket("/ws")
async def ws_handler(ws: WebSocket):
    # 从 query string 提取 token 鉴权
    token = ws.query_params.get("token","")
    data = verify_token(token) if token else None
    pid = data["pid"] if data else None

    await ws.accept()
    if not pid:
        await ws.send_json({"type":"error","message":"请先登录"})
        await ws.close()
        return

    # 检查封禁状态
    s_banned = get_session()
    banned_row = s_banned.execute(text("SELECT is_banned FROM users WHERE player_id=:pid"), {"pid": pid}).fetchone()
    s_banned.close()
    if banned_row and banned_row[0]:
        await ws.send_json({"type":"error","message":"账号已被封禁"})
        await ws.close()
        return

    # 检查并发连接数
    client_ip = ws.client.host
    ip_connections = [c for c in _WS_CONNECTIONS.get(client_ip, []) if not c.client_state.DISCONNECTED]
    if len(ip_connections) >= 5:
        await ws.send_json({"type":"error","message":"连接数过多，请稍后再试"})
        await ws.close()
        return
    # 注册连接
    if client_ip not in _WS_CONNECTIONS:
        _WS_CONNECTIONS[client_ip] = []
    _WS_CONNECTIONS[client_ip].append(ws)

    session = get_session()
    # 新用户自动初始化血月医院预设
    td_init = TagDAO(session, pid)
    if len(td_init.all_hints()) == 0:
        preset_path = os.path.join("presets", "血月医院.json")
        if os.path.exists(preset_path):
            with open(preset_path, encoding="utf-8") as f: preset = json.load(f)
            for tag in preset["tags"]:
                td_init.create(tag["category"], tag["tag_name"], tag["tag_hint"], tag["tag_detail"])
            session.commit()

    hot_tags, hot_memories, world_book, hooks = get_initial_state(pid)
    ctx = []

    # Find player and world intro
    pd = {}; world_intro = ""; world_name = ""; world_desc = ""
    for c in TagDAO(session, pid).hints_by_category().get("character", []):
        d = TagDAO(session, pid).get_detail("character", c["tag_name"])
        if d and isinstance(d, dict) and (d.get("是否玩家") or d.get("is_player")): pd = d; break
    worlds = TagDAO(session, pid).hints_by_category().get("world",[])
    if worlds:
        wn = worlds[0]["tag_name"]
        wd = TagDAO(session, pid).get_detail("world", wn)
        if wd and isinstance(wd, dict):
            world_intro = wd.get("表面介绍") or wd.get("surface_intro","")
            world_name = wn
            world_desc = (wd.get("通关条件") or wd.get("clear_condition",""))[:30]
            opening_monologue = wd.get("开场白") or wd.get("opening_monologue","")
    # 构建分类标签数据（供前端变量面板渲染）
    all_tags_cat = {}
    hints_by_cat = TagDAO(session, pid).hints_by_category()
    for cat, hints in hints_by_cat.items():
        all_tags_cat[cat] = []
        for h in hints:
            detail = TagDAO(session, pid).get_detail(cat, h["tag_name"])
            all_tags_cat[cat].append({"tag_name": h["tag_name"], "tag_hint": h["tag_hint"], "tag_detail": detail or {}})
    await ws.send_json({"type": "init_state", "hotTags": hot_tags, "hotMemories": hot_memories,
        "player_detail": pd, "world_intro": world_intro, "world_name": world_name, "world_desc": world_desc,
        "opening_monologue": opening_monologue, "all_tags_by_category": all_tags_cat,
        "world_book": world_book, "hooks": hooks})
    # 将开场白加入ctx，确保AI第一轮知道开场说了什么
    if opening_monologue:
        ctx.append({"role": "assistant", "content": opening_monologue})
    abort = False

    try:
        while True:
            d = await ws.receive_json()
            if d.get("type") == "cancel": abort = True; await ws.send_json({"type": "cancelled"}); continue
            if d.get("type") != "user_turn": continue
            ak1 = d.get("apiKey1",""); ak2 = d.get("apiKey2",""); ui = d.get("userInput","")
            model_small = d.get("modelSmall",""); model_large = d.get("modelLarge","")
            n_value = int(d.get("nValue",5) or 5)  # 上下文窗口轮数
            my_wb = d.get("myWorldBook", [])  # 玩家自管世界书
            if not ak1 or not ui:
                await ws.send_json({"type":"error","message":"API Key or input missing"}); continue
            if not ak2: ak2 = ak1       # 兼容单Key：Pass2 复用 Pass1
            if not model_large: model_large = model_small  # 兼容单模型

            # 对话速率限制
            if not check_rate_limit(f"turn:{pid}", 6, 60):
                await ws.send_json({"type":"error","message":"请稍后再试（每分钟最多6轮对话）"})
                continue

            # 积分检查（处理前）
            pts_row = session.execute(text("SELECT balance FROM point_accounts WHERE player_id=:pid"), {"pid": pid}).fetchone()
            if pts_row and pts_row[0] < 5:
                await ws.send_json({"type":"error","message":"积分不足（需要5积分/轮）。请签到或兑换积分。当前余额: "+str(pts_row[0])})
                continue

            abort = False
            try:
                # 合并玩家自管世界书与模板世界书（相同id以玩家版本为准）
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
                td = TagDAO(session, pid); md = MemoryDAO(session, pid)
                # 消费上一轮的inject队列，注入到本次world_context
                _ensure_hook_session(pid)
                hs = HOOK_SESSION[pid]
                inj_texts = hs.get("inject_queue", [])
                if inj_texts:
                    hs["inject_queue"] = []
                log = await process_turn(api_key_small=ak1, api_key_large=ak2,
                    user_input=ui, tag_dao=td, mem_dao=md,
                    hot_tag_names=hot_tags, hot_memory_ids=hot_memories, recent_context=ctx,
                    model_small=model_small, model_large=model_large,
                    world_book=merged_wb, hooks=hooks, inject_texts=inj_texts)
                if abort: continue

                narrative = log["pass2"]["narrative"]
                for i in range(0, len(narrative), 10):
                    if abort: break
                    await ws.send_json({"type":"narrative_chunk","text":narrative[i:i+10]})
                    await asyncio.sleep(0.03)
                if abort: continue

                session.commit()
                sync = log["final_state"]["sync"]
                hot_tags = [t for t in (sync["keepTags"]+sync["addTags"]) if t not in set(sync["dropTags"])]
                hot_memories = [m for m in (sync["keepMemories"]+sync["addMemories"]) if m not in set(sync["dropMemories"])]
                ctx.append({"role":"user","content":ui}); ctx.append({"role":"assistant","content":narrative})
                ctx = ctx[-(n_value*2):]  # n轮 = n*2条消息

                # 构建 turn_context 并检查 hooks
                _pass1_output = (log.get("pass1") or {}).get("output") or {}
                fetch_tags = _pass1_output.get("fetchTags", [])
                if not isinstance(fetch_tags, list):
                    fetch_tags = []
                _ops = log.get("pass2", {}).get("data_ops", {})
                if not isinstance(_ops, dict):
                    _ops = {}
                ai_triggers = log.get("pass2", {}).get("ai_triggers", [])
                turn_ctx = _build_turn_context(pid, narrative, fetch_tags, hot_tags, hot_memories, session, _ops, ai_triggers)

                # 处理延迟效果
                delayed_effects = _process_delayed_effects(pid)
                if delayed_effects:
                    print(f"[Hook] {len(delayed_effects)} delayed effects now active for player {pid}")

                # 检查当前轮hooks
                _ensure_hook_session(pid)
                hs = HOOK_SESSION[pid]
                triggered_effects = check_hooks(hooks, turn_ctx, hs["triggered_ids"])

                # 合并延迟效果（延迟效果排在前面，因为它们更早触发）
                all_hook_effects = delayed_effects + triggered_effects

                # 记录本轮触发的hook_id（once检查）
                for eff in triggered_effects:
                    hid = eff.get("_hook_id", "")
                    if hid:
                        hs["triggered_ids"].add(hid)
                        print(f"[Hook] Triggered: {hid} (type={eff.get('type','')})")

                # 分离即时效果和延迟效果
                immediate_effects = []
                for eff in all_hook_effects:
                    hook_id = eff.get("_hook_id", "")
                    # 延迟到期效果直接进入immediate，不再次检查delay
                    if eff.get("_delayed_ready"):
                        del eff["_delayed_ready"]  # 清理内部标记
                        immediate_effects.append(eff)
                        continue
                    # 查找原始hook的delay_turns
                    delay = 0
                    for hook in hooks:
                        if hook.get("id") == hook_id:
                            delay = hook.get("delay_turns", 0)
                            break
                    if delay > 0:
                        # 延迟执行：存入pending
                        existing_pending = [pe for pe in hs["pending"] if pe.get("hook_id") == hook_id]
                        if not existing_pending:
                            hs["pending"].append({
                                "hook_id": hook_id,
                                "effects": [eff],
                                "remaining_turns": delay,
                            })
                    else:
                        immediate_effects.append(eff)

                # 分离inject效果（后端处理，不发前端）
                inject_texts = []
                frontend_effects = []
                for eff in immediate_effects:
                    if eff.get("type") == "inject":
                        txt = (eff.get("params") or {}).get("text", "")
                        if txt:
                            inject_texts.append(txt)
                    else:
                        frontend_effects.append(eff)

                # 存储inject文本供下一轮使用
                if inject_texts:
                    if "inject_queue" not in hs:
                        hs["inject_queue"] = []
                    hs["inject_queue"].extend(inject_texts)

                # 发送hook_effects给前端（不含inject）
                if frontend_effects:
                    clean_effects = []
                    _internal_keys = {"type", "params", "_priority", "_hook_id", "_delayed_ready"}
                    for eff in frontend_effects:
                        ce = {"type": eff.get("type", ""), "params": eff.get("params", {})}
                        for k in list(eff.keys()):
                            if k not in _internal_keys:
                                ce[k] = eff[k]
                        clean_effects.append(ce)
                    await ws.send_json({"type": "hook_effects", "effects": clean_effects})

                # 处理成就
                achievements_list = extract_achievements(immediate_effects)
                for ach in achievements_list:
                    try:
                        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
                        session.execute(text(
                            "INSERT IGNORE INTO player_achievements (player_id, achievement_key, achievement_name, icon, scenario_name, unlocked_at) "
                            "VALUES (:pid, :ak, :an, :ic, :sn, :ua)"
                        ), {"pid": pid, "ak": ach["achievement_key"], "an": ach["achievement_name"],
                            "ic": ach["icon"], "sn": ach["scenario_name"], "ua": now_str})
                        session.commit()
                    except Exception as e:
                        print(f"[Achievement] Write failed: {e}")

                # 检查是否有ending效果
                hook_ending = extract_ending_type(immediate_effects)

                s2 = get_session()
                pd = {}
                for c in TagDAO(s2, pid).hints_by_category().get("character", []):
                    d = TagDAO(s2, pid).get_detail("character", c["tag_name"])
                    if d and isinstance(d, dict) and (d.get("是否玩家") or d.get("is_player")): pd = d; break
                s2.close()
                p = log.get("persistence",{}) or {}
                ending_type = hook_ending if hook_ending else (_ops.get("ending_type", "none") if _ops else "none")
                # 构建最新分类标签数据
                all_tags_cat2 = {}
                hints2 = TagDAO(session, pid).hints_by_category()
                for cat, hints in hints2.items():
                    all_tags_cat2[cat] = []
                    for h in hints:
                        detail = TagDAO(session, pid).get_detail(cat, h["tag_name"])
                        all_tags_cat2[cat].append({"tag_name": h["tag_name"], "tag_hint": h["tag_hint"], "tag_detail": detail or {}})
                raw_pass2 = log["pass2"].get("raw_output","")
                await ws.send_json({
                    "type":"turn_complete","hotTags":hot_tags,"hotMemories":hot_memories,
                    "pass1_tokens":log["pass1"].get("input_tokens",0)+log["pass1"].get("output_tokens",0),
                    "pass2_tokens":log["pass2"].get("input_tokens",0)+log["pass2"].get("output_tokens",0),
                    "latency_ms":int(log["pass1"].get("latency_ms",0)+log["pass2"].get("latency_ms",0)),
                    "player_detail":pd,"created":p.get("created",0),"updated":p.get("updated",0),"dropped":p.get("dropped",0),
                    "ending_type": ending_type,
                    "all_tags_by_category": all_tags_cat2,
                    "raw_output_pass2": raw_pass2[:500] if raw_pass2 else "",
                })
                print_turn_summary(log)
                # 积分消耗：每轮对话 -5 积分
                try:
                    now = time.strftime("%Y-%m-%d %H:%M:%S")
                    session.execute(text("UPDATE point_accounts SET balance=GREATEST(balance-5,0), total_spent=total_spent+5 WHERE player_id=:pid"), {"pid": pid})
                    session.execute(text("INSERT INTO point_transactions (player_id, amount, reason, ref_id, created_at) VALUES (:pid, -5, '游戏', :ref, :ca)"),
                                  {"pid": pid, "ref": f"turn_{int(time.time())}", "ca": now})
                    session.commit()
                except Exception as e:
                    print(f"[Points] Deduction failed: {e}")
                # 后台总结：每 N 轮触发
                if len(ctx) >= n_value*2 and len(ctx) % (n_value*2) == 0:
                    last_mid = hot_memories[-1] if hot_memories else "r0"
                    asyncio.create_task(_do_summary(ak1, ctx, last_mid, session, pid))
            except TurnError as te:
                await ws.send_json({"type":"error","message":str(te)[:1200]})
            except Exception as e:
                import traceback as _tb
                _tblines = _tb.format_exc().split("\n")[-5:]
                _detail = str(e)[:200] + " | " + " <- ".join([l.strip() for l in _tblines if l.strip()])
                print(f"[WS ERROR] {_detail}")
                await ws.send_json({"type":"error","message":"AI调用失败: "+_detail[:500]})
    except WebSocketDisconnect: pass
    except Exception: pass
    finally: session.close()

@app.get("/debug/state")
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
        if d and isinstance(d, dict) and (d.get("是否玩家") or d.get("is_player")): pd = d; break
    hints = td.hints_by_category()
    result = {
        "player": pd,
        "counts": counts,
        "tags_by_category": {cat: [h["tag_name"] for h in hints.get(cat,[])] for cat in hints},
        "memory_count": len(mems)
    }
    s.close()
    return result

# ── 存档 API ────────────────────────────────────────────

def _pid(request: Request) -> str:
    # Check Authorization header
    auth = request.headers.get("Authorization","")
    if auth.startswith("Bearer "):
        data = verify_token(auth[7:])
        if data:
            s = get_session()
            row = s.execute(text("SELECT is_banned FROM users WHERE player_id=:pid"), {"pid": data["pid"]}).fetchone()
            s.close()
            if row and row[0]:
                raise HTTPException(status_code=403, detail="账号已被封禁")
            return data["pid"]
    # Also check X-Token header for compatibility
    xtoken = request.headers.get("X-Token","")
    if xtoken:
        data = verify_token(xtoken)
        if data:
            s = get_session()
            row = s.execute(text("SELECT is_banned FROM users WHERE player_id=:pid"), {"pid": data["pid"]}).fetchone()
            s.close()
            if row and row[0]:
                raise HTTPException(status_code=403, detail="账号已被封禁")
            return data["pid"]
    raise HTTPException(status_code=401, detail="Invalid or missing authentication token")

@app.get("/api/saves")
def list_saves(request: Request):
    pid = _pid(request); s = get_session(); result = SaveDAO(s, pid).list(); s.close()
    return {"saves": result}

@app.get("/api/saves/{sid}")
def get_save(sid: int, request: Request):
    pid = _pid(request); s = get_session(); data = SaveDAO(s, pid).get(sid); s.close()
    if not data: return {"error": "not found"}
    return {"save": data}

@app.post("/api/saves")
async def create_save(request: Request):
    body = await request.json()
    body_size = len(json.dumps(body).encode('utf-8'))
    if body_size > 500 * 1024:  # 500KB
        return {"error": "数据过大，请精简内容"}
    pid = _pid(request); s = get_session(); dao = SaveDAO(s, pid)
    build = _build_save_data(s, pid, body.get("recent_messages"))
    dao.save(body.get("slot_name","存档"), body.get("turn_number",0), build, body.get("is_auto",False))
    if dao.count() > 10: dao.auto_clean(10)
    s.commit(); s.close()
    return {"ok": True, "count": dao.count()}

@app.delete("/api/saves/{sid}")
def delete_save(sid: int, request: Request):
    pid = _pid(request); s = get_session(); SaveDAO(s, pid).delete(sid); s.commit(); s.close()
    return {"ok": True}

@app.post("/api/saves/upload")
async def upload_save(request: Request):
    body = await request.json()
    pid = _pid(request); s = get_session(); dao = SaveDAO(s, pid)
    save_data = body.get("save_data")
    if not save_data: return {"error": "no save_data"}
    dao.save(body.get("slot_name","导入存档"), body.get("turn_number",0), save_data, False)
    s.commit(); s.close()
    return {"ok": True}

def _build_save_data(session, pid, recent_messages=None):
    td = TagDAO(session, pid)
    md = MemoryDAO(session, pid)
    data = {"tags": {}, "memories": [], "recent_messages": recent_messages or []}
    for cat in ["world","map","rule","character","item"]:
        hints = td.hints_by_category().get(cat, [])
        data["tags"][cat] = []
        for h in hints:
            detail = td.get_detail(cat, h["tag_name"])
            data["tags"][cat].append({"tag_name": h["tag_name"], "tag_hint": h["tag_hint"], "tag_detail": detail})
    for m in md.all_hints():
        detail = md.multi_detail([m["memory_id"]]).get(m["memory_id"])
        data["memories"].append({"memory_id": m["memory_id"], "memory_hint": m["memory_hint"], "memory_detail": detail})
    return data

# ── 回滚 API ──
@app.post("/api/rollback/{turn_number}")
def rollback_to_turn(turn_number: int, request: Request):
    """回滚到指定turn，删除该turn之后的所有存档和标签变更"""
    pid = _pid(request)
    s = get_session()
    save = s.execute(text(
        "SELECT save_data FROM save_slots WHERE player_id=:pid AND turn_number<=:tn ORDER BY turn_number DESC LIMIT 1"
    ), {"pid": pid, "tn": turn_number}).fetchone()
    if not save:
        s.close()
        return {"error": "no save found for rollback"}
    # 清空当前标签和记忆
    for t in ["world_library","world_detail_library","map_library","map_detail_library",
              "rule_library","rule_detail_library","character_library","character_detail_library",
              "item_library","item_detail_library","memory_library","memory_detail_library"]:
        s.execute(text(f"DELETE FROM {t} WHERE player_id=:pid"), {"pid": pid})
    # 恢复存档数据
    data = json.loads(save[0])
    td = TagDAO(s, pid)
    for cat, tags in data.get("tags", {}).items():
        for tag in tags:
            td.create(cat, tag["tag_name"], tag["tag_hint"], tag["tag_detail"])
    s.commit(); s.close()
    HOT_INIT.pop(pid, None)
    HOOK_SESSION.pop(pid, None)
    return {"ok": True, "turn": turn_number}

# ── 预设 API ──
@app.get("/api/presets")
def list_presets():
    import glob
    presets = []
    for f in sorted(glob.glob("presets/*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
                presets.append({"name": data["name"], "rank": data["rank"], "desc": data["desc"], "filename": os.path.basename(f)})
        except Exception as e:
            print(f"[Preset] Skip {f}: {e}")
    return {"presets": presets}

@app.post("/api/presets/{filename}/load")
def load_preset(filename: str, request: Request):
    pid = _pid(request)
    if not pid: return {"error": "请先登录"}
    path = os.path.join("presets", filename)
    if not os.path.exists(path): return {"error": "not found"}
    with open(path, encoding="utf-8") as f: data = json.load(f)
    s = get_session(); td = TagDAO(s, pid); md = MemoryDAO(s, pid)
    # 清空当前数据
    for t in ["world_library","world_detail_library","map_library","map_detail_library",
              "rule_library","rule_detail_library","character_library","character_detail_library",
              "item_library","item_detail_library"]:
        s.execute(text(f"DELETE FROM {t} WHERE player_id=:pid"), {"pid":pid})
    # 写入预设
    for tag in data["tags"]:
        td.create(tag["category"], tag["tag_name"], tag["tag_hint"], tag["tag_detail"])
    # 保存世界书和hooks到缓存
    wb = data.get("world_book") or []
    preset_hooks = data.get("hooks") or []
    HOT_INIT[pid] = ([t["tag_name"] for t in td.all_hints()], [m["memory_id"] for m in md.all_hints()], wb, preset_hooks)
    # 重置hook会话（切换副本）
    HOOK_SESSION.pop(pid, None)
    s.commit(); s.close()
    return {"ok": True, "name": data["name"]}

# ── 云端副本 API ──
@app.get("/api/copies")
def list_copies():
    s = get_session(); result = CloudDAO(s).list_all(); s.close()
    return {"copies": result}

@app.get("/api/copies/{cid}")
def get_copy(cid: int):
    s = get_session(); dao = CloudDAO(s); data = dao.get(cid); dao.download_count(cid); s.commit(); s.close()
    if not data: return {"error": "not found"}
    return data

@app.post("/api/copies/upload")
async def upload_copy(request: Request):
    body = await request.json()
    body_size = len(json.dumps(body).encode('utf-8'))
    if body_size > 500 * 1024:  # 500KB
        return {"error": "数据过大，请精简内容"}
    pid = _pid(request); s = get_session()
    CloudDAO(s).upload(pid, body.get("title",""), body.get("desc",""), body.get("tags",""), body.get("save_data",{}))
    s.commit(); s.close()
    return {"ok": True}

@app.post("/api/copies/{cid}/load")
async def load_copy(cid: int, request: Request):
    pid = _pid(request); s = get_session(); dao = CloudDAO(s); data = dao.get(cid)
    if not data: s.close(); return {"error": "not found"}
    # 清空+写入用户数据
    td = TagDAO(s, pid)
    for t in ["world_library","world_detail_library","map_library","map_detail_library",
              "rule_library","rule_detail_library","character_library","character_detail_library",
              "item_library","item_detail_library"]:
        s.execute(text(f"DELETE FROM {t} WHERE player_id=:pid"), {"pid":pid})
    for tag in data.get("tags",[]):
        td.create(tag.get("category","character"), tag["tag_name"], tag.get("tag_hint",""), tag.get("tag_detail",{}))
    wb = data.get("world_book") or []
    preset_hooks = data.get("hooks") or []
    HOT_INIT[pid] = ([t["tag_name"] for t in td.all_hints()], [], wb, preset_hooks)
    # 重置hook会话（切换副本）
    HOOK_SESSION.pop(pid, None)
    s.commit(); s.close()
    return {"ok": True}

@app.delete("/api/copies/{cid}")
def delete_copy(cid: int, request: Request):
    pid = _pid(request); s = get_session(); CloudDAO(s).delete(cid, pid); s.commit(); s.close()
    return {"ok": True}

@app.get("/debug/turn-logs")
def debug_turn_logs():
    import glob
    files = sorted(glob.glob("logs/turn_*.json"), reverse=True)[:10]
    logs = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
                logs.append({"turn_id": d.get("turn_id"), "input": d.get("user_input", "")[:60],
                             "pass1_tokens": d.get("pass1", {}).get("input_tokens", 0),
                             "latency_ms": int(d.get("pass1", {}).get("latency_ms", 0) + d.get("pass2", {}).get("latency_ms", 0))})
        except Exception as e:
            print(f"[TurnLog] Skip {f}: {e}")
    return {"recent_turns": logs}

# ── 评分 API ──────────────────────────────────────────

@app.get("/api/ratings/{target_type}/{target_id}")
def get_ratings(target_type: str, target_id: str):
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT AVG(rating), COUNT(*) FROM template_ratings WHERE target_type=:tt AND target_id=:tid"
        ), {"tt": target_type, "tid": target_id}).fetchone()
        avg = round(float(row[0] or 0), 1)
        cnt = row[1] or 0
        dist = {}
        for r in range(1, 6):
            dist[r] = s.execute(text(
                "SELECT COUNT(*) FROM template_ratings WHERE target_type=:tt AND target_id=:tid AND rating=:r"
            ), {"tt": target_type, "tid": target_id, "r": r}).fetchone()[0]
        return {"avg_rating": avg, "count": cnt, "distribution": dist}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.post("/api/ratings/{target_type}/{target_id}")
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
                "SELECT AVG(rating), COUNT(*) FROM template_ratings WHERE target_type='copy' AND target_id=:tid"
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

# ── 评论 API ──────────────────────────────────────────
@app.post("/api/comments/like/{comment_id}")
def toggle_like(comment_id: int, request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        row = s.execute(text("SELECT 1 FROM comment_likes WHERE comment_id=:cid AND player_id=:pid"),
                        {"cid": comment_id, "pid": pid}).fetchone()
        if row:
            s.execute(text("DELETE FROM comment_likes WHERE comment_id=:cid AND player_id=:pid"),
                      {"cid": comment_id, "pid": pid})
            s.execute(text("UPDATE template_comments SET likes=GREATEST(likes-1,0) WHERE id=:cid"),
                      {"cid": comment_id})
        else:
            s.execute(text("INSERT INTO comment_likes (comment_id, player_id) VALUES (:cid, :pid)"),
                      {"cid": comment_id, "pid": pid})
            s.execute(text("UPDATE template_comments SET likes=likes+1 WHERE id=:cid"),
                      {"cid": comment_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.post("/api/comments/report/{comment_id}")
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
            "INSERT INTO comment_reports (comment_id, reporter_id, reason, created_at) VALUES (:cid, :pid, :rs, :ca)"
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

@app.get("/api/comments/{target_type}/{target_id}")
def get_comments(target_type: str, target_id: str, request: Request, page: int = 1, size: int = 20, sort: str = "time"):
    s = get_session()
    try:
        order = "created_at DESC" if sort == "time" else "likes DESC"
        offset = (page - 1) * size
        total = s.execute(text(
            "SELECT COUNT(*) FROM template_comments WHERE target_type=:tt AND target_id=:tid AND is_approved=1"
        ), {"tt": target_type, "tid": target_id}).fetchone()[0]
        rows = s.execute(text(
            f"SELECT id, player_id, username, content, parent_id, likes, created_at "
            f"FROM template_comments WHERE target_type=:tt AND target_id=:tid AND is_approved=1 "
            f"ORDER BY {order} LIMIT :lim OFFSET :off"
        ), {"tt": target_type, "tid": target_id, "lim": size, "off": offset})
        comments = [{"id": r[0], "player_id": r[1], "username": r[2], "content": r[3],
                     "parent_id": r[4], "likes": r[5], "created_at": r[6]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"comments": comments, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.post("/api/comments/{target_type}/{target_id}")
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
        user_row = s.execute(text("SELECT username FROM users WHERE player_id=:pid"), {"pid": pid}).fetchone()
        username = user_row[0] if user_row else "anonymous"
        s.execute(text(
            "INSERT INTO template_comments (target_type, target_id, player_id, username, content, parent_id, created_at) "
            "VALUES (:tt, :tid, :pid, :un, :ct, :pi, :ca)"
        ), {"tt": target_type, "tid": target_id, "pid": pid, "un": username, "ct": content, "pi": parent_id, "ca": now})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.delete("/api/comments/{target_type}/{target_id}/{comment_id}")
def delete_comment(target_type: str, target_id: str, comment_id: int, request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        row = s.execute(text("SELECT player_id FROM template_comments WHERE id=:id"), {"id": comment_id}).fetchone()
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


# ── 用户面板 API ──────────────────────────────────────

@app.get("/api/user/profile")
def user_profile(request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        user = s.execute(text("SELECT player_id, username, created_at, is_admin, avatar_url FROM users WHERE player_id=:pid"), {"pid": pid}).fetchone()
        if not user:
            return {"error": "user not found"}
        pts = s.execute(text("SELECT balance, total_earned, total_spent, sign_in_streak, last_sign_in_date FROM point_accounts WHERE player_id=:pid"), {"pid": pid}).fetchone()
        if not pts:
            # 自动为已有用户创建积分账户
            today = time.strftime("%Y-%m-%d")
            s.execute(text(
                "INSERT INTO point_accounts (player_id, balance, total_earned, total_spent, sign_in_streak, last_sign_in_date, created_at) "
                "VALUES (:pid, 99999, 99999, 0, 0, '', :ca)"
            ), {"pid": pid, "ca": today})
            s.commit()
            pts = s.execute(text("SELECT balance, total_earned, total_spent, sign_in_streak, last_sign_in_date FROM point_accounts WHERE player_id=:pid"), {"pid": pid}).fetchone()
        # 获取今日是否已签到
        today_str = time.strftime("%Y-%m-%d")
        signed_in_today = bool(pts and pts[4] == today_str)
        # 统计
        play_count = s.execute(text("SELECT COUNT(*) FROM point_transactions WHERE player_id=:pid AND reason='游戏'"), {"pid": pid}).fetchone()[0]
        clear_count = s.execute(text("SELECT COUNT(*) FROM point_transactions WHERE player_id=:pid AND reason='通关'"), {"pid": pid}).fetchone()[0]
        template_count = s.execute(text("SELECT COUNT(*) FROM shared_copies WHERE uploader_id=:pid"), {"pid": pid}).fetchone()[0]
        # 成就列表
        ach_rows = s.execute(text(
            "SELECT achievement_key, achievement_name, icon, scenario_name, unlocked_at FROM player_achievements WHERE player_id=:pid ORDER BY unlocked_at DESC"
        ), {"pid": pid}).fetchall()
        achievements = [{"key": r[0], "name": r[1], "icon": r[2], "scenario_name": r[3], "unlocked_at": r[4]} for r in ach_rows]
        return {
            "player_id": user[0], "username": user[1], "created_at": user[2],
            "is_admin": bool(user[3]), "avatar_url": user[4] or "",
            "points": pts[0] if pts else 0, "total_earned": pts[1] if pts else 0,
            "total_spent": pts[2] if pts else 0, "sign_in_streak": pts[3] if pts else 0,
            "last_sign_in_date": pts[4] if pts else "",
            "signed_in_today": signed_in_today,
            "play_count": play_count, "clear_count": clear_count, "template_count": template_count,
            "achievements": achievements
        }
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.put("/api/user/profile")
async def update_profile(request: Request):
    pid = _pid(request)
    body = await request.json()
    avatar_url = body.get("avatar_url", None)
    s = get_session()
    try:
        if avatar_url is not None:
            s.execute(text("UPDATE users SET avatar_url=:av WHERE player_id=:pid"), {"av": avatar_url, "pid": pid})
            s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.post("/api/user/sign-in")
def user_sign_in(request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        today = time.strftime("%Y-%m-%d")
        # 确保积分账户存在
        existing = s.execute(text("SELECT 1 FROM point_accounts WHERE player_id=:pid"), {"pid": pid}).fetchone()
        if not existing:
            s.execute(text(
                "INSERT INTO point_accounts (player_id, balance, total_earned, total_spent, sign_in_streak, created_at) "
                "VALUES (:pid, 99999, 99999, 0, 0, :ca)"
            ), {"pid": pid, "ca": today})
        # 检查今日是否已签到
        row = s.execute(text("SELECT last_sign_in_date, sign_in_streak FROM point_accounts WHERE player_id=:pid"), {"pid": pid}).fetchone()
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
            "UPDATE point_accounts SET balance=balance+:bonus, total_earned=total_earned+:bonus, "
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

@app.get("/api/user/point-history")
def point_history(request: Request, page: int = 1, size: int = 20):
    pid = _pid(request)
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text("SELECT COUNT(*) FROM point_transactions WHERE player_id=:pid"), {"pid": pid}).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, amount, reason, ref_id, created_at FROM point_transactions "
            "WHERE player_id=:pid ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {"pid": pid, "lim": size, "off": offset})
        txns = [{"id": r[0], "amount": r[1], "reason": r[2], "ref_id": r[3], "created_at": r[4]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"transactions": txns, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# ── 积分兑换 API ──────────────────────────────────────

@app.post("/api/points/exchange")
async def exchange_points(request: Request):
    pid = _pid(request)
    body = await request.json()
    code = (body.get("code", "") or "").strip()
    if not code:
        return {"error": "code is required"}
    s = get_session()
    try:
        row = s.execute(text("SELECT points, is_used FROM exchange_codes WHERE code=:cd"), {"cd": code}).fetchone()
        if not row:
            return {"error": "invalid code"}
        if row[1]:
            return {"error": "code already used"}
        pts = row[0]
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        # 标记兑换码已使用
        s.execute(text("UPDATE exchange_codes SET is_used=1, used_by=:pid, used_at=:ca WHERE code=:cd"),
                  {"pid": pid, "ca": now, "cd": code})
        # 确保积分账户存在
        acc = s.execute(text("SELECT 1 FROM point_accounts WHERE player_id=:pid"), {"pid": pid}).fetchone()
        if not acc:
            s.execute(text(
                "INSERT INTO point_accounts (player_id, balance, total_earned, total_spent, sign_in_streak, created_at) "
                "VALUES (:pid, 0, 0, 0, 0, :ca)"
            ), {"pid": pid, "ca": now})
        # 充值积分
        s.execute(text(
            "UPDATE point_accounts SET balance=balance+:pts, total_earned=total_earned+:pts WHERE player_id=:pid"
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

# ── 建议 API ──────────────────────────────────────────

@app.post("/api/suggestions")
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
        user_row = s.execute(text("SELECT username FROM users WHERE player_id=:pid"), {"pid": pid}).fetchone()
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

@app.get("/api/suggestions/my")
def my_suggestions(request: Request):
    pid = _pid(request)
    s = get_session()
    try:
        rows = s.execute(text(
            "SELECT id, category, content, status, admin_reply, created_at FROM suggestions "
            "WHERE player_id=:pid ORDER BY created_at DESC"
        ), {"pid": pid})
        items = [{"id": r[0], "category": r[1], "content": r[2], "status": r[3],
                  "admin_reply": r[4], "created_at": r[5]} for r in rows]
        return {"suggestions": items}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# ── 公告 API ──────────────────────────────────────────

@app.get("/api/announcements")
def latest_announcement():
    s = get_session()
    try:
        row = s.execute(text(
            "SELECT id, content, created_by, created_at FROM system_announcements "
            "WHERE is_active=1 ORDER BY created_at DESC LIMIT 1"
        )).fetchone()
        if not row:
            return {"announcement": None}
        return {"announcement": {"id": row[0], "content": row[1], "created_by": row[2], "created_at": row[3]}}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.get("/api/announcements/list")
def announcement_list(page: int = 1, size: int = 20):
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text("SELECT COUNT(*) FROM system_announcements WHERE is_active=1")).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, content, created_by, created_at FROM system_announcements "
            "WHERE is_active=1 ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {"lim": size, "off": offset})
        items = [{"id": r[0], "content": r[1], "created_by": r[2], "created_at": r[3]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"announcements": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# ── 审核接口（预留，待接入AI审核） ──────────────────────────
@app.post("/api/review/template")
async def review_template(request: Request):
    return {"approved": True}

@app.post("/api/review/comment")
async def review_comment(request: Request):
    return {"approved": True}

# ── 管理面板 API ──────────────────────────────────────

# 用户管理
@app.get("/api/admin/users")
def admin_users(request: Request, search: str = "", page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err: return err
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
        users = [{"player_id": r[0], "username": r[1], "created_at": r[2],
                  "is_admin": bool(r[3]), "avatar_url": r[4] or "",
                  "is_banned": bool(r[5]), "points": r[6]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"users": users, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.get("/api/admin/users/{target_pid}")
def admin_user_detail(target_pid: str, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        user = s.execute(text("SELECT player_id, username, created_at, is_admin, avatar_url FROM users WHERE player_id=:pid"), {"pid": target_pid}).fetchone()
        if not user: return {"error": "用户不存在"}
        pts = s.execute(text("SELECT balance, total_earned, total_spent, sign_in_streak, last_sign_in_date FROM point_accounts WHERE player_id=:pid"), {"pid": target_pid}).fetchone()
        comment_cnt = s.execute(text("SELECT COUNT(*) FROM template_comments WHERE player_id=:pid"), {"pid": target_pid}).fetchone()[0]
        copy_cnt = s.execute(text("SELECT COUNT(*) FROM shared_copies WHERE uploader_id=:pid"), {"pid": target_pid}).fetchone()[0]
        return {"player_id": user[0], "username": user[1], "created_at": user[2], "is_admin": bool(user[3]), "avatar_url": user[4] or "",
                "points": {"balance": pts[0] if pts else 0, "total_earned": pts[1] if pts else 0, "total_spent": pts[2] if pts else 0, "sign_in_streak": pts[3] if pts else 0},
                "comment_count": comment_cnt, "copy_count": copy_cnt}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.put("/api/admin/users/{target_pid}")
async def admin_update_user(target_pid: str, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    body = await request.json()
    s = get_session()
    try:
        if "balance" in body or "points" in body:
            val = int(body.get("balance") or body.get("points", 0))
            s.execute(text("UPDATE point_accounts SET balance=:bal WHERE player_id=:pid"), {"bal": val, "pid": target_pid})
        if "is_admin" in body:
            s.execute(text("UPDATE users SET is_admin=:adm WHERE player_id=:pid"), {"adm": 1 if body["is_admin"] else 0, "pid": target_pid})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.post("/api/admin/users/{target_pid}/ban")
def admin_toggle_ban(target_pid: str, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        row = s.execute(text("SELECT is_banned FROM users WHERE player_id=:pid"), {"pid": target_pid}).fetchone()
        if not row: return {"error": "用户不存在"}
        new_val = 0 if row[0] else 1
        s.execute(text("UPDATE users SET is_banned=:v WHERE player_id=:pid"), {"v": new_val, "pid": target_pid})
        s.commit()
        return {"ok": True, "is_banned": bool(new_val)}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# 兑换码管理
@app.post("/api/admin/exchange-codes")
async def admin_gen_codes(request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    body = await request.json()
    count = int(body.get("count", 1))
    points = int(body.get("points", 100))
    batch_id = (body.get("batch_id", "") or "").strip() or f"batch_{int(time.time())}"
    if count > 1000: count = 1000
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        codes = []
        for i in range(count):
            code_raw = hmac.new(XCHG_SECRET, f"{batch_id}:{i}:{time.time()}".encode(), _hl.sha256).digest()
            code_b32 = base64.b32encode(code_raw).decode().rstrip("=").upper()[:12]
            while len(code_b32) < 12: code_b32 += "A"
            code = f"FL-{code_b32[:4]}-{code_b32[4:8]}-{code_b32[8:12]}"
            s.execute(text(
                "INSERT INTO exchange_codes (code, points, batch_id, created_by, created_at) VALUES (:cd, :pts, :bid, :pid, :ca)"
            ), {"cd": code, "pts": points, "bid": batch_id, "pid": pid, "ca": now})
            codes.append(code)
        s.commit()
        return {"ok": True, "batch_id": batch_id, "count": count, "codes": codes}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.get("/api/admin/exchange-codes")
def admin_list_codes(request: Request, batch_id: str = "", page: int = 1, size: int = 50):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        offset = (page - 1) * size
        where = "WHERE 1=1"
        params = {}
        if batch_id:
            where += " AND batch_id=:bid"
            params["bid"] = batch_id
        total = s.execute(text(f"SELECT COUNT(*) FROM exchange_codes {where}"), params).fetchone()[0]
        rows = s.execute(text(
            f"SELECT code, points, batch_id, created_by, used_by, is_used, used_at, created_at FROM exchange_codes {where} ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {**params, "lim": size, "off": offset})
        items = [{"code": r[0], "points": r[1], "batch_id": r[2], "created_by": r[3], "used_by": r[4],
                  "is_used": bool(r[5]), "used_at": r[6], "created_at": r[7]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"codes": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# 评论管理
@app.get("/api/admin/comments")
def admin_comments(request: Request, status: str = "all", page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        offset = (page - 1) * size
        where = "WHERE 1=1"
        params = {}
        if status == "approved": where += " AND is_approved=1"
        elif status == "reported":
            where += " AND id IN (SELECT comment_id FROM comment_reports WHERE is_resolved=0)"
        elif status == "pending": where += " AND is_approved=0"
        total = s.execute(text(f"SELECT COUNT(*) FROM template_comments {where}"), params).fetchone()[0]
        rows = s.execute(text(
            f"SELECT id, target_type, target_id, player_id, username, content, parent_id, likes, is_approved, created_at FROM template_comments {where} ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {**params, "lim": size, "off": offset})
        items = [{"id": r[0], "target_type": r[1], "target_id": r[2], "player_id": r[3], "username": r[4],
                  "content": r[5], "parent_id": r[6], "likes": r[7], "is_approved": bool(r[8]), "created_at": r[9]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"comments": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.delete("/api/admin/comments/{comment_id}")
def admin_delete_comment(comment_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        s.execute(text("DELETE FROM template_comments WHERE id=:id"), {"id": comment_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.post("/api/admin/comments/{comment_id}/approve")
def admin_approve_comment(comment_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        s.execute(text("UPDATE template_comments SET is_approved=1 WHERE id=:id"), {"id": comment_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# 举报管理
@app.get("/api/admin/reports")
def admin_reports(request: Request, page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text("SELECT COUNT(*) FROM comment_reports")).fetchone()[0]
        rows = s.execute(text(
            "SELECT r.id, r.comment_id, r.reporter_id, r.reason, r.is_resolved, r.resolved_by, r.created_at, c.content "
            "FROM comment_reports r LEFT JOIN template_comments c ON r.comment_id=c.id ORDER BY r.created_at DESC LIMIT :lim OFFSET :off"
        ), {"lim": size, "off": offset})
        items = [{"id": r[0], "comment_id": r[1], "reporter_id": r[2], "reason": r[3], "is_resolved": bool(r[4]),
                  "resolved_by": r[5], "created_at": r[6], "comment_content": r[7]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"reports": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.put("/api/admin/reports/{report_id}")
async def admin_resolve_report(report_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    body = await request.json()
    s = get_session()
    try:
        s.execute(text("UPDATE comment_reports SET is_resolved=:ir, resolved_by=:rb WHERE id=:id"),
                  {"ir": 1 if body.get("is_resolved", True) else 0, "rb": body.get("resolved_by", pid), "id": report_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# 模板管理
@app.delete("/api/admin/templates/{target_type}/{target_id}")
def admin_delete_template(target_type: str, target_id: str, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        if target_type == "copy":
            s.execute(text("DELETE FROM shared_copies WHERE id=:id"), {"id": int(target_id)})
        elif target_type == "preset":
            # 预设删除文件
            pass
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# 建议管理
@app.get("/api/admin/suggestions")
def admin_suggestions(request: Request, page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text("SELECT COUNT(*) FROM suggestions")).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, player_id, username, category, content, status, admin_reply, created_at FROM suggestions ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {"lim": size, "off": offset})
        items = [{"id": r[0], "player_id": r[1], "username": r[2], "category": r[3], "content": r[4],
                  "status": r[5], "admin_reply": r[6], "created_at": r[7]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"suggestions": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.put("/api/admin/suggestions/{suggestion_id}")
async def admin_update_suggestion(suggestion_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    body = await request.json()
    s = get_session()
    try:
        if "status" in body:
            s.execute(text("UPDATE suggestions SET status=:st WHERE id=:id"), {"st": body["status"], "id": suggestion_id})
        if "admin_reply" in body:
            s.execute(text("UPDATE suggestions SET admin_reply=:rp WHERE id=:id"), {"rp": body["admin_reply"], "id": suggestion_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# 公告管理
@app.post("/api/admin/announcements")
async def admin_create_announcement(request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    body = await request.json()
    content = (body.get("content", "") or "").strip()
    if not content: return {"error": "content is required"}
    s = get_session()
    try:
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        s.execute(text(
            "INSERT INTO system_announcements (content, created_by, created_at) VALUES (:ct, :pid, :ca)"
        ), {"ct": content, "pid": pid, "ca": now})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.put("/api/admin/announcements/{announcement_id}")
async def admin_update_announcement(announcement_id: int, request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    body = await request.json()
    s = get_session()
    try:
        if "content" in body:
            s.execute(text("UPDATE system_announcements SET content=:ct WHERE id=:id"), {"ct": body["content"], "id": announcement_id})
        if "is_active" in body:
            s.execute(text("UPDATE system_announcements SET is_active=:ia WHERE id=:id"), {"ia": 1 if body["is_active"] else 0, "id": announcement_id})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.get("/api/admin/announcements")
def admin_all_announcements(request: Request, page: int = 1, size: int = 20):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        offset = (page - 1) * size
        total = s.execute(text("SELECT COUNT(*) FROM system_announcements")).fetchone()[0]
        rows = s.execute(text(
            "SELECT id, content, created_by, is_active, created_at FROM system_announcements ORDER BY created_at DESC LIMIT :lim OFFSET :off"
        ), {"lim": size, "off": offset})
        items = [{"id": r[0], "content": r[1], "created_by": r[2], "is_active": bool(r[3]), "created_at": r[4]} for r in rows]
        tp = (total + size - 1) // size if total > 0 else 0
        return {"announcements": items, "total": total, "page": page, "total_pages": tp}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# 系统统计
@app.get("/api/admin/stats")
def admin_stats(request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    s = get_session()
    try:
        total_users = s.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
        total_templates = s.execute(text("SELECT COUNT(*) FROM shared_copies")).fetchone()[0]
        total_comments = s.execute(text("SELECT COUNT(*) FROM template_comments")).fetchone()[0]
        total_points = s.execute(text("SELECT COALESCE(SUM(amount),0) FROM point_transactions WHERE amount>0")).fetchone()[0]
        total_spent = s.execute(text("SELECT COALESCE(SUM(ABS(amount)),0) FROM point_transactions WHERE amount<0")).fetchone()[0]
        # 今日活跃 + 近30天活跃
        today = time.strftime("%Y-%m-%d")
        today_active = s.execute(text("SELECT COUNT(DISTINCT player_id) FROM point_transactions WHERE created_at LIKE :td"), {"td": f"{today}%"}).fetchone()[0]
        thirty_days_ago = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400*30))
        active_30d = s.execute(text("SELECT COUNT(DISTINCT player_id) FROM point_transactions WHERE created_at >= :td"), {"td": thirty_days_ago}).fetchone()[0]
        return {"total_users": total_users, "total_templates": total_templates, "total_comments": total_comments,
                "total_points_issued": total_points, "total_points_consumed": total_spent,
                "today_active": today_active, "active_users_30d": active_30d}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# 系统配置管理
@app.get("/api/admin/config")
def admin_get_config(request: Request):
    pid, err = _admin_pid(request)
    if err: return err
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
                s.execute(text("INSERT INTO system_config (key_name, value, updated_at) VALUES (:k,:v,:t) ON DUPLICATE KEY UPDATE key_name=key_name"),
                           {"k": k, "v": v, "t": time.strftime("%Y-%m-%d %H:%M:%S")})
        s.commit()
        return {"config": config}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

@app.put("/api/admin/config")
async def admin_update_config(request: Request):
    pid, err = _admin_pid(request)
    if err: return err
    body = await request.json()
    s = get_session()
    try:
        for k, v in body.items():
            s.execute(text("INSERT INTO system_config (key_name, value, updated_at) VALUES (:k,:v,:t) ON DUPLICATE KEY UPDATE value=:v, updated_at=:t"),
                      {"k": k, "v": str(v), "t": time.strftime("%Y-%m-%d %H:%M:%S")})
        s.commit()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)[:200]}
    finally:
        s.close()

# ── 图片上传 API ──────────────────────────────────────

_UPLOAD_DIR = pathlib.Path(__file__).parent / "static" / "uploads"
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGES_PER_USER = 50

# Magic bytes for format validation
_MAGIC_BYTES = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG\r\n\x1a\n": ".png",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"RIFF": ".webp",  # RIFF....WEBP
}

def _validate_image_magic(content: bytes) -> str:
    """通过magic bytes验证图片格式，返回扩展名（含点）"""
    for magic, ext in _MAGIC_BYTES.items():
        if content[:len(magic)] == magic:
            if ext == ".webp":
                # WebP需要额外检查: RIFFxxxxWEBP
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    return ext
                continue
            return ext
    return ""

def _count_user_images(pid: str) -> int:
    """统计某用户的图片数量"""
    user_dir = _UPLOAD_DIR / pid
    if not user_dir.exists():
        return 0
    return len([f for f in user_dir.iterdir() if f.is_file() and f.suffix.lower() in _ALLOWED_EXTENSIONS])

@app.post("/api/upload/image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    pid = _pid(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # 检查扩展名
    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}. Allowed: jpg, png, gif, webp")

    # 读取文件内容
    content = await file.read()

    # 大小检查
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 2MB)")

    # Magic bytes验证
    detected_ext = _validate_image_magic(content)
    if not detected_ext:
        raise HTTPException(status_code=400, detail="Invalid image file (magic bytes mismatch)")

    # 使用检测到的扩展名（更可靠）
    if detected_ext != ext:
        ext = detected_ext

    # 配额检查
    user_dir = _UPLOAD_DIR / pid
    user_dir.mkdir(parents=True, exist_ok=True)
    current_count = _count_user_images(pid)
    if current_count >= _MAX_IMAGES_PER_USER:
        raise HTTPException(status_code=400, detail=f"Image quota exceeded ({_MAX_IMAGES_PER_USER} max). Please delete some images first.")

    # 保存文件
    import uuid
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = user_dir / filename
    with open(filepath, "wb") as f:
        f.write(content)

    url = f"/static/uploads/{pid}/{filename}"
    return {"url": url, "filename": filename, "size": len(content)}

@app.get("/api/upload/images")
def list_images(request: Request):
    pid = _pid(request)
    user_dir = _UPLOAD_DIR / pid
    if not user_dir.exists():
        return {"images": [], "count": 0, "quota": _MAX_IMAGES_PER_USER}
    images = []
    for f in sorted(user_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in _ALLOWED_EXTENSIONS:
            images.append({
                "filename": f.name,
                "url": f"/static/uploads/{pid}/{f.name}",
                "size": f.stat().st_size,
            })
    return {"images": images, "count": len(images), "quota": _MAX_IMAGES_PER_USER}

@app.delete("/api/upload/image/{filename}")
def delete_image(filename: str, request: Request):
    pid = _pid(request)
    # 安全检查：防止路径遍历
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = _UPLOAD_DIR / pid / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        filepath.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")
    return {"ok": True}

# ── 静态文件 ──────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

XCHG_SECRET = os.environ.get("XCHG_SECRET", "fenli_xchg_secret").encode()

if __name__ == "__main__":
    import uvicorn
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
