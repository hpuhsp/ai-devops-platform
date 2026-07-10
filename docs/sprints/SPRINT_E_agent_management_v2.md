# Sprint E：Agent 管理模块 V2 — 六大改进

> 版本: v1.0.0-draft | 日期: 2026-07-10 | 基于当前 Agent 管理模块现存问题分析

## 1. 概述

### 1.1 现状

当前 Agent 管理模块（V1）已实现三层模型架构（Model → Agent → Repository），具备基本的 CRUD 和管道编排能力。但在实际使用中存在 6 个关键不足：

1. **固定 5 阶段管道** — `code_review → change_intelligence → generator → validate_repair → quality_scorer` 硬编码，无法灵活增删排序
2. **无 Agent 预设模板** — 每次创建 Agent 需手动填写三个 JSON 配置槽位，缺乏常用场景模板
3. **配置无版本管理** — Agent 配置变更无记录，无法追溯/回滚
4. **Agent 性能无监控** — `agent_executions` 表有数据但无可视化监控面板
5. **单技能绑定限制** — 一个 Agent 只能绑定一个 Skill，无法串联多个技能形成复合 Agent
6. **策略引擎粗粒度** — `policy_config` 仅自由 JSON，缺少结构化策略定义（条件触发、超时策略、重试策略）

### 1.2 目标

六个改进每个独立可交付，按依赖关系分 Sprint 实施。整体目标：

- 使 Pipeline 可动态配置（不限于 5 个固定阶段）
- 简化 Agent 创建流程（预设模板）
- 具备配置审计能力（版本管理）
- 提供 Agent 性能可视化（监控面板）
- 支持复合 Agent（多技能串联）
- 策略引擎结构化（可声明式定义执行策略）

---

## 2. 改进项一：可插拔管道（Dynamic Pipeline）

### 2.1 动机

当前 `TestManagerAgent` 的 `_stages` 列表是硬编码的 7 个阶段（含 `context` 和 `mr_feedback`），顺序固定：
```python
self._stages = [
    ("code_review", self._stage_code_review),
    ("change_intelligence", self._stage_change_intelligence),
    ("context", self._stage_context),
    ("generator", self._stage_generator),
    ("validate_repair", self._stage_validate_repair),
    ("quality_scorer", self._stage_quality_scorer),
    ("mr_feedback", self._stage_mr_feedback),
]
```

这导致：
- 无法插入自定义阶段（如 `build`, `deploy`, `security_scan`）
- 无法调整阶段顺序
- `context` 和 `mr_feedback` 这种辅助阶段与业务阶段混在一起

### 2.2 设计方案

#### 2.2.1 Pipeline 定义数据模型

新增 `PipelineTemplate` 表，定义可复用的管道模板：

```sql
CREATE TABLE pipeline_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    stages JSONB NOT NULL,           -- [{"stage_type": "...", "order": N, "required": true/false}, ...]
    is_system BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 仓库绑定管道模板（替代硬编码）
ALTER TABLE repositories ADD COLUMN pipeline_template_id INT REFERENCES pipeline_templates(id);
ALTER TABLE repositories ADD COLUMN pipeline_overrides JSONB;  -- 按仓库覆盖 stages 列表
```

`stages` JSONB 结构：

```json
[
  {"stage_type": "code_review",        "order": 1, "required": true,  "alias": "代码审查"},
  {"stage_type": "change_intelligence", "order": 2, "required": false, "alias": "变更智能"},
  {"stage_type": "context",             "order": 3, "required": false, "alias": "上下文构建"},
  {"stage_type": "generator",           "order": 4, "required": true,  "alias": "测试生成"},
  {"stage_type": "validate_repair",     "order": 5, "required": false, "alias": "验证修复"},
  {"stage_type": "quality_scorer",      "order": 6, "required": false, "alias": "质量评分"},
  {"stage_type": "mr_feedback",         "order": 7, "required": false, "alias": "MR反馈"}
]
```

#### 2.2.2 系统预置模板

