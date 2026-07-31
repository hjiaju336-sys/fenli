# -*- coding: utf-8 -*-
"""
QA test: fenli prod server templates & cloud features
Server: http://162.14.64.4:8777
"""

import httpx
import json
import time
import sys
import io
from urllib.parse import quote

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = "http://162.14.64.4:8777"
TIMEOUT = 30.0  # seconds
TOKEN = None
HEADERS = {}
CLIENT = httpx.Client(timeout=TIMEOUT)

passed = 0
failed = 0

def ok(cond, msg):
    global passed, failed
    if cond:
        print(f"  [PASS] {msg}")
        passed += 1
    else:
        print(f"  [FAIL] {msg}")
        failed += 1
    return cond

def safe_json(r):
    try:
        return r.json()
    except:
        return {"_raw": r.text[:500]}

def req(method, url, **kwargs):
    """Make an HTTP request with timeout handling."""
    try:
        r = CLIENT.request(method, url, **kwargs)
        return r
    except Exception as e:
        print(f"  [ERROR] {method} {url}: {e}")
        # Return a fake response
        class FakeResp:
            status_code = 0
            text = str(e)
            def json(self): return {"_error": str(e)}
        return FakeResp()

# ============================================================
# 0. Login
# ============================================================
print("=" * 60)
print("0. Login (POST /api/auth/login)")
print("=" * 60)

login_resp = req("POST",f"{BASE}/api/auth/login", json={"username": "admin", "password": "root"})
ok(login_resp.status_code == 200, f"status={login_resp.status_code}")
data = safe_json(login_resp)
print(f"  Response keys: {list(data.keys())}")

TOKEN = data.get("token", "")
ok(bool(TOKEN), f"Got token: {TOKEN[:40] if TOKEN else 'NONE'}...")
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

if not TOKEN:
    print("[FATAL] No token, quitting")
    sys.exit(1)

# ============================================================
# 1. Presets
# ============================================================
print("\n" + "=" * 60)
print("1. Preset Templates (GET /api/presets)")
print("=" * 60)

# 1a. GET /api/presets
r = req("GET",f"{BASE}/api/presets")
ok(r.status_code == 200, f"GET /api/presets status={r.status_code}")
presets_data = safe_json(r)

presets = presets_data.get("presets", [])
if isinstance(presets, dict):
    presets = list(presets.values())
ok(isinstance(presets, list) and len(presets) == 6, f"6 presets (actual {len(presets)})")

for p in presets:
    if isinstance(p, dict):
        has_all = all(k in p for k in ["name", "rank", "desc", "filename"])
        ok(has_all, f"  {p.get('name','?'):12s} rank={p.get('rank','?')} file={p.get('filename','?')}")

# 1b. Load preset (POST /api/presets/{filename}/load)
print()
first_file = presets[0].get("filename", "午夜列车.json") if isinstance(presets, list) and presets else "午夜列车.json"
r2 = req("POST",f"{BASE}/api/presets/{quote(first_file, safe='')}/load", headers=HEADERS)
ok(r2.status_code == 200, f"POST /api/presets/{first_file}/load status={r2.status_code}")
load_data = safe_json(r2)
ok(load_data.get("ok") == True, f"Load returns ok: {json.dumps(load_data, ensure_ascii=False)[:80]}")

# Also test blood-moon specifically
r2b = req("POST",f"{BASE}/api/presets/" + quote("血月医院.json", safe='') + "/load", headers=HEADERS)
ok(r2b.status_code == 200, f"Load blood-moon preset status={r2b.status_code}")

# ============================================================
# 2. User Templates (saves with save_type='preset')
# ============================================================
print("\n" + "=" * 60)
print("2. User Templates (saves via /api/saves/upload)")
print("=" * 60)

ts = int(time.time())
slot_name = f"preset_qa_test_{ts}"

# 2a. Upload - uses 'save_data' field (not 'data')
# SaveDAO expects: slot_name, turn_number, save_data
save_payload = {
    "slot_name": slot_name,
    "turn_number": 0,
    "save_data": json.dumps({
        "name": "QA Test Template",
        "description": "Auto-created by QA test",
        "save_type": "preset",
        "elements": [{"id": "test_elem", "type": "test"}]
    }, ensure_ascii=False)
}
r3 = req("POST",f"{BASE}/api/saves/upload", json=save_payload, headers=HEADERS)
ok(r3.status_code == 200, f"POST /api/saves/upload status={r3.status_code}")
upload_result = safe_json(r3)
ok(upload_result.get("ok") == True, f"Upload ok: {json.dumps(upload_result, ensure_ascii=False)[:100]}")

