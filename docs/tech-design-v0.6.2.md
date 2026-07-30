# 技术方案：v0.6.2 提示词优化 + 前端渲染修复

> 版本：v1.0 | 日期：2026-07-29 | Tech Lead： | PM 确认：

## 1. 方案概述

对应 PRD v0.6.2 的 4 项改动：Pass2 prompt 重构（F1）、前端换行渲染（F2）、temperature 调整（F3）、正则加固（F4）。

改动集中在 2 个文件：
- `src/pass2.py` — F1/F3/F4
- `static/index.html` + `static/m.html` — F2

## 2. 分派方案

| Agent | 负责 | 文件 | 预估 |
|------|------|------|------|
| **Backend Agent** | F1: prompt 重构 + F3: temperature + F4: 正则 | `src/pass2.py` | 1h |
| **Web Agent** | F2: `\n` → `<br>` 渲染 | `static/index.html`, `static/m.html` | 0.5h |
| **QA Agent** | 10 轮连贯对话测试 | WebSocket | 0.5h |

## 3. F1: Pass2 System Prompt 重构

### 当前问题
- 7 段松散指令，无优先级
- 无 few-shot 示例，AI 凭空猜格式
- narrative 字段规范未强调 JSON 转义

### 新 Prompt 结构

```
[角色] 1 句话
[输出格式] JSON 模板 + 完整 few-shot 示例（含 narrative 内 \n 正确转义为 \\n）
[叙事规范] 字数 / 视角 / 禁止项 / 换行用 \n
[数据操作] create/update/drop 字段清单
[规则 & 结局] 保留原有逻辑
[角色行为] 保留原有逻辑
[字段规范] 保留原有映射
```

### Few-shot 示例要点

示例必须展示：
- narrative 字段内 `\n` 的正确 JSON 转义：`"推开门。\n\n走廊里一片漆黑。\n你摸到了开关。"` 
- data_ops 中 create 的完整字段
- 中文引号 `「」` 可正常使用（不需要转义）

### Temperature

第 215 行：`temperature=0.8` → `temperature=0.7`

## 4. F2: 前端 \n 渲染

### 问题定位

`index.html:1012`：
```javascript
bub.textContent += d.text;  // \n 不渲染为换行
```

### 方案：流式阶段收集，turn_complete 时统一转换

**流式阶段**（narrative_chunk）：保持 `textContent` 追加不变（流式时换行在 chunk 边界会被截断，实时转 `<br>` 会产生闪烁）。

**turn_complete 时**（index.html:1005-1006）：在 `highlightQuotes` 之前，先将 `data-raw` 中的 `\n` 替换为 `<br>`，再走引号高亮。

```javascript
// 在 highlightQuotes 之前
var formatted = raw.replace(/\n/g, '<br>');
aiBubbles[bi].innerHTML = highlightQuotes(formatted);
```

同时 `escHTML` 先于 `\n→<br>`，保证 XSS 安全。

### 存档恢复（line 991）

同样逻辑：AI 气泡的 `sm.content` 先 `escHTML` → 再 `\n→<br>` → 再走 `highlightQuotes`。

### 移动端同步

检查 m.html 中对应的 narrative 渲染逻辑，同样修复。

## 5. F4: 正则加固

`pass2.py:170`：
```python
# 改前
nar_match = re.search(r'"narrative"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned, re.DOTALL)

# 改后：允许 \n \r \t 等转义
nar_match = re.search(r'"narrative"\s*:\s*"(.*?)"(?=\s*[,}])', cleaned, re.DOTALL)
```

更安全的提取：先找到 `"narrative": "`，然后匹配到下一个 `",` 或 `"}`（JSON 字段分隔符）。

## 6. QA 测试要求 🔴

**核心验收：同一副本连续 10 轮对话**

```
第 1 轮：建立场景认知（观察环境）
第 2 轮：与 NPC 互动
第 3 轮：探索/移动
第 4 轮：触发规则/事件
第 5 轮：应对规则后果
第 6 轮：发现线索
第 7 轮：角色关系发展
第 8 轮：面临选择
第 9 轮：选择后果
第 10 轮：阶段性结局/过渡
```

每轮验收：
- [ ] JSON 解析成功（无 fallback 触发）
- [ ] narrative 包含有意义的剧情推进（非敷衍、非重复）
- [ ] 正确引用前面建立的信息（NPC 名字、位置、规则）
- [ ] 前端显示正常（换行、引号高亮）

## 7. 执行顺序

```
Backend Agent (F1+F3+F4) ──→ Web Agent (F2) ──→ QA Agent (10轮测试)
       1h                          0.5h                   0.5h
```

Web Agent 依赖 Backend 完成（需要新 prompt 产出的 narrative 格式来验证前端渲染）。
