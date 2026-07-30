# -*- coding: utf-8 -*-
import asyncio
import json
import websockets
import time
import sys
import io

# Fix Windows GBK encoding issue
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

TOKEN = "eyJhbGciOiAiSFMyNTYiLCAidHlwIjogIkpXVCJ9.eyJwaWQiOiAidTAwMSIsICJuYW1lIjogImFkbWluIiwgImV4cCI6IDE3ODc5MjI0MzZ9.mCl5PfIm9hMzRAKJQEkjJWdNJhiHiaBxEB_ta7TmCn0"
API_KEY = "sk-6faaf8d1366b4e979339dc1fbeb4fdc6"
MODEL_SMALL = "deepseek-v4-flash"
MODEL_LARGE = "deepseek-v4-flash"
WS_URL = "ws://localhost:8777/ws"

test_inputs = [
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


async def run_test():
    url = f"{WS_URL}?token={TOKEN}"
    async with websockets.connect(url, ping_interval=30, ping_timeout=60) as ws:
        print("=== WS Connected ===")

        # Wait for init_state
        init_msg = await asyncio.wait_for(ws.recv(), timeout=30)
        init_data = json.loads(init_msg)
        print("=== init_state received ===")
        print(f"  world_name: {init_data.get('world_name', 'N/A')}")
        print(f"  opening_monologue: {(init_data.get('opening_monologue', '') or '')[:80]}...")
        print(f"  hotTags count: {len(init_data.get('hotTags', []))}")
        print(f"  hotMemories count: {len(init_data.get('hotMemories', []))}")
        print(f"  hooks count: {len(init_data.get('hooks', []))}")

        results = []

        for round_num, user_input in enumerate(test_inputs, 1):
            print(f"\n--- Round {round_num}: {user_input} ---")
            start_time = time.time()

            # Send user_turn
            turn_msg = {
                "type": "user_turn",
                "apiKey1": API_KEY,
                "apiKey2": API_KEY,
                "userInput": user_input,
                "modelSmall": MODEL_SMALL,
                "modelLarge": MODEL_LARGE,
                "nValue": 5,
            }
            await ws.send(json.dumps(turn_msg))

            # Collect narrative chunks + wait for turn_complete
            narrative_parts = []
            turn_complete_data = None
            hook_effects = []

            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=120)
                    msg = json.loads(raw)
                    msg_type = msg.get("type", "")

                    if msg_type == "narrative_chunk":
                        narrative_parts.append(msg.get("text", ""))

                    elif msg_type == "turn_complete":
                        turn_complete_data = msg
                        break

                    elif msg_type == "hook_effects":
                        hook_effects.extend(msg.get("effects", []))

                    elif msg_type == "error":
                        print(f"  [ERROR] {msg.get('message', '')}")
                        break

                    elif msg_type == "cancelled":
                        print(f"  [CANCELLED]")
                        break

                    else:
                        print(f"  [OTHER] type={msg_type}")

            except asyncio.TimeoutError:
                print(f"  [TIMEOUT] No response within 120s")
                results.append({
                    "round": round_num, "input": user_input,
                    "narrative_len": 0, "created": 0, "updated": 0, "dropped": 0,
                    "coherent": "TIMEOUT", "notes": "Timeout after 120s",
                })
                continue

            narrative = "".join(narrative_parts)
            elapsed = time.time() - start_time

            if turn_complete_data:
                created = turn_complete_data.get("created", 0)
                updated = turn_complete_data.get("updated", 0)
                dropped = turn_complete_data.get("dropped", 0)
                ending_type = turn_complete_data.get("ending_type", "none")
                latency = turn_complete_data.get("latency_ms", 0)
                raw_pass2 = turn_complete_data.get("raw_output_pass2", "")

                data_ops_total = created + updated + dropped
                if data_ops_total == 0 and len(narrative) == 0:
                    coherent = "EMPTY_OUTPUT"
                elif data_ops_total == 0:
                    coherent = "NO_DATA_OPS"
                elif len(narrative) < 100:
                    coherent = "NARRATIVE_TOO_SHORT"
                else:
                    coherent = "OK"

                notes = f"latency={latency}ms, ending={ending_type}"
                if len(hook_effects) > 0:
                    notes += f", hooks={len(hook_effects)}"

                results.append({
                    "round": round_num, "input": user_input,
                    "narrative_len": len(narrative),
                    "created": created, "updated": updated, "dropped": dropped,
                    "coherent": coherent, "notes": notes,
                    "narrative_preview": narrative[:100],
                    "raw_output_pass2": raw_pass2 if (data_ops_total == 0 or len(narrative) == 0) else "",
                })

                print(f"  narrative: {len(narrative)} chars")
                print(f"  data_ops: C={created} U={updated} D={dropped}")
                print(f"  coherent: {coherent}")
                print(f"  elapsed: {elapsed:.1f}s {notes}")
            else:
                results.append({
                    "round": round_num, "input": user_input,
                    "narrative_len": len(narrative), "created": 0, "updated": 0, "dropped": 0,
                    "coherent": "NO_TURN_COMPLETE",
                    "notes": f"No turn_complete received, narrative_chunks={len(narrative_parts)}",
                })

        # Print summary table
        print("\n" + "=" * 100)
        print("SUMMARY TABLE")
        print("=" * 100)
        print(f"{'Round':<6} {'Narrative':>10} {'C':>5} {'U':>5} {'D':>5} {'Ops?':<6} {'Coherent':<16} Preview")
        print("-" * 100)

        total_data_ops_rounds = 0
        for r in results:
            has_ops = "YES" if (r["created"] + r["updated"] + r["dropped"]) > 0 else "NO"
            if has_ops == "YES":
                total_data_ops_rounds += 1
            preview = r.get("narrative_preview", "")[:60]
            print(f"  {r['round']:<4} {r['narrative_len']:>8}字 {r['created']:>4} {r['updated']:>4} {r['dropped']:>4} {has_ops:<6} {r['coherent']:<16} {preview}")

        print("-" * 100)
        print(f"\n  data_ops present: {total_data_ops_rounds}/10 rounds")
        print(f"  All 10 have data_ops: {'YES [PASS]' if total_data_ops_rounds == 10 else 'NO [FAIL]'}")

        # Print raw_output for failed rounds
        failed_rounds = [r for r in results if r.get("raw_output_pass2")]
        if failed_rounds:
            print("\n=== FAILED ROUNDS RAW OUTPUT ===")
            for r in failed_rounds:
                print(f"\n  Round {r['round']}: {r['input']}")
                raw = r.get("raw_output_pass2", "")
                print(f"  raw_output length: {len(raw)}")
                print(f"  raw_output: {raw}")


if __name__ == "__main__":
    asyncio.run(run_test())
