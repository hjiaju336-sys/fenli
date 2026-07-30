# PRD：v0.6.2 提示词稳定性优化 + 前端渲染修复

> 版本：v1.0 | 日期：2026-07-29 | 状态：待老板审核 | PM 签字：PM 暂代 🐾

## 1. 背景与调研

### 问题现象

老板反馈当前系统存在两个核心问题：

1. **AI 叙事不稳定**：连续多轮对话中，AI 输出质量波动大，逻辑断裂，无法稳定跑完 10 轮连贯对话
2. **前端显示异常**：AI 返回的 `\n` 换行符在前端没有渲染为换行，所有文字挤成一段

### 根因分析（已确认）

PM 调查后定位到以下不稳定因素：

| # | 因素 | 影响 | 严重度 |
|------|------|------|--------|
| **A** | Pass2 prompt 结构松散 | AI 常忘记输出 JSON 格式、忘记字段规范、narrative 中出现未转义换行破坏 JSON | 🔴 |
| **B** | 叙事长度约束矛盾 | "200-500 字"但"信息密度优先"→ AI 有时输出 600+ 字，有时 50 字敷衍 | 🟡 |
| **D** | 前端 textContent 不渲染换行 | `narrative_chunk` 用 `textContent` 拼接，`\n` 被当纯文本显示 | 🔴 |
| **E** | JSON 内嵌 narrative 转义不完整 | `parse_ai2_output` 的正则 fallback `[^"\\]` 在遇到 `\n"` 等组合时截断 narrative | 🟡 |
| **F** | temperature=0.8 偏高 | 叙事类任务 0.8 导致输出格式波动 | 🟡 |
| **G** | 缺少输出示例 | AI 没有参考样本，每次凭空猜测 data_ops 字段格式 | 🟡 |

> 注：上下文截断不是问题——Pass1 召回 + Summary 记忆系统设计的初衷就是用小模型召回替代长上下文，实现伪无限记忆。`recent_context[-10:]` 保留最近对话节奏感即可，历史细节由记忆系统补充。

## 2. 目标用户

- **直接用户**：玩家（获得稳定、连贯的游戏体验）
- **间接受益者**：老板（API 调用不浪费在格式错误的重试上）

## 3. 核心目标与成功指标

| 目标 | 衡量标准 |
|------|----------|
| 10 轮连贯对话 | 同一副本内连续 10 轮，AI 正确引用前文、角色/NPC/规则一致、无逻辑断裂 |
| 前端正常显示 | `\n` → 换行、`\n\n` → 段落间距、JSON 内嵌换行正确转义 |
| 格式稳定 | 20 轮测试中 JSON 解析成功率为 100%（当前的 `parse_ai2_output` 已处理大部分异常，目标是不需要 fallback） |
| Pass1 召回稳定 | 10 轮内标签 keep/fetch 决策一致，不会出现"前一轮 keep 的角色下一轮莫名 drop" |

## 4. 功能范围

### P0 — 必须修

#### F1：Pass2 System Prompt 重构 🔴

**问题**：当前 prompt 用「输出纯JSON」「叙事」「数据操作」「规则执行」「结局检测」「角色行为」「字段规范」7 个松散的段落堆砌指令，缺乏优先级、缺乏示例、缺乏错误预防。

**目标**：重写为结构化 prompt，包含：
- 角色定义（一句话）
- 输出格式（带完整示例，含 `\n` 在 JSON string 中的正确转义 `\\n`）
- 叙事规范（字数、视角、禁止项）
- 数据操作规范（create/update/drop 的字段清单）
- **1-2 个 few-shot 示例**：展示一个完整的输入→输出对

**验收标准**：
- [ ] 新 prompt 包含至少 1 个完整的 JSON 输出示例（含 narrative + data_ops）
- [ ] prompt 中明确禁止 narrative 中出现未转义的换行符和双引号
- [ ] 20 轮测试 JSON 解析成功率 = 100%

#### F2：前端 narrative 换行渲染 🔴

**问题**：`index.html:1012` 用 `bub.textContent += d.text` 拼接流式 chunk。`textContent` 不解析 HTML，`\n` 原样显示。

同时 `index.html:991` 在加载存档恢复消息时，AI 气泡用 `highlightQuotes(sm.content)` 返回的是 `escHTML` 处理后的文本，也不渲染换行。

