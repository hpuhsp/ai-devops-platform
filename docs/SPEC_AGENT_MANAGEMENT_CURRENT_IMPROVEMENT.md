# Agent 管理模块现阶段改进规格文档

> 版本: v1.0-draft  
> 日期: 2026-07-11  
> 范围: Agent 管理、流水线规则、通知策略、AI 单元测试工作流的近期改进  
> 原则: 当前阶段优先消除概念重叠和运行时不一致，不引入过重的通用 Agent 平台

---

## 1. 背景与问题

当前平台已经具备 AI 模型配置、Agent 管理、仓库配置、流水线规则、通知配置和 AI 单元测试链路能力。但在产品和架构边界上存在几类问题：

1. 仓库配置中存在 `agent_bindings`，与流水线规则中的阶段选择形成重复配置。
2. Agent 管理界面展示了 `Skill Config`、`Model Config`、`Policy Config`，但运行时部分阶段仍硬编码 Skill 名称，Agent 的 `skill_name` 替换能力未完全兑现。
3. 通知策略目前主要挂在仓库 `skills_config.notifications` 下，已支持事件过滤和严重级别过滤，但还不是独立策略模型，难以支持不同事件发送到不同群组或个人。
4. `TestManagerAgent` 同时承担阶段编排、执行记录、通知发送、Git/MR 回写、质量评分入口等职责，后续继续叠加 SkillsHub、MCP、Hook、Rules 会导致类和配置模型过重。
5. AI 单元测试能力后期希望可抽离复用，并可接入 GitLab CI，因此需要形成独立、清晰、可嵌入的工作流内核。

---

## 2. 设计目标

### 2.1 近期目标

1. 明确 `仓库 / 流水线规则 / Agent / Skill / MCP / 通知策略` 的职责边界。
2. 移除或弱化“添加仓库时绑定 Agent”的主流程，避免配置心智重复。
3. 让流水线规则成为阶段启停的唯一入口。
4. 让 Agent 成为阶段执行能力的配置包，而不是触发规则或通知规则的容器。
5. 将通知策略从仓库 JSON 配置逐步升级为独立策略模型。
6. 将 `TestManagerAgent` 演进为可抽离的 AI 单元测试工作流编排器。

### 2.2 非目标

当前阶段不做以下事情：

1. 不建设完整通用 Agent 平台。
2. 不把 Rules、Hooks、通知路由都塞进 Agent 配置。
3. 不要求 Agent 动态编排任意 DAG。
4. 不立即实现完整 MCPHub。
5. 不立即替代 GitLab CI 的构建、发布和 Runner 能力。

---

## 3. 核心概念边界

### 3.1 仓库 Repository

仓库只负责目标代码库的基础接入信息：

- 仓库名称
- Git 平台类型
- 仓库地址
- 访问令牌
- Webhook Secret
- 是否启用
- 默认通知渠道或默认通知策略
- 可选的仓库级运行限制，例如超时、并发、默认沙箱类型

仓库不应直接决定跑哪个 Agent。

### 3.2 流水线规则 Pipeline Rule

流水线规则负责决定某个分支或事件应运行哪些阶段：

- 分支匹配模式
- 优先级
- 执行阶段，例如代码审查、单元测试、质量评分、自动合并
- 启用状态

流水线规则是“是否执行某能力”的入口。

### 3.3 阶段 Stage

阶段是平台内部稳定的能力槽位，例如：

- `code_review`
- `change_intelligence`
- `test_context`
- `test_generator`
- `test_validate_repair`
- `quality_scorer`
- `mr_feedback`

阶段定义输入、输出、状态和失败阻断策略。

### 3.4 Agent

Agent 是某个阶段的执行配置包，负责描述“这个阶段如何执行”：

- 模型选择
- 指令或 Prompt 模板
- Skill 列表
- MCP 工具列表
- Skill 配置
- 模型参数配置
- 策略配置，例如最大重试次数、质量阈值、是否需要人工确认
- Guardrails，例如超时、Token 预算、可写文件范围、工具权限

Agent 不负责分支匹配、Webhook 触发、通知接收人选择。

### 3.5 Skill

Skill 是具体能力实现，可以是内置 Python Skill，也可以后续接入组织内部 SkillsHub。

