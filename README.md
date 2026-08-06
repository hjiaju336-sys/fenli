# 无限流规则怪谈 (Fenli)

AI 驱动的规则怪谈文字互动游戏。双 Pass 架构：Pass1 标签召回 + Pass2 叙事生成，支持伪无限上下文、Hook 事件引擎、剧本工坊。

## 技术栈

- **后端**: Python FastAPI + MySQL + WebSocket
- **前端**: 原生 JS/CSS（桌面端 + 移动端自适应）
- **AI**: DeepSeek v4 Flash (Pass1 召回) + DeepSeek v4 Flash/Pro (Pass2 叙事)
- **部署**: 腾讯云 2核4G Ubuntu 24.04，systemd 管理

## 快速启动

```bash
# 1. 配置环境变量
cp mvp/.env.example mvp/.env
# 编辑 .env 填入 MySQL密码、JWT密钥、管理员密码、API Key

# 2. 安装依赖
cd mvp
pip install -r requirements.txt

# 3. 启动
python server.py
# → http://localhost:8777
```

## 项目结构

```
mvp/
├── server.py              # FastAPI 入口
├── ws_handler.py          # WebSocket 处理
├── routes/                # HTTP 路由 (8个模块)
├── src/                   # 核心引擎 (orchestrator/pass1/pass2/hook_engine...)
├── ddl/migrations.py      # 数据库迁移
├── static/                # 前端 (index.html/m.html/common.js)
└── presets/               # 6个预设副本
```

## 部署

服务器通过 systemd 管理（`fenli.service`），部署脚本 `~/deploy.sh`：

```bash
ssh root@162.14.64.4
cd /home/ubuntu/fenli && git pull origin master && bash ~/deploy.sh
```

健康检查: `GET http://162.14.64.4:8777/api/health`

## 文档

- `docs/未来方向-产品演进路线.md` — 三个战略方向（叙事者系统/题材插件化/多人共享世界）
- `docs/需求清单-全量.md` — 完整需求列表
- `docs/功能清单.md` — 已实现功能
- `docs/技术栈.md` — 技术选型说明
- `.claude/CLAUDE.md` — OPC Agent 框架配置

## 版本

v0.7.1 — AI调试面板 + 前端补全 + 移动端修复 + 副本封面动画