**目标**：
- 流式接收时，将 `\n` 替换为 `<br>`，改用 `innerHTML` 追加（但要防 XSS）
- 或者：保持 textContent 追加，在 turn_complete 时统一做 `\n` → `<br>` 替换
- `highlightQuotes` 中增加换行处理

**验收标准**：
- [ ] AI 输出中的 `\n` 在前端正确显示为换行
- [ ] 连续两个 `\n\n` 显示为段落间距
- [ ] 不引入 XSS（HTML 标签仍被转义）

### P1 — 应该修

#### F3：prompt 参数调整 🟡

**问题**：`temperature=0.8` 对叙事任务偏高，导致格式波动。叙事可以 0.7-0.8 但 JSON 结构部分应更稳定。

**目标**：
- Pass2 temperature 从 0.8 降为 0.7
- Pass1 temperature 保持 0.3（检索任务，低温度合理 ✅）
- 或者拆分：narrative 用 0.8，data_ops 结构走单独约束

**验收标准**：
- [ ] 10 轮测试中无 JSON 格式错误

#### F4：parse_ai2_output 正则加固 🟡

**问题**：`pass2.py:170` 的 fallback 正则是 `r'"narrative"\s*:\s*"((?:[^"\\]|\\.)*)"'`——遇到 `"narrative": "...\n..."` 时，`\n` 之后的 `"` 会提前终止匹配，导致 narrative 被截断。

**目标**：让正则支持 `\n`、`\r`、`\t` 等 JSON 转义序列。

**验收标准**：
- [ ] 包含 `\n` 的 narrative 在 JSON 解析失败时，正则 fallback 也能完整提取
- [ ] 不会误匹配到 data_ops 部分的引号

---

## 5. 用户流程

```
玩家输入 → Pass1 召回 → Pass2 叙事（新 prompt）
       → 流式推送 → 前端 textContent 收集
       → turn_complete → \n → <br> → innerHTML 渲染
       → 玩家看到带换行的流畅叙事
```

---

## 6. 多端差异

- **桌面端 (index.html)**：F2 改动涉及 `handleWS` 函数的 `narrative_chunk` 分支 + turn_complete 的 re-render 逻辑
- **移动端 (m.html)**：需同步修复 narrative 渲染（m.html 可能共用或复制了 handleWS 逻辑）

---

## 7. 非功能需求

| 维度 | 要求 |
|------|------|
| 稳定性 | 连续 20 轮 JSON 解析无 fallback 触发 |
| 安全性 | 前端 `\n` → `<br>` 转换后仍保持 `escHTML` 防护，不可引入 XSS |
| 兼容性 | Pass2 prompt 对 DeepSeek/Anthropic/OpenAI 均适用 |
| 性能 | prompt 改动不影响单轮延迟（不增加 token 预算） |

---

## 8. 风险与假设

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Few-shot 示例可能导致 AI 过度模仿 | 每轮 narrative 结构雷同 | 示例强调"格式参考，内容创造" |
| `\n` → `<br>` 在流式渲染中闪烁 | 换行位置每次 chunk 边界不同 | 流式阶段不转换，turn_complete 后统一替换 |
| 温度降低 → 叙事缺乏创造性 | 剧情变得平淡 | 先用 0.7 试，如果太死板回调到 0.75 |

---

## 9. 附录

### A. 问题代码位置

| 文件 | 行号 | 问题 |
|------|------|------|
| `src/pass2.py` | 12-44 | PASS2_SYSTEM_PROMPT 结构松散 |
| `src/pass2.py` | 46-56 | PASS2_USER_TEMPLATE 缺少格式化约束 |
| `src/pass2.py` | 106-110 | 上下文截断粗暴 (300char × 10) |
| `src/pass2.py` | 170 | 正则 fallback 不支持转义换行 |
| `src/pass2.py` | 215 | temperature=0.8 |
| `static/index.html` | 1012 | textContent 不渲染 \n |
| `static/index.html` | 991 | 存档恢复的 AI 气泡也未处理换行 |
| `static/m.html` | - | 需同步检查 |

---

> 🐾 PM 代签，老板审核通过后移交 Tech Lead 出技术方案。
