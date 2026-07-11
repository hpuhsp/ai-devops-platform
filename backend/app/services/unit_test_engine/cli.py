"""CLI entry point for AI unit test workflow integration.

This intentionally does not reimplement a CI runner. It either triggers the
platform API when --api-url/--repo-id are provided, or writes a deterministic
local report that documents why standalone execution is not configured yet.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-test-engine")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run or trigger the AI unit test workflow")
    run.add_argument("--repo-url", required=True)
    run.add_argument("--branch", default="")
    run.add_argument("--commit", default="")
    run.add_argument("--before", default="")
    run.add_argument("--author", default="ci")
    run.add_argument("--output", default="ai-test-report.json")
    run.add_argument("--api-url", default="", help="Optional platform base URL, e.g. http://host:8090")
    run.add_argument("--repo-id", type=int, default=None, help="Repository id in the platform when using --api-url")
    run.add_argument("--timeout", type=int, default=30)
    return parser


def _report_base(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "repo_url": args.repo_url,
        "branch": args.branch,
        "commit_sha": args.commit,
        "before_sha": args.before,
        "author": args.author,
        "stages": [],
        "artifacts": [],
        "events": [],
    }


def _write_report(path: str, report: dict[str, Any]):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _trigger_platform(args: argparse.Namespace) -> dict[str, Any]:
    if args.repo_id is None:
        raise ValueError("--repo-id is required when --api-url is provided")

    base = args.api_url.rstrip("/")
    payload = {
        "repo_id": args.repo_id,
        "branch": args.branch,
        "commit_sha": args.commit,
        "before_sha": args.before,
        "author": args.author,
        "metadata": {"source": "ai-test-engine-cli"},
    }
    request = urllib.request.Request(
        f"{base}/api/v1/unit-test/trigger",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        body = json.loads(response.read().decode("utf-8"))

    report = _report_base(args)
    report.update({
        "status": "triggered",
        "mode": "platform_api",
        "platform": {
            "api_url": base,
            "repo_id": args.repo_id,
            "task_id": body.get("task_id"),
            "response": body,
        },
    })
    return report


def _standalone_report(args: argparse.Namespace) -> dict[str, Any]:
    report = _report_base(args)
    report.update({
        "status": "skipped",
        "mode": "standalone",
        "reason": "standalone AI execution adapter is not configured; use --api-url to trigger the platform workflow",
        "events": [
            {
                "event": "workflow_skipped",
                "stage": "unit_test",
                "status": "skipped",
                "reason": "standalone adapter not configured",
            }
        ],
    })
    return report


def run_command(args: argparse.Namespace) -> int:
    try:
        report = _trigger_platform(args) if args.api_url else _standalone_report(args)
        _write_report(args.output, report)
        print(json.dumps({
            "status": report["status"],
            "mode": report["mode"],
            "output": args.output,
            "task_id": report.get("platform", {}).get("task_id"),
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        report = _report_base(args)
        report.update({
            "status": "failed",
            "mode": "platform_api" if args.api_url else "standalone",
            "reason": str(exc),
        })
        try:
            _write_report(args.output, report)
        except OSError as write_exc:
            report["report_write_error"] = str(write_exc)
        print(json.dumps({
            "status": "failed",
            "output": args.output,
            "reason": str(exc),
            "report_write_error": report.get("report_write_error"),
        }, ensure_ascii=False), file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_command(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