| 模板名 | 包含阶段 | 适用场景 |
|--------|---------|---------|
| 标准 Git Flow | 全 7 阶段 | 默认模板 |
| 纯代码审查 | code_review → mr_feedback | 仅审查不生成测试 |
| 轻量级测试 | change_intelligence → generator → mr_feedback | 跳过审查，直接生成 |
| 全量验证 | code_review → generator → validate_repair → quality_scorer | MR 前完整检查 |

#### 2.2.3 运行时变化

`TestManagerAgent` 改为从 `PipelineTemplate` 加载阶段定义，而非硬编码 `_stages`：

```python
class TestManagerAgent:
    def __init__(self, pipeline_definition: list[dict] = None):
        self._stages = pipeline_definition or self._DEFAULT_STAGES
        # _stages 变为可注入
```

#### 2.2.4 影响的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/models/pipeline_template.py` | 新增 | PipelineTemplate ORM 模型 |
| `backend/app/models/repository.py` | 修改 | 新增 `pipeline_template_id`, `pipeline_overrides` 字段 |
| `backend/app/api/v1/endpoints/pipeline.py` | 新增 | PipelineTemplate CRUD API |
| `backend/app/api/v1/router.py` | 修改 | 注册新路由 |
| `backend/app/services/agents/test_manager.py` | 重构 | `__init__` 接受 `pipeline_definition` 参数 |
| `backend/app/tasks/ai_tasks.py` | 修改 | `_ai_pipeline` 加载管道模板 |
| `backend/alembic/versions/` | 新增 | 数据库迁移 |
| `frontend/src/pages/config/PipelinePage.tsx` | 新增 | 管道模板管理页面 |
| `frontend/src/pages/config/RepositoriesPage.tsx` | 修改 | 仓库配置增加管道模板选择 |
| `frontend/src/services/api.ts` | 修改 | 新增 API 调用 |

#### 2.2.5 验证

- 单元测试：`backend/tests/unit/test_pipeline_template.py`
- 集成测试：创建管道模板 → 绑定仓库 → 触发 Webhook → 确认阶段按定义顺序执行
- 边界：required 阶段缺失应阻止保存；空阶段列表兜底为 `code_review`

---

## 3. 改进项二：Agent 预设模板（Agent Templates）

### 3.1 动机

创建 Agent 时需填写三个 JSON 配置槽位（skill_config, model_config, policy_config），对新手不友好，且常用配置无法复用。

### 3.2 设计方案

#### 3.2.1 数据模型

```sql
CREATE TABLE agent_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    stage_type VARCHAR(50) NOT NULL,
    skill_name VARCHAR(100) NOT NULL,
    skill_config JSONB DEFAULT '{}',
    model_config JSONB DEFAULT '{}',
    policy_config JSONB DEFAULT '{}',
    tags TEXT[],                    -- 搜索/分类标签
    is_system BOOLEAN DEFAULT FALSE,
    usage_count INT DEFAULT 0,      -- 使用次数统计
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### 3.2.2 系统预置模板

| 模板名 | 阶段 | 核心配置 | 标签 |
|--------|------|---------|------|
| 严格审查型 | code_review | policy: max_retry=0, require_review=true | review, strict |
| 快速审查型 | code_review | model.temperature=0.1, max_diff_lines=1000 | review, fast |
| 全面测试生成 | generator | policy.max_retry=3, skill.run_tests=true | test, full |
| 轻量生成 | generator | skill.max_diff_lines=500, skill.run_tests=false | test, quick |
| 高精度评分 | quality_scorer | model.temperature=0.05, skill.detailed=true | score, precise |
| 自动修复型 | validate_repair | policy.max_retry=5, policy.repair_all=true | repair, auto |

#### 3.2.3 API 变化

```
GET  /api/v1/agent-templates             # 列表（支持 tag 筛选）
GET  /api/v1/agent-templates/{id}        # 详情
POST /api/v1/agent-templates             # 创建自定义模板
POST /api/v1/agent-templates/{id}/apply  # 从模板创建 Agent（核心操作）
```

`/apply` 的行为：读取模板配置 → 填充到 AgentCreate → 允许用户覆盖个别字段 → 创建 Agent。

#### 3.2.4 前端变化

AgentsPage 创建对话框增加「从模板创建」按钮，弹出模板选择器。
选择后预填表单，用户可调整。

#### 3.2.5 影响的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/models/agent_template.py` | 新增 | AgentTemplate ORM 模型 |
| `backend/app/api/v1/endpoints/agents.py` | 修改 | 新增 `/agent-templates` 路由（或用独立文件） |
| `backend/app/core/init_agents.py` | 修改 | 启动时初始化系统预置模板 |
| `frontend/src/pages/config/AgentsPage.tsx` | 修改 | 增加"从模板创建"流程 |
| `frontend/src/services/api.ts` | 修改 | 新增 API |

