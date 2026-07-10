"""
Quality Scorer — evaluates generated test quality across 4 dimensions.
Uses LLM for assessment, returns a 0-10 score with per-dimension breakdown + risk level.
"""
import json
import structlog

logger = structlog.get_logger()

SCORING_SYSTEM_PROMPT = """你是一位单元测试质量评审专家。请根据以下 4 个维度对生成的测试代码进行评分。

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

## 风险等级判定规则
- high: total_score < 5.0 或 business_coverage < 1.5 或 execution_success = 0
- medium: total_score < 7.0 或 business_coverage < 2.0
- low: total_score >= 7.0 且所有维度 >= 1.5

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
}"""


def compute_risk_level(total_score: float, dimensions: dict) -> tuple[str, str]:
    """Derive risk_level and risk_reason from score data."""
    biz = dimensions.get("business_coverage", {}).get("score", 0)
    exec_s = dimensions.get("execution_success", {}).get("score", 0)
    all_above_15 = all(
        d.get("score", 0) >= 1.5 for d in dimensions.values()
    )

    if total_score < 5.0 or biz < 1.5 or exec_s == 0:
        return "high", f"总分 {total_score} 过低或关键维度不达标"
    if total_score < 7.0 or biz < 2.0:
        return "medium", f"总分 {total_score} 中等，建议补充覆盖"
    if all_above_15:
        return "low", "质量达标，可放心合并"
    return "medium", "部分维度得分偏低"


class QualityScorer:
    """Evaluate generated test quality using LLM scoring."""

    async def score(
        self,
        engine,
        test_files: list[dict],
        validation_status: str,
        repair_rounds: int = 0,
    ) -> dict:
        user_prompt = self._build_prompt(test_files, validation_status, repair_rounds)

        try:
            response = await engine.complete_with_system(SCORING_SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            logger.error("quality_scorer.llm_failed", error=str(exc))
            return self._fallback_score(validation_status, repair_rounds)

        try:
            data = json.loads(response.content)
            if "risk_level" not in data:
                data["risk_level"], data["risk_reason"] = compute_risk_level(
                    data.get("total_score", 0), data.get("dimensions", {})
                )
            data["prompt_tokens"] = response.prompt_tokens
            data["completion_tokens"] = response.completion_tokens
            return data
        except (json.JSONDecodeError, ValueError):
            logger.warning("quality_scorer.parse_failed")
            result = self._fallback_score(validation_status, repair_rounds)
            result["prompt_tokens"] = response.prompt_tokens
            result["completion_tokens"] = response.completion_tokens
            return result

    def _build_prompt(
        self, test_files: list[dict], validation_status: str, repair_rounds: int
    ) -> str:
        parts = [
            f"## 执行结果\n- 状态: {validation_status}\n- 修复轮次: {repair_rounds}\n",
            "## 测试代码\n",
        ]
        for tf in test_files:
            content = tf.get("content", "")
            if len(content) > 4000:
                content = content[:4000] + "\n# ... (truncated)"
            parts.append(f"### `{tf.get('path', 'unknown')}`\n```python\n{content}\n```\n")
        return "".join(parts)

    def _fallback_score(self, validation_status: str, repair_rounds: int) -> dict:
        """Rule-based fallback when LLM scoring fails."""
        if validation_status == "all_pass" and repair_rounds == 0:
            exec_score, exec_note = 2.0, "全部通过（规则推断）"
        elif validation_status == "all_pass":
            exec_score, exec_note = 1.0, "经修复后通过（规则推断）"
        else:
            exec_score, exec_note = 0.0, "执行失败（规则推断）"

        default_score = 1.5
        dimensions = {
            "business_coverage": {"score": default_score, "max": 3.0, "note": "fallback estimate"},
            "scenario_coverage": {"score": default_score, "max": 2.5, "note": "fallback estimate"},
            "maintainability": {"score": default_score, "max": 2.5, "note": "fallback estimate"},
            "execution_success": {"score": exec_score, "max": 2.0, "note": exec_note},
        }
        total = sum(d["score"] for d in dimensions.values())
        risk_level, risk_reason = compute_risk_level(total, dimensions)

        return {
            "total_score": round(total, 1),
            "dimensions": dimensions,
            "risk_level": risk_level,
            "risk_reason": risk_reason,
            "suggestions": [],
            "summary": "规则推断评分（LLM 调用失败）",
            "fallback": True,
        }
