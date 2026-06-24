# AI DevOps 效能平台

基于 AI 的 DevOps 效能平台，一期实现 AI 代码审核、AI 单测生成（Git WorkTree 隔离）、飞书通知、Git Flow 分支自动化管理。

## 架构

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 一键启动

```bash
# 启动核心服务
docker compose up -d postgres redis api worker

# 启动全部服务（含前端）
docker compose up -d

# 包含测试 Git 平台（Gitea）
docker compose --profile testing up -d
```

## 服务端口

| 服务 | 地址 |
|------|------|
| API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| 前端 | http://localhost:3000 |
| Celery Flower | http://localhost:5555 |
| Gitea (测试) | http://localhost:3001 |

## Webhook 配置

在 Git 平台配置 Webhook 指向：
```
http://YOUR_SERVER:8000/webhook/{platform}
# platform: gitlab / github / gitea
```

## 本地开发

```bash
# 后端
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload

# Celery Worker
celery -A app.tasks.celery_app worker --loglevel=info

# 前端
cd frontend
npm install
npm run dev
```

## 运行测试

```bash
cd backend
python -m pytest tests/ -v
# 或在容器内： docker compose exec api python -m pytest tests/ -q
```

## 环境变量与密钥

加密密钥用于加密存储 Git Token / AI API Key，**api 与 worker 必须使用同一个值**。
仓库内的默认值仅供本地调试；非 DEBUG 模式下若仍为默认值，应用会拒绝启动。

```bash
cp .env.example .env        # docker compose 会自动读取根目录 .env
# 生成强随机值：
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

| 变量 | 说明 |
|------|------|
| `ENCRYPTION_KEY` | Fernet/AES 密钥，加密 Token/API Key（api、worker 必须一致） |
| `SECRET_KEY` | 应用签名密钥 |
| `SQL_ECHO` | 设为 `true` 打印所有 SQL（默认关闭，已与 DEBUG 解耦） |

## 数据库迁移（Alembic）

DEBUG 模式下应用启动时自动 `create_all` 建表（本地便利）。其它环境以 Alembic 迁移为准：

```bash
cd backend
alembic upgrade head                          # 应用迁移
alembic revision --autogenerate -m "xxx"      # 模型变更后生成新迁移
# 已用 create_all 建过表的库，首次接入迁移先打标记：
alembic stamp head
```

## 分支规则配置指南

流水线对每个分支执行哪些阶段由 **分支规则引擎** 决定。进入「配置管理 → 流水线规则」进行管理。

### 快速套用模板

| 模板 | 适用场景 |
|------|---------|
| 标准 Git Flow | feature/hotfix/release/develop/main 各自有独立阶段策略 |
| Trunk-Based | main 分支全量，feature 仅审核+单测 |
| 纯审核模式 | 所有分支只执行 AI 代码审查 |

### 自定义规则说明

- **分支匹配**：支持 fnmatch 通配符，如 `feature/*`、`hotfix/*`、`*`（兜底）
- **执行阶段**：`code_review`、`test_generation`、`auto_merge`（二期：`build`、`deploy`）
- **优先级**：数字越大越先匹配，命中第一条即停止
- **默认兜底**：无规则命中时只执行 `code_review`

### 流水线节点状态说明

| 状态 | 含义 | 动画效果 |
|------|------|---------|
| pending | 等待执行 | 灰色圆圈 |
| running | 执行中 | 蓝色脉冲 + 流光连接线 |
| done | 成功完成 | 绿色弹跳 ✓ |
| failed | 执行失败 | 红色抖动 ✗ |
| blocked | 审核拦截 | 红色抖动（含 Critical/High 问题数） |
| skipped | 规则跳过 | 灰色半透明淡入 |

## 二期预留

- Jenkins 构建数据接入（`jenkins_builds` 表已预留，规则阶段 `build`/`deploy` 已声明）
- Slack / 钉钉通知适配器（`NotificationProvider` 接口已抽象）
- AI 智能构建优化
- 自动发布流水线