#### 3.2.6 验证

- 单元测试列表/创建/应用模板
- 从模板创建 Agent 后验证三个配置槽位正确填充
- 系统模板不可删除

---

## 4. 改进项三：Agent 配置版本管理（Versioning）

### 4.1 动机

当前 Agent 配置修改无记录，无法回答"上周这个 Agent 配的是什么模型？"、"谁改了什么？"等问题。

### 4.2 设计方案

#### 4.2.1 数据模型

方式：**快照表 + Diff**，每次 Agent 更新时自动生成版本记录。

```sql
CREATE TABLE agent_versions (
    id SERIAL PRIMARY KEY,
    agent_id INT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version INT NOT NULL,               -- 自增版本号
    snapshot JSONB NOT NULL,            -- 完整 Agent 配置快照
    change_summary VARCHAR(500),        -- 变更摘要（自动生成或手动填写）
    changed_by VARCHAR(100),            -- 修改人 user_key
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(agent_id, version)
);
```

#### 4.2.2 截图字段（snapshot）

```json
{
  "name": "默认代码审查",
  "description": "...",
  "stage_type": "code_review",
  "skill_name": "code_review",
  "model_id": 1,
  "skill_config": {},
  "model_config": {},
  "policy_config": {"max_retry": 0},
  "enabled": true
}
```

#### 4.2.3 触发机制

在 `agents.py` 的 `update_agent` 和 `clone_agent` 中插入版本记录：

```python
# 在 agent 更新后自动创建版本
_agent_changed(agent, db, "updated")  →  INSERT INTO agent_versions
```

使用 SQLAlchemy `after_update` 事件监听器，自动捕获变更：

```python
@event.listens_for(Agent, 'after_update')
def _on_agent_update(mapper, connection, target):
    # 计算 diff，插入 agent_versions
```

#### 4.2.4 API 变化

```
GET  /api/v1/agents/{id}/versions              # 版本列表
GET  /api/v1/agents/{id}/versions/{version}    # 版本详情
POST /api/v1/agents/{id}/rollback/{version}    # 回滚到指定版本
```

`rollback` 行为：读取指定版本的 snapshot → 覆盖当前 Agent 字段 → 创建新版本记录 → 返回新版本。

#### 4.2.5 前端变化

Agent 详情/编辑页增加「版本历史」标签页，展示：
- 版本号/时间/变更人/变更摘要
- 点击版本可对比 Diff（当前 vs 历史）
- 「回滚到此版本」按钮

#### 4.2.6 影响的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/models/agent_version.py` | 新增 | AgentVersion ORM 模型 |
| `backend/app/api/v1/endpoints/agents.py` | 修改 | 新增版本管理路由 |
| `backend/app/services/agents/versioning.py` | 新增 | 版本记录/对比/Diff 生成逻辑 |
| `frontend/src/pages/config/AgentVersions.tsx` | 新增 | 版本历史页面 |
| `frontend/src/pages/config/AgentsPage.tsx` | 修改 | 增加版本入口 |
| `frontend/src/services/api.ts` | 修改 | 新增 API |

#### 4.2.7 验证

