# AI Test Manager Agent 规格文档

> 版本: v1.0
> 日期: 2026-07-11
> 范围: AI 单元测试流水线内核、TestManagerAgent、子 Agent、开源 SKILL.md 能力包
> 原则: 平台外层确定性，单测内核 Agentic；LLM 决策必须受控、可审计、可回退。

## 1. 目标

将当前硬编码顺序的 `TestManagerAgent` 重构为 LLM 驱动的 AI 单测管理者 Agent。

外层流水线只决定是否进入 AI 单测能力；进入后由 `TestManagerAgent` 观察变更上下文，自主决定调用哪些专业子 Agent、调用顺序、是否迭代、何时结束，直到产出合格测试或给出明确失败原因。

## 2. 非目标

当前阶段不建设通用 Agent 平台，不支持任意 DAG 编排，不在运行时无审查地从 GitHub 拉取并执行第三方脚本，不替代 GitLab CI Runner。

当前阶段也不恢复已删除的通知策略模块。

## 3. 核心定位

```text
AI DevOps Platform
  = deterministic DevOps runtime
  + agentic AI test manager
  + professional sub agents
  + curated SKILL.md registry
  + controlled tool runtime
```

### 3.1 TestManagerAgent

`TestManagerAgent` 是真正的 AI Agent，负责:

- 观察 diff、变更文件、分支、历史步骤输出、验证失败、质量结果。
- 判断下一步 action。
- 决定调用哪个子 Agent 或工具。
- 根据结果继续迭代或结束。
- 控制预算、轮次、写入范围和失败策略。

### 3.2 子 Agent

子 Agent 是专业能力单元，不是固定脚本别名。

建议内置子 Agent:

- `CodeReviewAgent`: 审查代码风险和阻断项。
- `ChangeAnalysisAgent`: 判断变更影响、测试必要性和目标。
- `ContextAgent`: 选择最小必要上下文。
- `GeneratorAgent`: 生成测试代码。
- `ValidatorAgent`: 确定性执行测试并解析失败。
- `RepairAgent`: 基于失败信息修复测试。
- `QualityAgent`: 评估测试质量。
- `FeedbackAgent`: 回写 MR 评论或任务摘要。

### 3.3 Skill.md 能力包

Skill 是行业最佳实践和组织规范的能力载体，优先复用 GitHub 上优秀开源 `SKILL.md`，但必须经过 curated registry 管理。

每个 Skill 包至少包含:

```text
skill-name/
  SKILL.md
  references/
  scripts/
```

运行时只默认读取 `SKILL.md` 的摘要和路由信息；`references/` 和 `scripts/` 必须按需加载或显式允许。

### 3.4 Tool

Tool 是确定性执行能力，例如:

- 读取 diff
- 创建 worktree
- 写测试文件
- 运行测试命令
- 解析 pytest/JUnit/Jest 输出
- 发布 MR 评论

LLM 只能选择 action，不能直接执行 shell 或任意脚本。

## 4. 决策循环

`TestManagerAgent.run()` 的目标形态:

```text
observe current state
while not done and budget remains:
  load relevant skill cards
  ask manager LLM for next structured decision
  validate decision schema and policy
  execute selected action
  record trace and stage result
  update state
  evaluate finish criteria
fallback if manager decision fails
```

Manager 决策必须是结构化 JSON:

```json
{
  "action": "generate_tests",
  "reason": "change analysis found testable service logic without existing coverage",
  "inputs": {
    "focus": ["OrderService.calculate_total"]
  },
  "expected_outcome": "generated tests cover changed branches"
}
```

允许的 action:

- `analyze_change`
- `build_context`
- `generate_tests`
- `validate_tests`
- `score_quality`
- `publish_feedback`
- `finish`
- `fail`

当前阶段 `validate_tests` 可继续复用已有验证与修复闭环，后续再拆为 `run_tests` 和 `repair_tests` 两个独立 action。

## 5. Skill 选择与 Token 控制

Skill 加载分三层:

```text
Skill Card: name, summary, when_to_use, token_budget
Skill Summary: SKILL.md 摘要和执行规则
Full Skill: 完整 SKILL.md + references，仅复杂任务按需加载
```

Manager 决策只读取 Skill Card。子 Agent 执行时按需读取 Skill Summary。默认不加载 Full Skill。

Token 节省策略:

- 只传 diff 摘要、目标文件、失败摘要，不传完整历史。
- 工具输出先压缩再进入下一轮。
- 每个 action 输出固定 schema。
- Manager trace 保存完整原因，但下一轮只传压缩状态。
- 小模型可承担路由和分类，强模型用于生成和复杂修复。

## 6. GitHub 开源 Skill 接入

引入 `OpenSkillRegistry`:

```text
OpenSkillRegistry
  - loads local mirrored GitHub skills
  - indexes SKILL.md files
  - exposes skill cards
  - validates allowed agents/actions
  - records source repo and commit sha
```

Skill 元数据:

```json
{
  "name": "pytest-unit-test",
  "source": "github",
  "repo_url": "https://github.com/example/skills",
  "commit_sha": "locked-sha",
  "path": "pytest-unit-test",
  "allowed_agents": ["GeneratorAgent", "RepairAgent"],
  "token_budget": 1200,
  "enabled": true
}
```

运行时不直接 `git clone` 未审查仓库。GitHub skill 必须先同步到本地 curated 目录，锁定 commit，再由平台加载。

## 7. 安全与治理

必须具备:

- action allowlist
- max rounds
- max LLM calls
- max duration
- max token budget
- allowed write paths
- no secret access
- no arbitrary shell execution
- structured decision validation
- deterministic fallback
- trace and audit record

默认策略:

- 只能写测试文件。
- 第三方 Skill 自带脚本不自动执行。
- Manager 输出非法 JSON 时进入 fallback。
- 超预算时 fail，并记录原因。

## 8. 当前阶段实施计划

### Step 1: 规格与边界

- 新增本文档。
- 明确外层流水线与内层 Agentic loop 的职责边界。

### Step 2: Skill.md Registry

- 新增 `OpenSkillRegistry`。
- 支持扫描本地 curated `SKILL.md`。
- 输出 Skill Card。
- 不联网，不执行第三方脚本。

### Step 3: Agentic 决策模型

- 新增 `ManagerDecision`。
- 新增 `ManagerDecisionEngine`。
- 使用 `AIEngine.complete_with_system` 获取结构化 JSON 决策。
- LLM 不可用或输出非法时使用 deterministic fallback。

### Step 4: TestManagerAgent 改造

- 保留现有 `_stage_*` 方法作为受控 action executor。
- 将 `run()` 改为 observe-decide-act loop。
- 继续输出 `stage_results`、`events`、`pipeline_status`，降低前端改造成本。

### Step 5: 测试与验证

- 覆盖 fallback 顺序。
- 覆盖非法 action 拒绝。
- 覆盖 gated/failed/blocked 行为。
- 覆盖 skill card 加载。

## 9. 验收标准

- `TestManagerAgent` 不再依赖固定 `_stages` 顺序驱动主流程。
- Manager 每轮都有 `manager_trace`。
- 所有 action 都经过 allowlist。
- 无 LLM 或 LLM 决策失败时任务仍可按安全 fallback 执行。
- `SKILL.md` 能力包可以被索引为 Skill Card。
- 不恢复通知策略模块，不引入通用 Agent 平台。
