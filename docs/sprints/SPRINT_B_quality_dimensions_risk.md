# Sprint B：质量维度对齐 + 独立风险建议

## 1. 背景与动机

### 1.1 现状
当前 `QualityScorer` 使用 5 个评分维度：
1. `compilation`（编译通过）— 权重 2.0
2. `assertion_quality`（断言质量）— 权重 3.0
3. `exception_coverage`（异常覆盖）— 权重 2.0
4. `mock_quality`（Mock 合理性）— 权重 1.5
5. `maintainability`（可维护性）— 权重 1.5

### 1.2 规范文档要求
根据《AI单元测试Agent_Prompt与规则规范_V1.0》，质量评估应使用 4 个维度：
1. **Business Coverage（业务覆盖度）**：是否覆盖核心业务逻辑、关键分支、边界条件
2. **Scenario Coverage（场景覆盖度）**：正常路径 + 异常路径 + 边界值 + 并发场景
3. **Maintainability（可维护性）**：命名清晰、无魔法数字、Fixture 复用、断言可读
4. **Execution Success（执行成功率）**：编译通过、无运行时错误、断言全部通过

### 1.3 风险建议缺失
当前 MR 评论和飞书通知仅展示质量分数和建议列表，**缺少独立的风险等级建议**（高/中/低），开发者无法快速判断是否需要人工 Review。

## 2. 质量维度改造

### 2.1 新维度定义

| 维度 | Key | 权重 | 评分标准 |
|------|-----|------|---------|
| 业务覆盖度 | `business_coverage` | 3.0 | 核心函数是否被测试覆盖；关键分支（if/else/try-catch）是否命中；边界值（空值、极值、零值）是否测试 |
| 场景覆盖度 | `scenario_coverage` | 2.5 | 正常路径 ✓；异常路径（InvalidInput/NotFound/PermissionDenied）✓；边界值 ✓；参数组合 ✓ |
| 可维护性 | `maintainability` | 2.5 | 测试命名语义清晰（test_<action>_<scenario>）；无魔法数字/字符串；Fixture 复用合理；断言信息可读 |
| 执行成功率 | `execution_success` | 2.0 | 编译通过（预判定）；无运行时错误；所有断言通过；无 flaky test 模式（如 time.sleep） |

**总分**：10.0 分制，各维度满分等于其权重。

### 2.2 新 System Prompt

```
你是一位单元测试质量评审专家。请根据以下 4 个维度对生成的测试代码进行评分。

## 评分维度

### 1. 业务覆盖度 (business_coverage) — 满分 3.0
评估测试是否覆盖了目标函数的核心业务逻辑：
- 核心函数/方法是否都有对应测试用例
- 关键分支（if/elif/else、try/except）是否被覆盖
- 边界值（None、空字符串、0、极大值、空列表）是否被测试
- 业务规则（如权限检查、状态转换）是否有对应测试

评分参考：
- 3.0: 所有核心逻辑 + 分支 + 边界值均覆盖
- 2.0: 核心逻辑覆盖，但缺少部分分支或边界
- 1.0: 仅覆盖正常路径
- 0.0: 未覆盖任何核心逻辑

### 2. 场景覆盖度 (scenario_coverage) — 满分 2.5
评估测试场景的多样性：
- 正常路径（Happy Path）
- 异常路径（InvalidInput、NotFound、PermissionDenied、Timeout）
- 边界值（空输入、极值、特殊字符）
- 参数组合（多参数函数的不同组合）

评分参考：
- 2.5: 正常 + 异常 + 边界 + 组合均有覆盖
- 1.5: 正常 + 异常 + 边界
- 1.0: 正常 + 异常
- 0.0: 仅正常路径

### 3. 可维护性 (maintainability) — 满分 2.5
评估测试代码的可读性和可维护性：
- 命名：test_<被测行为>_<场景>（如 test_transfer_insufficient_balance）
- 无魔法数字/字符串（使用常量或有意义的变量名）
- Fixture 复用合理（setup/teardown 使用 @fixture）
- 断言信息可读（assert 带 msg 参数）
- 单个测试只验证一个行为

评分参考：
- 2.5: 命名清晰 + Fixture 复用 + 断言可读 + 单一职责
- 1.5: 命名基本清晰 + 部分 Fixture 复用
- 0.5: 命名混乱或有魔法数字
- 0.0: 完全不可维护

### 4. 执行成功率 (execution_success) — 满分 2.0
此维度根据实际执行结果预判定：
- 2.0: 全部通过，无错误
- 1.0: 经过修复后通过（repair_rounds > 0）
- 0.5: 部分通过（>50% 测试通过）
- 0.0: 全部失败或编译错误

## 输出格式（严格 JSON）
{
  "total_score": 8.5,
  "dimensions": {
    "business_coverage": {"score": 2.5, "max": 3.0, "note": "中文说明"},
    "scenario_coverage": {"score": 2.0, "max": 2.5, "note": "中文说明"},
    "maintainability": {"score": 2.0, "max": 2.5, "note": "中文说明"},
    "execution_success": {"score": 2.0, "max": 2.0, "note": "中文说明"}
  },
  "risk_level": "high|medium|low",
  "risk_reason": "中文简述风险判断原因",
  "suggestions": ["改进建议1", "改进建议2"],
  "summary": "一句话总结"
}

## 风险等级判定规则
- high: total_score < 5.0 或 business_coverage < 1.5 或 execution_success = 0
- medium: total_score < 7.0 或 business_coverage < 2.0
- low: total_score >= 7.0 且所有维度 >= 1.5
```

