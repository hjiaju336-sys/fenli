# Hook 事件系统 PRD

> PM Agent | 日期: 2026-07-29 | 优先级: P0
> 目标: 剧本作者可通过填空式表单定义游戏内事件触发与效果，无需代码基础

---

## 一、背景

### 1.1 问题现状

- 结局系统仅有3种硬编码类型（victory/death/escape），完全依赖AI判定，不可靠
- 剧本作者（尤其是玩家自创剧本）无法定义自定义事件、特效、结局逻辑
- UI表现单一，缺乏沉浸感，无法承载"乙女向暗黑二次元"的视觉定位
- 图片/自定义资源无法上传集成

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **作者零代码** | 全部通过下拉菜单+填空完成配置 |
| **确定性执行** | Hook条件在后端检查，不依赖AI判断 |
| **排列组合** | 一个触发条件可绑定多个效果，顺序执行 |
| **玩家可控** | 恐怖效果有降级开关，输入锁定有强制解锁 |
| **副本自封闭** | 成就仅记录在玩家主页，不跨副本注入 |

---

## 二、用户故事

| # | 角色 | 需求 | 验收标准 |
|---|------|------|----------|
| US1 | 剧本作者 | 我填几个关键词，玩家触发后弹出NPC立绘和台词 | 关键词匹配→立绘弹出+台词显示 |
| US2 | 剧本作者 | 玩家血量低于30时画面闪红，AI开始描述濒死感 | 状态条件满足→闪红特效+inject文本 |
| US3 | 剧本作者 | 玩家发现隐藏真相且集齐5个记忆后触发真结局 | 多条件AND→结局卡弹出 |
| US4 | 剧本作者 | 上传一张血迹纸条图片，玩家进入某区域时弹出 | 关键词/状态触发→图片弹窗 |
| US5 | 玩家 | 太恐怖了，我想关掉闪烁和震动 | 设置开关→对应效果降级 |
| US6 | 玩家 | 输入框被锁了，我要能解除 | ×按钮或超时自动解锁 |
| US7 | 玩家 | 我在主页能看到我达成了哪些副本的成就 | 主页勋章墙按副本分组展示 |

---

## 三、触发器体系

### 3.1 关键词触发器

```json
{
  "trigger": {
    "type": "keyword",
    "words": ["发现", "真相", "镜子"],
    "source": "ai_reply"  // ai_reply | new_tags | both
  }
}
```

- `source: ai_reply` — 仅检查AI回复内容
- `source: new_tags` — 仅检查本轮新发现的标签名
- `source: both` — 两者都检查（默认）

匹配规则：用户输入的关键词，以空格分隔，任一出现在source文本中即触发。

### 3.2 状态触发器

```json
{
  "trigger": {
    "type": "state",
    "conditions": [
      {"field":"hp","op":"lte","value":30},
      {"field":"turns","op":"gte","value":5},
      {"field":"has_item","value":"铜钥匙"}
    ],
    "logic": "and"  // and | or
  }
}
```

**支持的状态字段（10种）**：

| 字段 | 操作符 | 值类型 | 说明 |
|------|--------|--------|------|
| `hp` | lte / gte / eq | 数字 | 玩家血量 |
| `sanity` | lte / gte / eq | 数字 | 理智值 |
| `turns` | gte | 数字 | 当前回合数 |
| `has_item` | — | 物品名 | 背包是否含有 |
| `has_tag` | — | 标签名 | 是否已发现某标签 |
| `mem_count` | gte | 数字 | 当前记忆碎片数 |
| `npc_fav` | gte / lte | NPC名+数字 | 指定NPC好感度阈值 |
| `visited_map` | — | 地图名 | 是否去过某地图 |
| `rule_triggered` | — | 规则名 | 规则是否被触发过 |
| `rule_broken` | — | 规则名 | 规则是否被违反过 |

### 3.3 触发控制

| 属性 | 说明 | 默认值 |
|------|------|--------|
| `once` | true=触发一次后不再触发 | true |
| `priority` | 数字越大越先执行 | 0 |
| `delay_turns` | 触发后延迟N回合再执行效果 | 0 |

---

## 四、效果体系（9类46种）

### 🟢 治愈/温暖（7种）