- 更新 Agent 后确认版本 +1
- 回滚后确认配置恢复到指定版本
- 删除 Agent 时级联删除版本记录
- 系统 Agent 也可回滚（但只允许回滚到系统模板版本）

---

## 5. 改进项四：Agent 性能监控面板（Agent Monitor）

### 5.1 动机

`agent_executions` 表记录了每次 Agent 调用的完整数据（状态、Token 消耗、耗时、轮次），但缺乏可视化面板查看趋势——无法回答"哪个 Agent 失败率最高？"、"Token 消耗趋势如何？"等问题。

### 5.2 设计方案

#### 5.2.1 数据聚合

新增 `agent_stats` 物化视图或 API 层聚合，按时间窗口提供：

```sql
-- 每次查询时聚合（API 层），或定期物化
CREATE MATERIALIZED VIEW agent_stats_hourly AS
SELECT
    agent_type,
    date_trunc('hour', created_at) AS hour,
    COUNT(*) AS total_calls,
    SUM(CASE WHEN status IN ('success', 'all_pass', 'passed') THEN 1 ELSE 0 END) AS success_calls,
    SUM(CASE WHEN status IN ('failed', 'error') THEN 1 ELSE 0 END) AS failed_calls,
    AVG(duration_ms) AS avg_duration_ms,
    COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
    COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
    COUNT(DISTINCT task_id) AS affected_tasks
FROM agent_executions
GROUP BY agent_type, date_trunc('hour', created_at);
```

#### 5.2.2 API

```
GET /api/v1/stats/agents/overview            # 今日概览（总数/成功率/Token 趋势）
GET /api/v1/stats/agents/{agent_type}        # 单个 Agent 详情趋势
GET /api/v1/stats/agents/ranking             # 按失败率/耗时排序
```

#### 5.2.3 前端监控面板

位置：在 DashboardPage 增加「Agent 监控」Tab，或独立页面 `/monitor/agents`

包含：
- **总览卡片**：今日调用次数、成功率、平均耗时、总 Token 消耗
- **趋势折线图**：按小时的调用量/成功率/Token
- **Agent 排行表**：按失败率降序，显示最近 24h 数据
- **单 Agent 详情**：点击进入详情，展示轮次分布、失败类型饼图、耗时分布
- **失败记录列表**：最近的失败调用，可跳转到对应任务详情

图表优先使用后端聚合数据，前端 `@ant-design/charts` 渲染（项目已有依赖）。

#### 5.2.4 影响的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/api/v1/endpoints/stats.py` | 修改 | 新增 Agent 统计端点 |
| `backend/app/services/stats/agent_stats.py` | 新增 | Agent 统计聚合逻辑 |
| `frontend/src/pages/dashboard/DashboardPage.tsx` | 修改 | 增加 Agent 监控 Tab |
| `frontend/src/pages/monitor/AgentMonitor.tsx` | 可选新增 | 独立监控页面 |
| `frontend/src/services/api.ts` | 修改 | 新增请求函数 |

#### 5.2.5 验证

- 确认 API 返回聚合数据与原始 `agent_executions` 表一致
- 趋势图跨天数据正常
- 空数据（无执行记录）展示友好空状态

---

## 6. 改进项五：复合 Agent（Compound Agent）

### 6.1 动机

当前一个 Agent 只能绑定一个 `skill_name`，无法完成"先审查再评分"、"先生成再验证"这种需要多技能串联的复合任务。比如用户希望一个 Agent 同时做 `code_review` + `quality_scorer`。

### 6.2 设计方案

#### 6.2.1 数据模型扩展

在 `agents` 表增加复合 Agent 支持，有两种路径：

**路径 A（推荐）— 子 Agent 引用**

```json
// Agent.skill_config 中扩展复合定义
{
  "compound": {
    "mode": "sequential",        // sequential | parallel | conditional
    "sub_agents": [
      {"agent_id": 1, "on_fail": "stop"},    // 失败则整个停止
      {"agent_id": 3, "on_fail": "continue"} // 失败继续执行
    ]
  }
}
```