### 2.3 代码改造

**文件**：`backend/app/services/agents/quality_scorer.py`

**改造点**：
1. 替换 `SCORING_SYSTEM_PROMPT` 为新版 4 维度 prompt
2. 更新 `_fallback_score()` 方法适配新维度
3. 新增 `risk_level` 和 `risk_reason` 字段到输出结构
4. 更新 `QualityScorer.score()` 返回值解析逻辑

**新 fallback 逻辑**：
```python
def _fallback_score(self, validation_status: str, repair_rounds: int) -> dict:
    # execution_success
    if validation_status == "all_pass" and repair_rounds == 0:
        exec_score, exec_note = 2.0, "全部通过（规则推断）"
    elif validation_status == "all_pass":
        exec_score, exec_note = 1.0, "经修复后通过（规则推断）"
    else:
        exec_score, exec_note = 0.0, "执行失败（规则推断）"

    # 其他维度给默认中间值
    default_score = 1.5
    dimensions = {
        "business_coverage": {"score": default_score, "max": 3.0, "note": "fallback estimate"},
        "scenario_coverage": {"score": default_score, "max": 2.5, "note": "fallback estimate"},
        "maintainability": {"score": default_score, "max": 2.5, "note": "fallback estimate"},
        "execution_success": {"score": exec_score, "max": 2.0, "note": exec_note},
    }
    total = sum(d["score"] for d in dimensions.values())

    # 风险等级
    if total < 5.0 or exec_score == 0:
        risk_level, risk_reason = "high", "总分过低或执行失败"
    elif total < 7.0:
        risk_level, risk_reason = "medium", "总分中等，建议人工 Review"
    else:
        risk_level, risk_reason = "low", "质量达标"

    return {
        "total_score": round(total, 1),
        "dimensions": dimensions,
        "risk_level": risk_level,
        "risk_reason": risk_reason,
        "suggestions": [],
        "summary": "规则推断评分（LLM 调用失败）",
        "fallback": True,
    }
```

## 3. 独立风险建议

### 3.1 风险等级定义

| 等级 | 含义 | 建议动作 |
|------|------|---------|
| `high` | 测试质量低或覆盖不足，合并后可能引入回归 | **建议人工 Review 后再合并** |
| `medium` | 测试质量中等，部分场景覆盖不足 | 建议补充关键异常路径测试 |
| `low` | 测试质量良好，覆盖全面 | 可放心合并 |

### 3.2 MR 评论集成

**文件**：`backend/app/services/notify/mr_comment.py`

在 `build_test_report_comment` 中新增风险建议区块：

```python
def build_test_report_comment(
    change_intel: dict,
    test_result: dict,
    repair_history: list,
    ai_branch: str | None,
    quality_score: dict | None,
) -> str:
    lines = ["## AI 测试生成报告", ""]

    # ... 现有区块 ...

    # 新增：风险建议区块
    if quality_score:
        risk_level = quality_score.get("risk_level", "low")
        risk_reason = quality_score.get("risk_reason", "")
        risk_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(risk_level, "⚪")

        lines.append("### 风险建议")
        lines.append(f"- **等级**: {risk_emoji} {risk_level.upper()}")
        if risk_reason:
            lines.append(f"- **原因**: {risk_reason}")
        lines.append(f"- **总分**: {quality_score.get('total_score', 'N/A')}/10")

        # 维度明细
        dims = quality_score.get("dimensions", {})
        if dims:
            lines.append("")
            lines.append("| 维度 | 得分 | 满分 |")
            lines.append("|------|------|------|")
            dim_labels = {
                "business_coverage": "业务覆盖度",
                "scenario_coverage": "场景覆盖度",
                "maintainability": "可维护性",
                "execution_success": "执行成功率",
            }
            for key, label in dim_labels.items():
                d = dims.get(key, {})
                lines.append(f"| {label} | {d.get('score', 'N/A')} | {d.get('max', 'N/A')} |")

        # 高风险时添加醒目提示
        if risk_level == "high":
            lines.append("")
            lines.append("> ⚠️ **建议人工 Review 后再合并**：测试覆盖度不足或执行失败，合并后可能引入回归缺陷。")

        lines.append("")

    return "\n".join(lines)
```

