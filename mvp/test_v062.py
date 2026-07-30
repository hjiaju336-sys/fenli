"""
v0.6.2 10轮连贯对话验收测试脚本
"""
import asyncio
import json
import sys
import time
import re
import httpx
import websockets

BASE_URL = "http://localhost:8777"
WS_URL = "ws://localhost:8777/ws"
USERNAME = "admin"
PASSWORD = "123456"
API_KEY = "sk-6faaf8d1366b4e979339dc1fbeb4fdc6"
MODEL_SMALL = "deepseek-v4-flash"
MODEL_LARGE = "deepseek-v4-flash"  # Using flash for both due to reasoning model issues

# 10轮输入
INPUTS = [
    "我睁开眼睛，观察周围的环境",
    "查看房间里的物品和细节",
    "尝试打开门，看看外面是什么",
    "如果遇到其他人，上前交谈",
    "查看墙壁上或地上是否有文字或标记",
    "检查自己的口袋和随身物品",
    "根据之前发现的线索，做出一个决定",
    "面对这个决定的后果",
    "寻找逃离或解决问题的关键",
    "完成当前场景的故事",
]

results = []


def count_chinese_chars(text):
    """统计中文字符数（不含空格和标点）"""
    count = 0
    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf':
            count += 1
    return count


def parse_data_ops(narrative, data_ops):
    """解析 data_ops JSON"""
    if data_ops is None:
        return False, "data_ops is None"
    if not isinstance(data_ops, dict):
        return False, f"data_ops is not dict: {type(data_ops)}"
    # Check for create/update/drop keys
    has_ops = False
    for key in ("create", "update", "drop"):
        if key in data_ops:
            has_ops = True
            break
    if not has_ops:
        return False, "no create/update/drop in data_ops"
    return True, "OK"