**路径 B — 内置 CompoundSkill**

新增 `compound` Skill 类型，`CompoundSkill` 内部按配置依次调用子技能：

```python
class CompoundSkill(SkillBase):
    name = "compound"
    stage_type = "*"  # 可绑定任意阶段

    async def execute(self, context, engine) -> SkillResult:
        for sub in self.config.get("steps", []):
            sub_skill = skill_registry.get(sub["skill_name"])
            result = await sub_skill.execute(context, engine)
            if not result.success and sub.get("on_fail") == "stop":
                return result
        return merged_result
```

**推荐路径 A**，因为复用现有的 Agent 配置（模型绑定、策略配置），且子 Agent 独立可观测。

#### 6.2.2 Agent 模型变更

在 `Agent` 模型中新增字段：

```python
class Agent(Base):
    # ... 现有字段 ...
    agent_type = Column(String(20), default="simple")  # simple | compound
    # compound 时从 skill_config 读取 compound 定义
```

#### 6.2.3 API 变化

```
POST /api/v1/agents/compound     # 创建复合 Agent
# body: {name, description, stage_type, compound: {mode, sub_agents: [{agent_id, on_fail}]}}
```

GET 返回复合 Agent 时增加 `compound` 字段和子 Agent 摘要。

#### 6.2.4 pipeline 变化

`TestManagerAgent._stage_generator` 等阶段函数中，当 `agent_resolver.get_skill_name()` 返回的 Agent 是 compound 类型时，不走 `skill_registry.execute(skill_name)`，而是调用 `CompoundExecutor`：

```python
if agent_resolver.get_binding(stage_type).agent_type == "compound":
    result = await compound_executor.run(agent, context, engine)
else:
    result = await skill_registry.execute(skill_name, context, engine)
```

`agent_executions` 中复合 Agent 执行记录展开为多条（每条子 Agent 一条记录，通过 `parent_execution_id` 关联）。

#### 6.2.5 影响的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/models/agent.py` | 修改 | 新增 `agent_type` 字段 |
| `backend/app/services/agents/compound_executor.py` | 新增 | 复合 Agent 执行引擎 |
| `backend/app/services/agents/test_manager.py` | 修改 | `_engine_for` / `_execute_stage` 判断复合类型 |
| `backend/app/models/agent_execution.py` | 修改 | 新增 `parent_execution_id` 字段 |
| `backend/app/api/v1/endpoints/agents.py` | 修改 | 新增复合 Agent 创建/查看逻辑 |
| `frontend/src/pages/config/AgentsPage.tsx` | 修改 | 复合 Agent 配置 UI |

#### 6.2.6 验证

- 创建复合 Agent 并绑定到仓库
- 触发管道后确认子 Agent 按顺序执行
- 子 Agent 失败时 `on_fail=stop` 和 `on_fail=continue` 行为正确
- `agent_executions` 父子关联记录正确

---

## 7. 改进项六：结构化策略引擎（Policy Engine）

### 7.1 动机

当前 `policy_config` 是自由格式 JSON，缺乏结构化和可解释性。比如 `{"max_retry": 3, "require_review": true}` 是约定俗成的 key，没有 schema 校验也没有运行时解释。

需要一个可声明、可扩展的策略引擎，支持条件触发和组合策略。

### 7.2 设计方案

#### 7.2.1 结构化策略 Schema

`policy_config` 从自由 JSON 升级为结构化策略定义：

```json
{
  "execution": {
    "timeout_seconds": 120,
    "max_retry": 3,
    "retry_delay_seconds": 10,
    "retry_backoff": "exponential"     // fixed | exponential
  },
  "quality": {
    "min_score": 6.0,
    "require_coverage": true,
    "min_coverage_delta": 0.5
  },
  "conditions": [
    {
      "if": {"changed_files_contain": "**/payment/**"},
      "then": {"stage": "security_scan", "required": true}
    },
    {
      "if": {"branch_pattern": "hotfix/*"},
      "then": {"max_retry": 0, "require_review": true}
    }
  ],
  "notification": {
    "on_success": ["feishu"],
    "on_failure": ["feishu", "slack"],
    "on_retry": false
  }
}
```

