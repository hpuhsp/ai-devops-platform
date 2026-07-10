# Sprint A：分阶段模型路由（Per-Stage Model Routing）

## 1. 背景与动机

### 1.1 现状
当前每个仓库仅配置单一 AI 模型（`Repository.ai_model_id`），所有 Pipeline 阶段（变更分析、测试生成、修复、质量评分）共用同一个 `AIEngine` 实例。

**问题**：
- 变更分析（Change Intelligence）需要强推理能力 → 适合 Claude/Gemini
- 测试代码生成需要高质量代码输出 → 适合 Claude/DeepSeek
- 测试修复需要快速迭代 + 低成本 → 适合 DeepSeek
- 质量评分需要准确判断 → 适合 Claude/GPT-4o

单一模型无法同时满足"高质量分析 + 低成本修复"的需求。

### 1.2 目标
实现 **分阶段模型路由**：每个 Pipeline 阶段可独立配置使用不同的 AI 模型，未配置时自动回退到仓库默认模型。

## 2. 数据模型设计

### 2.1 存储方案：复用 `skills_config` JSONB 字段

在 `Repository.skills_config` 中新增 `stage_models` 子结构，**无需新建数据库表或字段**。

```json
{
  "stage_models": {
    "analysis": 1,
    "generation": 2,
    "repair": 3,
    "scoring": 1
  },
  "agents": {
    "repair_enabled": true
  }
}
```

**字段说明**：
| Key | 类型 | 含义 | 对应阶段 |
|-----|------|------|---------|
| `analysis` | int (AIModel.id) | 变更分析 + 上下文分析使用的模型 | ChangeIntelligence, Context |
| `generation` | int (AIModel.id) | 测试代码生成使用的模型 | Generator |
| `repair` | int (AIModel.id) | 测试修复使用的模型 | RepairAgent |
| `scoring` | int (AIModel.id) | 质量评分使用的模型 | QualityScorer |

### 2.2 回退策略
```
stage_models[stage] 存在且对应 AIModel 记录存在 → 使用该模型
stage_models[stage] 不存在或记录无效 → 回退到 repo.ai_model_id
repo.ai_model_id 也不存在 → 回退到系统默认 AIEngine()
```

### 2.3 无需数据库迁移
`skills_config` 已是 JSONB 类型，直接写入新 key 即可，零迁移成本。

## 3. 核心实现

### 3.1 新增模块：`backend/app/services/ai/stage_router.py`

```python
"""Per-stage model routing. Resolves AIEngine for each pipeline stage."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import structlog

logger = structlog.get_logger()

# Pipeline stages that support independent model routing
STAGE_ANALYSIS = "analysis"
STAGE_GENERATION = "generation"
STAGE_REPAIR = "repair"
STAGE_SCORING = "scoring"

ALL_STAGES = [STAGE_ANALYSIS, STAGE_GENERATION, STAGE_REPAIR, STAGE_SCORING]


@dataclass
class StageRouter:
    """Resolves per-stage AIEngine instances from repo config."""

    # Pre-built engines keyed by AIModel.id
    _engines_by_id: dict[int, "AIEngine"]
    # stage_name -> AIModel.id mapping from skills_config.stage_models
    _stage_models: dict[str, int]
    # Fallback engine (repo default or system default)
    _fallback_engine: "AIEngine"
    _fallback_model_id: Optional[int]

    def get_engine(self, stage: str) -> "AIEngine":
        """Return the AIEngine for a given stage, with fallback chain."""
        model_id = self._stage_models.get(stage)
        if model_id and model_id in self._engines_by_id:
            return self._engines_by_id[model_id]
        if model_id:
            logger.warning("stage_router.model_not_found",
                           stage=stage, model_id=model_id, fallback="repo_default")
        return self._fallback_engine

    def get_model_label(self, stage: str) -> str:
        """Return human-readable model label for logging/notifications."""
        model_id = self._stage_models.get(stage)
        if model_id and model_id in self._engines_by_id:
            engine = self._engines_by_id[model_id]
            return engine.model_config.model_id
        return self._fallback_engine.model_config.model_id
```

### 3.2 工厂函数：`build_stage_router`