async def run_test():
    print("=" * 70)
    print("v0.6.2 10轮连贯对话验收测试")
    print("=" * 70)

    # Step 1: Login
    print("\n[1] 登录获取 token...")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": USERNAME, "password": PASSWORD},
        )
        if resp.status_code != 200:
            print(f"  LOGIN FAILED: {resp.status_code} {resp.text}")
            return
        data = resp.json()
        token = data["token"]
        pid = data["player_id"]
        print(f"  Token obtained: {token[:30]}... (pid={pid})")

        # Step 1.5: Check/load 血月医院 preset
        print("\n[1.5] 确保血月医院预设已加载...")
        try:
            load_resp = await client.post(
                f"{BASE_URL}/api/presets/血月医院.json/load",
                headers={"Authorization": f"Bearer {token}"},
            )
            if load_resp.status_code == 200:
                print(f"  血月医院预设已加载: {load_resp.json()}")
            else:
                print(f"  Load preset response: {load_resp.status_code} {load_resp.text}")
        except Exception as e:
            print(f"  Load preset error: {e}")

    # Step 2: Connect WebSocket
    print("\n[2] 连接 WebSocket...")
    ws_url = f"{WS_URL}?token={token}"

    try:
        async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
            print("  WebSocket connected")

            # Step 3: Receive init_state
            print("\n[3] 等待 init_state...")
            msg = await asyncio.wait_for(ws.recv(), timeout=30)
            init = json.loads(msg)
            world_name = init.get("world_name", "unknown")
            world_intro = init.get("world_intro", "")[:80]
            opening = init.get("opening_monologue", "")[:80]
            print(f"  world_name: {world_name}")
            print(f"  world_intro: {world_intro}")
            print(f"  opening_monologue: {opening}")
            print(f"  hotTags count: {len(init.get('hotTags', []))}")

            # Step 4: Run 10 rounds
            for idx, user_input in enumerate(INPUTS):
                round_num = idx + 1
                print(f"\n{'─' * 60}")
                print(f"[Round {round_num}/10] 输入: {user_input}")
                print(f"{'─' * 60}")

                # Send user_turn
                turn_msg = {
                    "type": "user_turn",
                    "apiKey1": API_KEY,
                    "apiKey2": API_KEY,
                    "userInput": user_input,
                    "modelSmall": MODEL_SMALL,
                    "modelLarge": MODEL_LARGE,
                    "nValue": 5,
                    "myWorldBook": [],
                }
                await ws.send(json.dumps(turn_msg))

                # Collect all messages until turn_complete
                narrative_chunks = []
                turn_complete_data = None
                errors = []
                timeout_count = 0

                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=120)
                    except asyncio.TimeoutError:
                        timeout_count += 1
                        if timeout_count > 2:
                            errors.append("TIMEOUT: no response after 120s x3")
                            break
                        print(f"  [等待中... {timeout_count}/3]")
                        continue

                    msg = json.loads(raw)
                    msg_type = msg.get("type")

                    if msg_type == "narrative_chunk":
                        narrative_chunks.append(msg.get("text", ""))
                    elif msg_type == "turn_complete":
                        turn_complete_data = msg
                        break
                    elif msg_type == "error":
                        errors.append(f"Server error: {msg.get('message', '')[:300]}")
                        break
                    elif msg_type == "hook_effects":
                        print(f"  [Hook触发] {len(msg.get('effects', []))} 个效果")
                    else:
                        print(f"  [其他消息] type={msg_type}")

                full_narrative = "".join(narrative_chunks)

                # Analyze this round
                cc_count = count_chinese_chars(full_narrative)
                total_chars = len(full_narrative)

                # Check JSON/data_ops
                data_ops = None
                if turn_complete_data:
                    # data_ops is embedded in the pass2 output - we need to check via hook_effects or the raw data
                    # For turn_complete, we can check created/updated/dropped counts
                    created = turn_complete_data.get("created", 0)
                    updated = turn_complete_data.get("updated", 0)
                    dropped = turn_complete_data.get("dropped", 0)
                    # At least one operation is good enough
                    json_ok = (created + updated + dropped) > 0
                    data_ops = {"created": created, "updated": updated, "dropped": dropped}
                else:
                    json_ok = False

                # Check for \n in narrative
                has_newline = "\\n" in json.dumps(full_narrative, ensure_ascii=False) or "\n" in full_narrative

                # Check narrative length (should be 200-400 Chinese chars)
                length_ok = cc_count >= 100  # min threshold, good is 200+

                # Check errors
                has_error = len(errors) > 0

                # Record result
                round_result = {
                    "round": round_num,
                    "input": user_input,
                    "narrative_length_zh": cc_count,
                    "narrative_length_total": total_chars,
                    "json_ok": json_ok,
                    "data_ops": data_ops,
                    "has_error": has_error,
                    "errors": errors,
                    "has_newline": has_newline,
                    "narrative_preview": full_narrative[:200] + "..." if len(full_narrative) > 200 else full_narrative,
                    "narrative_full": full_narrative,
                    "turn_complete": turn_complete_data is not None,
                    "pass1_tokens": turn_complete_data.get("pass1_tokens", 0) if turn_complete_data else 0,
                    "pass2_tokens": turn_complete_data.get("pass2_tokens", 0) if turn_complete_data else 0,
                    "latency_ms": turn_complete_data.get("latency_ms", 0) if turn_complete_data else 0,
                    "ending_type": turn_complete_data.get("ending_type", "none") if turn_complete_data else "none",
                }
                results.append(round_result)

                # Print summary for this round
                print(f"  字数(中文): {cc_count} | JSON ops: {json_ok} | "
                      f"turn_complete: {turn_complete_data is not None}")
                print(f"  latency: {round_result['latency_ms']}ms | "
                      f"tokens: P1={round_result['pass1_tokens']} P2={round_result['pass2_tokens']}")
                print(f"  narrative: {full_narrative[:150]}...")
                if has_error:
                    print(f"  ERRORS: {errors}")

                # Small delay between rounds
                await asyncio.sleep(1)

    except websockets.exceptions.ConnectionClosed as e:
        print(f"\n  WebSocket 连接关闭: {e}")
    except Exception as e:
        print(f"\n  Error: {e}")
        import traceback
        traceback.print_exc()

    # Step 5: Check server logs for pass1 method
    print("\n\n[4] 检查服务端日志中的 Pass1 method...")
    try:
        import glob as gb
        log_files = sorted(gb.glob("D:/project/规则怪谈/fenli/mvp/logs/turn_*.json"), reverse=True)[:10]
        pass1_methods = []
        for lf in log_files:
            try:
                with open(lf, encoding="utf-8") as fh:
                    log_data = json.load(fh)
                    p1_method = log_data.get("pass1", {}).get("method", "unknown")
                    p2_method = log_data.get("pass2", {}).get("method", "unknown")
                    turn_input = log_data.get("user_input", "")[:40]
                    pass1_methods.append((lf, p1_method, p2_method, turn_input))
            except:
                pass
        for lf, m1, m2, inp in pass1_methods:
            print(f"  {lf[-30:]}: P1={m1}, P2={m2}, input={inp}")
    except Exception as e:
        print(f"  Cannot read logs: {e}")

    # Step 6: Print full report
    print("\n\n" + "=" * 70)
    print("## v0.6.2 10轮连贯对话测试报告")
    print("=" * 70)

    print("\n| 轮次 | 字数(中) | JSON | turn_complete | 耗时ms | 备注 |")
    print("|------|----------|------|---------------|--------|------|")
    for r in results:
        json_mark = "PASS" if r["json_ok"] else "FAIL"
        tc_mark = "PASS" if r["turn_complete"] else "FAIL"
        error_note = ""
        if r["has_error"]:
            error_note = f"ERROR: {'; '.join(r['errors'][:2])}"
        ending_note = f" ending={r['ending_type']}" if r['ending_type'] != 'none' else ""
        print(f"| {r['round']} | {r['narrative_length_zh']} | {json_mark} | {tc_mark} | {r['latency_ms']} | {error_note}{ending_note} |")

    # Compute stats
    total_zh = sum(r["narrative_length_zh"] for r in results)
    avg_zh = total_zh // len(results) if results else 0
    json_success = sum(1 for r in results if r["json_ok"])
    tc_success = sum(1 for r in results if r["turn_complete"])
    has_newline_rounds = sum(1 for r in results if r["has_newline"])

    print(f"\n### 综合统计")
    print(f"- 总轮次: {len(results)}")
    print(f"- turn_complete 成功: {tc_success}/{len(results)}")
    print(f"- JSON data_ops 活跃: {json_success}/{len(results)}")
    print(f"- 平均中文叙事字数: {avg_zh}")
    print(f"- 包含换行符的轮次: {has_newline_rounds}/{len(results)}")

    print(f"\n### 每轮详细叙事")
    for r in results:
        print(f"\n--- 第{r['round']}轮 ---")
        print(f"字数(中文): {r['narrative_length_zh']} | data_ops: {r['data_ops']}")
        print(f"叙事: {r['narrative_full'][:300]}")
        if r['has_error']:
            print(f"错误: {r['errors']}")

    print(f"\n### 连贯性分析")
    print("需要在所有轮次 narratives 中检查以下要素的持续性引用:")
    print("- NPC名称一致性 (轮椅老人、黑衣护士等)")
    print("- 地点一致性 (医院一楼/二楼/地下室)")
    print("- 物品引用 (手电筒、手术刀、万能钥匙)")
    print("- 规则引用 (天黑勿视、敲门必应等)")

    # Search for coherence patterns
    all_text = " ".join(r["narrative_full"] for r in results)
    coherence_checks = [
        ("轮椅老人", "轮椅老人"),
        ("黑衣护士", "黑衣护士"),
        ("手电筒", "手电筒"),
        ("病号服", "病号服"),
        ("血月", "血月"),
        ("医院一楼", "医院一楼"),
        ("镜面", "镜面"),
    ]
    print("\n连贯性关键词出现次数:")
    for key, _ in coherence_checks:
        count = all_text.count(key)
        print(f"  '{key}': {count}次")

    print(f"\n### 换行检查")
    for r in results:
        nl_in_text = "\n" in r["narrative_full"]
        nl_in_json = "\\n" in json.dumps(r["narrative_full"], ensure_ascii=False)
        print(f"  第{r['round']}轮: 文本换行={nl_in_text}, JSON换行转义={nl_in_json}")

    print(f"\n### 发现的问题")
    issues = []
    for r in results:
        if r["has_error"]:
            issues.append(f"第{r['round']}轮报错: {r['errors']}")
        if r["narrative_length_zh"] < 80:
            issues.append(f"第{r['round']}轮叙事过短 ({r['narrative_length_zh']}字)")
        if not r["json_ok"]:
            issues.append(f"第{r['round']}轮 data_ops 无操作")
        if not r["turn_complete"]:
            issues.append(f"第{r['round']}轮未收到 turn_complete")
    if not issues:
        print("  无严重问题")
    else:
        for iss in issues:
            print(f"  - {iss}")

    # Full results JSON dump
    print("\n\n### 完整原始数据 (JSON)")
    clean_results = []
    for r in results:
        cr = {k: v for k, v in r.items() if k != "narrative_full"}
        cr["narrative_preview"] = r["narrative_full"][:500]
        clean_results.append(cr)
    print(json.dumps(clean_results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run_test())
