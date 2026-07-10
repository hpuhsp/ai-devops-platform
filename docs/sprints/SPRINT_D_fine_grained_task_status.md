# Sprint D：细粒度任务状态机

## 1. 背景与动机

### 1.1 现状
当前 `AITask.status` 仅有 4 个状态：
```
pending → running → success / failed
```

所有 Pipeline 阶段（代码审查、变更分析、上下文构建、测试生成、验证修复、质量评分、MR 反馈）共享同一个 `running` 状态，前端无法展示 Pipeline 的实时进度。

### 1.2 规范文档要求
根据《AI单元测试Agent_API接口设计文档_V1.0》，任务状态应为 7 个：

```
CREATED → ANALYZING → GENERATING → EXECUTING → REPAIRING → SUCCESS / FAILED
```

| 状态 | 含义 | 对应 Pipeline 阶段 |
|------|------|-------------------|
| `CREATED` | 任务已创建，尚未开始 | 任务入库后 |
| `ANALYZING` | 正在分析代码变更 | code_review + change_intelligence + context |
| `GENERATING` | 正在生成测试代码 | generator |
| `EXECUTING` | 正在执行测试 | validate（首次执行） |
| `REPAIRING` | 正在修复失败的测试 | repair + 重新执行 |
| `SUCCESS` | 全部完成，测试通过 | 终态 |
| `FAILED` | 执行失败，无法继续 | 终态 |

### 1.3 目标
实现 7 状态细粒度状态机，前端可实时展示 Pipeline 进度。

## 2. 状态机设计

### 2.1 状态枚举

```python
# backend/app/models/task_status.py (新增)

class TaskStatus:
    CREATED = "created"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    EXECUTING = "executing"
    REPAIRING = "repairing"
    SUCCESS = "success"
    FAILED = "failed"

    # 终态集合
    TERMINAL = {SUCCESS, FAILED}

    # 合法转换表
    TRANSITIONS = {
        CREATED:   {ANALYZING, FAILED},
        ANALYZING: {GENERATING, FAILED},       # 分析后可能 gated（→FAILED with reason）
        GENERATING:{EXECUTING, FAILED},
        EXECUTING: {REPAIRING, SUCCESS, FAILED},  # 通过→SUCCESS，失败→REPAIRING
        REPAIRING: {EXECUTING, SUCCESS, FAILED},  # 修复后重新执行，或修复成功
        SUCCESS:   set(),                        # 终态
        FAILED:    set(),                        # 终态
    }

    ALL = set(TRANSITIONS.keys())

    @classmethod
    def is_valid_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, set())
```

### 2.2 状态转换图

```
CREATED ──→ ANALYZING ──→ GENERATING ──→ EXECUTING ──→ SUCCESS
   │            │              │              │            ↑
   │            ↓              ↓              ↓            │
   └──────→ FAILED ←──────────┴──────── REPAIRING ────────┘
                                    ↑        │
                                    └────────┘
                              (repair → re-execute)
```

### 2.3 特殊处理：变更分析 Gated

当 `change_intelligence` 返回 `need_test = false` 时：
- 状态从 `ANALYZING` → `SUCCESS`（分析完成，决定不生成测试）
- `output_data` 中记录 `gated = true` 和 `skip_reason`

**注意**：这不是失败，而是分析成功后的正常决策。

修正状态转换：
```python
TRANSITIONS = {
    CREATED:    {ANALYZING, FAILED},
    ANALYZING:  {GENERATING, SUCCESS, FAILED},  # SUCCESS = gated（不需要测试）
    GENERATING: {EXECUTING, FAILED},
    EXECUTING:  {REPAIRING, SUCCESS, FAILED},
    REPAIRING:  {EXECUTING, SUCCESS, FAILED},
    SUCCESS:    set(),
    FAILED:     set(),
}
```

## 3. 数据库变更

### 3.1 字段扩容

