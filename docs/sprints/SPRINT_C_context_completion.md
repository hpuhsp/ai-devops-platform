# Sprint C：Context 补全（项目规则 + 历史 Bug）

## 1. 背景与动机

### 1.1 现状
当前 `ContextAgent.build_context()` 输出以下信息：
- `target_functions`：目标函数源码、导入、调用者/被调用者、mock 候选
- `project_test_framework`：检测到的测试框架（pytest/unittest）
- `fixtures_available`：已有 conftest fixtures
- `test_style_example`：已有测试的风格示例
- `dependencies`：项目依赖列表
- `codegraph_available`：CodeGraph 是否可用

### 1.2 规范文档要求
根据《AI单元测试Agent_Prompt与规则规范_V1.0》，Generator Agent 的输入上下文还应包含：
1. **项目规则（Project Rules）**：编码规范、测试规范、命名约定、禁止使用的模式
2. **历史 Bug（Historical Bugs）**：近期同文件/同模块的缺陷记录，帮助 Generator 避免重复犯错

### 1.3 当前缺失
- `ContextAgent` 不读取任何项目规则文件
- `ChangeIntelligenceSkill` 中 `historical_defects` 从 `context.extra` 读取，但 **从未被填充**
- Generator Agent 的 prompt 中没有注入项目规则和历史 Bug 信息

## 2. 项目规则（Project Rules）

### 2.1 规则来源

按优先级从高到低扫描以下位置：

| 优先级 | 路径 | 格式 | 说明 |
|--------|------|------|------|
| 1 | `.ai-devops/rules.md` | Markdown | 项目自定义 AI 测试规则 |
| 2 | `.ai-devops/test-rules.md` | Markdown | 项目自定义测试规范 |
| 3 | `CONTRIBUTING.md` 中的 `## Testing` 段落 | Markdown | 通用贡献指南中的测试章节 |
| 4 | `pyproject.toml` 的 `[tool.ai-devops]` 段 | TOML | 配置文件中的规则 |
| 5 | `.cursorrules` / `.clinerules` | 文本 | 通用 AI 编码规则（可提取测试相关部分） |

### 2.2 规则提取逻辑

```python
def _discover_project_rules(self) -> str:
    """Scan well-known locations for project-specific test rules."""
    rules_parts = []

    # Priority 1: .ai-devops/rules.md
    for rule_path in [
        self.root / ".ai-devops" / "rules.md",
        self.root / ".ai-devops" / "test-rules.md",
    ]:
        if rule_path.exists():
            content = rule_path.read_text(encoding="utf-8", errors="replace")
            rules_parts.append(f"## 来自 {rule_path.relative_to(self.root)}\n{content.strip()}")
            break  # 只取第一个最高优先级

    # Priority 3: CONTRIBUTING.md ## Testing section
    contributing = self.root / "CONTRIBUTING.md"
    if contributing.exists() and not rules_parts:
        text = contributing.read_text(encoding="utf-8", errors="replace")
        testing_section = self._extract_section(text, "Testing")
        if testing_section:
            rules_parts.append(f"## 来自 CONTRIBUTING.md (Testing 章节)\n{testing_section}")

    # Priority 4: pyproject.toml [tool.ai-devops]
    pyproject = self.root / "pyproject.toml"
    if pyproject.exists() and not rules_parts:
        try:
            import tomllib
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            ai_rules = data.get("tool", {}).get("ai-devops", {})
            if "test_rules" in ai_rules:
                rules_parts.append(f"## 来自 pyproject.toml [tool.ai-devops]\n{ai_rules['test_rules']}")
        except Exception:
            pass

    # Priority 5: .cursorrules / .clinerules (test-related extraction)
    for rule_file in [".cursorrules", ".clinerules"]:
        rule_path = self.root / rule_file
        if rule_path.exists() and not rules_parts:
            text = rule_path.read_text(encoding="utf-8", errors="replace")
            test_rules = self._extract_test_related(text)
            if test_rules:
                rules_parts.append(f"## 来自 {rule_file} (测试相关)\n{test_rules}")
            break

    if not rules_parts:
        return ""

    combined = "\n\n".join(rules_parts)
    # 限制总长度，避免 prompt 过长
    max_chars = 2000
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n\n[... 规则已截断 ...]"

    return combined
```

