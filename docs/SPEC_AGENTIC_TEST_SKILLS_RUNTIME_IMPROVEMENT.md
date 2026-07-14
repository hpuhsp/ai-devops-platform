# Agentic 单元测试 Skills Runtime 改进规格

> 日期: 2026-07-14
> 阶段: 下一阶段改进计划
> 范围: AI 单元测试模块、TestManagerAgent、子 Agent、项目级 Skills Runtime

## 1. 背景

当前单元测试模块已经完成第一阶段收敛：

- 流水线外层负责决定是否执行代码审查、单元测试等阶段。
- 代码审查与单元测试职责已拆开。
- `TestManagerAgent` 已作为单元测试域的决策核心。
- `TestManagerAgent` 可以基于上下文选择 `analyze_change`、`generate_tests`、`validate_tests` 等 action。
- `SKILL.md` 当前会被扫描成 `Skill Card`，提供给 Manager Prompt 作为决策参考。

但当前实现仍存在一个核心不足：

```text
Skill Card 只是摘要信息，不是真正可执行的能力包。
子 Agent 主要还是 Python Stage Executor，不是完整意义上的专业 Agent。
```

下一阶段目标是把单元测试模块从“LLM 决策 + Python 执行器”升级为“LLM Manager + 专业子 Agent + 可治理 Skills Runtime”的架构。

## 2. 目标

本次改进目标是形成一个可控、可审计、可扩展的 AI 单元测试 Agent 系统。

核心目标：

- `TestManagerAgent` 保持为单元测试域的编排与决策核心。
- 子能力从固定 Python 方法逐步升级为专业子 Agent。
- `项目根目录/skills` 成为项目级 Skills 主目录。
- `SKILL.md` 不再只作为摘要卡片，而是可被加载、解释和受控调用的能力包。
- 支持组织级或用户级 Skills 扩展，但必须显式配置、挂载和授权。
- 保留现有 builtin Python executor 作为稳定兜底。
- 所有 Skill 调用必须有权限边界、结构化输入输出、执行审计和失败回退。

目标架构：

```text
Pipeline Rule
  -> TestManagerAgent
      -> ChangeUnderstandingAgent
      -> TestPlanningAgent
      -> TestGenerationAgent
      -> TestReviewAgent
      -> TestRunnerAgent
      -> TestRepairAgent
      -> QualityJudgeAgent
      -> FeedbackAgent
          -> Skill Runtime
              -> project skills/
              -> org/user skills roots
              -> builtin executor fallback
```

## 3. 非目标

当前阶段不做以下事情：

- 不实现通用 Agent 平台。
- 不支持任意 DAG 编排。
- 不允许第三方 Skill 任意执行 shell。
- 不默认信任用户级或外部 GitHub Skills。
- 不替代 GitLab CI Runner、GitHub Actions 或 Jenkins。
- 不要求一次性把所有 Python executor 替换成 Agent。
- 不在 Agent 管理页面恢复过重的 MCP、Hook、Rules 任意配置。

## 4. 目录与来源策略

Skills 来源按优先级处理：

```text
1. 项目根目录/skills
2. AI_DEVOPS_SKILLS_ROOTS 指定的组织级或用户级目录
3. builtin Python executor
```

明确约束：

- 不扫描、不依赖、不兼容 `项目根目录/.qoder/skills`。
- `.qoder/skills` 属于个人工具或本地实验目录，不进入平台产品设计。
- 团队共享能力必须进入 `项目根目录/skills` 或显式配置的 `AI_DEVOPS_SKILLS_ROOTS`。

### 4.1 项目级 skills

`项目根目录/skills` 是推荐主路径。

原因：

- 可版本化。
- 可代码审查。
- 可随项目交付。
- 可在 CI 或 Docker 中复现。
- 适合团队沉淀项目级测试规范。

建议目录：

```text
skills/
  pytest-unit-test/
    SKILL.md
    references/
      patterns.md
      anti-patterns.md
    scripts/
      inspect_tests.py
    skill.json
```

### 4.2 组织级或用户级 skills

通过环境变量显式启用：

```text
AI_DEVOPS_SKILLS_ROOTS=/app/skills:/mnt/org-skills:/mnt/user-skills
```

如果系统运行在 Docker 中，宿主机目录必须挂载进容器。

默认不扫描宿主机用户目录，避免不可复现和供应链风险。

## 5. Skill Package 规范

每个 Skill 至少包含：

```text
SKILL.md
```

建议包含：

```text
skill.json
references/
scripts/
examples/
```

### 5.1 SKILL.md

`SKILL.md` 用于描述能力边界、触发条件、执行流程和输出要求。

必须包含：

- name
- description
- allowed_agents
- token_budget
- input_contract
- output_contract
- permissions