| ID | 效果 | 参数 | 说明 |
|----|------|------|------|
| `golden_glow` | 金色微光 | duration(秒,默认3) | 边缘亮起暖金色柔光 |
| `petal_fall` | 花瓣飘落 | style: sakura/light/gold | 花瓣/光点飘落 |
| `heartbeat_warm` | 心跳回暖 | duration(秒,默认5) | 边框暗红→暖金呼吸式变化 |
| `npc_comfort` | NPC安慰 | npc_name, line | 指定NPC立绘弹出+温暖台词 |
| `warm_flashback` | 温暖闪回 | text | 半透明叠加温暖回忆文字 |
| `sunlight` | 阳光洒落 | — | 聊天区背景变暖+光束 |
| `music_box` | 音乐盒 | — | 舒缓音效+画面微微变亮 |

### 🔴 恐怖/紧张（7种，支持玩家关闭）

| ID | 效果 | 参数 | 可关闭 |
|----|------|------|--------|
| `flash_red` | 红色闪烁 | duration(秒,默认0.5) | ✅ |
| `screen_shake` | 屏幕震动 | intensity: light/medium/heavy | ✅ |
| `vignette_pulse` | 暗角脉动 | duration(秒,默认3) | ✅ |
| `glitch_text` | 故障乱码 | duration(秒,默认2) | ✅ |
| `screen_blur` | 画面模糊 | duration(秒,默认2) | — |
| `blood_edge` | 血色渐变 | duration(秒,默认3) | ✅ |
| `sudden_silence` | 突然静音 | duration(秒,默认2) | — |

### 🟡 剧情/叙事（6种）

| ID | 效果 | 参数 |
|----|------|------|
| `typewriter` | 打字机文字 | text |
| `rule_reveal` | 规则揭示牌 | rule_name, rule_text |
| `scene_transition` | 场景过渡 | text（"—— 三天后 ——"） |
| `fullscreen_text` | 全屏大字 | text, style: normal/blood/gold |
| `diary_flip` | 日记翻页 | title, content, image(可选) |
| `chapter_title` | 章节标题 | text, subtitle(可选) |

### 🟣 角色互动（6种）

| ID | 效果 | 参数 |
|----|------|------|
| `portrait_popup` | 立绘弹窗 | npc_name, line, expression(可选) |
| `expression_change` | 表情切换 | npc_name, expression |
| `fav_animation` | 好感度变化 | npc_name, amount(+5/-3) |
| `npc_enter` | NPC登场 | npc_name, line(可选) |
| `npc_exit` | NPC退场 | npc_name, style: fade/shatter |
| `npc_chat` | NPC气泡 | npc_name, content |

### 🔵 UI变化（5种，全部配安全解锁）

| ID | 效果 | 参数 | 安全机制 |
|----|------|------|----------|
| `border_color` | 边框变色 | color, duration(秒) | 超时恢复 |
| `chat_bg` | 聊天背景 | image_url, duration(秒) | 玩家可手动恢复 |
| `status_flash` | 状态栏闪烁 | color, duration(秒) | 超时恢复 |
| `input_lock` | 输入框锁定 | text, unlock_method | **强制：超时≤15s + ×按钮** |
| `button_morph` | 按钮形态 | icon, color, duration(秒) | 超时恢复 |

`input_lock` 的 `unlock_method`：
- `{"type":"timeout","seconds":10}` — 超时解锁（最长15秒）
- `{"type":"manual"}` — 显示×按钮手动解除
- `{"type":"input","keyword":"我坚持行动"}` — 输入特定内容解锁
- 三者必须至少选其一，否则无法保存

### 🟠 弹窗/图片（7种）

| ID | 效果 | 参数 | 内容来源 |
|----|------|------|----------|
| `clue_image` | 线索图片 | image_url, caption(可选) | 作者上传 |
| `scene_illustration` | 场景插图 | image_url, style: fullscreen/half | 作者上传 |
| `note_card` | 笔记卡片 | title, content, image(可选), style: parchment/medical/diary | 作者填 |
| `binary_choice` | 二选一 | option_a, option_b, result_a, result_b | 作者填 |
| `fullscreen_text_popup` | 全屏文字弹窗 | text, style | 作者填 |
| `dialogue_bubble` | 台词气泡 | npc_name, line | 选择NPC+填台词 |
| `ending_card` | 结局卡片 | title, desc, icon, background_image(可选) | 作者填 |

### ⚪ 机制/局内（5种）

| ID | 效果 | 参数 |
|----|------|------|
| `reveal_tag` | 揭示标签 | tag_name |
| `give_item` | 获得物品 | item_name, item_desc |
| `attr_change` | 属性变化 | field: hp/sanity, amount: +10/-5 |
| `point_reward` | 积分奖励 | amount |
| `local_flag` | 局内标记 | flag_name |

