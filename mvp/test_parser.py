import re, json

# Test 1: Clean JSON with nested data_ops
t1 = '{"narrative": "test", "data_ops": {"create": [{"tag_name": "x", "tag_detail": {"a": 1, "b": 2}}], "update": [], "drop": []}}'
print("=== Test 1: Clean JSON with nested data_ops ===")
try:
    r = json.loads(t1)
    print(f"  json.loads: OK, data_ops={r['data_ops']}")
except Exception as e:
    print(f"  json.loads: FAILED - {e}")

# Test 2: Reasoning prefix + JSON
t2 = '好，让我分析一下当前世界状态...根据玩家行为生成叙事。\n\n{"narrative": "你推开门，走廊昏暗。", "data_ops": {"create": [{"tag_name": "月光病房", "tag_detail": {"血量": 100}}], "update": [], "drop": []}}'
print("\n=== Test 2: Reasoning prefix + JSON ===")
try:
    r = json.loads(t2)
    print(f"  json.loads: OK")
except Exception as e:
    print(f"  json.loads: FAILED (expected)")

# Test regex fallback for data_ops
print("\n=== Test 3: Regex fallback for data_ops ===")
m_ops = re.search(r'"data_ops"\s*:\s*(\{.*?\})\s*\}', t2, re.DOTALL)
if m_ops:
    print(f"  regex matched: {m_ops.group(1)[:100]}")
    try:
        parsed = json.loads(m_ops.group(1))
        print(f"  parsed OK: {parsed}")
    except Exception as e:
        print(f"  parsed FAILED: {e}")
else:
    print("  regex: NO MATCH")

# Test 4: Flat data_ops (no nesting)
t3 = 'thinking... {"narrative": "test", "data_ops": {"create": [], "update": [], "drop": []}}'
print("\n=== Test 4: Flat data_ops with prefix ===")
m_ops2 = re.search(r'"data_ops"\s*:\s*(\{.*?\})\s*\}', t3, re.DOTALL)
if m_ops2:
    print(f"  regex matched: {m_ops2.group(1)}")
    try:
        parsed = json.loads(m_ops2.group(1))
        print(f"  parsed OK: {parsed}")
    except Exception as e:
        print(f"  parsed FAILED: {e}")
else:
    print("  regex: NO MATCH")

# Test 5: Better approach - strip reasoning prefix
print("\n=== Test 5: Strip reasoning prefix then parse ===")
# Find the outermost JSON by finding first { and last }
first_brace = t2.find('{')
last_brace = t2.rfind('}')
if first_brace >= 0 and last_brace > first_brace:
    json_part = t2[first_brace:last_brace + 1]
    try:
        r = json.loads(json_part)
        print(f"  Stripped json.loads: OK, narrative={len(r['narrative'])} chars, ops keys={list(r['data_ops'].keys())}")
    except Exception as e:
        print(f"  Stripped json.loads: FAILED - {e}")

# Test 6: Realistic deepseek-v4-flash output (reasoning mixed with JSON)
t4 = 'The player opens the door. I need to describe the corridor with moonlight. The nurse is nearby.\n\n{"narrative": "你推开门，走廊昏暗的灯光忽明忽暗。\\\\n\\\\n月光透过破窗照进来，在地板上投下惨白的光斑。远处传来微弱的脚步声。", "data_ops": {"create": [], "update": [{"tag_name": "黑衣护士", "category": "character", "tag_detail": {"当前位置": "走廊", "当前意图": "巡逻"}}], "drop": []}}'

print("\n=== Test 6: Realistic model output ===")
fb = t4.find('{')
lb = t4.rfind('}')
json_part2 = t4[fb:lb + 1]
try:
    r = json.loads(json_part2)
    print(f"  json.loads: OK")
    print(f"  narrative: {len(r['narrative'])} chars")
    print(f"  data_ops: create={len(r['data_ops']['create'])}, update={len(r['data_ops']['update'])}, drop={len(r['data_ops']['drop'])}")
except Exception as e:
    print(f"  json.loads: FAILED - {e}")