### 2.3 辅助方法

```python
def _extract_section(self, text: str, section_name: str) -> str | None:
    """Extract a markdown section by heading name."""
    lines = text.split("\n")
    capturing = False
    section_lines = []
    heading_level = 0

    for line in lines:
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line.lstrip("#").strip().lower()
            if section_name.lower() in title:
                capturing = True
                heading_level = level
                continue
            elif capturing and level <= heading_level:
                break

        if capturing:
            section_lines.append(line)

    result = "\n".join(section_lines).strip()
    return result if result else None

def _extract_test_related(self, text: str) -> str:
    """Extract test-related lines from generic AI rules."""
    keywords = ["test", "测试", "pytest", "unittest", "mock", "fixture", "assert", "断言"]
    lines = text.split("\n")
    relevant = [line for line in lines if any(kw in line.lower() for kw in keywords)]
    return "\n".join(relevant[:30]) if relevant else ""
```

## 3. 历史 Bug（Historical Bugs）

### 3.1 数据来源

历史 Bug 通过 `SkillContext.extra["historical_defects"]` 传入。需要在上游填充此数据。

**数据源优先级**：

| 来源 | 获取方式 | 说明 |
|------|---------|------|
| Git log 分析 | `git log --grep="fix\|bug\|修复\|缺陷"` | 从 commit message 中提取近期修复 |
| Webhook payload | GitLab/GitHub MR 关联的 issue | 从事件数据中提取 |
| 外部 API | JIRA/飞书项目 查询 | 可选，需要额外配置 |

### 3.2 Git Log 分析实现

在 `ContextAgent` 中新增方法：

```python
def _scan_historical_defects(self, target_files: list[str]) -> list[dict]:
    """Scan git log for recent bug fixes in target files."""
    defects = []
    try:
        for file_path in target_files[:5]:  # 限制扫描文件数
            result = subprocess.run(
                [
                    "git", "log",
                    "--oneline",
                    "--since=30 days ago",
                    "--grep=fix|bug|修复|缺陷|hotfix",
                    "--all-match",
                    "--", file_path,
                ],
                cwd=str(self.root),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split("\n")[:5]:  # 每文件最多 5 条
                    parts = line.split(" ", 1)
                    if len(parts) == 2:
                        defects.append({
                            "commit": parts[0],
                            "message": parts[1],
                            "file": file_path,
                        })
    except (subprocess.TimeoutExpired, OSError):
        pass

    return defects[:15]  # 总计最多 15 条
```

### 3.3 在 Pipeline 中填充 historical_defects

**文件**：`backend/app/tasks/ai_tasks.py`

在 `_ai_pipeline` 中，构建 `SkillContext` 后填充 `historical_defects`：

```python
# 在构建 SkillContext 之后
skill_context.extra["historical_defects_count"] = 0
skill_context.extra["historical_defects"] = []

# 如果 worktree 已就绪（在 context stage 中创建），可以扫描
# 但 context stage 中 worktree 是临时创建的，需要在该阶段内填充
```

**更好的方案**：在 `_stage_context` 中，ContextAgent 创建后直接扫描并注入：

```python
# 在 TestManagerAgent._stage_context 中
agent = ContextAgent(worktree_path=str(wt.path))
context_output = agent.build_context(targets)

# 新增：扫描历史缺陷
historical_defects = agent.scan_historical_defects(
    [t.get("file", "") for t in targets]
)
context_output["historical_defects"] = historical_defects

# 注入到 skill_context.extra 供 ChangeIntelligence 使用
ctx.skill_context.extra["historical_defects"] = len(historical_defects)
ctx.skill_context.extra["historical_defects_detail"] = historical_defects
```

