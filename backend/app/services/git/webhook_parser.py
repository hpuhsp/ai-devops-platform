"""
Webhook event parser — normalizes GitLab/GitHub/Gitea payloads to unified format.
"""
from dataclasses import dataclass
from typing import Optional


def _normalize_url(url: str) -> str:
    """Strip .git suffix, trailing slash, and URL fragment for consistent matching."""
    if not url:
        return url
    url = url.split("#")[0].rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


@dataclass
class WebhookEvent:
    platform: str           # gitlab/github/gitea
    event_type: str         # push/mr_open/mr_update/tag
    repo_url: str
    branch: str
    commit_sha: str
    author: str
    author_email: str
    before_sha: Optional[str] = None
    mr_iid: Optional[int] = None
    mr_title: Optional[str] = None
    mr_description: Optional[str] = None
    mr_source_branch: Optional[str] = None
    mr_target_branch: Optional[str] = None
    raw_payload: dict = None


def _gitlab_repo_url(payload: dict) -> str:
    """Extract git_http_url from GitLab payload.
    Test webhooks only have 'project'; real push events have both 'repository' and 'project'.
    """
    url = (
        payload.get("repository", {}).get("git_http_url")
        or payload.get("project", {}).get("git_http_url")
        or payload.get("project", {}).get("http_url")
        or payload.get("repository", {}).get("url")
        or ""
    )
    return _normalize_url(url)


def parse_gitlab(payload: dict, event_header: str) -> WebhookEvent:
    event_type = {
        "Push Hook": "push",
        "Merge Request Hook": "mr_open",
        "Tag Push Hook": "tag",
    }.get(event_header, "unknown")

    if event_type == "push":
        return WebhookEvent(
            platform="gitlab",
            event_type="push",
            repo_url=_gitlab_repo_url(payload),
            branch=payload.get("ref", "").replace("refs/heads/", ""),
            commit_sha=payload.get("after", ""),
            before_sha=payload.get("before", ""),
            author=payload.get("user_name", ""),
            author_email=payload.get("user_email", ""),
            raw_payload=payload,
        )
    elif event_type in ("mr_open", "mr_update"):
        attrs = payload.get("object_attributes", {})
        return WebhookEvent(
            platform="gitlab",
            event_type=f"mr_{attrs.get('action', 'open')}",
            repo_url=_gitlab_repo_url(payload),
            branch=attrs.get("source_branch", ""),
            commit_sha=attrs.get("last_commit", {}).get("id", ""),
            author=payload.get("user", {}).get("name", ""),
            author_email=payload.get("user", {}).get("email", ""),
            mr_iid=attrs.get("iid"),
            mr_title=attrs.get("title"),
            mr_description=attrs.get("description"),
            mr_source_branch=attrs.get("source_branch"),
            mr_target_branch=attrs.get("target_branch"),
            raw_payload=payload,
        )
    return WebhookEvent(
        platform="gitlab",
        event_type=event_type,
        repo_url=_gitlab_repo_url(payload),
        branch="",
        commit_sha="",
        author="",
        author_email="",
        raw_payload=payload,
    )


def parse_github(payload: dict, event_header: str) -> WebhookEvent:
    if event_header == "push":
        return WebhookEvent(
            platform="github",
            event_type="push",
            repo_url=_normalize_url(payload["repository"]["clone_url"]),
            branch=payload.get("ref", "").replace("refs/heads/", ""),
            commit_sha=payload.get("after", ""),
            before_sha=payload.get("before", ""),
            author=payload.get("pusher", {}).get("name", ""),
            author_email=payload.get("pusher", {}).get("email", ""),
            raw_payload=payload,
        )
    elif event_header == "pull_request":
        pr = payload.get("pull_request", {})
        return WebhookEvent(
            platform="github",
            event_type=f"mr_{payload.get('action', 'open')}",
            repo_url=_normalize_url(payload["repository"]["clone_url"]),
            branch=pr.get("head", {}).get("ref", ""),
            commit_sha=pr.get("head", {}).get("sha", ""),
            author=pr.get("user", {}).get("login", ""),
            author_email="",
            mr_iid=pr.get("number"),
            mr_title=pr.get("title"),
            mr_description=pr.get("body"),
            mr_source_branch=pr.get("head", {}).get("ref"),
            mr_target_branch=pr.get("base", {}).get("ref"),
            raw_payload=payload,
        )
    return WebhookEvent(
        platform="github",
        event_type=event_header,
        repo_url=_normalize_url(payload.get("repository", {}).get("clone_url", "")),
        branch="",
        commit_sha="",
        author="",
        author_email="",
        raw_payload=payload,
    )


def parse_gitea(payload: dict, event_header: str) -> WebhookEvent:
    # Gitea uses same structure as GitHub push events
    if event_header == "push":
        return WebhookEvent(
            platform="gitea",
            event_type="push",
            repo_url=_normalize_url(payload["repository"]["clone_url"]),
            branch=payload.get("ref", "").replace("refs/heads/", ""),
            commit_sha=payload.get("after", ""),
            before_sha=payload.get("before", ""),
            author=payload.get("pusher", {}).get("login", ""),
            author_email=payload.get("pusher", {}).get("email", ""),
            raw_payload=payload,
        )
    elif event_header in ("pull_request",):
        pr = payload.get("pull_request", {})
        return WebhookEvent(
            platform="gitea",
            event_type=f"mr_{payload.get('action', 'open')}",
            repo_url=_normalize_url(payload["repository"]["clone_url"]),
            branch=pr.get("head", {}).get("ref", ""),
            commit_sha=pr.get("head", {}).get("sha", ""),
            author=pr.get("user", {}).get("login", ""),
            author_email="",
            mr_iid=pr.get("number"),
            mr_title=pr.get("title"),
            mr_description=pr.get("body"),
            mr_source_branch=pr.get("head", {}).get("ref"),
            mr_target_branch=pr.get("base", {}).get("ref"),
            raw_payload=payload,
        )
    return WebhookEvent(
        platform="gitea",
        event_type=event_header,
        repo_url=_normalize_url(payload.get("repository", {}).get("clone_url", "")),
        branch="",
        commit_sha="",
        author="",
        author_email="",
        raw_payload=payload,
    )
