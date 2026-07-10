"""
MR Comment — posts AI test agent report as a comment on GitLab/GitHub/Gitea MRs.
"""
import httpx
import structlog
from urllib.parse import urlparse

logger = structlog.get_logger()

RISK_ICONS = {"high": "\U0001f7e0", "medium": "\U0001f7e1", "low": "\U0001f7e2", "none": "\u26aa"}


class MRCommentService:
    """Post markdown comments to MR/PR on supported platforms."""

    def __init__(self, platform: str, repo_url: str, git_token: str):
        self.platform = platform.lower()
        self.repo_url = repo_url
        self.git_token = git_token
        self._base_url, self._project_path = self._parse_repo_url()

    def _parse_repo_url(self) -> tuple[str, str]:
        parsed = urlparse(self.repo_url.rstrip("/").removesuffix(".git"))
        base = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port and parsed.port not in (80, 443):
            base += f":{parsed.port}"
        path = parsed.path.lstrip("/")
        return base, path

    async def post_comment(self, mr_iid: str, body: str) -> bool:
        if not self.git_token or not mr_iid:
            logger.warning("mr_comment.skip", reason="no token or mr_iid")
            return False

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if self.platform == "gitlab":
                    return await self._post_gitlab(client, mr_iid, body)
                elif self.platform == "github":
                    return await self._post_github(client, mr_iid, body)
                elif self.platform == "gitea":
                    return await self._post_gitea(client, mr_iid, body)
                else:
                    logger.warning("mr_comment.unsupported_platform", platform=self.platform)
                    return False
        except Exception as exc:
            logger.error("mr_comment.failed", error=str(exc), platform=self.platform)
            return False

    async def _post_gitlab(self, client: httpx.AsyncClient, mr_iid: str, body: str) -> bool:
        from urllib.parse import quote
        project_id = quote(self._project_path, safe="")
        url = f"{self._base_url}/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes"
        resp = await client.post(
            url,
            headers={"PRIVATE-TOKEN": self.git_token},
            json={"body": body},
        )
        if resp.status_code in (200, 201):
            logger.info("mr_comment.posted", platform="gitlab", mr_iid=mr_iid)
            return True
        logger.warning("mr_comment.gitlab_error", status=resp.status_code, body=resp.text[:200])
        return False

    async def _post_github(self, client: httpx.AsyncClient, pr_number: str, body: str) -> bool:
        url = f"https://api.github.com/repos/{self._project_path}/issues/{pr_number}/comments"
        resp = await client.post(
            url,
            headers={
                "Authorization": f"token {self.git_token}",
                "Accept": "application/vnd.github.v3+json",
            },
            json={"body": body},
        )
        if resp.status_code in (200, 201):
            logger.info("mr_comment.posted", platform="github", pr=pr_number)
            return True
        logger.warning("mr_comment.github_error", status=resp.status_code, body=resp.text[:200])
        return False

    async def _post_gitea(self, client: httpx.AsyncClient, issue_index: str, body: str) -> bool:
        url = f"{self._base_url}/api/v1/repos/{self._project_path}/issues/{issue_index}/comments"
        resp = await client.post(
            url,
            headers={"Authorization": f"token {self.git_token}"},
            json={"body": body},
        )
        if resp.status_code in (200, 201):
            logger.info("mr_comment.posted", platform="gitea", issue=issue_index)
            return True
        logger.warning("mr_comment.gitea_error", status=resp.status_code, body=resp.text[:200])
        return False


