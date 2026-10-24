"""Sends the payload-free `take_over` Update to a task's Temporal workflow (`TASK-N`), flipping it to interactive."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

#: The Update's name: the task workflow registers the same one.
UPDATE = "take_over"


def temporal_take_over(address: str) -> Callable[[str], bool]:
    """A `take_over(task)` over the Temporal frontend at `address`: True once sent, False when the task has no workflow."""
    return lambda task: asyncio.run(send_take_over(address, task))


async def send_take_over(address: str, task: str) -> bool:
    from temporalio.client import Client  # noqa: PLC0415 - the optional `temporal` extra
    from temporalio.service import RPCError, RPCStatusCode  # noqa: PLC0415

    client = await Client.connect(address)
    try:
        await client.get_workflow_handle(task).execute_update(UPDATE)
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
    return True
