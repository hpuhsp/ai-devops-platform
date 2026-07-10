# AI 单元测试 Agent 精进增强 — 开发总规格文档

> 基于: AI单元测试Agent技术详细设计方案_V1.0 + AI单元测试Agent平台建设方案规格文档_V1.0
> 当前基线: ai-devops-platform 一期（已就绪）
> 版本: V2.0-dev | 日期: 2026-07-07

---

## 1. 建设目标

将一期的**单次 LLM 调用生成测试**升级为**多 Agent 协作的智能测试闭环**：

| 能力 | 一期现状 | 本次目标 |
|------|---------|---------|
| 触发方式 | Push + MR 同等对待 | MR 优先，Push 可配置跳过测试生成 |
| 变更分析 | 无（直接生成） | Change Intelligence 决策是否生成 |
| 上下文 | 仅 diff + changed_files | 已有测试发现 + 导入依赖 + 项目规范 |
| 生成策略 | 单次 prompt | Multi-Agent: Context → Generator → Validator → Repair |
| 测试执行 | 白名单 pytest 单次运行 | 运行 → 失败分析 → 修复 → 重试（最多 3 轮） |
| 反馈 | 飞书通知 | 飞书 + **MR Comment 回写** |
| 质量评估 | pass/fail | 测试质量评分（覆盖率增量 + 断言质量 + 可维护性） |

---

## 2. 架构演进

```
┌─────────────────────────────────────────────────────────────────────┐
│                     现有基础设施（不变）                               │
│  PostgreSQL │ Redis │ Celery │ FastAPI │ React │ Docker Compose      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                   新增 / 增强模块                                     │
│                                                                      │
│  ┌────────────────┐   ┌────────────────────┐   ┌────────────────┐  │
│  │ Change Intel   │   │  Test Agent Orch   │   │  MR Feedback   │  │
│  │  (决策层)      │   │  (多Agent编排)      │   │  (Comment)     │  │
│  └───────┬────────┘   └────────┬───────────┘   └───────┬────────┘  │
│          │                     │                        │           │
│  ┌───────▼────────┐   ┌───────▼───────────────────────▼────────┐  │
│  │ Context Agent  │   │         Generator Agent                 │  │
│  │ (已有测试/导入  │   │  (增强 prompt + 业务理解)                │  │
│  │  图/项目规范)   │   └───────────────────┬───────────────────┘  │
│  └────────────────┘                       │                       │
│                           ┌───────────────▼────────────────────┐  │
│                           │       Validator Agent               │  │
│                           │  (WorkTree 执行 + 结果分析)          │  │
│                           └───────────────┬────────────────────┘  │
│                                           │ fail?                  │
│                           ┌───────────────▼────────────────────┐  │
│                           │       Repair Agent                  │  │
│                           │  (失败分析 + 修复 + 重试)            │  │
│                           └────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 模块详细设计

### 3.1 Change Intelligence（变更智能分析）

**位置**: `backend/app/services/skills/builtin/change_intelligence.py`

**职责**: 基于 diff + CodeGraph 影响面决策是否需要生成测试，并精确定位测试目标

**输入**:
- git diff（内容）
- 修改文件列表（`git diff --name-only`）
- 文件类型（.py / .java / .ts / config / docs）
- **CodeGraph 影响面**（`codegraph diff-impact --format json`）— 被变更函数的所有调用者/被调用者
- 历史缺陷数据（查询 `ai_tasks` 中同文件近 30 天的 `blocked` 记录数）
- 覆盖率变化（可选，若项目接入 coverage 工具则读取）

**CodeGraph 接入方式决策**:

CodeGraph 支持 CLI / MCP / TypeScript API 三种方式。本项目选择 **CLI**，原因：
- 后端为 Python，TypeScript API 需跨语言服务，ROI 不划算
- MCP 设计语义是 "Tool for LLM"（动态工具发现），而本场景是管道中确定性步骤直接调用
- CLI 对预构建 db 的支持最直接，零额外依赖

**前提**: 目标开发项目已预先执行 `codegraph index` 生成 `codegraph.db` 并提交至 git。
本平台**不**在运行时执行 index，**不**向目标仓库写入任何文件（零侵入原则）。

**CodeGraph 集成流程**:
```bash
# WorkTree checkout 后，codegraph.db 已随代码一起存在
# 直接查询预构建的 db，无需 index
codegraph diff-impact --db codegraph.db --format json < changed_files.txt
```

输出示例:
```json
{
  "affected_symbols": [
    {"symbol": "OrderService.create_order", "file": "app/services/order.py", "callers": ["api.views.create_order_view", "tasks.process_order"]},
    {"symbol": "OrderValidator.validate", "file": "app/validators/order.py", "callers": ["OrderService.create_order"]}
  ]
}
```

**降级策略**:
1. `codegraph` CLI 未安装（`shutil.which("codegraph") is None`）→ 退化为纯文件级分析
2. 目标仓库无 `codegraph.db` → 退化为纯文件级分析
3. 两者均可用时才启用精确影响面分析

**输出 schema**:
```json
{
  "need_test": true,
  "risk_level": "high|medium|low|none",
  "reason": "新增核心业务方法 OrderService.create_order，影响 2 个调用者",
  "targets": [
    {"file": "app/services/order.py", "functions": ["create_order", "validate_params"], "callers": ["create_order_view"]},
    {"file": "app/validators/order.py", "functions": ["validate"], "callers": ["create_order"]}
  ],
  "impact_radius": 4,
  "historical_defects": 2,
  "skip_reason": null
}
```

**跳过规则（无需 LLM，快速路径）**:
- 纯文档变更（.md / .txt / .rst）
- 纯配置变更（.yml / .toml / .ini，无逻辑）
- 仅删除文件
- diff 为空
- CodeGraph 影响面 = 0 且无新增函数

**LLM 判断场景**:
- 新增/修改业务函数
- 修改核心逻辑分支
- 变更涉及错误处理
- CodeGraph 影响半径 ≥ 3（高风险变更）

---

### 3.2 Context Agent（上下文构建）

**位置**: `backend/app/services/agents/context_agent.py`

**职责**: 为 Generator 准备丰富上下文（Repository Intelligence）

**收集内容**:
1. **已有测试发现**: 扫描 `tests/` 或 `*_test.py` 或 `test_*.py`，提取已测函数列表
2. **导入依赖**: 解析目标文件的 import 语句，获取依赖模块接口
3. **项目测试规范**: 检测 `conftest.py` / `pytest.ini` / `setup.cfg` 中的 fixture 和配置
4. **目标函数签名+文档**: 提取待测函数的完整源码（非 diff，是完整最新版本）
5. **已有测试样例**: 取同目录或同模块的 1-2 个已有测试文件作为风格参考
6. **CodeGraph 调用链**（新增）: 使用 `codegraph refs {symbol}` 和 `codegraph impact {symbol}` 获取:
   - 被测函数的调用者（谁调用了它 → 理解使用场景）
   - 被测函数的被调用者（它调用了谁 → 需要 mock 的依赖）
   - 完整影响链（帮助 Generator 理解函数在系统中的角色）

**CodeGraph 上下文查询**（基于预构建 db，零运行时写入）:
```bash
# 获取函数的调用者（谁调用了它）
codegraph refs OrderService.create_order --db codegraph.db --format json