## 4. ContextAgent 输出结构升级

### 4.1 新增字段

```python
def build_context(self, targets: list[dict]) -> dict:
    return {
        # ... 现有字段 ...
        "target_functions": [...],
        "project_test_framework": "pytest",
        "fixtures_available": [...],
        "test_style_example": "...",
        "dependencies": [...],
        "codegraph_available": True,

        # 新增字段
        "project_rules": "...",           # 项目规则文本（可能为空字符串）
        "historical_defects": [           # 历史缺陷列表
            {"commit": "abc1234", "message": "fix: null check in transfer", "file": "app/payment.py"},
        ],
    }
```

### 4.2 公开方法

```python
def scan_historical_defects(self, target_files: list[str]) -> list[dict]:
    """Public method for pipeline to scan historical defects."""
    return self._scan_historical_defects(target_files)
```

## 5. Generator Agent Prompt 增强

### 5.1 现有 Prompt 结构

Generator Agent（`test_generation.py` skill）的 prompt 中已包含：
- 目标函数源码
- 测试框架信息
- Fixtures 列表
- 测试风格示例
- 依赖列表

### 5.2 新增注入内容

在 `test_generation.py` 的 `_build_user_prompt` 中新增：

```python
# 项目规则
project_rules = context_output.get("project_rules", "")
if project_rules:
    parts.append(f"\n## 项目测试规则\n```\n{project_rules}\n```")

# 历史缺陷
historical_defects = context_output.get("historical_defects", [])
if historical_defects:
    defect_lines = "\n".join(
        f"  - [{d['commit']}] {d['message']} ({d['file']})"
        for d in historical_defects[:10]
    )
    parts.append(f"\n## 近期历史缺陷（请避免类似问题）\n{defect_lines}")
```

### 5.3 System Prompt 补充

在 `test_generation.py` 的 `SYSTEM_PROMPT` 中新增：

```
## 额外上下文利用规则
- 如果提供了「项目测试规则」，严格遵守其中的命名约定、禁止模式、框架要求
- 如果提供了「近期历史缺陷」，确保生成的测试能覆盖这些 Bug 对应的场景，防止回归
- 历史缺陷中提到的错误类型（如 NoneType、IndexError），必须有对应的异常测试用例
```

## 6. ChangeIntelligence 集成

### 6.1 修复 historical_defects 填充

当前 `ChangeIntelligenceSkill._build_prompt` 已读取 `historical_defects` 但值始终为 0。

**修复**：确保 `_stage_context` 在 `_stage_change_intelligence` **之前**执行，并将结果注入 `skill_context.extra`。

**当前执行顺序**（已正确）：
1. `code_review`
2. `change_intelligence` ← 此时 historical_defects 尚未填充
3. `context` ← 这里扫描历史缺陷
4. `generator`
5. `validate_repair`
6. `quality_scorer`
7. `mr_feedback`

**问题**：`change_intelligence` 在 `context` 之前执行，无法获得历史缺陷数据。

**解决方案**：将历史缺陷扫描提前到 `change_intelligence` 阶段之前，作为独立的轻量级操作。

```python
# 在 TestManagerAgent._stage_change_intelligence 中
# 新增：轻量级历史缺陷扫描（不依赖 worktree，使用 git log on bare repo）
# 或者：调整阶段顺序，将 context 提前到 change_intelligence 之前
```

**推荐方案**：在 `_ai_pipeline` 构建 SkillContext 时，直接从 git_agent 获取历史缺陷（无需 worktree）：

```python
# 在 _ai_pipeline 中，构建 SkillContext 之后
historical = await git_agent.get_recent_defect_commits(
    files=skill_context.changed_files, since="30 days"
)
skill_context.extra["historical_defects"] = len(historical)
skill_context.extra["historical_defects_detail"] = historical
```

