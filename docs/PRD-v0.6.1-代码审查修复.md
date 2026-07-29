# PRD：v0.6.1 稳定性修复 — 恢复 AI 召回 + 前端 Bug 清零

> 版本：v1.1 | 日期：2026-07-29 | 状态：待老板审核 | PM 签字：PM 暂代 🐾

## 1. 背景与调研

### 为什么做这个？

老板接手项目后发现上一轮团队交付质量不佳，经 PM 实地验证（启动服务器 + WebSocket 全链路测试），确认以下事实：

- ✅ 核心游戏循环能跑（WebSocket → AI 叙事 → 返回客户端）
- ❌ 但 `orchestrator.py` 用简陋关键词匹配替代了 AI 召回，pass1.py 被架空
- ❌ 另外存在 4 个前端/稳定性 Bug

### 召回系统设计意图（老板确认）

```
用户输入 → Pass1 (便宜小模型) 读全部标签 hint → 智能输出 keep/fetch/drop
       → Hard Sync (免费 SQL) 按 fetch 拉详细信息
       → Pass2 (贵的大模型) 只吃相关上下文 → 生成叙事
```

**核心目的：帮老板省钱 💸**。用小模型少量 token 做召回，换大模型不吃全库。游戏越久标签越多，不做召回的话 Pass2 token 消耗会线性膨胀。关键词匹配虽然免费，但中文语义理解太差，召不准 → 漏信息 → Pass2 生成质量差 → 浪费大模型 token。

`pass1.py` 是正确方案，`_keyword_recall()` 是上一轮团队半途而废留下的半成品。

### 验证过程

PM 实际执行了以下验证（2026-07-29）：
1. 启动服务器，确认 FastAPI + MySQL 正常运行
2. 测试登录/预设/存档/云端副本 API 全部通过
3. 通过 WebSocket 完成 1 轮完整游戏对话（AI 正常返回 282 字中文叙事）
4. 逐文件审查 `orchestrator.py`、`pass1.py`、`pass2.py`、`ai_provider.py`、`server.py`、`index.html`

---

## 2. 目标用户

- **直接用户**：Tech Lead Agent（接收需求并分派执行）
- **间接受益者**：玩家（更好的剧情体验）、老板（产品质量提升）

---

## 3. 核心目标与成功指标

| 目标 | 衡量标准 |
|------|----------|
| 恢复 AI 召回，降低 Pass2 token | 单轮 Pass2 input tokens 相比"全库喂入"节省 ≥ 40% |
| 消灭流式空内容崩溃 | 发送 20 轮 v4 模型对话，0 次 NoneType 崩溃 |
| Token 过期不丢数据 | 过期 token 请求不写入 NULL player_id |
| 弹窗不叠加 | 连续触发 5 次弹窗，页面只存在 1 个 overlay |
| 全流程回归通过 | 桌面端 + 移动端 5 轮对话无报错 |

---

## 4. 功能范围

### P0 — 必须修（阻塞上线）

#### F1：恢复 AI Pass1 标签召回 🔴🔴🔴

**为什么这是省钱功能**：游戏越久标签越多（角色/物品/地图/规则/记忆持续累积），不做召回 Pass2 就得吃全库 → token 线性膨胀。用小模型（deepseek-v4-flash，便宜）做一次召回，选出真正相关的标签，让大模型（deepseek-v4-pro，贵）只吃压缩后的上下文。单轮 Pass1 成本 ≈ 0.5-1K token，但能帮 Pass2 省掉 5-10K token 的全库开销。

**现状**：`orchestrator.py:70-82` 的 `_keyword_recall()` 按空格分词 + N-gram 子串匹配。中文不分词（"推开病房的门" → 按空格 split 后是一整坨），语义理解为零。`pass1.py:75-122` 有完整实现的 `run_pass1()`（含 prompt、JSON 解析、解析失败回退）但从未被调用。

**验收标准**：
- [ ] `orchestrator.py` 的 `process_turn_async()` 调用 `pass1.run_pass1()` 替代 `_keyword_recall()`
- [ ] Pass1 使用 `model_small`（用户配置的便宜模型），不额外消耗大模型额度
- [ ] AI Pass1 返回的 keepTags / fetchTags / dropTags / keepMemories / fetchMemories 正确传入 hard_sync
- [ ] 当 Pass1 AI 调用失败时，自动回退到 `_keyword_recall()` 作为 fallback（保留现有代码）
- [ ] Pass1 的 token 消耗和延迟记录到 turn log，方便老板审计成本
- [ ] 20 轮压力测试：Pass2 input tokens 相比不做召回的全库模式节省 ≥ 40%

