# PRD：v0.8.0 代码重构 — 拆巨石 + 统一前端

> 版本：v1.0 | 日期：2026-07-31 | 状态：待老板审核 | PM 签字：PM 暂代 🐾

## 1. 背景

代码结构专家评估综合 5.0/10，两个核心问题：
- `server.py` 1939 行混合路由/WebSocket/DDL/积分/管理/图片上传
- `index.html`(2088行) 和 `m.html`(1038行) 零代码共享，每次改功能写两遍

不改架构直接加支付/角色羁绊/UGC = 在沙滩上盖楼。

## 2. 核心目标

| 目标 | 标准 |
|------|------|
| server.py 拆分 | 从 1939 行降到 < 500 行，新增 6-8 个模块 |
| 前端统一 | 提取公共 JS/CSS，index.html 降到 < 1200 行，m.html < 700 行 |
| 功能不变 | 重构后所有 API 行为一致，前端 10/10 对话通过 |
| 零回滚 | 每个模块拆完立刻验证，不积压 |

## 3. 功能范围

### F1：server.py 拆分为路由模块 🔴

```
server.py （1939行 → ~400行，只保留入口+启动）
├── routes/auth.py          # 登录/注册/鉴权 (~200行)
├── routes/game.py          # 预设/存档/云端副本/WebSocket (~300行)
├── routes/community.py     # 评分/评论/举报/建议/公告 (~250行)
├── routes/admin.py         # 管理面板全部API (~350行)
├── routes/points.py        # 签到/兑换/积分流水 (~150行)
├── routes/upload.py        # 图片上传/审核 (~120行)
├── db/migrations.py        # DDL建表/迁移 (_ensure_* 系列) (~250行)
├── middleware.py           # 速率限制/鉴权守卫 (~80行)
```

### F2：提取前端公共 JS/CSS 🔴

```
static/
├── index.html              # 桌面端（2088行 → ~1200行）
├── m.html                  # 移动端（1038行 → ~700行）
├── common.js               # 共享 JS（新建 ~400行）
│   ├── _auth() / _fetch() / _pid()
│   ├── showToast() / showAlert() / showConfirm()
│   ├── highlightQuotes() / escHTML()
│   ├── ST/LG localStorage 封装
│   └── connectWS() / handleWS() 公共逻辑
├── common.css              # 共享 CSS（新建 ~300行）
│   ├── :root 变量、按钮、弹窗、聊天气泡
│   └── 动画(@keyframes)、响应式断点
├── theme-horror.css        # 血橙恐怖主题
├── theme-night.css         # 夜间护眼主题
└── theme-pink.css          # 粉色可爱主题
```

### F3：core 模块零改动 🟢

以下模块代码质量评分高，本次不动：
- `src/ai_provider.py` (363行) — AI Provider 抽象层 ✅
- `src/orchestrator.py` (208行) — 双 Pass 编排器 ✅
- `src/pass1.py` (123行) — Pass1 召回 ✅
- `src/pass2.py` (258行) — Pass2 叙事 ✅
- `src/hook_engine.py` (207行) — Hook 触发引擎 ✅
- `src/db.py` (227行) — DAO 数据层 ✅
- `src/auth.py` (31行) — JWT ✅

## 4. 非功能需求

| 维度 | 要求 |
|------|------|
| 兼容 | 所有 API 路由路径不变，请求/响应格式不变 |
| 性能 | 重启后响应延迟不增加 |
| 可测试 | 每个新路由模块可独立启动测试 |

## 5. 风险与应对

| 风险 | 缓解 |
|------|------|
| 拆分过程中引入新 Bug | 每个模块拆完立刻重启+curl 验证，不积压 |
| 前端提取 common.js 破坏现有逻辑 | index.html 和 m.html 逐个函数迁移，迁移一个验证一个 |
| WebSocket 逻辑跨模块耦合深 | WebSocket handler 拆分优先级放最后 |

## 6. 不在本次范围

- ❌ 加新功能
- ❌ 改数据库 schema
- ❌ 接入支付
- ❌ 前端 UI 改动

---

> 🐾 PM 代签，老板确认后移交 Tech Lead 出技术方案+分派。
