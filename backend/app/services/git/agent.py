"""
Git Agent — handles repo cloning, branch management, and diff extraction.
WorkTree mechanism provides isolated environments for test execution.
"""
import os
import subprocess
import shutil
import uuid
import hashlib
import time
from pathlib import Path
import structlog

from app.core.config import settings

logger = structlog.get_logger()

REPOS_BASE_DIR = Path("/tmp/ai-devops-repos")
WORKTREE_BASE_DIR = Path(settings.WORKTREE_BASE_DIR)
REPO_CACHE_TTL_SECONDS = int(os.getenv("REPO_CACHE_TTL_SECONDS", str(14 * 24 * 60 * 60)))
REPO_CACHE_LAST_ACCESS = ".last_access"


class GitAgent:
    def __init__(self, repo_url: str, git_token: str = None):
        self.repo_url = repo_url
        self.git_token = git_token
        self._authenticated_url = self._build_auth_url()
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        repo_hash = hashlib.sha1(self._normalized_cache_url().encode("utf-8")).hexdigest()[:12]
        self.local_path = REPOS_BASE_DIR / f"{repo_name}-{repo_hash}"
        REPOS_BASE_DIR.mkdir(parents=True, exist_ok=True)
        WORKTREE_BASE_DIR.mkdir(parents=True, exist_ok=True)
        self.cleanup_stale_repo_caches()

    def _normalized_cache_url(self) -> str:
        url = self.repo_url.split("#")[0].rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        return url.lower()

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

    @classmethod
    def cleanup_stale_repo_caches(cls, ttl_seconds: int = REPO_CACHE_TTL_SECONDS) -> int:
        """Remove repo caches that have not been accessed within ttl_seconds."""
        if ttl_seconds <= 0 or not REPOS_BASE_DIR.exists():
            return 0

        now = time.time()
        removed = 0
        for path in REPOS_BASE_DIR.iterdir():
            if not path.is_dir():
                continue
            marker = path / REPO_CACHE_LAST_ACCESS
            try:
                last_access = marker.stat().st_mtime if marker.exists() else path.stat().st_mtime
            except OSError:
                continue
            if now - last_access <= ttl_seconds:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
            logger.info("git.cache_removed", path=str(path), ttl_seconds=ttl_seconds)
        return removed

    def _touch_cache(self) -> None:
        try:
            self.local_path.mkdir(parents=True, exist_ok=True)
            (self.local_path / REPO_CACHE_LAST_ACCESS).touch()
        except OSError as exc:
            logger.warning("git.cache_touch_failed", path=str(self.local_path), error=str(exc))

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
        self._touch_cache()
        return self.local_path

    @staticmethod
    def _is_safe_branch(branch: str) -> bool:
        return bool(branch) and not any(part in branch for part in ("..", "~", "^", ":", "\\", "?", "*", "["))

    def fetch_branch(self, branch: str) -> bool:
        """Fetch one branch into the local bare cache."""
        if not self._is_safe_branch(branch):
            logger.warning("git.fetch_branch_unsafe", branch=branch)
            return False
        self.ensure_repo()
        result = self._run(
            ["git", "fetch", "origin", f"+refs/heads/{branch}:refs/heads/{branch}"],
            check=False,
        )
        if result.returncode == 0:
            self._touch_cache()
            logger.info("git.branch_fetched", branch=branch)
            return True
        logger.warning("git.branch_fetch_failed", branch=branch, error=result.stderr.strip()[:500])
        return False

    def has_commit(self, commit_sha: str) -> bool:
        if not commit_sha:
            return False
        result = self._run(["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"], check=False)
        return result.returncode == 0

    def ensure_commit(self, commit_sha: str, branch: str = "") -> None:
        """Ensure a commit object exists locally, fetching the branch once if needed."""
        self.ensure_repo()
        if self.has_commit(commit_sha):
            self._touch_cache()
            return

        if branch:
            self.fetch_branch(branch)
            if self.has_commit(commit_sha):
                self._touch_cache()
                return

        result = self._run(["git", "fetch", "--all", "--prune"], check=False)
        if result.returncode == 0 and self.has_commit(commit_sha):
            self._touch_cache()
            return

        raise RuntimeError(
            f"Unable to find commit {commit_sha} in local cache after fetch. "
            f"Branch='{branch or '-'}'. Check Git token permissions and whether the branch was pushed."
        )

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

    def get_commit_diff(self, commit_sha: str, branch: str = "") -> tuple[str, list[str]]:
        """Get diff for a single commit."""
        self.ensure_commit(commit_sha, branch)
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


    def push_ai_branch(
        self,
        base_ref: str,
        branch_name: str,
        files: list[dict],
        commit_message: str = "chore(ai): add generated unit tests",
    ) -> dict:
        """
        Create an AI branch from base_ref, write test files, commit, and push.
        Returns {"success": bool, "branch": str, "commit_sha": str | None, "error": str | None}
        """
        self.ensure_repo()
        worktree_path = WORKTREE_BASE_DIR / f"push-{uuid.uuid4().hex[:8]}"

        try:
            # Create worktree at base_ref
            self._run(["git", "worktree", "add", "-b", branch_name, str(worktree_path), base_ref])

            # Write files
            for f in files:
                fp = worktree_path / f["path"]
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(f["content"])

            # Stage and commit
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(worktree_path), capture_output=True, text=True, check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=str(worktree_path), capture_output=True, text=True, check=True,
            )
            sha_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(worktree_path), capture_output=True, text=True, check=True,
            )
            commit_sha = sha_result.stdout.strip()

            # Push to remote
            push_result = subprocess.run(
                ["git", "push", self._authenticated_url, f"HEAD:refs/heads/{branch_name}"],
                cwd=str(worktree_path), capture_output=True, text=True, check=False,
            )
            if push_result.returncode != 0:
                return {
                    "success": False, "branch": branch_name,
                    "commit_sha": None, "error": push_result.stderr[:500],
                }

            logger.info("git.ai_branch_pushed", branch=branch_name, sha=commit_sha[:8])
            return {"success": True, "branch": branch_name, "commit_sha": commit_sha, "error": None}

        except Exception as exc:
            logger.error("git.push_ai_branch_failed", error=str(exc))
            return {"success": False, "branch": branch_name, "commit_sha": None, "error": str(exc)}
        finally:
            try:
                self._run(["git", "worktree", "remove", "--force", str(worktree_path)])
            except Exception:
                shutil.rmtree(worktree_path, ignore_errors=True)


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

    def read_coverage(self, filename: str = "coverage.xml") -> dict:
        """Parse a Cobertura coverage.xml produced by pytest-cov.

        Returns a dict with total line-rate (percent), lines-run, lines-covered,
        and a per-file breakdown. Returns an empty dict if the file is missing or
        malformed — callers must treat this as "coverage not measured".
        """
        import xml.etree.ElementTree as ET

        cov_path = self.path / filename
        if not cov_path.exists():
            logger.info("worktree.coverage_missing", path=str(cov_path))
            return {}
        try:
            tree = ET.parse(str(cov_path))
            root = tree.getroot()
            line_rate = float(root.attrib.get("line-rate", "0"))
            lines_valid = int(root.attrib.get("lines-valid", "0"))
            lines_covered = int(root.attrib.get("lines-covered", "0"))

            per_file: dict[str, dict] = {}
            for pkg in root.findall(".//package"):
                for cls in pkg.findall(".//class"):
                    name = cls.attrib.get("filename", "")
                    lr = float(cls.attrib.get("line-rate", "0"))
                    lv = int(cls.attrib.get("lines-valid", "0"))
                    lc = int(cls.attrib.get("lines-covered", "0"))
                    if name:
                        per_file[name] = {
                            "line_rate": round(lr * 100, 2),
                            "lines_valid": lv,
                            "lines_covered": lc,
                        }

            return {
                "line_rate": round(line_rate * 100, 2),
                "lines_valid": lines_valid,
                "lines_covered": lines_covered,
                "files": per_file,
            }
        except Exception as exc:
            logger.warning("worktree.coverage_parse_error", error=str(exc), path=str(cov_path))
            return {}


    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()
