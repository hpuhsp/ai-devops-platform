# AI DevOps 效能平台 — 一期架构设计文档

> 版本: v1.0.0-draft | 日期: 2026-06-21 | 架构师: AI Agent

---

## 1. 系统上下文

```
┌──────────────────────────────────────────────────────────────────┐
│                        外部系统                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ GitLab   │  │  GitHub  │  │  Gitea   │  │   飞书 / Slack  │  │
│  │(Webhook) │  │(Webhook) │  │(Webhook) │  │   (通知接收)    │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │
└───────┼─────────────┼─────────────┼─────────────────┼───────────┘
        │  Push/MR Event             │                 │ Card Message
        └──────────────┬─────────────┘                 │
                       ▼                               │
┌──────────────────────────────────────────────────────────────────┐
│               AI DevOps 效能平台 (本系统)                          │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    FastAPI Gateway                           │ │
│  │  /webhook  /api/v1/config  /api/v1/tasks  /api/v1/stats    │ │
│  └──────┬───────────┬──────────────┬──────────────┬───────────┘ │
│         │           │              │              │              │
│  ┌──────▼──────┐ ┌──▼──────────┐ ┌▼───────────┐ ┌▼──────────┐ │
│  │ Webhook     │ │ AI Engine   │ │ Git Agent  │ │ Notify    │ │
│  │ Dispatcher  │ │ (LiteLLM)  │ │ (WorkTree) │ │ Adapter   │ │
│  └──────┬──────┘ └──┬──────────┘ └────────────┘ └───────────┘ │
│         │           │                                            │
│  ┌──────▼───────────▼─────────────────────────────────────────┐ │
│  │                 Celery Task Queue (Redis)                    │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │             PostgreSQL (持久化) + Redis (缓存/队列)           │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │          React + Ant Design 管理平台 / 动态驾驶舱             │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 技术选型决策

| 层次 | 选型 | 决策理由 |
|------|------|---------|
| 后端框架 | Python 3.11 + FastAPI | 最快上手、原生 async、AI 生态最丰富 |
| AI 适配 | LiteLLM | 统一接口支持 100+ 模型，OpenAI 兼容，支持 Deepseek/本地模型 |
| 任务队列 | Celery 5 + Redis | AI 任务天然异步；Redis 兼任缓存 |
| 数据库 | PostgreSQL 16 | 关系型事务、JSON 列支持、成熟运维 |
| ORM | SQLAlchemy 2.0 (async) | 行业标准，Alembic 迁移 |
| Git 操作 | GitPython + subprocess | WorkTree 操作 subprocess 更可靠 |
| 前端 | React 18 + Vite + Ant Design 5 | 最广泛的中后台生态 |
| 状态管理 | Zustand | 比 Redux 轻量，比 Context 可预测 |
| 容器化 | Docker + Docker Compose | 本地验证与生产部署一致 |

---

## 3. 模块划分

### 3.1 Webhook Dispatcher（事件接收器）
- 接收 GitLab/GitHub/Gitea 的 Push、MR/PR、Tag 事件
- 验证签名（HMAC-SHA256）
- 路由到对应 Celery Task

### 3.2 AI Engine（AI 引擎）
- LiteLLM 统一适配层，支持配置化模型切换
- Token 计费统计（记录 prompt_tokens / completion_tokens）
- 支持流式输出
- 扩展点：二期可接入本地 Ollama 模型

### 3.3 Skills Engine（技能引擎）
- 技能注册表（内置 + 项目级 `.ai-skills.yml`）
- 内置技能：`code_review`、`test_generation`
- 技能执行上下文：携带 diff、文件内容、仓库信息
- 扩展点：技能热加载，支持自定义 Prompt 模板

### 3.4 Git Agent（Git 操作代理）
- 基于 GitPython 的仓库管理
- **Git WorkTree 机制**：为单测生成创建隔离工作区，避免污染主分支
- 智能分支管理：feature → develop → main 流转规则
- 自动合并检查：CI状态、Review状态、冲突检测

### 3.5 Notify Adapter（通知适配器）
- 统一 `NotificationProvider` 接口
- 飞书适配器：支持 Webhook Bot 和 企业应用 两种模式
- 富文本卡片：代码审核结果、单测覆盖率、合并状态
- 扩展点：Slack、钉钉 适配器（二期）

### 3.6 Web 管理平台
- 配置管理：模型配置、飞书配置、Git 平台配置、规则配置
- 任务日志：实时查看 AI 任务执行日志
- 动态驾驶舱：一期数据 + 二期 Jenkins 占位面板

---

## 4. 数据库设计

```sql
-- 平台配置
CREATE TABLE platform_configs (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI 模型配置
CREATE TABLE ai_models (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    provider VARCHAR(50) NOT NULL,  -- openai/deepseek/ollama/custom
    model_id VARCHAR(200) NOT NULL,
    api_base VARCHAR(500),
    api_key_encrypted TEXT,          -- AES 加密存储
    is_default BOOLEAN DEFAULT FALSE,
    config JSONB,                    -- temperature, max_tokens 等
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 仓库配置
CREATE TABLE repositories (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(20) NOT NULL,   -- gitlab/github/gitea
    repo_url VARCHAR(500) NOT NULL,
    webhook_secret VARCHAR(200),
    git_token_encrypted TEXT,
    branch_rules JSONB,              -- {"feature/*": "develop", "develop": "main"}
    ai_model_id INT REFERENCES ai_models(id),
    skills_config JSONB,             -- 覆盖默认 skills 配置
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 任务记录
CREATE TABLE ai_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(100) UNIQUE NOT NULL,  -- Celery task ID
    repo_id INT REFERENCES repositories(id),
    task_type VARCHAR(50) NOT NULL,  -- code_review/test_generation/auto_merge
    status VARCHAR(20) NOT NULL,     -- pending/running/success/failed
    trigger_event JSONB,             -- 原始 webhook 事件
    input_data JSONB,
    output_data JSONB,
    error_message TEXT,
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    duration_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 通知配置
CREATE TABLE notify_configs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    provider VARCHAR(30) NOT NULL,   -- feishu_webhook/feishu_app/slack
    config JSONB NOT NULL,           -- provider-specific 配置
    is_default BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 统计快照（驾驶舱数据源）
CREATE TABLE stats_snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    metric_type VARCHAR(50) NOT NULL,
    value NUMERIC NOT NULL,
    dimensions JSONB,                -- repo_id, task_type 等维度
    UNIQUE(date, metric_type, dimensions)
);

-- 二期预留：Jenkins 构建数据
CREATE TABLE jenkins_builds (
    id SERIAL PRIMARY KEY,
    job_name VARCHAR(200) NOT NULL,
    build_number INT NOT NULL,
    status VARCHAR(20),
    duration_ms INT,
    repo_url VARCHAR(500),
    triggered_by VARCHAR(100),
    build_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 5. API 契约（核心接口）

```
# Webhook 接收
POST /webhook/{platform}           # platform: gitlab/github/gitea

# 配置管理
GET  /api/v1/models                # 列出 AI 模型配置
POST /api/v1/models                # 新增
PUT  /api/v1/models/{id}           # 更新
DELETE /api/v1/models/{id}

GET  /api/v1/repositories          # 仓库列表
POST /api/v1/repositories
PUT  /api/v1/repositories/{id}

GET  /api/v1/notify-configs
POST /api/v1/notify-configs

# 任务管理
GET  /api/v1/tasks                 # 任务列表（分页、筛选）
GET  /api/v1/tasks/{id}            # 任务详情
GET  /api/v1/tasks/{id}/logs       # 实时日志（SSE）

# 驾驶舱统计
GET  /api/v1/stats/overview        # 总览数据
GET  /api/v1/stats/trends          # 趋势图数据
GET  /api/v1/stats/by-repo         # 按仓库统计

# 二期预留
GET  /api/v1/jenkins/builds        # Jenkins 构建数据（占位）
GET  /api/v1/jenkins/stats         # Jenkins 统计（占位）
```

---

## 6. 二期扩展点设计

| 扩展点 | 设计位置 | 说明 |
|--------|---------|------|
| 新通知渠道 | `NotificationProvider` 接口 | 实现 `send()` 方法即可接入 |
| 新 AI 技能 | `SkillBase` 基类 + skills 注册表 | 一个 YAML + 一个 Python 类 |
| Jenkins 集成 | `jenkins_builds` 表已预留 | 新增 Adapter 写入即可 |
| 自定义构建 | Celery task 扩展 | 新增 task_type 处理器 |
| 多租户 | `repositories` 表加 `tenant_id` | 现有查询加过滤条件 |
