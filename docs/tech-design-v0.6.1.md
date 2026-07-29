# 技术方案：v0.6.1 稳定性修复 — 恢复 AI 召回 + 前端 Bug 清零

> 版本：v1.0 | 日期：2026-07-29 | Tech Lead： | PM 确认：

## 1. 方案概述

对应 PRD v0.6.1 的 6 项修复，改动集中在 `src/` 目录（后端核心流程）和 `static/index.html`（前端）。不新增依赖，不改数据库 schema，不改 API 协议。

### 代码质量评估

| 模块 | 行数 | 质量 | 本次策略 |
|------|------|------|----------|
| `src/pass1.py` | 122 | ✅ 干净，prompt + 解析 + fallback 完备 | 直接接入 |
| `src/pass2.py` | 238 | ✅ 干净，流式 + JSON 修复 + hooks 分离 | 不动 |
| `src/ai_provider.py` | 360 | ⚠️ 流式空字符串问题 | 微修（F2） |
| `src/orchestrator.py` | 170 | ⚠️ 关键词召回需替换 | 重构接入点（F1） |
| `server.py` | 1781 | 🔴 巨石文件，混合了 DB/鉴权/API/WS/Hook/Admin | **本次不动**（拆分为独立 PRD） |
| `static/index.html` | 1783 | 🔴 全部 JS 内联，无模块化 | 局部修复（F3/F4/F5） |
| `static/m.html` | 801 | 🔴 与 index.html 代码重复 | 同步修复 F4/F5 |

**结论**：`src/` 模块架构合理，本次改动干净；`server.py` 和前端是真正的技术债，但拆分属于独立工程，不在本次范围。

---

## 2. 架构设计

### 修复前后数据流对比

```
修复前（当前）：
  用户输入 → _keyword_recall() [免费但不准]
          → Hard Sync (SQL)
          → Pass2 (大模型) ← 上下文可能缺漏

修复后（目标）：
  用户输入 → Pass1 (小模型, ~1K token) [精准召回]
          → 失败? → _keyword_recall() [fallback]
          → Hard Sync (SQL)  
          → Pass2 (大模型) ← 只吃精准上下文，token 大幅压缩
```

### 改动涉及的文件

```
src/orchestrator.py   ← F1: 接入 pass1.run_pass1()
src/ai_provider.py    ← F2: 流式空字符串过滤
server.py             ← F3: _pid() None 安全
static/index.html     ← F3/F4/F5: fetch 封装 + 弹窗 + CSS
static/m.html         ← F4/F5: 同步修复（如适用）
```

---

## 3. 技术选型

无新增依赖。所有修复使用现有技术栈：
- Python 3.14 + FastAPI + SQLAlchemy
- 原生 JavaScript (ES6) + CSS3
- 现有 AI Provider 抽象层

---

## 4. 接口设计

### 4.1 F1: orchestrator 接入 Pass1

**现状** (`orchestrator.py:70-82`)：
```python
keep_tags, fetch_tags, drop_tags, keep_mems, fetch_mems = _keyword_recall(
    user_input, all_tags, all_memories, hot_tag_names)
```

**目标**：
```python
# 主路径：AI 召回
try:
    pass1_result = await run_pass1(
        provider=provider,
        api_key=api_key_small,
        user_input=user_input,
        hot_tag_names=hot_tag_names,
        all_tags=all_tags,
        all_memories=all_memories,
        recent_context=recent_context,
        model_name=model_small,
    )
    keep_tags = pass1_result["keepTags"]
    fetch_tags = pass1_result["fetchTags"]
    drop_tags = pass1_result["dropTags"]
    keep_mems = pass1_result["keepMemories"]
    fetch_mems = pass1_result["fetchMemories"]
    log["pass1"] = { ... pass1_result tokens/latency ... }
except Exception as e:
    # Fallback: 关键词匹配
    keep_tags, fetch_tags, drop_tags, keep_mems, fetch_mems = _keyword_recall(...)
    log["pass1"] = {"fallback": True, "error": str(e)}
```

**关键设计决策**：
- `api_key_small` 用于 Pass1（小模型），`api_key_large` 用于 Pass2（大模型）——当前已支持双 Key 配置
- Pass1 失败不回退整个 turn，只回退到关键词召回
- Pass1 的 input/output tokens 和 latency 记录到 turn log，方便老板审计

**接口契约（pass1.run_pass1 已有）**：