# 获取函数调用的下游依赖（它调用了谁）
codegraph impact OrderService.create_order --db codegraph.db --format json

# 获取文件结构摘要
codegraph file-summary app/services/order.py --db codegraph.db --format json
```

**输出 schema**:
```json
{
  "target_functions": [
    {
      "file": "app/services/order.py",
      "function": "create_order",
      "source_code": "def create_order(self, params: dict)...",
      "imports": ["from app.models import Order", "from app.db import session"],
      "existing_test_file": "tests/test_order.py",
      "callers": ["api.views.create_order_view", "tasks.process_order"],
      "callees": ["OrderValidator.validate", "db.session.commit", "Order.save"],
      "mock_candidates": ["db.session", "OrderValidator.validate"]
    }
  ],
  "project_test_framework": "pytest",
  "fixtures_available": ["db_session", "mock_redis", "test_client"],
  "test_style_example": "...(已有测试文件片段)...",
  "dependencies": ["sqlalchemy", "redis", "httpx"],
  "codegraph_available": true
}
```

---

### 3.3 Generator Agent（测试生成）

**位置**: 增强现有 `backend/app/services/skills/builtin/test_generation.py`

**增强点**:
- 接收 Context Agent 输出作为 prompt 的一部分
- System prompt 注入项目规范、已有测试样例风格
- 输出增加 `test_quality_hints`（自评覆盖维度）

**输出 schema 增强**:
```json
{
  "framework": "pytest",
  "files": [
    {
      "path": "tests/test_order_service.py",
      "content": "...",
      "description": "OrderService.create_order 正常/异常用例",
      "covers_functions": ["create_order"],
      "test_cases": ["test_create_order_success", "test_create_order_invalid_params", "test_create_order_db_error"]
    }
  ],
  "run_command": "pytest tests/test_order_service.py -v",
  "estimated_coverage_delta": "+12%",
  "quality_hints": {
    "boundary_covered": true,
    "exception_covered": true,
    "mock_minimal": true
  }
}
```

---

### 3.4 Validator Agent（验证执行）

**位置**: `backend/app/services/agents/validator_agent.py`

**职责**: 在 WorkTree 中执行测试并分析结果

**增强点（相对一期）**:
- 解析 pytest 详细输出（不仅是 pass/fail 计数，还有具体失败信息）
- 分析失败类型：ImportError / AssertionError / AttributeError / Timeout
- 判断是否可修复（ImportError → 大概率可修复；Timeout → 不重试）

**输出 schema**:
```json
{
  "status": "partial_fail",
  "total": 5,
  "passed": 3,
  "failed": 2,
  "failures": [
    {
      "test_name": "test_create_order_invalid_params",
      "error_type": "AssertionError",
      "message": "Expected ValidationError but got None",
      "traceback": "...(截断)...",
      "repairable": true
    }
  ],
  "execution_time_ms": 3200,
  "can_repair": true
}
```

---

### 3.5 Repair Agent（自动修复）

**位置**: `backend/app/services/agents/repair_agent.py`

**职责**: 分析失败原因，修复测试代码，重新提交执行

**修复策略**:
1. **ImportError**: 检查缺失模块，补充 mock 或修正 import 路径
2. **AssertionError**: 分析期望 vs 实际，调整断言或 mock 返回值
3. **AttributeError**: 检查对象结构，修正属性访问
4. **不修复**: Timeout / MemoryError / 超过 3 轮修复

**修复循环**:
```
max_repair_rounds = 3
for round in 1..max_repair_rounds:
    result = validator.execute(test_files)
    if result.all_pass:
        break
    if not result.can_repair:
        break
    test_files = repair_agent.fix(test_files, result.failures)
