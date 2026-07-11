"""Workflow side-effect port tests."""
import asyncio
from types import SimpleNamespace

from app.services.unit_test_engine import InMemoryWorkflowPorts, PipelineContext, UnitTestWorkflow


def test_workflow_ports_capture_side_effects_without_platform_services():
    ports = InMemoryWorkflowPorts()
    manager = UnitTestWorkflow()
    manager._loop = asyncio.new_event_loop()

    ctx = PipelineContext(
        task_id="task-1",
        ports=ports,
        skill_context=SimpleNamespace(repo_id=1, branch="feature/demo"),
        event_data={"mr_iid": 7},
    )

    async def scenario():
        await manager._persist(ctx, "code_review", {"status": "success"})
        await manager._record(ctx, "code_review", "success", output_data={"score": 100})
        await manager._notify(ctx, {"type": "code_review_result"}, "code_review")
        feedback = await ctx.ports.publish_mr_feedback(ctx)
        return feedback

    try:
        feedback = manager._loop.run_until_complete(scenario())
    finally:
        manager._loop.close()

    assert ctx.output_data["code_review"]["status"] == "success"
    assert ports.persisted == [("code_review", {"status": "success"})]
    assert ports.records[0]["agent_type"] == "code_review"
    assert ports.records[0]["status"] == "success"
    assert ports.notifications[0]["stage_type"] == "code_review"
    assert feedback == {"ai_branch": None, "mr_iid": 7}