| 参数 | 类型 | 来源 |
|------|------|------|
| `provider` | AIProvider | orchestrator 已创建 |
| `api_key` | str | `api_key_small` |
| `user_input` | str | WebSocket 消息 |
| `hot_tag_names` | list[str] | 当前热区标签名 |
| `all_tags` | list[dict] | tag_dao.all_hints() |
| `all_memories` | list[dict] | mem_dao.all_hints() |
| `recent_context` | list[dict] | WS handler 维护的 ctx |
| `model_name` | str | `model_small` |

| 返回值 | 类型 | 用途 |
|------|------|------|
| `keepTags` | list[str] | → hot_tags 保持 |
| `fetchTags` | list[str] | → hard_sync 拉详情 |
| `dropTags` | list[str] | → 从热区移除 |
| `keepMemories` | list[str] | → hot_memories |
| `fetchMemories` | list[str] | → hard_sync 拉详情 |
| `input_tokens` | int | → turn log |
| `output_tokens` | int | → turn log |
| `latency_ms` | float | → turn log |

### 4.2 F2: 流式空字符串过滤

**位置**：`ai_provider.py`

**改动 1**：`StreamResult.collect()` (line 68-72)
```python
# 改前
if chunk is not None:
    chunks.append(chunk)

# 改后
if chunk is not None and chunk != "":
    chunks.append(chunk)
```

**改动 2**：`DeepSeekProvider.chat_stream()` (line 236-239)
```python
# 改前
if "content" in delta:
    yield delta["content"] or ""

# 改后
if "content" in delta and delta["content"]:
    yield delta["content"]
```

**改动 3**：`AnthropicProvider.chat_stream()` (line 177) 同理加固
```python
# 改前
yield data.get("delta", {}).get("text", "")

# 改后
text = data.get("delta", {}).get("text", "")
if text:
    yield text
```

### 4.3 F3: Token 过期全局拦截

**后端**：`server.py:670-681` 的 `_pid()` 已经是正确的（抛 401），不需要改。

**前端**：新增 `_fetch()` 包装器替代裸 `fetch()`，注入到 `index.html`：

```javascript
// 全局 fetch 包装：统一 401 + 网络异常 + JSON 解析
async function _fetch(url, opts) {
  opts = opts || {};
  opts.headers = opts.headers || {};
  if (!opts.headers['Authorization']) {
    opts.headers['Authorization'] = 'Bearer ' + _auth();
  }
  try {
    var resp = await fetch(url, opts);
    if (resp.status === 401) {
      ST.remove('token');
      _token = '';
      showToast('登录已过期，请重新登录', 'error');
      setTimeout(function() { navTo('page-login'); }, 1500);
      throw new Error('Unauthorized');
    }
    var data = await resp.json();
    if (data.error) throw new Error(data.error);
    return data;
  } catch (e) {
    if (e.message !== 'Unauthorized') {
      showToast('网络错误: ' + e.message, 'error');
    }
    throw e;
  }
}
```

**迁移策略**：F3 不要求全部迁移。本次至少覆盖游戏核心流程（WebSocket 消息发送、存档保存、世界书更新），其余 fetch 调用渐进式替换。

### 4.4 F4: 弹窗 DOM 清理

**位置**：`index.html:519-520`

```javascript
// 改前：直接 document.body.appendChild(o)
// 改后：先清理已有弹窗
function _cleanPopups() {
  document.querySelectorAll('.popup-overlay').forEach(function(el) {
    if (el.id !== 'popup-api' && el.id !== 'popup-saves' && el.id !== 'popup-ending') {
      el.remove();
    }
  });
}

function showAlert(msg, cb) {
  _cleanPopups();
  // ... 原有逻辑不变
}

function showConfirm(msg, cb) {
  _cleanPopups();
  // ... 原有逻辑不变
}
```

### 4.5 F5: toggleSpoiler CSS 替代 setTimeout

**位置**：`index.html:537`

```css
/* 新增 CSS */
.v-item.spoiler { 
  opacity: 0; max-height: 0; overflow: hidden; 
  transition: opacity 0.3s ease, max-height 0.3s ease; 
}
.v-item.spoiler.visible { 
  opacity: 1; max-height: 200px; 
}
```

```javascript
// 改前：setTimeout(function() { ... }, 600)
// 改后：直接切换 class，CSS transition 处理动画
function toggleSpoiler() {
  var cb = document.getElementById('spoiler-toggle');
  if (cb.checked) {
    showConfirm('剧透可能影响游戏体验，确定开启吗？', function() {
      _spoilerOn = true;
      document.querySelectorAll('.v-item.spoiler').forEach(function(el) {
        el.classList.add('visible');
      });
    });
  } else {
    _spoilerOn = false;
    document.querySelectorAll('.v-item.spoiler').forEach(function(el) {
      el.classList.remove('visible');
    });
    cb.checked = false;
  }
}
```

