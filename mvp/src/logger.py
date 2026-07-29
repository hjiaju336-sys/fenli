"""
回合日志记录 — JSON 格式，便于调试面板读取
"""

import json
import os
from datetime import datetime


def save_turn_log(log: dict, log_dir: str = "logs"):
    """保存回合日志到 JSON 文件"""
    os.makedirs(log_dir, exist_ok=True)
    turn_id = log.get("turn_id", int(datetime.now().timestamp()))
    filename = os.path.join(log_dir, f"turn_{turn_id:04d}.json")

    # 截断过长的 narrative 用于日志展示
    log_copy = json.loads(json.dumps(log, ensure_ascii=False, default=str))
    if "pass2" in log_copy and "narrative" in log_copy["pass2"]:
        narrative = log_copy["pass2"]["narrative"]
        log_copy["pass2"]["narrative_preview"] = narrative[:500] + ("..." if len(narrative) > 500 else "")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(log_copy, f, ensure_ascii=False, indent=2)


def print_turn_summary(log: dict):
    """控制台输出回合摘要"""
    p1 = log.get("pass1", {})
    p2 = log.get("pass2", {})
    val = log.get("validation", {})
    per = log.get("persistence", {})

        # Windows console safe: avoid emoji and special Unicode chars
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Turn #{log.get('turn_id', '?')} | {log.get('timestamp', '')}")
    user_preview = log.get('user_input', '')[:80]
    print(f"Input: {user_preview}...")
    print(sep)
    print(f"[Pass1] tokens: {p1.get('input_tokens', '?')}+{p1.get('output_tokens', '?')} | {p1.get('latency_ms', 0):.0f}ms")
    p1_out = p1.get("output", {})
    print(f"        keep:{len(p1_out.get('keepTags', []))} fetch:{len(p1_out.get('fetchTags', []))} drop:{len(p1_out.get('dropTags', []))}")
    print(f"[Sync]  details: {log.get('hard_sync', {}).get('tag_details_count', 0)} tags {log.get('hard_sync', {}).get('memory_details_count', 0)} mems")
    print(f"[Pass2] tokens: {p2.get('input_tokens', '?')}+{p2.get('output_tokens', '?')} | {p2.get('latency_ms', 0):.0f}ms")
    print(f"[Check] {'PASS' if val.get('passed') else 'FAIL: ' + str(val.get('errors', []))}")
    print(f"[DB]    +{per.get('created', 0)} ~{per.get('updated', 0)} -{per.get('dropped', 0)}")
    narrative = p2.get("narrative", "")
    if narrative:
        print(f"[Story] {narrative[:200]}...")
    if log.get("errors"):
        print(f"[Errors] {len(log['errors'])}: {log['errors']}")
    print(f"{sep}\n")


def get_recent_context(logs: list[dict], n: int = 3) -> list[dict]:
    """从历史回合日志中提取最近N轮上下文"""
    context = []
    for log in logs[-n:]:
        context.append({"role": "user", "content": log.get("user_input", "")})
        narrative = log.get("pass2", {}).get("narrative", "")
        if narrative:
            context.append({"role": "assistant", "content": narrative})
    return context
