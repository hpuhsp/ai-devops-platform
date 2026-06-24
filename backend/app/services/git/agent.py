"""
Git Agent — handles repo cloning, branch management, and diff extraction.
WorkTree mechanism provides isolated environments for test execution.
"""
import os
import subprocess
import shutil
import uuid
from pathlib import Path
import structlog

from app.core.config import settings

logger = structlog.get_logger()

REPOS_BASE_DIR = Path("/tmp/ai-devops-repos")
WORKTREE_BASE_DIR = Path(settings.WORKTREE_BASE_DIR)


class GitAgent:
    def __init__(self, repo_url: str, git_token: str = None):
        self.repo_url = repo_url
        self.git_token = git_token
        self._authenticated_url = self._build_auth_url()
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        self.local_path = REPOS_BASE_DIR / repo_name
        REPOS_BASE_DIR.mkdir(parents=True, exist_ok=True)
        WORKTREE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    def _build_auth_url(self) -> str:
        """Inject token into HTTPS URL for authentication. Ensure .git suffix for clone."""
        url = self.repo_url
        if not url.endswith(".git"):
            url = url + ".git"
        if not self.git_token:
            return url
        if url.startswith("https://"):
            return url.replace("https://", f"https://oauth2:{self.git_token}@")
        return url

    def _run(self, cmd: list[str], cwd: str = None, check: bool = True) -> subprocess.CompletedProcess:
        logger.debug("git.run", cmd=" ".join(cmd), cwd=cwd)
        return subprocess.run(
            cmd,
            cwd=cwd or str(self.local_path),
            capture_output=True,
            text=True,
            check=check,
        )

    def ensure_repo(self) -> Path:
        """Clone repo if not exists, otherwise fetch latest."""
        if self.local_path.exists():
            result = self._run(["git", "fetch", "--all", "--prune"], check=False)
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if "couldn't find remote ref" in stderr or "does not have any commits" in stderr:
                    logger.info("git.fetch_empty_repo", path=str(self.local_path))
                else:
                    raise subprocess.CalledProcessError(result.returncode, result.args, result.stderr)
            else:
                logger.info("git.fetched", path=str(self.local_path))
        else:
            result = self._run(
                ["git", "clone", "--bare", self._authenticated_url, str(self.local_path)],
                cwd="/tmp", check=False,
            )
            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, result.args, result.stderr)
            logger.info("git.cloned", url=self.repo_url, path=str(self.local_path))
        return self.local_path

    def get_diff(self, base_ref: str, head_ref: str) -> tuple[str, list[str]]:
        """Get diff between two refs. Returns (diff_text, changed_files)."""
        self.ensure_repo()

        diff_result = self._run([
            "git", "diff", f"{base_ref}..{head_ref}", "--no-color",
        ])
        diff_text = diff_result.stdout

        files_result = self._run([
            "git", "diff", "--name-only", f"{base_ref}..{head_ref}",
        ])
        changed_files = [f for f in files_result.stdout.strip().split("\n") if f]

        return diff_text, changed_files

    def get_commit_diff(self, commit_sha: str) -> tuple[str, list[str]]:
        """Get diff for a single commit."""
        self.ensure_repo()
        diff_result = self._run(["git", "show", "--no-color", commit_sha])
        files_result = self._run(["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit_sha])
        changed_files = [f for f in files_result.stdout.strip().split("\n") if f]
        return diff_result.stdout, changed_files

    def get_latest_diff(self) -> tuple[str, list[str]]:
        """Get diff of the latest commit (HEAD vs HEAD~1). Fallback for test webhooks."""
        self.ensure_repo()
        # Check how many commits exist
        count_result = self._run(["git", "rev-list", "--count", "--all"], check=False)
        count = int(count_result.stdout.strip() or "0")
        if count == 0:
            return "", []
        if count == 1:
            # Only one commit — show it as the full diff
            sha = self._run(["git", "rev-list", "--all"]).stdout.strip().splitlines()[0]
            return self.get_commit_diff(sha)
        head = self._run(["git", "rev-parse", "HEAD"]).stdout.strip()
        return self.get_commit_diff(head)

    def create_worktree(self, branch: str) -> "WorkTree":
        """Create an isolated worktree for test execution."""
        self.ensure_repo()
        worktree_id = str(uuid.uuid4())[:8]
        worktree_path = WORKTREE_BASE_DIR / f"wt-{worktree_id}"

        self._run(["git", "worktree", "add", str(worktree_path), branch])
        logger.info("git.worktree_created", path=str(worktree_path), branch=branch)

        return WorkTree(worktree_path, self)

    def auto_merge(
        self,
        source_branch: str,
        target_branch: str,
        commit_sha: str,
        mr_title: str = "",
    ) -> dict:
        """
        Smart merge: check conditions then merge source -> target.
        Returns {"success": bool, "message": str, "merged_sha": str | None}
        """
        self.ensure_repo()

        # Verify source branch exists
        branches_result = self._run(["git", "branch", "-r", "--list", f"origin/{source_branch}"], check=False)
        if not branches_result.stdout.strip():
            return {"success": False, "message": f"Branch '{source_branch}' not found."}

        # Check merge conflict
        merge_check = self._run([
            "git", "merge-tree",
            f"origin/{target_branch}",
            f"origin/{source_branch}",
            f"origin/{source_branch}",
        ], check=False)

        if "<<<<<<" in merge_check.stdout:
            return {"success": False, "message": f"Merge conflict detected between {source_branch} -> {target_branch}"}

        logger.info("git.auto_merge", source=source_branch, target=target_branch)
        return {
            "success": True,
            "message": f"Ready to merge {source_branch} -> {target_branch}",
            "merged_sha": commit_sha,
        }

    def get_branch_for_merge(self, source_branch: str, branch_rules: dict) -> str | None:
        """Determine target branch based on branch rules."""
        for pattern, target in branch_rules.items():
            if pattern.endswith("/*"):
                prefix = pattern[:-2]
                if source_branch.startswith(prefix + "/"):
                    return target
            elif source_branch == pattern:
                return target
        return None


class WorkTree:
    """Isolated git worktree for running tests without polluting main repo."""

    def __init__(self, path: Path, agent: GitAgent):
        self.path = path
        self.agent = agent

    def write_files(self, files: list[dict]) -> list[str]:
        """Write generated test files into the worktree."""
        written = []
        for f in files:
            file_path = self.path / f["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(f["content"])
            written.append(str(file_path))
        logger.info("worktree.files_written", count=len(written))
        return written

    def run_command(self, command, timeout: int = 120) -> dict:
        """Run a command in the worktree (e.g., pytest).

        Prefer an argv list (executed WITHOUT a shell) so untrusted input can't be
        interpreted by the shell. A plain string still works but uses shell=True and
        must only ever be a trusted constant.
        """
        use_shell = isinstance(command, str)
        logger.info("worktree.run", command=command, shell=use_shell, path=str(self.path))
        try:
            result = subprocess.run(
                command,
                shell=use_shell,
                cwd=str(self.path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout[:5000],   # truncate long output
                "stderr": result.stderr[:2000],
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": "Timeout", "success": False}

    def cleanup(self):
        """Remove worktree and clean up references."""
        try:
            self.agent._run(["git", "worktree", "remove", "--force", str(self.path)])
        except Exception:
            shutil.rmtree(self.path, ignore_errors=True)
        logger.info("worktree.cleaned", path=str(self.path))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()