---

## 5. 执行岗分派

| 岗位 | 负责 | 预估工时 |
|------|------|----------|
| **Backend Agent** | F1: orchestrator 接入 pass1 + F2: ai_provider 修复 + F3 后端确认 | 1.5h |
| **Web Agent** | F3: 前端 `_fetch()` 封装 + F4: 弹窗清理 + F5: CSS transition | 1.5h |
| **Code Reviewer** | 审查 Backend + Web 的全部改动 | 0.5h |
| **QA Agent** | 桌面+移动双端 5 轮回归测试 + Pass1 fallback 验证 | 1h |

总计：2 人并行 → **~3h 完成全部修复 + 审查 + 测试**

---

## 6. 排期估算

```
Backend:  F1 (1h) ──→ F2 (0.3h) ──→ F3-后端 (0.2h)  ─┐
                                                        ├──→ Code Review (0.5h) ──→ QA (1h)
Web:      F3-前端 (0.5h) → F4 (0.5h) → F5 (0.5h)      ─┘
```

| 里程碑 | 预计完成 |
|--------|----------|
| Backend + Web 开发完成 | 1.5h |
| Code Review 通过 | 2h |
| QA 回归测试通过 | 3h |
| **交付** | **3h** |

---

## 7. 技术风险与应对

| 风险 | 概率 | 应对 |
|------|------|------|
| Pass1 prompt 对中文标签召回效果不佳 | 中 | `pass1.py:109` 已有空结果回退；如频繁 fallback，后续迭代优化 prompt |
| Pass1 增加 ~1-2s 延迟，用户可感知 | 中 | 前端已有"AI 思考中..."状态；Pass1 用 flash 模型延迟通常在 0.5-1s |
| `model_small` 为空 → Pass1 报错 | 低 | 当 `model_small` 为空时直接 fallback 关键词，不调 Pass1 |
| m.html 与 index.html 的 F4/F5 改动不同步 | 低 | Web Agent 需确认 m.html 中 showAlert/showConfirm 是否共用（目前可能是复制粘贴的） |
| `_fetch()` 迁移不完整 → 部分 API 仍裸调 | 高 | F3 只要求核心流程覆盖，其余标记 TODO 渐进迁移 |

---

## 8. F1 核心改动伪代码

```python
# orchestrator.py — process_turn_async() 中的改动

# 删除/注释掉原有的 _keyword_recall() 调用（保留函数定义）
# 新增：

from pass1 import run_pass1

# Step 1: AI 召回（主路径）或关键词 fallback
t0 = time.time()
pass1_fallback = False
try:
    if not model_small:
        raise ValueError("no small model configured, use keyword fallback")
    
    pass1_result = await run_pass1(
        provider=provider,
        api_key=api_key_small,
        user_input=user_input,
        hot_tag_names=hot_tag_names,
        all_tags=all_tags,
        all_memories=all_memories,
        recent_context=recent_context,
        model_name=model_small,
    )
    keep_tags = pass1_result["keepTags"]
    fetch_tags = pass1_result["fetchTags"]
    drop_tags = pass1_result["dropTags"]
    keep_mems = pass1_result["keepMemories"]
    fetch_mems = pass1_result["fetchMemories"]
    log["pass1"] = {
        "method": "ai",
        "input_tokens": pass1_result["input_tokens"],
        "output_tokens": pass1_result["output_tokens"],
        "latency_ms": pass1_result["latency_ms"],
        "output": { ... },
    }
except Exception as e:
    pass1_fallback = True
    keep_tags, fetch_tags, drop_tags, keep_mems, fetch_mems = _keyword_recall(
        user_input, all_tags, all_memories, hot_tag_names)
    log["pass1"] = {
        "method": "keyword_fallback",
        "error": str(e)[:200],
        "output": { ... },
    }
```

---

## 9. 不在本次范围的已知技术债

| 项 | 原因 | 建议 |
|------|------|------|
| `server.py` 拆分为模块 | 1781 行巨石，混合 7 类职责 | 独立 PRD：拆为 `routes/` `ws_handler.py` `admin.py` 等 |
| `index.html` JS 提取为 `.js` 文件 | 1783 行内联，无模块化 | 独立 PRD：提取 + 模块化 + 消除 m.html 重复 |
| `m.html` 与 `index.html` 代码去重 | 大量 JS 逻辑复制粘贴 | 与上一条合并处理 |
| `pass1.py` / `pass2.py` prompt 迭代 | 可能召回不够准 | 先用当前 prompt 跑，收集数据后再优化 |

---

> Tech Lead 方案完成，请 PM 确认后分派执行岗。
