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
```

## 二期预留

- Jenkins 构建数据接入（`jenkins_builds` 表已预留）
- Slack / 钉钉通知适配器（`NotificationProvider` 接口已抽象）
- AI 智能构建优化
- 自动发布流水线