Skill 应满足统一协议：

```python
class Skill:
    name: str
    version: str
    stage_type: str

    async def execute(context, engine, config) -> SkillResult:
        ...
```

### 3.6 MCP Tool

MCP 用于接入外部工具和上下文资源，例如：

- CodeGraph
- 代码搜索
- 覆盖率读取
- 缺陷库查询
- 制品库查询
- 组织内部知识库

当前阶段优先支持只读 MCP 工具。涉及写操作的 MCP 工具必须有权限、审计、超时、预算控制。

### 3.7 通知策略 Notification Policy

通知策略消费结构化事件，不应绑定单个 Agent。

策略维度包括：

- 仓库
- 分支模式
- 流水线阶段
- 事件类型
- 状态
- 严重级别
- 是否阻断
- 接收目标
- 通知渠道
- 静默规则

---

## 4. 推荐目标架构

```text
Webhook / Manual Trigger / GitLab CI
        |
        v
Repository Resolver
        |
        v
Pipeline Rule Resolver
        |
        v
Workflow Orchestrator
        |
        +--> Stage Runtime
                 |
                 +--> Agent Resolver
                 |       |
                 |       +--> Model Resolver
                 |       +--> Skill Resolver
                 |       +--> MCP Tool Resolver
                 |       +--> Policy Resolver
                 |
                 +--> Skill Runtime
                 +--> Sandbox Runner
                 +--> Artifact Store
                 +--> Event Bus
                          |
                          +--> Notification Policy Engine
                          +--> MR Comment Writer
                          +--> Dashboard Status Writer
```

---

## 5. 现阶段产品改进规格

### 5.1 仓库配置页

#### 5.1.1 调整目标

仓库配置页只保留仓库接入和默认行为配置，不再把 Agent 绑定作为主配置项。

#### 5.1.2 页面保留

- 仓库名称
- Git 平台
- 仓库地址
- Git Token
- Webhook Secret
- 默认通知策略或默认通知渠道
- 启用状态

#### 5.1.3 页面移除或移动

当前“Agent 绑定”区域不应出现在添加仓库主流程中。

处理方式：

1. 第一阶段：从添加仓库弹窗隐藏 Agent 绑定区域。
2. 第二阶段：保留为“高级覆盖配置”，默认折叠，仅供特殊仓库覆盖系统默认 Agent。
3. 第三阶段：用阶段级 Agent Profile 或策略覆盖替代 `repository.agent_bindings`。

#### 5.1.4 兼容要求

后端可暂时保留 `repositories.agent_bindings` 字段，用于兼容历史数据，但前端不再引导用户使用。

---

### 5.2 流水线规则页

#### 5.2.1 调整目标

流水线规则是阶段启停的唯一入口。

#### 5.2.2 规则字段

- 规则名称
- 分支匹配
- 优先级
- 执行阶段
- 启用状态

#### 5.2.3 阶段建议

将当前阶段从混合命名收敛为稳定内部阶段：

| 当前阶段 | 建议阶段 | 说明 |
|---|---|---|
| `code_review` | `code_review` | 代码审查 |
| `test_generation` | `unit_test` | 单元测试总阶段，对用户展示 |
| `auto_merge` | `mr_feedback` 或 `auto_merge` | 需区分 MR 回写与自动合并 |
| `build` | `build` | 二期 |
| `deploy` | `deploy` | 二期 |

`unit_test` 在内部可展开为：

- `change_intelligence`
- `test_context`
- `test_generator`
- `test_validate_repair`
- `quality_scorer`

用户在规则里只勾选“单元测试”，不需要理解内部多个 Agent。

---

### 5.3 Agent 管理页

#### 5.3.1 调整目标

Agent 管理页应从“配置表单”升级为“阶段能力配置包管理”。

#### 5.3.2 Agent 字段

建议 Agent 结构：

