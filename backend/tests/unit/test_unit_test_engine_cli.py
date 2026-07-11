"""AI unit test engine CLI tests."""
import json
from pathlib import Path

from app.services.unit_test_engine.cli import main


def test_cli_writes_standalone_report(tmp_path: Path):
    output = tmp_path / "ai-test-report.json"

    code = main([
        "run",
        "--repo-url", "https://git.example.com/group/project.git",
        "--branch", "feature/demo",
        "--commit", "abc123",
        "--before", "def456",
        "--output", str(output),
    ])

    report = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert report["schema_version"] == "1.0"
    assert report["status"] == "skipped"
    assert report["mode"] == "standalone"
    assert report["branch"] == "feature/demo"
    assert report["commit_sha"] == "abc123"
    assert report["events"][0]["event"] == "workflow_skipped"


def test_cli_requires_repo_id_when_triggering_platform(tmp_path: Path):
    output = tmp_path / "ai-test-report.json"

    code = main([
        "run",
        "--repo-url", "https://git.example.com/group/project.git",
        "--api-url", "http://platform.example.com",
        "--output", str(output),
    ])

    report = json.loads(output.read_text(encoding="utf-8"))
    assert code == 2
    assert report["status"] == "failed"
    assert "--repo-id is required" in report["reason"]
