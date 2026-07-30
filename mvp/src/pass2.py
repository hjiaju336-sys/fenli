"""
Pass 2: AI-2 剧情生成 + 数据操作

输入: 用户输入 + 未总结上下文 + 格式化后的召回标签详情 + 记忆详情
输出: 流式叙事 narrative + 结构化 data_ops (create/update/drop)
"""

import json
import re
from ai_provider import AIProvider, StreamResult, resolve_model

PASS2_SYSTEM_PROMPT = """你是无限流规则怪谈游戏的叙事引擎。输出严格JSON，生成第二人称沉浸式剧情。

## 输出格式（严格JSON，无其他文本）
{"narrative":"...","data_ops":{"create":[...],"update":[...],"drop":[...]}}

## 示例
输入：玩家说「我推开病房的门」
输出：
{"narrative":"你伸手推开病房的门，吱呀一声，门轴发出刺耳的呻吟。\\n\\n房间里弥漫着消毒水的气味，窗帘半掩，月光在地板上投下惨白的格子。\\n\\n病床上，一个身影缓缓坐了起来。","data_ops":{"create":[{"tag_name":"月光病房","category":"map","tag_hint":"废弃的病房，月光透过窗帘","tag_detail":{"表面描述":"一间废弃已久的病房，墙皮剥落","隐藏信息":"这间病房曾住过一个自杀的病人，月圆之夜会有怪事发生","所属副本":"血月医院","相连区域":"走廊","危险等级":"中"}}],"update":[{"tag_name":"护士长","category":"character","tag_detail":{"当前位置":"月光病房","当前意图":"质问闯入者","对玩家的态度":"敌意"}}],"drop":[]}}

## 叙事规范
- 第二人称「你」，200-400字，信息密度优先，避免冗长描写
- **禁止** narrative 中出现未转义的双引号 `"` —— 引用与对话必须使用中文引号「」
- **禁止** narrative 中出现未转义的反斜杠 `\\`
- **禁止** 输出 JSON 以外的任何文本（不要输出「好的，以下是...」等开场白）
- 换行用 `\\n`，段落间距用 `\\n\\n`
- 自然融入已解锁的记忆信息，不要让角色突然知道未获取的信息
- 场景切换、角色登场/退场、物品变化必须通过 data_ops 反映

## 数据操作规范
- create: 新实体，必须包含 tag_name / category / tag_hint（15字以内）/ tag_detail（完整对象，所有字段必须写全）
- update: 已有实体的 tag_detail 必须写完整对象（全量覆盖），**不能只写变化的字段**
- drop: 实体退场时使用，只需 ["tag_name1", "tag_name2", ...] 字符串数组

## 规则执行
检查「生效规则」的 triggers → 匹配则严格按 consequence 执行（扣血/扣理智/强制移动/即死等）

## 结局检测
通关条件达成 → "ending_type":"victory"；血量≤0 或 理智≤0 → "ending_type":"death"；特殊逃脱 → "ending_type":"escape"

## 角色行为
- NPC 严格遵守自身的「说话风格」和「口头禅」，绝不说「禁止说」中的内容
- 好感度驱动行为：>60 主动帮助，<30 回避；信任 >70 分享秘密，<20 可能说谎
- 态度变化时必须在 data_ops 中 update 角色

## 字段规范
- character: 是否玩家 / 角色类型 / 所属副本 / 当前位置 / 血量 / 理智 / 外貌 / 行为逻辑 / 持有物品 / 当前意图 / 对玩家的态度
- item: 所属副本 / 物品类型 / 表面描述 / 隐藏信息 / 所在位置 / 效果
- map: 所属副本 / 表面描述 / 隐藏信息 / 相连区域 / 危险等级
- rule: 所属副本 / 发现程度 / 细则列表（名称 / 条文内容 / 细则解释 / 触发条件 / 触发后果 / 优先级）
- world: 表面介绍 / 隐藏真相 / 入口条件 / 通关条件
- category: world / map / rule / character / item"""

PASS2_USER_TEMPLATE = """## 玩家行动
{user_input}

## 近期对话
{recent_context}

## 世界状态
{world_context}

---
基于以上信息，生成剧情叙事。输出纯JSON。
**重要：每轮必须通过 data_ops 反映当前回合发生的任何新事实，包括但不限于：新地点、新物品、新角色、状态变化。即使没有新实体，也必须至少 update 某个现有标签来反映环境或状态的变化。data_ops 不能为空。**"""


def _build_hooks_section(hooks: list[dict]) -> str:
    """为 ai_trigger 类型的 hook 生成 prompt 段落"""
    if not hooks:
        return ""
    ai_trigger_hooks = [h for h in hooks if isinstance(h, dict)
                        and isinstance(h.get("trigger"), dict)
                        and h["trigger"].get("type") == "ai_trigger"
                        and h.get("id", "").strip()]
    if not ai_trigger_hooks:
        return ""
    ids_list = []
    for h in ai_trigger_hooks:
        hid = h.get("id", "")
        # 尝试从第一个效果中提取描述
        effects = h.get("effects", [])
        desc = ""
        if isinstance(effects, list) and len(effects) > 0:
            first = effects[0]
            if isinstance(first, dict):
                desc = first.get("params", {}).get("name", "") or first.get("type", "")
        line = f"- {hid}" + (f": {desc}" if desc else "")
        ids_list.append(line)
    return f"""
## 可用事件触发标识
剧情到达以下关键节点时，在回复末尾的 ---HOOKS--- 区域输出对应的标识名列表（JSON数组）。不确定则输出空数组 []。

{chr(10).join(ids_list)}

示例输出:
---HOOKS---
["blood_moon_first", "nurse_encounter"]

注意:
- ---HOOKS--- 独立于JSON之外，不要放进data_ops
- 标识名必须精确匹配上述列表
- 只在剧情确实到达对应节点时才输出
"""