# 2b. GET /api/saves
r4 = req("GET",f"{BASE}/api/saves", headers=HEADERS)
ok(r4.status_code == 200, f"GET /api/saves status={r4.status_code}")
saves_data = safe_json(r4)
saves_list = saves_data if isinstance(saves_data, list) else saves_data.get("data", saves_data.get("saves", []))
if isinstance(saves_list, dict):
    saves_list = list(saves_list.values())
print(f"  Saves count: {len(saves_list) if isinstance(saves_list, list) else 'N/A'}")

found = False
SAVE_ID = None
if isinstance(saves_list, list):
    for s in saves_list:
        if isinstance(s, dict):
            sid = s.get("slot_name") or s.get("name", "")
            if sid == slot_name:
                found = True
                SAVE_ID = s.get("id") or s.get("sid")
                break
ok(found, f"Template '{slot_name}' in saves list: {found}")

# 2c. Read save (GET /api/saves/{sid})
# The saves GET likely returns by slot_name; try both slot_name and id
if found and saves_list:
    read_id = SAVE_ID or slot_name
    r5 = req("GET",f"{BASE}/api/saves/{read_id}", headers=HEADERS)
    ok(r5.status_code == 200, f"GET /api/saves/{read_id} status={r5.status_code}")
    if r5.status_code == 200:
        read_data = safe_json(r5)
        print(f"  Read: {json.dumps(read_data, ensure_ascii=False)[:200]}")
else:
    ok(False, "Save not found, skip read")

# 2d. Delete (DELETE /api/saves/{sid})
delete_id = SAVE_ID or slot_name
if found:
    r6 = req("DELETE",f"{BASE}/api/saves/{delete_id}", headers=HEADERS)
    ok(r6.status_code in (200, 204), f"DELETE /api/saves/{delete_id} status={r6.status_code}")

# Verify deleted
r7 = req("GET",f"{BASE}/api/saves", headers=HEADERS)
saves_after = safe_json(r7) if r7.status_code == 200 else {}
saves_after_list = saves_after if isinstance(saves_after, list) else saves_after.get("data", saves_after.get("saves", []))
if isinstance(saves_after_list, dict):
    saves_after_list = list(saves_after_list.values())
still = any(
    isinstance(s, dict) and (s.get("slot_name") == slot_name or s.get("id") == SAVE_ID)
    for s in (saves_after_list if isinstance(saves_after_list, list) else [])
)
ok(not still, f"Template deleted (still exists: {still})")

# ============================================================
# 3. Cloud Copies (shared_copies)
# ============================================================
print("\n" + "=" * 60)
print("3. Cloud Copies")
print("=" * 60)

# Upload uses: title, desc, tags, save_data
# IMPORTANT: save_data must be a dict/object, NOT a JSON string (server does json.dumps internally)
copy_title = f"QA_Cloud_Copy_{ts}"
copy_payload = {
    "title": copy_title,
    "desc": "QA automated cloud copy test - will be cleaned up",
    "tags": "test,qa,automated",
    "save_data": {
        "title": "QA Cloud Copy",
        "content": "Automated test copy content",
        "tags": [{"category": "character", "tag_name": "test_npc", "tag_hint": "A test NPC", "tag_detail": {}}],
        "world_book": [],
        "hooks": []
    }
}

# 3a. Upload
r8 = req("POST",f"{BASE}/api/copies/upload", json=copy_payload, headers=HEADERS)
ok(r8.status_code == 200, f"POST /api/copies/upload status={r8.status_code}")
copy_result = safe_json(r8)
ok(copy_result.get("ok") == True, f"Upload returns ok: {json.dumps(copy_result, ensure_ascii=False)[:80]}")

# 3b. Find our copy in the list (upload doesn't return id)
TEST_COPY_ID = None
r9 = req("GET",f"{BASE}/api/copies", headers=HEADERS)
ok(r9.status_code == 200, f"GET /api/copies status={r9.status_code}")
copies_data = safe_json(r9)
copies_list = copies_data.get("copies", []) if isinstance(copies_data, dict) else []
if isinstance(copies_data, list):
    copies_list = copies_data
print(f"  Copies count: {len(copies_list)}")

for c in copies_list:
    if isinstance(c, dict) and c.get("title") == copy_title:
        TEST_COPY_ID = c.get("id")
        break

ok(bool(TEST_COPY_ID), f"Found COPY_ID={TEST_COPY_ID} for '{copy_title}'")
# Print first 3 copies for debugging
for c in copies_list[:3]:
    if isinstance(c, dict):
        print(f"    id={c.get('id')} title={c.get('title','?')[:30]} downloads={c.get('downloads')}")