```json
{
  "name": "Python 单测生成 Agent",
  "description": "负责基于变更上下文生成 pytest 单元测试",
  "stage_type": "test_generator",
  "model_id": 1,
  "instructions": "...",
  "skills": [
    {
      "name": "test_generation",
      "version": "1.0.0",
      "config": {}
    }
  ],
  "mcp_tools": [
    {
      "server": "codegraph",
      "tools": ["refs", "impact", "file_summary"],
      "permission": "read"
    }
  ],
  "model_config": {
    "temperature": 0.2,
    "max_tokens": 12000
  },
  "policy_config": {
    "timeout_sec": 120,
    "max_retry": 3,
    "quality_threshold": 7.5,
    "require_human_approval": false
  },
  "guardrails": {
    "allowed_write_patterns": ["tests/**"],
    "deny_shell": true,
    "max_tool_calls": 20
  },
  "enabled": true,
  "is_system": false
}
```

#### 5.3.3 当前阶段可先落地的字段

不一次性实现全部字段。近期优先：

1. `instructions`
2. `skills`
3. `skill_config`
4. `model_id`
5. `model_config`
6. `policy_config`
7. `enabled`
8. `is_system`

MCP 字段可先预留数据结构和 UI 占位，不强制执行。

#### 5.3.4 系统 Agent 规则

系统 Agent 可修改：

- 模型绑定
- 模型参数
- Skill 配置
- Policy 配置
- 启用状态

系统 Agent 不可修改：

- 阶段类型
- 核心 Skill 绑定
- 是否系统 Agent

---

### 5.4 通知策略

#### 5.4.1 调整目标

通知策略从仓库 JSON 配置升级为独立策略模型。

#### 5.4.2 策略字段

```json
{
  "name": "高危代码审查通知",
  "repo_ids": [1, 2],
  "branch_patterns": ["main", "release/*"],
  "event_types": ["code_review_result", "pipeline_failed"],
  "stage_types": ["code_review"],
  "status": ["blocked", "failed"],
  "min_severity": "high",
  "blocked_only": true,
  "notify_config_id": 1,
  "targets": [
    {
      "type": "group",
      "id": "feishu_group_xxx"
    }
  ],
  "enabled": true
}
```

#### 5.4.3 事件类型建议

- `pipeline_started`
- `pipeline_success`
- `pipeline_failed`
- `stage_started`
- `stage_success`
- `stage_failed`
- `code_review_result`
- `unit_test_generated`
- `unit_test_failed`
- `unit_test_repaired`
- `quality_score_result`
- `mr_comment_posted`

#### 5.4.4 发送原则

Agent 不直接发送通知。Agent 或 Stage 只产出事件，通知策略根据事件决定是否发送、发给谁、用哪个渠道。

---

## 6. AI 单元测试模块改进规格

### 6.1 目标

将当前 `TestManagerAgent` 演进为可抽离的 AI 单元测试工作流内核。

该内核应支持：

- 平台内调用
- 手动触发
- Webhook 触发
- GitLab CI 中调用
- 后续独立打包为服务或库

### 6.2 推荐模块

```text
unit_test_engine/
  workflow.py              # 编排状态机
  stages/
    change_intelligence.py
    context_builder.py
    generator.py
    validator.py
    repair.py
    quality_scorer.py
  runtime/
    agent_runtime.py
    skill_runtime.py
    model_runtime.py
    mcp_runtime.py
  sandbox/
    base.py
    process_runner.py
    docker_runner.py
  artifacts/
    store.py
    schemas.py
  events/
    bus.py
    schemas.py
```

### 6.3 标准流程

```text
Change Intelligence
        |
        v
Context Builder
        |
        v
Test Generator
        |
        v
Sandbox Runner
        |
        v
Validator
        |
        +-- failed and repairable --> Repair --> Sandbox Runner
        |
        v
Quality Scorer
        |
        v
Artifacts + Events
```

### 6.4 阶段输入输出

每个阶段必须遵守统一协议：

```python
class Stage:
    name: str
    required_inputs: list[str]
    produced_outputs: list[str]

    async def run(context: WorkflowContext) -> StageResult:
        ...
```

```json
{
  "status": "success|failed|blocked|skipped",
  "reason": null,
  "output": {},
  "artifacts": [],
  "events": [],
  "metrics": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "duration_ms": 0
  }
}
```

### 6.5 失败阻断规则

