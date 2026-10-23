"""The take-over seam sends the payload-free `take_over` Update to workflow `TASK-N` on a Temporal test server."""

from __future__ import annotations

import asyncio

from temporalio import workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from starpulse._internal.server.take_over import UPDATE, send_take_over


@workflow.defn(name="stub_task")
class StubTask:
    def __init__(self) -> None:
        self.taken = False

    @workflow.update(name=UPDATE)
    def take_over(self) -> None:
        self.taken = True

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self.taken)
        return "taken"


def test_the_update_reaches_the_workflow_named_for_the_task() -> None:
    async def scenario() -> str:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(env.client, task_queue="q", workflows=[StubTask]):
                handle = await env.client.start_workflow(StubTask.run, id="TASK-7", task_queue="q")
                assert await send_take_over(env.client.service_client.config.target_host, "TASK-7")
                return await handle.result()

    assert asyncio.run(scenario()) == "taken"


def test_a_task_with_no_workflow_is_not_taken_over() -> None:
    async def scenario() -> bool:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            return await send_take_over(env.client.service_client.config.target_host, "TASK-404")

    assert asyncio.run(scenario()) is False