```python
async def build_stage_router(
    repo,           # Repository model instance
    fallback_engine: "AIEngine",  # repo default engine
    db_session,     # async DB session to load AIModel records
) -> StageRouter:
    """Build a StageRouter from repository config."""
    from app.models.ai_model import AIModel
    from app.services.ai.engine import build_engine_from_db_model
    from sqlalchemy import select

    skills_config = repo.skills_config or {}
    stage_models = skills_config.get("stage_models", {})

    if not stage_models:
        return StageRouter(
            _engines_by_id={},
            _stage_models={},
            _fallback_engine=fallback_engine,
            _fallback_model_id=repo.ai_model_id,
        )

    # Collect unique model IDs referenced by stage_models
    needed_ids = {mid for mid in stage_models.values() if isinstance(mid, int)}

    # Load AIModel records
    engines_by_id = {}
    if needed_ids:
        result = await db_session.execute(
            select(AIModel).where(AIModel.id.in_(needed_ids))
        )
        for model in result.scalars():
            try:
                engines_by_id[model.id] = build_engine_from_db_model(model)
            except Exception as exc:
                logger.warning("stage_router.build_engine_failed",
                               model_id=model.id, error=str(exc))

    return StageRouter(
        _engines_by_id=engines_by_id,
        _stage_models=stage_models,
        _fallback_engine=fallback_engine,
        _fallback_model_id=repo.ai_model_id,
    )
```

### 3.3 同步版本（Celery 任务中使用）

```python
def build_stage_router_sync(
    repo,
    fallback_engine: "AIEngine",
    sync_session,
) -> StageRouter:
    """Synchronous version for use inside Celery tasks."""
    from app.models.ai_model import AIModel
    from app.services.ai.engine import build_engine_from_db_model

    skills_config = repo.skills_config or {}
    stage_models = skills_config.get("stage_models", {})

    if not stage_models:
        return StageRouter(
            _engines_by_id={},
            _stage_models={},
            _fallback_engine=fallback_engine,
            _fallback_model_id=repo.ai_model_id,
        )

    needed_ids = {mid for mid in stage_models.values() if isinstance(mid, int)}
    engines_by_id = {}
    if needed_ids:
        for model in sync_session.query(AIModel).filter(AIModel.id.in_(needed_ids)).all():
            try:
                engines_by_id[model.id] = build_engine_from_db_model(model)
            except Exception as exc:
                logger.warning("stage_router.build_engine_failed",
                               model_id=model.id, error=str(exc))

    return StageRouter(
        _engines_by_id=engines_by_id,
        _stage_models=stage_models,
        _fallback_engine=fallback_engine,
        _fallback_model_id=repo.ai_model_id,
    )
```

## 4. PipelineContext 改造

### 4.1 新增字段

```python
@dataclass
class PipelineContext:
    # ... existing fields ...
    stage_router: Optional[StageRouter] = None  # NEW: per-stage model router
```

### 4.2 TestManagerAgent 阶段改造

每个阶段从 `ctx.stage_router.get_engine(stage)` 获取引擎，而非直接使用 `ctx.engine`：

| 阶段 | 当前 | 改造后 |
|------|------|--------|
| `_stage_change_intelligence` | `ctx.engine` | `ctx.stage_router.get_engine("analysis")` |
| `_stage_context` | 无 LLM 调用 | 不变（无 LLM） |
| `_stage_generator` | `ctx.engine` | `ctx.stage_router.get_engine("generation")` |
| `_stage_validate_repair` → RepairAgent | `ctx.engine` | `ctx.stage_router.get_engine("repair")` |
| `_stage_quality_scorer` | `ctx.engine` | `ctx.stage_router.get_engine("scoring")` |
| `_stage_code_review` | `ctx.engine` | `ctx.stage_router.get_engine("analysis")` |

**回退保证**：当 `stage_router` 为 None 或未配置某阶段时，`get_engine()` 返回 `fallback_engine`（即原来的 `ctx.engine`），行为与改造前完全一致。

### 4.3 引擎解析辅助方法

在 `TestManagerAgent` 中添加辅助方法：

```python
def _engine_for(self, ctx: PipelineContext, stage: str) -> AIEngine:
    """Resolve engine for a stage, with safe fallback."""
    if ctx.stage_router:
        return ctx.stage_router.get_engine(stage)
    return ctx.engine
```

## 5. Pipeline 输出增强

### 5.1 `output_data` 新增 `model_usage` 字段

每个阶段的执行结果中记录实际使用的模型：

```json
{
  "model_usage": {
    "analysis": "claude-3-5-sonnet-20241022",
    "generation": "deepseek/deepseek-chat",
    "repair": "deepseek/deepseek-chat",
    "scoring": "gpt-4o-mini"
  }
}
```

### 5.2 AgentExecution 记录增强