**优先级**：P0 — 直接影响老板的 API 账单

---

#### F2：修复流式空 content 崩溃 🟡

**用户故事**：作为玩家，当我使用 DeepSeek v4 系列模型时，不应该因为 AI 返回了 `reasoning_content` 而没有 `content` 导致游戏崩溃。

**现状**：`ai_provider.py` 中 DeepSeek 和 OpenAI 的流式处理，当 delta 只有 `reasoning_content` 时，`delta["content"] or ""` 会 yield 空字符串。`StreamResult.collect()` 不过滤空字符串，可能导致下游 join 出问题。

**验收标准**：
- [ ] `StreamResult.collect()` 过滤空字符串（`if chunk` 改为 `if chunk is not None and chunk != ""`）
- [ ] DeepSeek provider 流式处理：当 content 为 null/空时跳过，不 yield 空字符串
- [ ] Anthropic provider 流式处理同样加保护
- [ ] 用 DeepSeek v4-flash 连续 20 轮对话，0 次崩溃

**优先级**：P0 — 影响使用 v4 模型的全部用户

---

#### F3：Token 过期全局拦截 🟡

**用户故事**：作为玩家，当我的登录过期时，应该看到友好的"登录已过期，请重新登录"提示，而不是数据悄无声息地写入失败或页面跳转异常。

**现状**：`server.py:670-681` 的 `_pid()` 在 token 无效时抛出 401。前端没有全局 fetch 拦截器，每个 API 调用的 401 响应处理不一致。`index.html:494` 的 `_auth()` 直接返回可能过期的 token。

**验收标准**：
- [ ] 前端封装一个 `_fetch(url, opts)` 函数，统一处理 401 → 清除 token → 跳转登录页
- [ ] `_pid()` 返回 None 时（非鉴权接口），不写入 NULL player_id
- [ ] 登录页显示"登录已过期，请重新登录"提示
- [ ] 所有现有 fetch 调用逐步迁移到 `_fetch`（本次至少覆盖游戏核心流程的调用）

**优先级**：P0 — 数据安全

---

### P1 — 应该修（提升体验）

#### F4：弹窗 DOM 清理 🟡

**用户故事**：作为玩家，我不应该在一次操作中看到多个弹窗叠加在一起。

**现状**：`index.html:519-520` 的 `showAlert()` 和 `showConfirm()` 每次都在 body 追加新的 `.popup-overlay.active`，关闭时只 remove 自己，不检查是否有残留。快速连续操作可能产生多层弹窗。

**验收标准**：
- [ ] `showAlert()` 和 `showConfirm()` 打开前先移除所有已有的 `.popup-overlay`（保留 `#popup-api`、`#popup-saves`、`#popup-ending`）
- [ ] 弹窗关闭时清理自身 DOM
- [ ] 10 秒内连续触发 5 次 showAlert，页面上始终只有 1 个弹窗

**优先级**：P1 — 体验问题，不阻塞功能

---

#### F5：toggleSpoiler CSS 替代 setTimeout 🟢

**用户故事**：（开发者视角）剧透切换的动画应该用 CSS transition 实现，而不是 setTimeout 600ms hack。

**现状**：`index.html:537` 的 `toggleSpoiler()` 使用 `setTimeout(..., 600)` 来等待 DOM 更新。这个硬编码延迟在高性能设备上浪费 600ms，在低性能设备上可能不够。

**验收标准**：
- [ ] 剧透字段的显隐改用 CSS transition（opacity + max-height）
- [ ] 移除 setTimeout 600ms hack
- [ ] 切换剧透开关，动画流畅（无闪烁、无延迟感）

**优先级**：P1 — 代码质量，不影响功能

---

### P2 — 建议修（技术债）

#### F6：前端 fetch 统一错误处理 🟢

**现有 `_fetchOk` 函数只处理了部分调用。建议所有 fetch 统一走 `_fetch` 包装器，包含：401 拦截、网络异常 toast、JSON 解析异常保护。**

**优先级**：P2 — 技术债，渐进式迁移即可

---