### 3.3 飞书通知集成

**文件**：`backend/app/services/notify/feishu.py`

在 `_build_test_gen_card` 中新增风险等级标签：

```python
# 风险等级标签
risk_level = (quality_score or {}).get("risk_level", "low")
risk_config = {
    "high": {"color": "red", "text": "🔴 高风险 — 建议人工 Review"},
    "medium": {"color": "yellow", "text": "🟡 中风险 — 建议补充测试"},
    "low": {"color": "green", "text": "🟢 低风险 — 可放心合并"},
}
risk_info = risk_config.get(risk_level, risk_config["low"])
```

在卡片中添加风险标签元素：
```python
# 在质量分数之后添加
{
    "tag": "div",
    "text": {
        "tag": "lark_md",
        "content": f"**风险建议**: {risk_info['text']}"
    }
}
```

### 3.4 前端风险展示

**文件**：`frontend/src/pages/logs/TaskDetailPage.tsx`

在质量评分节点中新增风险等级徽章：
- `high` → 红色徽章 "高风险"
- `medium` → 黄色徽章 "中风险"
- `low` → 绿色徽章 "低风险"

## 4. 向后兼容

### 4.1 旧维度映射
如果 `output_data` 中仍存在旧维度（`compilation`、`assertion_quality` 等），前端应兼容展示，不报错。

### 4.2 渐进迁移
- 新任务使用 4 维度
- 旧任务保持 5 维度展示
- 前端通过检测 `dimensions` 中的 key 来区分

## 5. 测试计划

### 5.1 单元测试

| 测试 | 验证内容 |
|------|---------|
| `test_quality_scorer_4_dimensions` | 评分输出包含 4 个新维度 |
| `test_quality_scorer_risk_level_high` | total < 5.0 时 risk_level = "high" |
| `test_quality_scorer_risk_level_medium` | total < 7.0 时 risk_level = "medium" |
| `test_quality_scorer_risk_level_low` | total >= 7.0 时 risk_level = "low" |
| `test_fallback_score_new_dimensions` | fallback 评分使用新维度 |
| `test_mr_comment_risk_section` | MR 评论包含风险建议区块 |
| `test_mr_comment_high_risk_warning` | 高风险时包含人工 Review 提示 |

### 5.2 验证清单

- [ ] 质量评分输出 4 个新维度（非旧的 5 个）
- [ ] 每个维度有正确的满分值
- [ ] risk_level 根据规则正确计算
- [ ] MR 评论包含风险建议区块
- [ ] 飞书卡片展示风险等级标签
- [ ] 前端正确展示新维度分数
- [ ] 旧任务（5 维度）前端不报错
- [ ] fallback 评分使用新维度结构
- [ ] 高风险时 MR 评论有醒目提示

## 6. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/services/agents/quality_scorer.py` | **重写** | 4 维度 prompt + risk_level + 新 fallback |
| `backend/app/services/notify/mr_comment.py` | 修改 | 新增风险建议区块 + 新维度表格 |
| `backend/app/services/notify/feishu.py` | 修改 | 卡片新增风险等级标签 |
| `frontend/src/pages/logs/TaskDetailPage.tsx` | 修改 | 新维度展示 + 风险徽章 |
| `tests/test_quality_scorer.py` | **新增/修改** | 4 维度 + 风险等级测试 |
| `tests/test_mr_comment.py` | **新增/修改** | 风险建议区块测试 |

## 7. 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LLM 不遵循新 prompt 格式 | JSON 解析失败时 fallback 兜底 |
| 旧维度数据导致前端报错 | 前端兼容检测，按 key 动态渲染 |
| 风险等级误判 | 规则保守（宁可 high 不可 low） |