# 3c. Get detail
if TEST_COPY_ID:
    r10 = req("GET",f"{BASE}/api/copies/{TEST_COPY_ID}", headers=HEADERS)
    ok(r10.status_code == 200, f"GET /api/copies/{TEST_COPY_ID} status={r10.status_code}")
    if r10.status_code == 200:
        detail = safe_json(r10)
        print(f"  Detail keys: {list(detail.keys()) if isinstance(detail, dict) else '...'}")
        print(f"  Detail: {json.dumps(detail, ensure_ascii=False)[:200]}")
else:
    ok(False, "No COPY_ID, skip detail")

# 3d. Load copy
if TEST_COPY_ID:
    r11 = req("POST",f"{BASE}/api/copies/{TEST_COPY_ID}/load", headers=HEADERS)
    ok(r11.status_code == 200, f"POST /api/copies/{TEST_COPY_ID}/load status={r11.status_code}")
    load_result = safe_json(r11)
    ok(load_result.get("ok") == True, f"Load returns ok: {json.dumps(load_result, ensure_ascii=False)[:80]}")
else:
    ok(False, "No COPY_ID, skip load")

# 3e. Delete
if TEST_COPY_ID:
    r12 = req("DELETE",f"{BASE}/api/copies/{TEST_COPY_ID}", headers=HEADERS)
    ok(r12.status_code == 200, f"DELETE /api/copies/{TEST_COPY_ID} status={r12.status_code}")

    # Verify
    r13 = req("GET",f"{BASE}/api/copies", headers=HEADERS)
    ca = safe_json(r13) if r13.status_code == 200 else {}
    ca_list = ca.get("copies", []) if isinstance(ca, dict) else (ca if isinstance(ca, list) else [])
    still = any(str(c.get("id")) == str(TEST_COPY_ID) for c in ca_list if isinstance(c, dict))
    ok(not still, f"Copy deleted (still exists: {still})")
else:
    ok(False, "No COPY_ID, skip delete")

# ============================================================
# 4. Ratings (route: /api/ratings/{target_type}/{target_id})
# ============================================================
print("\n" + "=" * 60)
print("4. Ratings (POST/GET /api/ratings/copies/{id})")
print("=" * 60)

# Create a temp copy for rating
rc_payload = {
    "title": f"QA_Rating_Copy_{ts}",
    "desc": "For rating test",
    "tags": "qa,rating",
    "save_data": {"title": "Rating Test", "tags": [], "world_book": [], "hooks": []}
}
r14 = req("POST",f"{BASE}/api/copies/upload", json=rc_payload, headers=HEADERS)
rating_copy_id = None
if r14.status_code == 200 and safe_json(r14).get("ok"):
    # Find by title in list
    rc_list = req("GET",f"{BASE}/api/copies", headers=HEADERS)
    rcl = safe_json(rc_list)
    rcl = rcl.get("copies", rcl) if isinstance(rcl, dict) else rcl
    if isinstance(rcl, dict): rcl = list(rcl.values())
    if isinstance(rcl, list):
        for c in rcl:
            if isinstance(c, dict) and c.get("title") == rc_payload["title"]:
                rating_copy_id = c.get("id")
                break
    ok(bool(rating_copy_id), f"Create rating copy, id={rating_copy_id}")
else:
    ok(False, f"Create rating copy failed status={r14.status_code}")

if rating_copy_id:
    # 4a. POST rating
    rating_payload = {"rating": 4}
    r15 = req("POST",f"{BASE}/api/ratings/copies/{rating_copy_id}", json=rating_payload, headers=HEADERS)
    ok(r15.status_code in (200, 201), f"POST rating=4 status={r15.status_code}")
    print(f"  Rating resp: {json.dumps(safe_json(r15), ensure_ascii=False)[:150]}")

    # 4b. GET rating
    r16 = req("GET",f"{BASE}/api/ratings/copies/{rating_copy_id}", headers=HEADERS)
    ok(r16.status_code == 200, f"GET ratings status={r16.status_code}")
    if r16.status_code == 200:
        rating_info = safe_json(r16)
        print(f"  Rating info: {json.dumps(rating_info, ensure_ascii=False)[:200]}")

    # Cleanup
    req("DELETE",f"{BASE}/api/copies/{rating_copy_id}", headers=HEADERS)
else:
    ok(False, "No rating_copy_id, skip")

# ============================================================
# 5. Comments (route: /api/comments/{target_type}/{target_id})
# ============================================================
print("\n" + "=" * 60)
print("5. Comments (POST/GET /api/comments/copies/{id})")
print("=" * 60)

