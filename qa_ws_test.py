import asyncio
import json
import httpx
import websockets

async def test():
    # ========== 1. 登录获取 token ==========
    async with httpx.AsyncClient() as c:
        r = await c.post(
            'http://162.14.64.4:8777/api/auth/login',
            json={'username': 'admin', 'password': 'root'}
        )
        print(f"Login status: {r.status_code}")
        resp = r.json()
        token = resp['token']
        print(f"Token obtained: {token[:20]}...")

    # ========== 2. WebSocket 连接 ==========
    uri = f'ws://162.14.64.4:8777/ws?token={token}'
    async with websockets.connect(uri) as ws:
        # 接收初始化消息
        init_raw = await asyncio.wait_for(ws.recv(), timeout=30)
        init = json.loads(init_raw)
        print(f"World: {init.get('world_name', 'N/A')}")
        print(f"Tags count: {len(init.get('hotTags', []))}")
        print(f"Init keys: {list(init.keys())}")
        print()

        # ========== 3. 三轮对话测试 ==========
        inputs = [
            "我睁开眼睛，观察周围的环境",
            "查看房间里的物品和细节",
            "尝试打开门，看看外面是什么"
        ]

        for i, msg in enumerate(inputs):
            print(f"{'='*60}")
            print(f"Round {i+1}: sending: {msg}")
            print(f"{'='*60}")

            turn = json.dumps({
                'type': 'user_turn',
                'userInput': msg,
                'apiKey1': 'sk-6faaf8d1366b4e979339dc1fbeb4fdc6',
                'apiKey2': 'sk-6faaf8d1366b4e979339dc1fbeb4fdc6',
                'modelSmall': 'deepseek-v4-flash',
                'modelLarge': 'deepseek-v4-flash',
                'nValue': 5,
                'myWorldBook': []
            })
            await ws.send(turn)

            narrative = ''
            chunk_count = 0
            turn_complete = None

            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                data = json.loads(raw)

                if data.get('type') == 'narrative_chunk':
                    narrative += data.get('text', '')
                    chunk_count += 1
                elif data.get('type') == 'turn_complete':
                    turn_complete = data
                    c_val = data.get('created', 0)
                    u_val = data.get('updated', 0)
                    d_val = data.get('dropped', 0)
                    print(f"  narrative_chunks: {chunk_count}")
                    print(f"  narrative length: {len(narrative)} chars")
                    print(f"  data_ops -> created={c_val}, updated={u_val}, dropped={d_val}")
                    print(f"  turn_complete keys: {list(data.keys())}")
                    # 验证项
                    checks = []
                    checks.append(("chunks>0", chunk_count > 0))
                    checks.append(("narrative>100", len(narrative) > 100))
                    ops_ok = not (c_val == 0 and u_val == 0 and d_val == 0)
                    checks.append(("data_ops_nonzero", ops_ok))
                    checks.append(("turn_complete_exists", turn_complete is not None))
                    for name, passed in checks:
                        status = "PASS" if passed else "FAIL"
                        print(f"  [{status}] {name}")
                    # 打印 narrative 前100字
                    print(f"  narrative preview: {narrative[:150]}...")
                    print()
                    break
                elif data.get('type') == 'error':
                    print(f"  ERROR: {data.get('message')}")
                    return

        # ========== 4. 连贯性评估 ==========
        print(f"{'='*60}")
        print("ALL 3 ROUNDS COMPLETED")
        print(f"{'='*60}")

asyncio.run(test())