1. 代码审查被阻断时，后续阶段默认不执行。
2. Change Intelligence 判断无需测试时，单测后续阶段跳过，流水线可成功结束。
3. Test Generator 没有生成文件时，验证和修复阶段阻断。
4. Validator 失败且不可修复时，修复阶段跳过，单测阶段失败。
5. Repair 超过最大轮次仍失败时，单测阶段失败。
6. Quality Scorer 不应默认阻断流水线，除非策略配置了质量阈值门禁。

### 6.6 GitLab CI 接入

后期可提供 CLI：

```bash
ai-test-engine run \
  --repo-url "$CI_REPOSITORY_URL" \
  --branch "$CI_COMMIT_REF_NAME" \
  --commit "$CI_COMMIT_SHA" \
  --before "$CI_COMMIT_BEFORE_SHA" \
  --output ai-test-report.json
```

GitLab CI 示例：

```yaml
ai_unit_test:
  stage: test
  image: python:3.11
  script:
    - ai-test-engine run --repo-url "$CI_REPOSITORY_URL" --branch "$CI_COMMIT_REF_NAME" --commit "$CI_COMMIT_SHA"
  artifacts:
    when: always
    paths:
      - ai-test-report.json
      - generated-tests/
```

---

## 7. 数据模型调整建议

### 7.1 短期保留

保留现有表：

- `agents`
- `repositories`
- `pipeline_rules`
- `notify_configs`
- `notification_logs`
- `agent_executions`

### 7.2 短期新增

建议新增通知策略表：