### ⚫ 沉浸/氛围（5种）

| ID | 效果 | 参数 |
|----|------|------|
| `bg_music` | 背景音乐 | track: tense/sad/peaceful/horror/warm |
| `sound_fx` | 播放音效 | fx: heartbeat/door/creak/scream/bell/rain/page |
| `color_tone` | 画面色调 | tone: cold/warm/red/desaturated |
| `particles` | 粒子效果 | type: rain/snow/ash/firefly/petal |
| `breathing` | 呼吸感 | duration(秒), intensity: subtle/normal |

### ⭐ 成就（5种，主页展示，不注入游戏逻辑）

| ID | 效果 | 参数 | 主页展示 |
|----|------|------|----------|
| `ach_clear` | 通关成就 | name, icon, scenario_name | 勋章墙+副本名 |
| `ach_collect` | 收集成就 | name, icon, scenario_name, target_count | 勋章+进度 |
| `ach_fav` | 好感度里程碑 | name, icon, scenario_name, npc_name, threshold | 勋章+NPC名 |
| `ach_explore` | 探索成就 | name, icon, scenario_name, map_name | 勋章+地图名 |
| `ach_custom` | 自定义成就 | name, icon, scenario_name, desc | 勋章+描述 |

**成就表存储**：

```sql
CREATE TABLE player_achievements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    player_id VARCHAR(255),
    achievement_key VARCHAR(255),        -- 剧本内唯一标识
    achievement_name VARCHAR(255),
    icon VARCHAR(10),
    scenario_name VARCHAR(255),          -- 来自哪个副本
    unlocked_at VARCHAR(50),
    UNIQUE KEY uk_ach (player_id, achievement_key)
);
```

成就**不**注入任何AI上下文，仅在玩家主页 `/api/user/profile` 返回 `achievements` 数组供展示。

---

## 五、编辑器UI设计

### 5.1 位置

在现有8步模板编辑器之后，增加第⑨步"⚡ 事件配置"。

### 5.2 操作流程

```
点击 [+ 添加事件]
  ↓
选择触发方式： [关键词触发 ▼] 或 [状态触发 ▼]
  ↓
填写触发条件（关键词 / 状态条件+逻辑）
  ↓
选择效果类型： [下拉选择46种效果]
  ↓
填写效果参数（图片上传、文字输入、NPC选择等）
  ↓
点击 [+ 添加效果] 可叠加多个效果到一个触发条件
  ↓
[保存事件]
  ↓
事件卡片出现在列表中，可拖拽排序、编辑、删除
```

### 5.3 效果参数输入方式

| 参数类型 | 输入方式 |
|----------|----------|
| 文字 | 文本框 |
| 数字 | 数字输入框 |
| NPC名 | 下拉（从本剧本角色列表自动读取） |
| 表情 | 下拉（默认/笑/悲/怒/惧/惊讶） |
| 物品名 | 下拉（从本剧本文本列表自动读取） |
| 地图名 | 下拉（从本剧本地图列表自动读取） |
| 规则名 | 下拉（从本剧本规则列表自动读取） |
| 标签名 | 下拉（从本剧本标签列表自动读取） |
| 图片 | 上传按钮 → 预览缩略图 |
| 颜色 | 预设色板（血红/暗紫/暖金/冷蓝/纯白） |
| 音效 | 预设选项 |
| 二选一内容 | 两个文本框 |
| 成就名 | 文本框 + emoji选择器 |

---

## 六、图片上传管线

### 6.1 流程

```
作者编辑器内点击[上传]
  → POST /api/upload/image (multipart, max 2MB, jpg/png/gif/webp)
  → 服务器验证: 格式 + 大小 + 用户配额(≤50张)
  → 保存: static/uploads/{player_id}/{uuid}.{ext}
  → 返回: {"url": "/static/uploads/u001/a1b2c3.png"}
  → 编辑器将url写入hook配置
  → 保存模板时图片URL随JSON存入shared_copies表
  → 其他玩家加载时直接通过已有URL访问
```

### 6.2 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/upload/image` | POST | 上传图片，form-data `file`字段 |
| `/api/upload/images` | GET | 列出当前用户的图片列表 |
| `/api/upload/image/{filename}` | DELETE | 删除指定图片 |

### 6.3 管理规则

- 每用户最多50张，超出提示清理
- 单张上限2MB
- 支持格式：PNG/JPG/GIF/WebP
- 文件名UUID防冲突
- 云端副本删除后，关联图片保留30天
- `static/uploads/` 目录加入 `.gitignore`

