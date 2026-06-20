"""Unit tests for webhook event parsing."""
import pytest
from app.services.git.webhook_parser import parse_gitlab, parse_github, parse_gitea


GITLAB_PUSH_PAYLOAD = {
    "object_kind": "push",
    "user_name": "John Doe",
    "user_email": "john@example.com",
    "ref": "refs/heads/feature/login",
    "before": "0000000000000000000000000000000000000000",
    "after": "abc1234567890abcdef",
    "repository": {"git_http_url": "https://gitlab.com/org/repo.git"},
}

GITLAB_MR_PAYLOAD = {
    "user": {"name": "Jane", "email": "jane@example.com"},
    "repository": {"git_http_url": "https://gitlab.com/org/repo.git"},
    "object_attributes": {
        "iid": 42,
        "title": "feat: Add login",
        "description": "Implements login flow",
        "action": "open",
        "source_branch": "feature/login",
        "target_branch": "develop",
        "last_commit": {"id": "abc123"},
    },
}

GITHUB_PUSH_PAYLOAD = {
    "ref": "refs/heads/main",
    "before": "aaa",
    "after": "bbb",
    "pusher": {"name": "alice", "email": "alice@example.com"},
    "repository": {"clone_url": "https://github.com/org/repo.git"},
}


def test_parse_gitlab_push():
    event = parse_gitlab(GITLAB_PUSH_PAYLOAD, "Push Hook")
    assert event.platform == "gitlab"
    assert event.event_type == "push"
    assert event.branch == "feature/login"
    assert event.commit_sha == "abc1234567890abcdef"
    assert event.author == "John Doe"


def test_parse_gitlab_mr():
    event = parse_gitlab(GITLAB_MR_PAYLOAD, "Merge Request Hook")
    assert event.event_type == "mr_open"
    assert event.mr_iid == 42
    assert event.mr_title == "feat: Add login"
    assert event.mr_source_branch == "feature/login"
    assert event.mr_target_branch == "develop"


def test_parse_github_push():
    event = parse_github(GITHUB_PUSH_PAYLOAD, "push")
    assert event.platform == "github"
    assert event.branch == "main"
    assert event.commit_sha == "bbb"
    assert event.author == "alice"


def test_parse_gitea_push():
    payload = {**GITHUB_PUSH_PAYLOAD, "pusher": {"login": "bob", "email": "bob@ex.com"}}
    event = parse_gitea(payload, "push")
    assert event.platform == "gitea"
    assert event.author == "bob"