def build_test_report_comment(
    change_intel: dict,
    test_result: dict,
    repair_history: list[dict] = None,
    ai_branch: str = None,
    quality_score: dict = None,
) -> str:
    """Build the markdown comment body per spec section 3.6."""
    targets = change_intel.get("targets", [])
    risk = change_intel.get("risk_level", "unknown")
    risk_icon = RISK_ICONS.get(risk, "\u2754")

    target_names = []
    for t in targets[:3]:
        funcs = t.get("functions", [])
        if funcs:
            target_names.append(f"`{funcs[0]}`")
    targets_str = ", ".join(target_names) if target_names else "detected changes"

    lines = [
        "## AI Test Agent Report",
        "",
        f"**Change Analysis**: {targets_str} ({len(targets)} target(s) identified)",
        f"**Risk Level**: {risk_icon} {risk.upper()}",
        "",
    ]

    # Test results table
    files = test_result.get("generated_files", [])
    wr = test_result.get("worktree_run", {})
    repair_rounds = wr.get("repair_rounds", 0)

    if files:
        lines.append("### Test Generation Results")
        lines.append("| File | Cases | Status | Repair Rounds |")
        lines.append("|------|-------|--------|---------------|")
        for f in files:
            path = f.get("path", "unknown")
            cases = len(f.get("test_cases", []))
            status = wr.get("status", "unknown")
            lines.append(f"| `{path}` | {cases} | {status} | {repair_rounds} |")
        lines.append("")

    # Coverage — prefer the real pytest-cov measurement; fall back to the
    # LLM's estimate only when the sandbox didn't produce coverage.xml.
    wr_cov = wr.get("measured_coverage_delta")
    estimated = test_result.get("estimated_coverage_delta")
    if wr_cov:
        lines.append("### Coverage")
        lines.append(f"- **Measured** (pytest-cov on generated tests): {wr_cov}")
        if estimated:
            lines.append(f"- LLM estimate: {estimated}")
        lines.append("")
    elif estimated:
        lines.append(f"### Coverage Delta (LLM estimate): {estimated}")
        lines.append("")

    # Repair history
    if repair_history:
        lines.append("### Repair History")
        for rh in repair_history:
            fixes = ", ".join(rh.get("fixes", [])[:3])
            lines.append(f"- Round {rh['round']}: {fixes}")
        lines.append("")

    # Quality score + risk advice
    if quality_score and quality_score.get("total_score"):
        total = quality_score["total_score"]
        risk_level = quality_score.get("risk_level", "low")
        risk_reason = quality_score.get("risk_reason", "")
        risk_emoji = {"high": "\U0001f534", "medium": "\U0001f7e1", "low": "\U0001f7e2"}.get(risk_level, "\u26aa")

        lines.append(f"### Quality Score: {total}/10")
        lines.append("")

        # Risk advice section
        lines.append("### Risk Advice")
        lines.append(f"- **Level**: {risk_emoji} {risk_level.upper()}")
        if risk_reason:
            lines.append(f"- **Reason**: {risk_reason}")
        lines.append("")

        # Dimension table
        dim_labels = {
            "business_coverage": "Business Coverage",
            "scenario_coverage": "Scenario Coverage",
            "maintainability": "Maintainability",
            "execution_success": "Execution Success",
        }
        # Support both new (4-dim) and legacy (5-dim) formats
        legacy_dim_labels = {
            "compilation": "Compilation",
            "assertion_quality": "Assertion Quality",
            "exception_coverage": "Exception Coverage",
            "mock_quality": "Mock Quality",
            "maintainability": "Maintainability",
        }

        dims = quality_score.get("dimensions", {})
        if dims:
            lines.append("| Dimension | Score | Max |")
            lines.append("|-----------|-------|-----|")
            labels = dim_labels if any(k in dim_labels for k in dims) else legacy_dim_labels
            for dim_key, dim_val in dims.items():
                score = dim_val.get("score", 0)
                max_score = dim_val.get("max", 0)
                label = labels.get(dim_key, dim_key)
                lines.append(f"| {label} | {score} | {max_score} |")
            lines.append("")

        suggestions = quality_score.get("suggestions", [])
        if suggestions:
            for s in suggestions[:3]:
                lines.append(f"- {s}")
            lines.append("")

        # High risk warning
        if risk_level == "high":
            lines.append("> \u26a0\ufe0f **Recommend manual review before merge**: Test coverage is insufficient or execution failed. Merging may introduce regression defects.")
            lines.append("")

    # AI branch info
    if ai_branch:
        lines.append(f"> Generated tests pushed to branch `{ai_branch}`.")
        lines.append("")

    return "\n".join(lines)