示例：

```markdown
---
name: pytest-unit-test
description: Generate and repair pytest unit tests for Python services.
allowed_agents: TestPlanningAgent,TestGenerationAgent,TestRepairAgent
token_budget: 1200
permissions:
  read: true
  write_patterns:
    - "tests/**/*.py"
  shell:
    allowed: false
---

# Pytest Unit Test

## When To Use

Use when changed files are Python service modules and existing project test framework is pytest.

## Workflow

1. Inspect changed functions and public behavior.
2. Identify edge cases and error paths.
3. Generate focused pytest tests.
4. Prefer existing fixtures and project test style.
5. Do not test third-party library behavior.

## Output

Return generated test files and rationale as structured JSON.
```

### 5.2 skill.json

`skill.json` 是机器可读配置，用于减少解析 Markdown 的不确定性。

建议结构：

```json
{
  "name": "pytest-unit-test",
  "version": "1.0.0",
  "entry": {
    "type": "prompt",
    "file": "SKILL.md"
  },
  "allowed_agents": [
    "TestGenerationAgent",
    "TestRepairAgent"
  ],
  "permissions": {
    "read": true,
    "write_patterns": [
      "tests/**/*.py"
    ],
    "shell": false
  },
  "references": [
    "references/patterns.md",
    "references/anti-patterns.md"
  ],
  "output_schema": "schemas/test_generation_result.json"
}
```

当前阶段可先支持 `SKILL.md`，后续再补 `skill.json`。

## 6. Skills Runtime 分层

Skills Runtime 分为三层。

### 6.1 Discovery

职责：

- 扫描 `skills/` 和 `AI_DEVOPS_SKILLS_ROOTS`。
- 建立 Skill Index。
- 提取 Skill Card。
- 校验基础元数据。

输出：

```json
{
  "name": "pytest-unit-test",
  "description": "Generate pytest tests",
  "source": "project",
  "path": "skills/pytest-unit-test/SKILL.md",
  "allowed_agents": ["TestGenerationAgent"],
  "token_budget": 1200
}
```

### 6.2 Loading

职责：

- Manager 或子 Agent 选中 Skill 后加载完整 `SKILL.md`。
- 按需加载 `references/`。
- 按 token budget 裁剪上下文。
- 记录加载来源和版本。

原则：

- 默认只加载 `SKILL.md`。
- references 必须由子 Agent 明确请求或由 Skill manifest 声明。
- scripts 不自动执行。

### 6.3 Execution

职责：

- 根据 Skill 类型选择执行方式。
- 调用 LLM prompt skill、builtin executor 或受控 tool adapter。
- 强制结构化输出。
- 记录审计日志。

支持执行类型：

```text
prompt      -> 将 SKILL.md 作为子 Agent system/context prompt
builtin     -> 调用现有 Python executor
tool        -> 调用白名单工具适配器
script      -> 后续支持，默认禁用
```

当前阶段建议先实现：

```text
prompt + builtin
```

暂不开放任意 script 执行。

## 7. 子 Agent 设计

子 Agent 不再只是 Python 方法名，而应有明确职责、输入、输出和可用 Skills。

### 7.1 ChangeUnderstandingAgent

职责：

- 理解变更意图。
- 判断是否需要单元测试。
- 输出受影响模块、风险等级、测试目标。

输入：

- diff
- changed_files
- code_review_result
- repo metadata

输出：

```json
{
  "need_test": true,
  "risk_level": "medium",
  "targets": [],
  "reason": ""
}
```

### 7.2 TestPlanningAgent

职责：

- 将变更目标转为测试计划。
- 选择测试框架。
- 选择合适 Skill。
- 生成测试用例清单。

输出：

```json
{
  "framework": "pytest",
  "selected_skills": ["pytest-unit-test"],
  "test_cases": []
}
```

### 7.3 TestGenerationAgent

职责：

- 基于测试计划和 Skill 生成测试文件。
- 遵循项目测试风格。
- 仅写入允许路径。

输出：

```json
{
  "generated_files": [
    {
      "path": "tests/test_service.py",
      "content": ""
    }
  ],
  "rationale": ""
}
```

### 7.4 TestReviewAgent

职责：

- 审查生成测试的有效性。
- 避免无断言、过度 mock、只测实现细节、脆弱测试。
- 判断是否需要重新生成。

输出：

```json
{
  "approved": true,
  "issues": [],
  "required_changes": []
}
```

### 7.5 TestRunnerAgent

职责：

- 执行受控测试命令。
- 收集 stdout、stderr、exit_code、失败用例。
- 不做修复。

输出：

```json
{
  "status": "passed",
  "exit_code": 0,
  "failed_tests": []
}
```

### 7.6 TestRepairAgent

职责：