## 5. 用户流程

本次修复不改变用户可见流程。修复前后玩家体验路径不变：

```
登录 → 选择副本 → 进入游戏 → 输入行动 → AI 生成叙事 → (循环) → 存档
```

修复后唯一可感知的变化：AI 的标签召回更准确 → 剧情更连贯、角色更记得住上下文。

---

## 6. 多端差异

- **桌面端 (index.html)**：F4/F5/F6 全部适用
- **移动端 (m.html)**：需要同步修复 F4/F5（m.html 可能共享部分 JS 逻辑，需 Tech Lead 确认代码复用情况）

---

## 7. 非功能需求

| 维度 | 要求 |
|------|------|
| 成本效率 | Pass1 单轮平均 token 消耗 ≤ 2000（含 input+output），Pass2 节省量 ≥ 2× Pass1 开销 |
| 延迟 | Pass1 AI 调用不应使单轮总延迟增加超过 2 秒 |
| 稳定性 | Pass1 失败时必须 fallback 到 `_keyword_recall()`，不允许游戏中断 |
| 兼容性 | 代码需同时兼容 Anthropic / OpenAI / DeepSeek 三种 API |
| 安全 | API Key 继续由前端透传，后端不存储 |

---

## 8. 商业化与收益模型 💰

本次修复的 **核心收益是降低单轮 API 平均成本**。以 100 轮对话、标签库 200 条为例：

| 方案 | 每轮 Pass2 上下文 | 100 轮总 token 估算 |
|------|-------------------|---------------------|
| 无召回（全库） | ~15K input tokens | ~1.5M tokens 💸💸💸 |
| 关键词匹配（当前） | ~5K input tokens 但不准 | ~500K + 召回不准 → 叙事质量损失 |
| AI 召回（目标） | ~3K input tokens 且精准 | ~300K + Pass1 ~50K = **~350K** ✅ |

相比无召回方案节省约 **75%**，相比当前关键词方案在成本基本持平的前提下大幅提升召回精准度。

---

## 9. 风险与假设

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Pass1 AI 调用增加延迟 | 单轮响应变慢 | 使用 flash 级小模型（延迟 < 1s）；超时 10s 后 fallback 关键词 |
| Pass1 返回格式不稳定 | JSON 解析失败 | pass1.py:106-109 已有回退逻辑（空结果不崩溃） |
| 前端改动引入新 Bug | 回归 | QA 必须跑桌面+移动双端全流程 |
| m.html 和 index.html 代码重复 | 修复需要改两处 | Tech Lead 评估是否提取公共 JS |

**假设**：
- `pass1.py` 的 prompt 设计合理，不需要重写（已验证 ✅）
- 用户配置的 `model_small` 应为 flash/便宜模型，不额外消耗大模型配额
- MySQL 数据库状态正常（已验证 ✅）

---

## 10. 附录

### A. 问题代码位置速查

| 文件 | 行号 | 问题 |
|------|------|------|
| `mvp/src/orchestrator.py` | 70-82 | `_keyword_recall()` 替代了 AI Pass1 |
| `mvp/src/orchestrator.py` | 48-57 | `process_turn_async()` 未调用 `pass1.run_pass1()` |
| `mvp/src/pass1.py` | 全文 | 完整实现但未被调用 |
| `mvp/src/ai_provider.py` | 69, 237-239 | 流式空 content/空字符串未过滤 |
| `mvp/server.py` | 670-681 | `_pid()` 401 无全局拦截 |
| `mvp/static/index.html` | 494, 519-520, 537 | Token 过期/弹窗叠加/setTimeout hack |

### B. 验证环境

- Python 3.14.5
- MySQL 8.0.31（运行中）
- 测试账号：admin / 123456
- 测试 API Key：sk-6faaf8d1366b4e979339dc1fbeb4fdc6 (DeepSeek)
- 项目路径：`D:/project/规则怪谈/fenli/mvp/`
- 启动命令：`cd mvp && MYSQL_PASS=root python server.py`

---

> 🐾 PM 代签，老板审核通过后移交 Tech Lead 进行技术方案设计。
> 
> Tech Lead～这个 PRD 拜托你啦！核心改动是 F1（接回 pass1.py），其他 5 项是稳定性修复。F1 的省钱逻辑已经在第 8 节算清楚了，有技术疑问随时找我哦～ 🙌