```

**输出 schema**:
```json
{
  "repair_rounds": 2,
  "final_status": "passed",
  "repairs_applied": [
    {"round": 1, "file": "tests/test_order.py", "fix": "添加 mock.patch('app.db.session')"},
    {"round": 2, "file": "tests/test_order.py", "fix": "修正 create_order 返回值断言"}
  ],
  "final_test_result": { "passed": 5, "failed": 0 }
}
```

---

### 3.6 MR Feedback（MR 回写）

**位置**: `backend/app/services/notify/mr_comment.py`

**职责**: 将测试结果作为 Comment 回写到 GitLab/GitHub/Gitea MR

**Comment 格式**:
```markdown
## 🤖 AI 单元测试 Agent 报告

**变更分析**: 检测到 `OrderService.create_order` 等 2 个函数需要测试覆盖
**风险等级**: 🟠 HIGH

### 测试生成结果
| 文件 | 用例数 | 通过 | 失败 | 修复轮次 |
|------|--------|------|------|----------|
| tests/test_order_service.py | 5 | 5 | 0 | 2 |

### 覆盖率增量: +12%

### 质量评估: 8.5/10
- ✅ 边界条件覆盖
- ✅ 异常场景覆盖
- ✅ Mock 使用合理

> 生成的测试文件已推送至分支 `ai/test/{mr_iid}`，可合入 MR。
```

**平台适配**:
- GitLab: `POST /api/v4/projects/:id/merge_requests/:iid/notes`
- GitHub: `POST /repos/:owner/:repo/pulls/:number/comments`
- Gitea: `POST /api/v1/repos/:owner/:repo/issues/:index/comments`

---

### 3.7 Test Quality Scoring（测试质量评分）

**位置**: `backend/app/services/agents/quality_scorer.py`

**评分维度（10 分制）**:
| 维度 | 权重 | 评判标准 |
|------|------|---------|
| 编译通过 | 2 | 生成的测试能否无错运行 |
| 断言质量 | 3 | 非空断言数 / 总测试数，是否检查具体值 |
| 异常覆盖 | 2 | 是否覆盖主要异常分支 |
| Mock 合理性 | 1.5 | 是否只 mock 外部依赖，不 mock 被测逻辑 |
| 可维护性 | 1.5 | 命名清晰、无硬编码魔数、fixture 复用 |

---

### 3.8 LLM 模型分级路由（LLM Gateway 策略）

**位置**: 增强现有 `backend/app/services/ai/engine.py`

**设计**: 不同 Agent 阶段使用不同模型，平衡质量与成本

| Agent 阶段 | 推荐模型 | 原因 |
|-----------|---------|------|
| Change Intelligence | 轻量模型（DeepSeek-V3） | 判断逻辑简单，不需要强推理 |
| Context Agent | 无 LLM（纯工具调用） | 仅做文件扫描 + CodeGraph 查询 |
| Generator Agent | 强模型（Claude/GPT-4o/DeepSeek-R1） | 代码生成质量要求高 |
| Validator Agent | 无 LLM（纯执行 + 正则解析） | pytest 运行 + 输出解析 |
| Repair Agent | 中等模型（DeepSeek-V3/GPT-4o-mini） | 定向修复，上下文明确 |
| Quality Scorer | 轻量模型（DeepSeek-V3） | 评分逻辑固定 |

**实现方式**:
- `AIEngine` 新增 `for_stage(stage_name)` 工厂方法
- 从 `ai_models` 表读取标记为不同 `purpose` 的模型配置
- 仓库级可覆盖（`repositories.skills_config.model_routing`）
- 未配置时所有阶段使用 `is_default=True` 的模型（兼容一期）

---

### 3.9 AI 分支推送（Generated Test Branch）

**位置**: 增强 `backend/app/services/git/agent.py`

**职责**: 测试生成并验证通过后，将测试文件推送到远程 AI 专属分支

**流程**:
```
WorkTree 测试通过
  → git checkout -b ai/test/{mr_iid}-{short_sha}
  → git add tests/test_*.py
  → git commit -m "AI: add unit tests for {targets}"
  → git push origin ai/test/{mr_iid}-{short_sha}
  → MR Comment 中包含分支链接