#### 7.2.2 Policy Schema 注册表

新增 `policy_schemas` 概念——每种 policy 字段有定义好的 schema（使用 Pydantic）：

```python
# backend/app/services/policy/schemas.py

class ExecutionPolicy(BaseModel):
    timeout_seconds: int = Field(default=60, ge=10, le=600)
    max_retry: int = Field(default=3, ge=0, le=10)
    retry_delay_seconds: int = Field(default=10, ge=0)
    retry_backoff: Literal["fixed", "exponential"] = "exponential"

class QualityPolicy(BaseModel):
    min_score: float = Field(default=6.0, ge=0, le=10)
    require_coverage: bool = False
    min_coverage_delta: float = Field(default=0.5, ge=0)

class PolicyConfig(BaseModel):
    execution: ExecutionPolicy = ExecutionPolicy()
    quality: QualityPolicy = QualityPolicy()
    conditions: list[ConditionRule] = []
    notification: NotificationPolicy = NotificationPolicy()
```

#### 7.2.3 策略评估引擎

```python
# backend/app/services/policy/engine.py

class PolicyEngine:
    def evaluate(self, policy: PolicyConfig, context: EvalContext) -> PolicyDecision:
        """评估策略，返回决策结果。"""
        decisions = []

        # 1. 条件策略评估
        for condition in policy.conditions:
            if self._match_condition(condition.if_, context):
                decisions.extend(self._apply_then(condition.then))

        # 2. 质量策略评估
        if context.quality_score < policy.quality.min_score:
            decisions.append(PolicyDecision("block", f"质量分 {context.quality_score} < {policy.quality.min_score}"))

        return PolicyDecisionGroup(decisions)

    def _match_condition(self, condition: dict, context: EvalContext) -> bool:
        """匹配条件表达式。"""
        for key, pattern in condition.items():
            if key == "changed_files_contain":
                if not any(Path(context.file).match(pattern) for context.changed_files):
                    return False
            elif key == "branch_pattern":
                if not fnmatch.fnmatch(context.branch, pattern):
                    return False
        return True
```

#### 7.2.4 Pipeline 集成

`TestManagerAgent` 在执行每个阶段前先调用 `PolicyEngine.evaluate()`，根据决策结果决定：
- `allow` — 正常执行
- `skip` — 跳过此阶段
- `block` — 阻止合并
- `override_config` — 使用策略指定的配置覆盖

```python
async def _run_stage(self, ctx, stage_name, stage_fn):
    policy_decision = self._policy_engine.evaluate(
        ctx.policy_config,
        EvalContext(stage=stage_name, quality_score=..., branch=ctx.skill_context.branch)
    )
    if policy_decision.action == "block":
        return StageResult(status="blocked", reason=policy_decision.reason)
    if policy_decision.action == "skip":
        return StageResult(status="skipped", reason=policy_decision.reason)
    # 合并策略覆写
    if policy_decision.config_overrides:
        ctx.override_config(policy_decision.config_overrides)
    return await stage_fn(ctx)
```

#### 7.2.5 Policy 继承链

每个阶段的最终 policy 由三层合并决定（优先级从高到低）：

1. **仓库级** `repositories.skills_config.policy_overrides` — 仓库自定义覆盖
2. **Agent 级** `agents.policy_config` — Agent 自身策略
3. **系统默认** — `PolicyConfig()` 默认值

合并策略：顶层 key 整体覆盖（不做深度 merge），避免意外残留。