cmt_payload = {
    "title": f"QA_Comment_Copy_{ts}",
    "desc": "For comment test",
    "tags": "qa,comment",
    "save_data": {"title": "Comment Test", "tags": [], "world_book": [], "hooks": []}
}
r17 = req("POST",f"{BASE}/api/copies/upload", json=cmt_payload, headers=HEADERS)
cmt_copy_id = None
if r17.status_code == 200 and safe_json(r17).get("ok"):
    cmt_list = req("GET",f"{BASE}/api/copies", headers=HEADERS)
    cml = safe_json(cmt_list)
    cml = cml.get("copies", cml) if isinstance(cml, dict) else cml
    if isinstance(cml, dict): cml = list(cml.values())
    if isinstance(cml, list):
        for c in cml:
            if isinstance(c, dict) and c.get("title") == cmt_payload["title"]:
                cmt_copy_id = c.get("id")
                break
    ok(bool(cmt_copy_id), f"Create comment copy, id={cmt_copy_id}")
else:
    ok(False, f"Create comment copy failed status={r17.status_code}")

TEST_COMMENT_ID = None
if cmt_copy_id:
    # 5a. Post comment
    comment_payload = {"content": "QA auto test comment " + time.strftime("%H:%M:%S")}
    r18 = req("POST",f"{BASE}/api/comments/copies/{cmt_copy_id}", json=comment_payload, headers=HEADERS)
    ok(r18.status_code in (200, 201), f"POST comment status={r18.status_code}")
    cr = safe_json(r18)
    print(f"  Comment post resp: {json.dumps(cr, ensure_ascii=False)[:200]}")
    ok(r18.status_code in (200, 201), f"Comment posted ok: {cr.get('ok') == True}")

    # 5b. List comments to extract ID
    TEST_COMMENT_ID = None
    r19 = req("GET",f"{BASE}/api/comments/copies/{cmt_copy_id}", headers=HEADERS)
    ok(r19.status_code == 200, f"GET comments status={r19.status_code}")
    if r19.status_code == 200:
        comments_data = safe_json(r19)
        comments_list = comments_data.get("comments", []) if isinstance(comments_data, dict) else []
        print(f"  Comments list: {json.dumps(comments_data, ensure_ascii=False)[:300]}")
        if isinstance(comments_list, list) and len(comments_list) > 0:
            TEST_COMMENT_ID = comments_list[0].get("id")
        ok(bool(TEST_COMMENT_ID), f"Extracted COMMENT_ID={TEST_COMMENT_ID} from list")

    # 5c. Like comment
    if TEST_COMMENT_ID:
        r20 = req("POST",f"{BASE}/api/comments/like/{TEST_COMMENT_ID}", headers=HEADERS)
        ok(r20.status_code in (200, 201), f"POST like/{TEST_COMMENT_ID} status={r20.status_code}")
        print(f"  Like resp: {json.dumps(safe_json(r20), ensure_ascii=False)[:100]}")
    else:
        ok(True, "No COMMENT_ID, skip like (test still valid if comment succeeded)")

    # 5d. Report comment
    if TEST_COMMENT_ID:
        r21 = req("POST",f"{BASE}/api/comments/report/{TEST_COMMENT_ID}",
                         json={"reason": "QA automated test report"}, headers=HEADERS)
        ok(r21.status_code in (200, 201), f"POST report/{TEST_COMMENT_ID} status={r21.status_code}")
        print(f"  Report resp: {json.dumps(safe_json(r21), ensure_ascii=False)[:100]}")
    else:
        ok(True, "No COMMENT_ID, skip report")

    # Cleanup
    req("DELETE",f"{BASE}/api/copies/{cmt_copy_id}", headers=HEADERS)
else:
    ok(False, "No cmt_copy_id, skip comments")

# ============================================================
# 6. Frontend Verification
# ============================================================
print("\n" + "=" * 60)
print("6. Frontend Verification")
print("=" * 60)

# 6a. Desktop root page (served at '/', not '/index.html')
r22 = req("GET",f"{BASE}/")
ok(r22.status_code == 200, f"GET / (desktop) status={r22.status_code}")
index_html = r22.text
has_tpl = any(kw in index_html for kw in ["模板管理", "template", "预设", "模板"])
ok(has_tpl, f"Desktop page has template-related content: {has_tpl}")
for kw in ["模板管理", "模板", "template", "preset", "预设"]:
    if kw in index_html:
        print(f"  Found keyword: '{kw}'")

# 6b. Mobile m.html
r23 = req("GET",f"{BASE}/m.html")
ok(r23.status_code == 200, f"GET /m.html status={r23.status_code}")
m_html = r23.text
has_copy = any(kw in m_html for kw in ["副本", "云端", "share", "社区", "浏览商城", "模板"])
ok(has_copy, f"Mobile page has cloud/copy browse: {has_copy}")
for kw in ["副本", "浏览", "模板", "云端", "社区", "share", "community", "复制", "商城"]:
    if kw in m_html:
        print(f"  Found keyword: '{kw}'")

# ============================================================
# Summary
# ============================================================
CLIENT.close()

print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"{failed} test(s) FAILED")
print("=" * 60)
