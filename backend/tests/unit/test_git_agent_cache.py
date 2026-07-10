"""Unit tests for GitAgent cache path and commit reachability helpers."""
from pathlib import Path
from types import SimpleNamespace
import os
import time

import pytest

from app.services.git import agent as git_agent_module
from app.services.git.agent import GitAgent


def test_repo_cache_path_uses_url_hash(monkeypatch, tmp_path):
    monkeypatch.setattr(git_agent_module, "REPOS_BASE_DIR", tmp_path / "repos")
    monkeypatch.setattr(git_agent_module, "WORKTREE_BASE_DIR", tmp_path / "worktrees")

    first = GitAgent("https://gitlab.example.com/team-a/test-devops.git")
    second = GitAgent("https://gitlab.example.com/team-b/test-devops.git")

    assert first.local_path.name.startswith("test-devops-")
    assert second.local_path.name.startswith("test-devops-")
    assert first.local_path != second.local_path


def test_ensure_commit_fetches_branch_when_commit_missing():
    calls = []
    agent = GitAgent.__new__(GitAgent)
    agent.local_path = Path("/tmp/repo.git")

    def fake_run(cmd, cwd=None, check=True):
        calls.append(cmd)
        if cmd[:3] == ["git", "cat-file", "-e"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        if cmd[:3] == ["git", "fetch", "origin"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    agent._run = fake_run
    agent.ensure_repo = lambda: None

    with pytest.raises(RuntimeError, match="Unable to find commit abc123"):
        agent.ensure_commit("abc123", "feature/demo")

    assert ["git", "fetch", "origin", "+refs/heads/feature/demo:refs/heads/feature/demo"] in calls


def test_ensure_commit_succeeds_after_branch_fetch():
    attempts = {"cat_file": 0}
    agent = GitAgent.__new__(GitAgent)
    agent.local_path = Path("/tmp/repo.git")

    def fake_run(cmd, cwd=None, check=True):
        if cmd[:3] == ["git", "cat-file", "-e"]:
            attempts["cat_file"] += 1
            return SimpleNamespace(returncode=0 if attempts["cat_file"] == 2 else 1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    agent._run = fake_run
    agent.ensure_repo = lambda: None

    agent.ensure_commit("abc123", "feature/demo")

    assert attempts["cat_file"] == 2


def test_cleanup_stale_repo_caches_removes_expired_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(git_agent_module, "REPOS_BASE_DIR", tmp_path)
    stale = tmp_path / "old-repo.git"
    fresh = tmp_path / "fresh-repo.git"
    stale.mkdir()
    fresh.mkdir()

    old_time = time.time() - 10_000
    os.utime(stale, (old_time, old_time))
    (fresh / ".last_access").touch()

    removed = GitAgent.cleanup_stale_repo_caches(ttl_seconds=60)

    assert removed == 1
    assert not stale.exists()
    assert fresh.exists()