当前 `status` 字段为 `String(20)`，新状态名最长 `analyzing`（9 字符），无需扩容。

### 3.2 向后兼容

旧数据中的状态值需要映射：
```python
LEGACY_STATUS_MAP = {
    "pending": TaskStatus.CREATED,
    "running": TaskStatus.ANALYZING,  # 旧 running 映射到 analyzing
}
```

### 3.3 数据库迁移

**新增迁移文件**：`backend/alembic/versions/0003_task_status_fine_grained.py`

```python
"""Fine-grained task status machine (4 states → 7 states)"""

from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    # 迁移旧数据
    op.execute("UPDATE ai_tasks SET status = 'created' WHERE status = 'pending'")
    op.execute("UPDATE ai_tasks SET status = 'analyzing' WHERE status = 'running'")
    # success/failed 保持不变


def downgrade():
    op.execute("UPDATE ai_tasks SET status = 'pending' WHERE status IN ('created', 'analyzing', 'generating', 'executing', 'repairing')")
    op.execute("UPDATE ai_tasks SET status = 'running' WHERE status = 'analyzing'")
```

## 4. 核心实现

### 4.1 PipelineContext 新增状态回调

```python
@dataclass
class PipelineContext:
    # ... existing fields ...
    status_callback: Optional[Callable] = None  # NEW: async callback to update task status
```

### 4.2 状态更新辅助函数

```python
# backend/app/tasks/ai_tasks.py

async def _update_task_status(task_id: str, new_status: str, loop=None):
    """Update task status in DB. Safe to call from async context."""
    from app.models.task_status import TaskStatus

    def _sync_update():
        with psycopg2.connect(settings.DATABASE_PURE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ai_tasks SET status = %s, updated_at = now() WHERE task_id = %s",
                    (new_status, task_id)
                )
            conn.commit()

    if loop:
        await loop.run_in_executor(None, _sync_update)
    else:
        _sync_update()
```

### 4.3 TestManagerAgent 状态注入

每个阶段执行前/后调用状态回调：

```python
async def run(self, ctx: PipelineContext):
    for stage_name, handler in self._stages:
        # 阶段前状态更新
        status_map = {
            "code_review": TaskStatus.ANALYZING,
            "change_intelligence": TaskStatus.ANALYZING,
            "context": TaskStatus.ANALYZING,
            "generator": TaskStatus.GENERATING,
            "validate_repair": TaskStatus.EXECUTING,  # 首次执行
            "quality_scorer": TaskStatus.EXECUTING,   # 测试已通过
            "mr_feedback": TaskStatus.SUCCESS,
        }

        new_status = status_map.get(stage_name)
        if new_status and ctx.status_callback:
            await ctx.status_callback(new_status)

        # ... 执行阶段 ...
```

### 4.4 Repair 循环中的状态切换

```python
# 在 _stage_validate_repair 中
async def _stage_validate_repair(self, ctx):
    # ...
    for round_num in range(1, max_rounds + 1):
        if round_num == 1:
            # 首次执行：状态已经是 EXECUTING
            pass
        else:
            # 后续修复轮次：切换到 REPAIRING
            if ctx.status_callback:
                await ctx.status_callback(TaskStatus.REPAIRING)

        # 执行测试
        result = await _run_worktree_tests(...)

        if result["status"] == "passed":
            # 测试通过
            if ctx.status_callback:
                await ctx.status_callback(TaskStatus.SUCCESS)
            break
        else:
            # 测试失败，尝试修复
            if round_num < max_rounds:
                # 状态切换到 REPAIRING（下一轮循环开头）
                pass
            else:
                # 最后一轮仍失败
                if ctx.status_callback:
                    await ctx.status_callback(TaskStatus.FAILED)
```

### 4.5 Change Intelligence Gated 处理