#### 7.2.6 影响的文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/services/policy/schemas.py` | 新增 | Pydantic 策略 Schema |
| `backend/app/services/policy/engine.py` | 新增 | 策略评估引擎 |
| `backend/app/services/policy/condition.py` | 新增 | 条件匹配器 |
| `backend/app/services/agents/test_manager.py` | 重构 | 集成 PolicyEngine |
| `backend/app/api/v1/endpoints/agents.py` | 修改 | 创建/更新 Agent 时校验 policy_config |
| `backend/app/core/config.py` | 修改 | 可能增加默认策略常量 |
| `frontend/src/pages/config/AgentsPage.tsx` | 修改 | Policy 配置 UI 从 JSON 输入改为结构化表单 |

#### 7.2.7 验证

- 策略 Schema 校验：非法 timeout 值应拒绝
- 条件匹配：`changed_files_contain: **/payment/**` 匹配 `src/payment/order.py`
- 三层合并：Agent 级覆盖仓库级
- `quality.min_score` block 逻辑：低分正确阻止

---

## 8. 实施路线图

| 改进项 | 依赖 | 预估人天 | 优先级 |
|--------|------|---------|--------|
| 1. 可插拔管道 | 无 | 3 | P0 — 基础设施 |
| 2. Agent 预设模板 | 无 | 2 | P1 — 体验提升 |
| 3. 配置版本管理 | 无 | 1.5 | P1 — 可追溯 |
| 4. Agent 监控面板 | 无 | 2.5 | P1 — 可观测 |
| 5. 复合 Agent | 依赖 1（管道可扩展） | 3 | P2 — 高级功能 |
| 6. 策略引擎 | 依赖 1（管道需要策略决策点） | 4 | P2 — 高级功能 |

### 建议实施顺序

```
Sprint E.1: 可插拔管道 (P0) + 版本管理 (P1)    — 先打好基础
Sprint E.2: Agent 预设模板 (P1) + 监控面板 (P1)  — 体验 + 可观测
Sprint E.3: 策略引擎 (P2) + 复合 Agent (P2)     — 高级功能收尾
```

---

## 9. 风险与开放问题

### 9.1 风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 可插拔管道破坏现有仓库的管线行为 | 中 | 高 | 默认模板与当前硬编码行为完全一致，存量仓库自动绑定标准模板 |
| 策略引擎过度设计 | 中 | 中 | YAGNI — 先实现执行和质量策略，条件策略简化 |
| 复合 Agent 的递归风险 | 低 | 高 | 禁止复合 Agent 引用自身（DB 层校验） |

### 9.2 开放问题

1. 可插拔管道的阶段是否需要支持「并行执行」？一期只做顺序，二期考虑并行
2. 版本管理的 Diff 对比：是否需要对 JSON 做语义化 Diff（只显示有变化的字段）？建议使用 `deepdiff` 库
3. 监控面板的保留周期：`agent_executions` 数据是否定时清理？建议通过配置保留天数（默认 90 天）
4. 复合 Agent 的子 Agent 是否允许也是复合 Agent？一期禁止嵌套（深度 = 1），二期开放

---

## 10. 附录：受影响文件全览

| 改进项 | 新增文件 | 修改文件 |
|--------|---------|---------|
| 1. 可插拔管道 | `models/pipeline_template.py`, `api/v1/endpoints/pipeline.py`, `frontend/.../PipelinePage.tsx` | `models/repository.py`, `agents/test_manager.py`, `tasks/ai_tasks.py`, `router.py`, `RepositoriesPage.tsx` |
| 2. Agent 模板 | `models/agent_template.py` | `agents.py` API, `init_agents.py`, `AgentsPage.tsx` |
| 3. 版本管理 | `models/agent_version.py`, `services/agents/versioning.py`, `AgentVersions.tsx` | `agents.py` API, `AgentsPage.tsx` |
| 4. 监控面板 | `services/stats/agent_stats.py` | `stats.py` API, `DashboardPage.tsx` |
| 5. 复合 Agent | `services/agents/compound_executor.py` | `models/agent.py`, `models/agent_execution.py`, `agents.py`, `test_manager.py` |
| 6. 策略引擎 | `services/policy/schemas.py`, `services/policy/engine.py`, `services/policy/condition.py` | `test_manager.py`, `agents.py`, `AgentsPage.tsx` |