def build_pass2_prompt(
    user_input: str,
    world_context: str,
    recent_context: list[dict] = None,
    hooks: list[dict] = None,
) -> str:
    """构造 AI-2 的完整 prompt"""
    ctx_text = ""
    if recent_context:
        lines = []
        for msg in recent_context[-10:]:
            role = "玩家" if msg["role"] == "user" else "剧情"
            lines.append(f"{role}: {msg['content'][:300]}")
        ctx_text = "\n".join(str(x) for x in lines if x is not None)

    base_prompt = PASS2_USER_TEMPLATE.format(
        user_input=user_input,
        recent_context=ctx_text or "(无)",
        world_context=world_context,
    )

    # 追加 ai_trigger hooks 说明
    hooks_section = _build_hooks_section(hooks or [])
    if hooks_section:
        base_prompt += hooks_section

    return base_prompt


def _extract_hooks(raw_text: str) -> tuple[str, list[str]]:
    """从 raw_output 中分离 ---HOOKS--- 区域，返回 (json_text, ai_triggers)"""
    hooks_marker = "---HOOKS---"
    if not raw_text or hooks_marker not in raw_text:
        return raw_text or "", []
    parts = raw_text.split(hooks_marker, 1)
    json_part = parts[0].strip()
    hooks_part = parts[1].strip()
    ai_triggers = []
    try:
        parsed = json.loads(hooks_part)
        if isinstance(parsed, list):
            ai_triggers = [str(x) for x in parsed if x]
    except json.JSONDecodeError:
        # 尝试正则提取数组
        arr_match = re.search(r'\[([^\]]*)\]', hooks_part)
        if arr_match:
            items = [s.strip().strip('"').strip("'") for s in arr_match.group(1).split(",") if s.strip()]
            ai_triggers = [i for i in items if i]
    return json_part, ai_triggers


def parse_ai2_output(text: str) -> dict:
    """解析 AI-2 的 JSON 输出，处理常见格式问题"""
    # 去除 ```json ... ``` 包裹
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # 去掉第一行 ```json 和最后一行 ```
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    # 截取最外层 JSON 对象（处理推理模型的 reasoning_content 前缀）
    # 找到第一个 { 和最后一个 }，丢弃前面的思考文字和后面的 HOOKS 等非 JSON 内容
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start != -1 and end != -1 and start < end:
        cleaned = cleaned[start:end + 1]

    # 尝试 JSON 解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: 正则提取
    result = {"narrative": "", "data_ops": {"create": [], "update": [], "drop": []}}

    # 提取 narrative: 先找到 "narrative": "，然后找下一个未转义的 " 后跟 , 或 }
    m = re.search(r'"narrative"\s*:\s*"', cleaned)
    if m:
        start = m.end()
        # 从 start 开始找未转义的 " 后跟 , 或 }
        end_match = re.search(r'(?<!\\)"(?=\s*[,}])', cleaned[start:])
        if end_match:
            result["narrative"] = cleaned[start:start + end_match.start()]

    # 提取 data_ops（如果 narrative 提取成功，说明基本格式是对的）
    ops_match = re.search(r'"data_ops"\s*:\s*(\{.*?\})\s*\}', cleaned, re.DOTALL)
    if ops_match:
        try:
            ops = json.loads(ops_match.group(1))
            result["data_ops"] = ops
        except json.JSONDecodeError:
            pass

    return result


async def run_pass2(
    provider: AIProvider,
    api_key: str,
    user_input: str,
    world_context: str,
    model_name: str = None,
    recent_context: list[dict] = None,
    hooks: list[dict] = None,
) -> dict:
    """
    执行 Pass 2，返回:
    {
      narrative: str,
      data_ops: {create, update, drop},
      input_tokens, output_tokens, latency_ms,
      raw_output: str,
      stream_chunks: int,
      ai_triggers: list[str]
    }
    """
    model = resolve_model(api_key, model_name, "large")
    prompt = build_pass2_prompt(user_input, world_context, recent_context, hooks)

    # 使用流式调用获取叙事
    stream: StreamResult = await provider.chat_stream(
        model=model,
        system=PASS2_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=16384,
        temperature=0.7,
    )

    # 消费流式，收集完整文本
    result = await stream.collect()

    # 分离 ---HOOKS--- 区域
    json_text, ai_triggers = _extract_hooks(result.text)

    # 解析 JSON
    parsed = parse_ai2_output(json_text)

    data_ops = parsed.get("data_ops", {"create": [], "update": [], "drop": []})
    if not isinstance(data_ops, dict):
        data_ops = {"create": [], "update": [], "drop": []}
    return {
        "narrative": parsed.get("narrative", ""),
        "data_ops": data_ops,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "latency_ms": result.latency_ms,
        "raw_output": result.text,
        "ai_triggers": ai_triggers,
    }