`agent_executions` 表的 `input_data` JSONB 中新增 `model_id` 字段，记录该轮实际使用的 AIModel.id（如有）。

## 6. API 变更

### 6.1 Repository 创建/更新

`POST /api/v1/repositories` 和 `PUT /api/v1/repositories/{id}` 的 `skills_config` 字段已支持任意 JSONB，无需修改 schema。

前端传入示例：
```json
{
  "skills_config": {
    "stage_models": {
      "analysis": 1,
      "generation": 2,
      "repair": 3,
      "scoring": 1
    }
  }
}
```

### 6.2 新增验证端点（可选）

`GET /api/v1/repositories/{id}/stage-models` — 返回解析后的阶段模型映射：

```json
{
  "stages": {
    "analysis": {"model_id": 1, "model_name": "Claude 3.5 Sonnet", "status": "configured"},
    "generation": {"model_id": 2, "model_name": "DeepSeek Chat", "status": "configured"},
    "repair": {"model_id": 3, "model_name": "DeepSeek Chat", "status": "configured"},
    "scoring": {"model_id": null, "model_name": "GPT-4o-mini (default)", "status": "fallback"}
  }
}
```

## 7. 前端变更

### 7.1 Repository 配置页

在 Repository 编辑表单中新增「分阶段模型配置」区域：
- 四个下拉选择器（分析模型 / 生成模型 / 修复模型 / 评分模型）
- 每个下拉选项来自 `GET /api/v1/models` 返回的模型列表
- 默认值为「跟随仓库默认模型」
- 保存时将选择写入 `skills_config.stage_models`

### 7.2 任务详情页

Pipeline 节点展示实际使用的模型名称（从 `model_usage` 读取）。

## 8. 测试计划

### 8.1 单元测试

| 测试 | 验证内容 |
|------|---------|
| `test_stage_router_configured` | 配置了 stage_models 时，各阶段返回对应引擎 |
| `test_stage_router_fallback` | 未配置时回退到 fallback_engine |
| `test_stage_router_invalid_model_id` | 配置了不存在的 model_id 时回退 |
| `test_stage_router_empty_config` | skills_config 无 stage_models 时全部回退 |
| `test_build_stage_router_sync` | 同步版本在 Celery 上下文中正确加载模型 |

### 8.2 集成测试

| 测试 | 验证内容 |
|------|---------|
| `test_pipeline_mixed_models` | 配置 analysis=ModelA, generation=ModelB，验证各阶段调用正确模型 |
| `test_pipeline_all_fallback` | 不配置 stage_models，验证行为与改造前一致 |
| `test_model_usage_in_output` | 验证 output_data 包含正确的 model_usage |

### 8.3 验证清单

- [ ] 每个阶段使用正确配置的模型
- [ ] 未配置阶段回退到仓库默认模型
- [ ] 无效 model_id 不导致 Pipeline 崩溃
- [ ] output_data 正确记录 model_usage
- [ ] 现有 Repository（无 stage_models 配置）行为不变
- [ ] API 创建/更新 Repository 可正确保存 stage_models
- [ ] 前端配置页面可正确展示和保存

## 9. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/services/ai/stage_router.py` | **新增** | StageRouter 数据类 + 工厂函数 |
| `backend/app/services/agents/test_manager.py` | 修改 | PipelineContext 新增 stage_router；各阶段使用 `_engine_for()` |
| `backend/app/tasks/ai_tasks.py` | 修改 | `_ai_pipeline` 中构建 StageRouter 并传入 PipelineContext |
| `backend/app/api/v1/endpoints/config.py` | 修改 | （可选）新增 stage-models 查询端点 |
| `backend/app/services/ai/__init__.py` | 修改 | 导出 StageRouter |
| `frontend/src/pages/config/RepositoryForm.tsx` | 修改 | 新增分阶段模型配置区域 |
| `frontend/src/pages/logs/TaskDetailPage.tsx` | 修改 | 展示 model_usage |
| `tests/test_stage_router.py` | **新增** | 单元测试 |
| `tests/test_pipeline_stage_models.py` | **新增** | 集成测试 |

## 10. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 多模型增加 API Key 管理复杂度 | 复用现有 AIModel CRUD，无需新加密机制 |
| 阶段模型加载失败导致 Pipeline 中断 | get_engine() 始终有 fallback，不会中断 |
| Celery 同步上下文中无法使用 async session | 提供 build_stage_router_sync 同步版本 |
| 前端配置错误 model_id | 后端验证 + fallback 兜底 |
