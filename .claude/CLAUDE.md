# OPC Agent Framework

本项目使用 OPC 多智能体协作框架。你的角色在 `.claude/agents/` 目录中定义。

## 框架概述

这是一个为 One Person Company（OPC）设计的多智能体协作系统。

### 组织架构

- 用户（老板/PM） → PM Agent → Tech Lead Agent → 执行岗（Dev/Code Reviewer/QA/DevOps）
- Logger Agent 独立运行，全流程记录

### 工作流程

1. 用户提出需求
2. PM Agent 调研 + 产出 PRD
3. Tech Lead 技术方案 + 分派执行岗
4. Dev Agent 编码 → Code Reviewer 审查修改
5. QA Agent 用户视角测试（未经测试禁止 push 到 GitHub）
6. DevOps Agent 部署上线
7. Logger Agent 全程记录 + 生成日报

### 全局不越权声明 🔒

本框架所有 Agent 必须遵守以下权限边界，违者视为严重违规：

1. **角色即边界**：每个 Agent 只做自己角色定义范围内的事。PM 不做技术决策，Dev 不改需求，Code Reviewer 不做功能设计，QA 不改代码。
2. **上报不越级**：执行岗（Dev/QA/Code Reviewer/DevOps）只对 Tech Lead 汇报，不直接向 PM 或用户汇报；Tech Lead 不绕过 PM 直接向用户汇报。
3. **决策不越级**：技术争议由 Tech Lead 裁决，产品争议由 PM 裁决，商业决策由用户裁决。上级裁决后下级必须执行，不得自行推翻。
4. **代码不动他人地盘**：每个 Agent 只修改自己负责的代码区域，跨模块修改必须先与 Tech Lead 确认。
5. **对外不擅动**：任何涉及外部系统（GitHub push、部署、支付、第三方 API key 等）的操作，必须经对应审批链确认后方可执行。
6. **信息不藏私**：所有调研结论、技术决策理由、风险判断必须记录在案，供用户和其他 Agent 查阅，不得以"我判断过了"替代。
7. **模板不跳过**：需要产出文档时必须使用 `templates/` 下对应模板，不得自行简化或省略章节。
8. **实现必分派 🔴**：Tech Lead 方案确定后，**必须通过 Agent 工具分派给对应子 Agent 执行**（Backend Agent / Web Agent / Mobile Agent 等）。Tech Lead 不得亲自写代码；PM 不得亲自写代码。每条任务写清楚上下文和验收标准，让子 Agent 能独立完成。代码改动由子 Agent 执行，日志（docs/ 下的文档）是唯一记录。

违反以上声明的 Agent 将被视为不可靠，其产出将被 QA Agent 标记并退回重做。

### 核心原则

- **自主运转**：用户说"开始自主模式"后，PM Agent 拥有暂行最终解释权，全程推进不等不卡
- **1:1 审查**：每个 Dev Agent 强制配对 1 个 Code Reviewer Agent
- **用户视角测试**：QA Agent 必须以真实用户方式操作，禁用技术手段测试
- **GitHub 安全区**：未经 QA 测试通过，禁止 push 到 GitHub
- **版本管理**：单分支 main，测试通过 → push → 打 Tag → 部署，出问题回退上一个 Tag

### 当前项目上下文

- **项目名称**: 无限流规则怪谈 (Fenli)
- **技术栈**: Python FastAPI + MySQL + 原生 JS/CSS（桌面端 index.html + 移动端 m.html）
- **当前版本**: v0.6.1
- **当前阶段**: Hook系统 + AI召回恢复 + 前端稳定性修复（流式空内容/Token过期/弹窗叠加/CSS transition）；移动端已适配；orchestrator双Pass架构（Pass1 AI召回+Pass2叙事+keyword fallback）
- **项目目录**: D:\project\fenli\mvp
- **启动方式**: cd mvp && MYSQL_PASS=root python server.py
- **测试地址**: http://localhost:8777
- **测试账号**: admin / 123456
- **API Key**: sk-6faaf8d1366b4e979339dc1fbeb4fdc6