```sql
CREATE TABLE notification_policies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    repo_ids JSONB DEFAULT '[]',
    branch_patterns JSONB DEFAULT '[]',
    event_types JSONB DEFAULT '[]',
    stage_types JSONB DEFAULT '[]',
    status_filter JSONB DEFAULT '[]',
    min_severity VARCHAR(20) DEFAULT 'all',
    blocked_only BOOLEAN DEFAULT FALSE,
    notify_config_id INT REFERENCES notify_configs(id),
    targets JSONB DEFAULT '[]',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 7.3 中期调整

建议对 `agents` 做兼容升级：

```sql
ALTER TABLE agents ADD COLUMN instructions TEXT;
ALTER TABLE agents ADD COLUMN skills JSONB DEFAULT '[]';
ALTER TABLE agents ADD COLUMN mcp_tools JSONB DEFAULT '[]';
ALTER TABLE agents ADD COLUMN guardrails JSONB DEFAULT '{}';
```

`skill_name` 可保留为兼容字段，后续由 `skills[0].name` 替代。

### 7.4 中期废弃

`repositories.agent_bindings` 标记为 deprecated。

迁移策略：

1. 保留读取兼容。
2. 前端隐藏主入口。
3. 后端日志提示历史配置。
4. 后续迁移为阶段默认 Agent Profile。

---

## 8. API 调整建议

### 8.1 Agent API

保留：

- `GET /api/v1/agents`
- `POST /api/v1/agents`
- `PUT /api/v1/agents/{id}`
- `DELETE /api/v1/agents/{id}`
- `POST /api/v1/agents/{id}/clone`

增强：

- `GET /api/v1/agents/stages`
- `GET /api/v1/agents/skills`
- `GET /api/v1/agents/mcp-tools`
- `POST /api/v1/agents/{id}/validate`

### 8.2 Notification Policy API

新增：

- `GET /api/v1/notification-policies`
- `POST /api/v1/notification-policies`
- `PUT /api/v1/notification-policies/{id}`
- `DELETE /api/v1/notification-policies/{id}`
- `POST /api/v1/notification-policies/{id}/test`

### 8.3 Unit Test Engine API

新增或预留：

- `POST /api/v1/unit-test/trigger`
- `GET /api/v1/tasks/{task_id}/stages`
- `GET /api/v1/tasks/{task_id}/artifacts`
- `GET /api/v1/tasks/{task_id}/events`

---

## 9. 前端交互调整建议

### 9.1 仓库配置

近期：

- 隐藏 Agent 绑定区域。
- 保留通知策略选择。
- 增加 Webhook 配置指引。

中期：

- 增加“高级配置”折叠区。
- 高级配置只放仓库级运行限制，不放阶段 Agent 选择。

### 9.2 流水线规则

近期：

- 明确提示：流水线规则决定执行哪些阶段。
- “单元测试”作为一个用户可理解阶段展示。
- 内部多 Agent 链路在任务详情页展示，不暴露在规则配置页。

### 9.3 Agent 管理

近期：

- 按阶段筛选 Agent。
- 展示 Agent 绑定模型、Skill、策略摘要。
- 系统 Agent 允许调整模型和策略，不允许改变阶段类型。

中期：

- Skills 改为多选或编排列表。
- MCP 工具改为可选工具列表。
- 增加 Guardrails 配置区。
- 增加“验证 Agent 配置”按钮。

### 9.4 通知配置

近期：

- 继续修复通知渠道删除、默认设置等基础问题。

中期：

- 新增“通知策略”菜单。
- 支持不同事件发送到不同群组或个人。
- 支持测试发送。
- 支持命中日志和跳过原因展示。

---

## 10. 实施计划

### Sprint 1: 配置边界收敛

目标：

- 仓库添加/编辑页隐藏 Agent 绑定主入口。
- 明确流水线规则是阶段启停入口。
- 系统 Agent 编辑只允许安全字段。
- 修正 Agent `skill_name` 配置未被运行时充分使用的问题。

验收：

- 添加仓库不再要求用户理解 Agent 绑定。
- 勾选规则阶段即可控制是否执行代码审查、单元测试等。
- Agent 管理中的 Skill 配置与运行时一致。

### Sprint 2: 通知策略独立化

目标：

- 新增 `notification_policies`。
- 通知发送从仓库 JSON 迁移到策略匹配。
- 兼容旧的仓库通知配置。
- 增加策略测试发送能力。

验收：

- 同一仓库不同事件可发送到不同群组或个人。
- 高危代码审查、单测失败、质量低分可以配置不同通知目标。
- 通知日志能说明发送、失败或跳过原因。

### Sprint 3: 单测工作流内核拆分

目标：

- 从 `TestManagerAgent` 拆出 `UnitTestWorkflow`。
- 阶段执行、通知发送、MR 回写、执行记录分离。
- 引入统一 `StageResult` 和事件模型。

验收：

- 单测链路可由平台内部调用。
- 后续可包装为 CLI 接入 GitLab CI。
- 任务详情可稳定展示每个阶段状态。

### Sprint 4: Agent 可插拔能力增强

目标：

- Agent 支持 `skills` 列表。
- 预留 `mcp_tools` 和 `guardrails`。
- SkillRuntime 支持内置 Skill 和外部 SkillsHub 适配器。

验收：

- 同一阶段可切换不同 Skill 实现。
- Agent 配置可验证。
- MCP 工具仅作为受控只读工具接入。

---

## 11. 风险与约束

| 风险 | 说明 | 缓解 |
|---|---|---|
| 设计过重 | 过早建设通用 Agent 平台会拖慢当前验证 | 先做边界收敛和单测内核 |
| Agent 配置与运行时不一致 | UI 支持 Skill，但代码仍硬编码 Skill | 优先修正运行时解析 |
| 通知噪音 | 多 Agent 多阶段容易产生大量消息 | 通知策略按事件和严重级别过滤 |
| MCP 权限风险 | MCP 工具可能具备外部系统访问能力 | 当前优先只读工具，写操作需审计 |
| 单测执行安全 | LLM 生成代码可能有风险 | WorkTree、白名单命令、超时、Docker 沙箱 |
| 与 GitLab CI 职责重叠 | 平台不应重做 CI Runner | 平台输出 AI 能力和报告，CI 负责确定性执行 |

---

## 12. 最终结论

当前阶段应把平台定位为 GitLab CI 的 AI 增强层，而不是 GitLab CI 的替代品。

最优改进路线是：

1. 仓库只做接入配置。
2. 流水线规则只做阶段选择。
3. Agent 只做阶段执行能力配置。
4. Skill/MCP 只做能力插件。
5. 通知策略只消费事件并路由消息。
6. AI 单元测试模块抽象为可独立运行的工作流内核。

这样既能支撑当前 100+ 项目的试点，也能为后续 SkillsHub、MCPHub、GitLab CI 接入和独立单测引擎抽离保留清晰扩展路径。