**GitAgent 新增方法**：
```python
async def get_recent_defect_commits(
    self, files: list[str], since: str = "30 days"
) -> list[dict]:
    """Get recent bug-fix commits for given files."""
    # 使用已 clone 的 repo（非 worktree）执行 git log
    # ...
```

## 7. 测试计划

### 7.1 单元测试

| 测试 | 验证内容 |
|------|---------|
| `test_discover_project_rules_ai_devops` | 检测到 `.ai-devops/rules.md` |
| `test_discover_project_rules_contributing` | 从 CONTRIBUTING.md 提取 Testing 章节 |
| `test_discover_project_rules_pyproject` | 从 pyproject.toml 提取规则 |
| `test_discover_project_rules_empty` | 无规则文件时返回空字符串 |
| `test_discover_project_rules_truncation` | 超长规则被截断到 2000 字符 |
| `test_scan_historical_defects` | 从 git log 中提取缺陷修复记录 |
| `test_scan_historical_defects_no_fixes` | 无缺陷修复时返回空列表 |
| `test_extract_section` | Markdown 章节提取正确 |
| `test_context_output_has_new_fields` | build_context 输出包含 project_rules 和 historical_defects |

### 7.2 集成测试

| 测试 | 验证内容 |
|------|---------|
| `test_pipeline_context_includes_rules` | Pipeline 执行后 output_data 包含项目规则 |
| `test_pipeline_context_includes_defects` | Pipeline 执行后 output_data 包含历史缺陷 |
| `test_generator_prompt_has_rules` | Generator prompt 中包含项目规则 |
| `test_generator_prompt_has_defects` | Generator prompt 中包含历史缺陷 |
| `test_change_intel_has_defect_count` | ChangeIntelligence 输入包含正确的 historical_defects 计数 |

### 7.3 验证清单

- [ ] ContextAgent 输出包含 `project_rules` 字段
- [ ] ContextAgent 输出包含 `historical_defects` 字段
- [ ] 项目规则从正确优先级位置读取
- [ ] 历史缺陷从 git log 正确提取
- [ ] Generator prompt 中包含项目规则和历史缺陷
- [ ] ChangeIntelligence 输入中 `historical_defects` 计数正确
- [ ] 无规则文件时不报错，返回空字符串
- [ ] 无历史缺陷时不报错，返回空列表
- [ ] 超长规则被截断，不影响 Pipeline

## 8. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/services/agents/context_agent.py` | 修改 | 新增 `_discover_project_rules` + `_scan_historical_defects` + 输出字段 |
| `backend/app/services/skills/builtin/test_generation.py` | 修改 | Prompt 注入项目规则和历史缺陷 |
| `backend/app/services/agents/test_manager.py` | 修改 | `_stage_context` 填充 historical_defects 到 skill_context.extra |
| `backend/app/tasks/ai_tasks.py` | 修改 | `_ai_pipeline` 中提前填充 historical_defects 到 skill_context.extra |
| `backend/app/services/git/agent.py` | 修改 | 新增 `get_recent_defect_commits` 方法 |
| `tests/test_context_agent.py` | **新增/修改** | 项目规则 + 历史缺陷测试 |
| `tests/test_generator_prompt.py` | **新增** | Generator prompt 增强测试 |

## 9. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 项目规则文件过大导致 prompt 超长 | 截断到 2000 字符 |
| git log 扫描耗时过长 | 限制文件数（5）和记录数（15），超时 10 秒 |
| 历史缺陷扫描结果不准确 | 仅作为参考信息，不影响 Pipeline 核心流程 |
| `.ai-devops/rules.md` 不存在 | 优雅降级，返回空字符串 |
| 阶段顺序导致数据不可用 | 在 _ai_pipeline 中提前扫描，不依赖 context stage |
