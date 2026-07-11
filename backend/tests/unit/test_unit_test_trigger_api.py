"""Unit test workflow trigger API helpers."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock


def _load_unit_test_endpoint():
    import types

    for mod_name in [
        "fastapi",
        "sqlalchemy",
        "sqlalchemy.ext.asyncio",
        "app.core.database",
    ]:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()
    for pkg in ["app.api", "app.api.v1", "app.api.v1.endpoints"]:
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)
    models_mod = types.ModuleType("app.models")
    models_mod.AITask = MagicMock()
    models_mod.Repository = MagicMock()
    sys.modules["app.models"] = models_mod

    spec = importlib.util.spec_from_file_location(
        "unit_test_endpoint",
        Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "endpoints" / "unit_test.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_unit_test_event_keeps_manual_trigger_context():
    mod = _load_unit_test_endpoint()
    repo = MagicMock()
    repo.repo_url = "https://git.example.com/group/project.git"

    body = mod.UnitTestTriggerRequest(
        repo_id=1,
        branch="feature/demo",
        commit_sha="abc123",
        before_sha="def456",
        author="tester",
        author_email="tester@example.com",
        metadata={"source": "api"},
    )

    event = mod._build_unit_test_event(repo, body)

    assert event["repo_url"] == repo.repo_url
    assert event["branch"] == "feature/demo"
    assert event["commit_sha"] == "abc123"
    assert event["before_sha"] == "def456"
    assert event["trigger_source"] == "manual_unit_test"
    assert event["metadata"] == {"source": "api"}