```python
async def _stage_change_intelligence(self, ctx):
    # ... 执行分析 ...
    if not ci_data.get("need_test", True):
        # Gated: 不需要测试，直接成功
        if ctx.status_callback:
            await ctx.status_callback(TaskStatus.SUCCESS)
        return StageResult(status="gated", output=ci_data)
```

## 5. Celery 任务改造

### 5.1 `process_push_event` 改造

```python
@celery_app.task(bind=True, name="ai_tasks.process_push_event", max_retries=2)
def process_push_event(self, repo_id: int, event_data: dict):
    task_id = self.request.id

    with SyncSession() as db:
        # 创建任务记录，状态 = created
        task = AITask(task_id=task_id, repo_id=repo_id, ...)
        task.status = TaskStatus.CREATED
        db.add(task)
        db.commit()

        # ... 加载 repo, model ...

        # 定义状态回调（同步版本，用于 Celery）
        def sync_status_callback(new_status):
            db.query(AITask).filter(AITask.task_id == task_id).update(
                {"status": new_status, "updated_at": func.now()}
            )
            db.commit()

        # 构建 async 包装
        async def async_status_callback(new_status):
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: sync_status_callback(new_status))

        # 运行 Pipeline
        try:
            _run_async(_ai_pipeline(repo, model, event_data, task_id,
                                     notify_cfg, enabled_stages,
                                     status_callback=async_status_callback))
        except Exception as exc:
            sync_status_callback(TaskStatus.FAILED)
            _mark_failed(db, task_id, str(exc))
```

### 5.2 `_ai_pipeline` 签名变更

```python
async def _ai_pipeline(repo, model, event_data, task_id, notify_cfg,
                        enabled_stages, status_callback=None):
    # ... 构建 PipelineContext ...
    pipeline_ctx = PipelineContext(
        # ... existing fields ...
        status_callback=status_callback,
    )

    # 初始状态
    if status_callback:
        await status_callback(TaskStatus.ANALYZING)

    await TestManagerAgent().run(pipeline_ctx)
```

## 6. API 变更

### 6.1 任务查询响应

`GET /api/v1/tasks/{task_id}` 响应中 `status` 字段现在返回 7 种状态之一：

```json
{
  "task_id": "abc-123",
  "status": "generating",
  "pipeline": {
    "nodes": [
      {"id": "code_review", "status": "done"},
      {"id": "change_intelligence", "status": "done"},
      {"id": "test_generation", "status": "running"},
      {"id": "auto_merge", "status": "pending"}
    ]
  }
}
```

### 6.2 前端 Pipeline 节点状态映射

| Task Status | Pipeline 节点高亮 |
|-------------|------------------|
| `created` | 所有节点 pending |
| `analyzing` | code_review + change_intelligence 节点 running |
| `generating` | code_review + change_intelligence done，generator running |
| `executing` | generator done，validate running |
| `repairing` | validate running（repair 模式） |
| `success` | 所有节点 done |
| `failed` | 当前阶段节点 failed |

### 6.3 SSE 流增强

`GET /api/v1/tasks/{task_id}/stream` 的 SSE 事件中新增 `status` 字段的细粒度值，前端可实时更新进度条。

## 7. 前端变更

### 7.1 任务列表页

**文件**：`frontend/src/pages/logs/TaskListPage.tsx`

状态标签映射：
```typescript
const STATUS_CONFIG = {
  created:    { color: "default", label: "已创建" },
  analyzing:  { color: "processing", label: "分析中" },
  generating: { color: "processing", label: "生成中" },
  executing:  { color: "processing", label: "执行中" },
  repairing:  { color: "warning", label: "修复中" },
  success:    { color: "success", label: "成功" },
  failed:     { color: "error", label: "失败" },
};
```

### 7.2 任务详情页

**文件**：`frontend/src/pages/logs/TaskDetailPage.tsx`

Pipeline 进度条根据当前状态高亮对应节点：
- 已完成节点：绿色 ✓
- 当前节点：蓝色动画
- 未来节点：灰色
- 失败节点：红色 ✗