```

**安全约束**:
- 仅当 `final_status == "passed"` 时推送
- 分支命名固定前缀 `ai/test/`，不会污染业务分支
- 需要仓库 `git_token` 有 push 权限（降级：不推送，仅在 Comment 中贴代码）
- 配置开关 `skills_config.test_generation.push_branch: true/false`

---

### 3.10 Docker 测试沙箱（Phase 2 预留设计）

**位置**: `backend/app/services/sandbox/docker_runner.py`（Phase 2 实现）

**当前方案**: WorkTree + subprocess 白名单（一期延续，本次增强不改变）

**Phase 2 演进设计预留**:
```yaml
sandbox:
  type: docker                     # "process" (当前) | "docker" (Phase 2)
  image: "python:3.11-slim"        # 基础镜像
  cpu_limit: "1.0"                 # CPU 核数限制
  memory_limit: "512m"             # 内存限制
  network: "none"                  # 网络隔离
  timeout: 120                     # 硬超时（秒）
  volumes:
    - "{worktree_path}:/workspace:rw"
```

**接口预留**: `TestRunner` 抽象基类
```python
class TestRunner(ABC):
    async def run(self, worktree_path: Path, command: list[str], timeout: int) -> RunResult: ...

class ProcessRunner(TestRunner): ...      # 当前实现
class DockerRunner(TestRunner): ...       # Phase 2
```

---

## 4. 数据模型变更

### 4.1 新增表: `agent_executions`
```sql
CREATE TABLE agent_executions (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(100) NOT NULL REFERENCES ai_tasks(task_id),
    agent_type VARCHAR(50) NOT NULL,  -- change_intel/context/generator/validator/repair
    round_number INT DEFAULT 1,       -- 修复轮次
    input_data JSONB,
    output_data JSONB,
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    duration_ms INT,
    status VARCHAR(20) NOT NULL,      -- success/failed/skipped
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_agent_executions_task_id ON agent_executions(task_id);
```

### 4.2 ai_tasks 表扩展（无 DDL 变更，JSONB 结构扩展）

`output_data.test_generation` 扩展字段:
```json
{
  "change_intelligence": { "need_test": true, "risk_level": "high", "targets": [...] },
  "context": { "target_functions": [...], "fixtures_available": [...] },
  "generation": { "files": [...], "quality_hints": {...} },
  "validation": { "rounds": [...], "final_status": "passed" },
  "repair": { "repairs_applied": [...], "total_rounds": 2 },
  "quality_score": 8.5,
  "mr_comment_posted": true
}
```

---

## 5. 配置扩展

### 5.0 架构约束

1. **目标仓库零侵入**: 本平台不向被分析的开发项目写入任何配置文件（无 `.ai-skills.yml`、无 `.ai-test.json`）。所有 Agent 流程配置存储在管理后台数据库中。
2. **无独立 Agent 管理模块**: Agent 链路固定（change_intel → context → generator → validator → repair），不需要动态注册/发现。配置能力收敛到仓库设置页的 `skills_config` JSONB 字段中，前端扩展表单区域即可。
3. **CodeGraph db 由目标仓库自行维护**: `codegraph.db` 由开发者在项目中预构建并提交 git，本平台仅读取查询。

### 5.1 仓库级配置（`repositories.skills_config` JSONB）

```json
{
  "test_generation": {
    "enabled": true,
    "trigger": "mr_only",             // "mr_only" | "push_and_mr" | "disabled"
    "max_repair_rounds": 3,
    "skip_patterns": ["docs/*", "*.md", "migrations/*"],
    "test_dir": "tests/",
    "language": "python",
    "framework": "pytest",
    "codegraph_db_path": "codegraph.db",  // 相对仓库根目录，null 则跳过 CodeGraph
    "docker_image": null,              // Phase 2: Docker 沙箱镜像
    "agents": {
      "change_intelligence": { "enabled": true, "model": null },
      "generator": { "model": null },
      "repair": { "model": null, "max_rounds": 3 }
    }
  }
}
```

> `agents.*.model` 为 null 时使用仓库绑定的默认模型（`ai_model_id`），显式指定时覆盖。

### 5.2 全局配置新增

`settings.py` 新增:
```python
MAX_REPAIR_ROUNDS: int = 3
CHANGE_INTEL_SKIP_EXTENSIONS: list = [".md", ".txt", ".rst", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".json"]
MR_COMMENT_ENABLED: bool = True
TEST_QUALITY_SCORING_ENABLED: bool = True
```

---

## 6. API 新增/变更

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/v1/tasks/{task_id}/agents` | 获取任务的 Agent 执行链详情 |
| GET | `/api/v1/stats/agent-performance` | Agent 各阶段耗时/成功率统计 |
| POST | `/api/v1/test-agent/trigger` | 手动触发（调试用，指定 repo+branch+commit） |

---

## 7. 前端增强

### 7.1 TaskDetailPage 增强
- 新增 **Agent 执行链时间线**：按 change_intel → context → generator → validator → repair 展示每步状态/耗时/token
- 修复轮次可视化：每轮显示失败原因 + 修复动作
- 测试质量雷达图（5 维度）

### 7.2 DashboardPage 增强
- 新 KPI 卡片: "AI 修复成功率"、"平均修复轮次"、"MR 采纳率"
- Agent 执行链路耗时分布图

---

## 8. 实施分 Sprint

### Sprint 1: Change Intelligence + MR 触发优化（~2天）
- 实现 `change_intelligence.py` skill
- 修改 `_ai_pipeline` 流程：先执行 change_intel 判断
- 配置 `trigger: mr_only` 逻辑
- 新增 Alembic 迁移: `agent_executions` 表

### Sprint 2: Context Agent + Generator 增强（~2天）
- 实现 `context_agent.py`
- WorkTree 中读取已有测试/fixture/import
- 增强 `test_generation.py` 的 prompt（注入 context）
- 新增 API: `/tasks/{task_id}/agents`

### Sprint 3: Validator + Repair Loop（~2天）
- 实现 `validator_agent.py`（详细 pytest 输出解析）
- 实现 `repair_agent.py`（失败修复 + 重试循环）
- 改造 `_ai_pipeline` 接入修复循环
- `_write_partial_output` 每轮写入进度

### Sprint 4: MR Feedback + Quality Scoring + 前端（~2天）
- 实现 `mr_comment.py`（GitLab/GitHub/Gitea 回写）
- 实现 `quality_scorer.py`
- 前端 Agent 执行链时间线
- 前端质量评分展示
- 统计 API 扩展

---

## 9. 验收指标

| 指标 | 目标 |
|------|------|
| 测试生成成功率（语法正确可运行） | ≥ 85% |
| 自动修复成功率（3 轮内修复通过） | ≥ 60% |
| 变更分析准确率（need_test 判断） | ≥ 90% |
| 单次全流程耗时（中等 MR） | ≤ 60s |
| MR Comment 回写成功率 | ≥ 95% |
| 测试质量评分平均分 | ≥ 7.5/10 |
| CodeGraph 影响面精确率（vs 纯文件分析） | ≥ 2x 目标函数命中 |
| **开发采纳率**（AI 分支被合入 MR 的比例） | ≥ 40%（首月） |
| AI 分支推送成功率 | ≥ 90% |

---

## 10. 风险与约束

| 风险 | 缓解 |
|------|------|
| LLM 生成代码不可控 | 白名单执行 + WorkTree 隔离 + 超时控制 |
| 修复循环死循环 | 硬上限 3 轮 + 不可修复类型直接跳出 |
| Token 成本爆炸 | Change Intel 前置过滤 + context 截断 + 模型分级 |
| MR Comment 权限 | 使用仓库 git_token（需有 API 权限），失败降级为仅飞书 |
| 并发大仓库 clone | 已有 bare clone + fetch 机制，WorkTree 轻量 |