- 根据失败日志修复生成测试。
- 优先修测试，不修改业务代码。
- 超过最大轮次后交给 Manager 判断失败。

输出：

```json
{
  "repaired_files": [],
  "repair_reason": "",
  "needs_rerun": true
}
```

### 7.7 QualityJudgeAgent

职责：

- 对测试质量评分。
- 评估覆盖关键路径、边界条件、可维护性。
- 生成最终质量结论。

输出：

```json
{
  "score": 86,
  "risk_level": "low",
  "summary": "",
  "recommendations": []
}
```

## 8. Manager 编排策略

`TestManagerAgent` 仍是唯一编排核心。

它负责：

- 观察当前状态。
- 选择下一个子 Agent。
- 选择或约束可用 Skill。
- 判断是否迭代。
- 判断是否完成、失败或需要人工介入。

推荐状态机：

```text
observe
  -> understand_change
  -> plan_tests
  -> generate_tests
  -> review_tests
  -> run_tests
  -> repair_tests
  -> run_tests
  -> judge_quality
  -> publish_feedback
  -> finish
```

允许跳转：

- 变更无需测试：`understand_change -> finish`
- 测试审查失败：`review_tests -> generate_tests`
- 测试执行失败：`run_tests -> repair_tests`
- 修复超过轮次：`repair_tests -> fail`
- 质量不达标：`judge_quality -> generate_tests` 或 `repair_tests`

## 9. 权限与安全

必须默认拒绝：

- 任意 shell 执行。
- 任意路径写入。
- 访问密钥、环境变量、凭证文件。
- 执行第三方 Skill scripts。
- 修改业务代码。

默认允许：

- 读取仓库 diff 和必要源码。
- 写入测试文件。
- 执行项目已识别的测试命令。
- 读取 Skill 的 `SKILL.md` 和声明的 references。

写入路径必须受控：

```text
tests/**
**/*.test.*
**/*.spec.*
```

具体路径应由项目语言和测试框架决定。

所有 Skill 调用必须记录：

- skill name
- skill source
- skill version/hash
- calling agent
- input summary
- output summary
- token usage
- permission decision
- duration
- status

## 10. 数据结构建议

### 10.1 AgentResult

```json
{
  "agent": "TestGenerationAgent",
  "status": "success",
  "skill": "pytest-unit-test",
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

### 10.2 ManagerTrace

```json
{
  "round": 1,
  "selected_agent": "TestPlanningAgent",
  "selected_skills": ["pytest-unit-test"],
  "reason": "",
  "expected_outcome": "",
  "source": "llm",
  "status": "success"
}
```

### 10.3 SkillInvocation

```json
{
  "skill_name": "pytest-unit-test",
  "skill_source": "project",
  "skill_path": "skills/pytest-unit-test/SKILL.md",
  "agent": "TestGenerationAgent",
  "execution_type": "prompt",
  "permissions": {},
  "status": "success"
}
```

## 11. 实施计划

### 阶段 1: 调整 Skill Registry 来源策略

目标：

- 优先扫描 `项目根目录/skills`。
- 支持 `AI_DEVOPS_SKILLS_ROOTS`。
- 完全移除 `.qoder/skills` 作为 Skills 来源。
- README 和规格文档同步更新。

任务：

- 修改 `OpenSkillRegistry._default_roots`。
- 增加 source 标记：`project`、`external`、`builtin`。
- 增加路径去重。
- 增加 `.qoder/skills` 排除校验。
- 增加单元测试。

验收：

- `skills/demo/SKILL.md` 可以被扫描为 project skill。
- 环境变量路径可以被扫描。
- `.qoder/skills` 不会被扫描。

### 阶段 2: Skill Loading

目标：

- 支持按 skill name 加载完整 `SKILL.md`。
- 支持按需加载 references。
- 支持 token budget 裁剪。

任务：

- 增加 `SkillPackage`。
- 增加 `load_skill(name)`。
- 增加 `load_reference(skill, path)`。
- Manager Prompt 中从只给 Card 升级为可选完整 Skill。

验收：

- Manager 选择 Skill 后，子 Agent 可以读取完整 Skill 指令。
- 默认不加载 scripts。

### 阶段 3: 使用 qodercli agent-creator 生成子 Agent

目标：

- 利用现有 `subagent-maker` 项目的 `qodercli agent-creator` 技能生成子 Agent 定义。
- 生成成功后，将子 Agent 定义复制到当前项目中，作为单元测试模块的专业子 Agent 基础。

前置条件：

- 用户已在电脑终端定位到：

```text
/d/WorkPlace/Learning/hermes-place/WorkPlace/WorkPlace/claudeCode/subagent-maker
```

- 用户已在该目录打开 `qodercli` 工具。
- 当前阶段只在用户确认后执行，不在规格确认前操作。

执行方式：

- 可通过 Computer Use 插件操作已打开的 `qodercli`。
- 使用 `agent-creator` 技能创建单元测试模块所需子 Agent。
- 生成结果先在 `subagent-maker` 目录中检查。
- 确认结构、命名、职责边界、输入输出契约后，再复制到当前项目。

建议创建的子 Agent：

- `ChangeUnderstandingAgent`
- `TestPlanningAgent`
- `TestGenerationAgent`
- `TestReviewAgent`
- `TestRunnerAgent`
- `TestRepairAgent`
- `QualityJudgeAgent`
- `FeedbackAgent`

复制目标建议：

```text
backend/app/services/unit_test_engine/subagents/
```

验收：

- 子 Agent 定义由 `qodercli agent-creator` 生成。
- 每个子 Agent 有明确职责、输入、输出、可用 Skills 和禁止行为。
- 生成文件复制到当前项目后，不直接接入运行链路，先进入代码审查。
- 不修改现有流水线行为。

### 阶段 4: 子 Agent 抽象

目标：

- 将现有 `_stage_*` 方法逐步包装为子 Agent 接口。

接口：

```python
class SubAgent:
    name: str
    allowed_actions: list[str]

    async def run(self, context, skills) -> AgentResult:
        ...