### 7.3 类型定义更新

**文件**：`frontend/src/types/task.ts`（或等效位置）

```typescript
export type TaskStatus =
  | 'created'
  | 'analyzing'
  | 'generating'
  | 'executing'
  | 'repairing'
  | 'success'
  | 'failed';
```

## 8. 测试计划

### 8.1 单元测试

| 测试 | 验证内容 |
|------|---------|
| `test_status_transitions_valid` | 合法转换通过验证 |
| `test_status_transitions_invalid` | 非法转换被拒绝 |
| `test_terminal_states` | SUCCESS/FAILED 无出边 |
| `test_gated_to_success` | ANALYZING → SUCCESS（gated）合法 |
| `test_repair_cycle` | EXECUTING → REPAIRING → EXECUTING 循环 |
| `test_legacy_status_map` | pending→created, running→analyzing |

### 8.2 集成测试

| 测试 | 验证内容 |
|------|---------|
| `test_pipeline_status_flow` | Pipeline 执行过程中状态按 CREATED→ANALYZING→GENERATING→EXECUTING→SUCCESS 流转 |
| `test_pipeline_repair_status` | 修复循环中状态在 EXECUTING↔REPAIRING 间切换 |
| `test_pipeline_gated_status` | Gated 时状态为 CREATED→ANALYZING→SUCCESS |
| `test_pipeline_failed_status` | 失败时状态为 ...→FAILED |
| `test_migration_legacy_data` | 迁移后旧 pending/running 数据正确转换 |

### 8.3 验证清单

- [ ] 新任务创建后状态为 `created`
- [ ] Pipeline 执行过程中状态正确流转
- [ ] 分析 gated 时状态为 `success`（非 failed）
- [ ] 修复循环中状态在 `executing`↔`repairing` 间切换
- [ ] 最终状态为 `success` 或 `failed`
- [ ] 旧数据（pending/running）迁移后正确展示
- [ ] API 返回正确的细粒度状态
- [ ] SSE 流推送细粒度状态更新
- [ ] 前端正确展示 7 种状态标签
- [ ] Pipeline 节点高亮与当前状态匹配

## 9. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/models/task_status.py` | **新增** | TaskStatus 枚举 + 转换规则 |
| `backend/app/models/__init__.py` | 修改 | 导出 TaskStatus |
| `backend/app/models/ai_task.py` | 修改 | 默认状态改为 `created` |
| `backend/alembic/versions/0003_task_status_fine_grained.py` | **新增** | 数据迁移 |
| `backend/app/services/agents/test_manager.py` | 修改 | 各阶段注入状态回调 |
| `backend/app/tasks/ai_tasks.py` | 修改 | 状态回调实现 + Pipeline 签名变更 |
| `backend/app/api/v1/endpoints/tasks.py` | 修改 | `_build_pipeline_nodes` 适配新状态 |
| `frontend/src/pages/logs/TaskListPage.tsx` | 修改 | 7 种状态标签 |
| `frontend/src/pages/logs/TaskDetailPage.tsx` | 修改 | Pipeline 节点高亮逻辑 |
| `tests/test_task_status.py` | **新增** | 状态机单元测试 |
| `tests/test_pipeline_status_flow.py` | **新增** | Pipeline 状态流集成测试 |

## 10. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 状态更新增加 DB 写入频率 | 仅在阶段切换时更新（最多 7 次/Pipeline），可忽略 |
| 旧前端不识别新状态 | 前端 fallback：未知状态显示为灰色 "未知" |
| 迁移失败导致旧数据不可读 | 迁移脚本包含完整 legacy→new 映射 |
| Celery 同步上下文中的状态更新 | 使用 psycopg2 直连 + run_in_executor |
| 并发 Pipeline 导致状态竞争 | Celery worker_prefetch_multiplier=1 保证串行 |