---

## 七、舒适度开关（玩家侧）

### 7.1 设置项

在设置弹窗中增加"体验偏好"区块：

| 开关 | 控制的效果 | 降级方式 |
|------|-----------|----------|
| ☑ 闪烁特效 | flash_red, glitch_text, screen_shake | 顶部小字提示替代 |
| ☑ 恐怖音效 | heartbeat, creak, scream, sudden_silence | 静音或忽略 |
| ☑ 画面扭曲 | screen_blur, vignette_pulse, blood_edge | 跳过效果 |
| ☑ 跳吓弹窗 | 所有popup类效果 | 改为3秒延迟+小图替代 |
| ☑ 输入锁定 | input_lock | 跳过锁定，不限制输入 |

存储：`localStorage.mvp_comfort = {flash: true, audio: false, ...}`

### 7.2 实现方式

前端在执行hook效果前检查开关：
```javascript
function shouldPlay(effectType) {
  if (effectType === 'flash_red') return comfort.flash !== false;
  if (effectType === 'screen_blur') return comfort.distort !== false;
  // ...
  return true; // 非恐怖效果默认执行
}
```

降级不影响后端逻辑。舒适度开关完全前端侧。

---

## 八、Hook执行引擎（后端）

### 8.1 流程

```
AI回复完成 → session.commit()
  ↓
_hook_engine(session, pid, hooks, turn_context):
  triggered = []
  for hook in hooks:
    if hook.once and already_triggered(hook.id): continue
    if check_trigger(hook.trigger, turn_context):
      triggered.append(hook)
  return triggered
  ↓
WS发送:
  {"type":"hook_effects","effects":[...触发的所有效果...]}
  ↓
如果有 ending 效果:
  同时发送 turn_complete（ending_type由hook决定）
  ↓
如果有 ach_* 效果:
  写入 player_achievements 表
```

### 8.2 WS消息格式

```json
{
  "type": "hook_effects",
  "effects": [
    {"type":"flash_red","params":{"duration":0.5}},
    {"type":"portrait_popup","params":{"npc_name":"护士长王秀兰","line":"你终于发现了...","expression":"惊讶"}},
    {"type":"ach_clear","params":{"name":"血月幸存者","icon":"🌕","scenario_name":"血月医院"}}
  ]
}
```

### 8.3 新增文件

| 文件 | 说明 |
|------|------|
| `src/hook_engine.py` | Hook触发器检查+效果排序+去重 |
| `static/uploads/` | 图片上传目录（新建） |

---

## 九、测试验收标准

| # | 场景 | 预期结果 |
|---|------|----------|
| T1 | 关键词hook触发 | 关键词匹配→效果执行 |
| T2 | 状态hook触发 | 条件全部满足→效果执行 |
| T3 | once=true | 同一hook不重复触发 |
| T4 | 一触发多效果 | 多个效果按priority顺序执行 |
| T5 | 图片上传→保存 | 上传成功→URL可访问→存入JSON→他人加载可见 |
| T6 | 舒适度关闭 | 闪烁效果降级为文字提示 |
| T7 | 输入锁定超时 | N秒后自动解锁 |
| T8 | 输入锁定×按钮 | 点击后立即解锁 |
| T9 | 成就解锁 | 触发后写入DB→主页可查看 |
| T10 | 玩家自创剧本带hook | 编辑器填写→保存→他人加载→hook正常触发 |
| T11 | ending hook | 触发结局→turn_complete含ending_type |
| T12 | 编辑器UI | 下拉自动读取剧本数据，上传显示预览 |

---

## 十、排期

| 阶段 | 内容 | 工期 | 执行岗 |
|------|------|------|--------|
| **1** | hook_engine.py 后端引擎 + WS消息 | 1天 | Backend Dev |
| **2** | 图片上传API + 配额管理 | 0.5天 | Backend Dev |
| **3** | 编辑器第⑨步UI + 表单逻辑 | 1天 | Web Dev |
| **4** | 前端效果渲染（46种） | 1.5天 | Web Dev |
| **5** | 舒适度开关 + 输入锁定安全 | 0.5天 | Web Dev |
| **6** | 成就表 + 主页勋章墙 | 0.5天 | Backend+Web |
| **7** | Code Review × 2 | 0.5天 | Reviewer |
| **8** | QA全流程测试 | 1天 | QA Agent |
| **总计** | | ~5天 | |

---

> 提交 Tech Lead 进行技术方案设计。