```

任务：

- 新增 `SubAgentContext`。
- 新增 `AgentResult`。
- 将 `change_intelligence`、`generator`、`validate_repair` 包装为 SubAgent。
- 保留旧 executor 作为 adapter。

验收：

- TestManager 调用的是子 Agent 接口，而不是直接调用 `_stage_*`。
- 旧测试继续通过。

### 阶段 5: TestReviewAgent

目标：

- 增加测试审查环节。
- 避免低质量测试进入执行。

任务：

- 新增 `TestReviewAgent`。
- 新增测试反模式 Skill。
- Manager 决策中增加 `review_tests` action。

验收：

- 无断言测试、只测 mock、只覆盖实现细节等问题可被识别。
- 审查失败时 Manager 可回到生成阶段。

### 阶段 6: 拆分 validate_tests

目标：

- 将当前 `validate_tests` 拆为 `run_tests` 和 `repair_tests`。

任务：

- 新增 `TestRunnerAgent`。
- 新增 `TestRepairAgent`。
- Manager 支持执行失败后的修复循环。
- 限制最大修复轮次。

验收：

- 测试执行和测试修复在 trace 中独立展示。
- 修复超过轮次后任务明确失败。

### 阶段 7: Skill Execution Adapter

目标：

- 支持受控执行 Skill 声明的 tool 或 script。

当前阶段只设计，不默认开启。

任务：

- 增加 permission schema。
- 增加 allowlist。
- 增加 sandbox policy。
- 增加审计日志。

验收：

- 默认拒绝 script。
- 显式 allow 后才可执行。
- 所有调用有审计记录。

## 12. 推荐优先级

建议先做：

1. `skills/` 作为项目级主目录。
2. Skill Loading。
3. 使用 `qodercli agent-creator` 生成子 Agent 定义。
4. 子 Agent 抽象。
5. TestReviewAgent。
6. 拆分 `run_tests` / `repair_tests`。

暂缓：

- 任意 script execution。
- MCP 任意接入。
- Agent 管理页面复杂配置。
- 图形化 Skill 编辑器。
- 通用 DAG 编排。
- `.qoder/skills` 兼容支持。

## 13. 成功标准

本阶段完成后，应满足：

- 用户可以把测试能力包放到 `项目根目录/skills`。
- Manager 可以看到项目级 Skill。
- 子 Agent 可以加载完整 `SKILL.md`。
- 子 Agent 定义可由 `/d/WorkPlace/Learning/hermes-place/WorkPlace/WorkPlace/claudeCode/subagent-maker` 中的 `qodercli agent-creator` 生成，并复制到当前项目。
- 单元测试链路中至少有一个子 Agent 使用 Skill 指令完成任务。
- Manager Trace 展示选择了哪个 Agent、哪个 Skill、为什么选择。
- 代码审查仍然在外层流水线，不进入单测 Manager action。
- 失败时能明确区分：Skill 不可用、Agent 决策失败、测试生成失败、测试执行失败、修复失败。

## 14. 结论

当前 `Skill Card` 是必要的发现层，但不是最终能力形态。

下一阶段应升级为：

```text
Skill Card
  -> Skill Package
  -> Skill Runtime
  -> SubAgent Invocation
  -> Manager-governed feedback loop
```

最终目标不是让 Python 脚本消失，而是让 Python executor 成为可替换、可回退的 builtin adapter；真正的专业能力由子 Agent 加载项目级或组织级 Skills 后完成。
