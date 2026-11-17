"""`subscribe` and `unsubscribe` ask the bridge to change a session's consumer, so the bridge alone writes it.

A read-then-write of the consumer from the CLI raced the bridge's own grants: the later write dropped the earlier
change, and JetStream offers no conditional consumer update to refuse a stale read. The CLI instead sends a core NATS
request on `starpulse-bridge.<board>.subscription`, a subject outside the board's stream so JetStream neither stores nor
acknowledges it, and the bridge applies it under the lock its tail's grants take (`Subscriber.change`). With no bridge
running, nothing answers and the request is `Unavailable`.
"""

import asyncio
import json
from typing import Any

import nats
from nats.errors import Error as NatsError
from nats.js.errors import BadRequestError

from starpulse.bridge.publisher import Unavailable
from starpulse.bridge.subscriber import Subscriber
from starpulse.bridge.subscriptions import explicit_subject
from starpulse.event_log.wake import StopEvent

_TIMEOUT_S = 5.0


def subject(board: str) -> str:
    return f"starpulse-bridge.{board}.subscription"


def ask(url: str, board: str, session: str, subjects: list[str], add: bool) -> dict[str, Any]:
    """The bridge's answer to adding `subjects` to `session`'s consumer, or removing them: `changed` and `subjects`.

    `Unavailable` when the server or the bridge does not answer, `ValueError` when the bridge refuses the change.
    """
    body = json.dumps({"session": session, "subjects": subjects, "add": add}).encode()

    async def request() -> bytes:
        client = await nats.connect(url, connect_timeout=_TIMEOUT_S, allow_reconnect=False)
        try:
            return (await client.request(subject(board), body, timeout=_TIMEOUT_S * 3)).data
        finally:
            await client.close()

    try:
        answer = json.loads(asyncio.run(request()))
    except (NatsError, OSError, TimeoutError) as exc:
        raise Unavailable(f"{type(exc).__name__}: {exc}") from exc
    if "unavailable" in answer:
        raise Unavailable(answer["unavailable"])
    if "error" in answer:
        raise ValueError(answer["error"])
    return answer


def answer(board: str, subscriber: Subscriber, data: bytes) -> bytes:
    """Apply one request to the subscriber and say what happened; a malformed or refused one changes nothing."""
    try:
        request = json.loads(data)
        session, items, add = request["session"], request["subjects"], request["add"]
        if not (isinstance(session, str) and isinstance(add, bool) and isinstance(items, list)):
            raise ValueError("session must be a string, subjects a list and add a boolean")
        if not all(isinstance(item, str) for item in items):
            raise ValueError("subjects must be strings")
        changed, filters = subscriber.change(session, [explicit_subject(board, item) for item in items], add)
        reply: dict[str, Any] = {"changed": changed, "subjects": filters}
    except Unavailable as exc:
        reply = {"unavailable": str(exc)}
    except (ValueError, KeyError, TypeError, BadRequestError) as exc:
        reply = {"error": str(exc)}
    return json.dumps(reply).encode()


def serve(url: str, board: str, subscriber: Subscriber, stop: StopEvent) -> None:
    """Answer requests until `stop` is set; a server that is down delays the start, and the client resubscribes on reconnect."""
    asyncio.run(_serve(url, board, subscriber, stop))


async def _serve(url: str, board: str, subscriber: Subscriber, stop: StopEvent) -> None:
    loop = asyncio.get_running_loop()

    async def respond(msg: Any) -> None:
        await msg.respond(await loop.run_in_executor(None, answer, board, subscriber, msg.data))

    # With no reconnect limit, `connect` retries a down server until it answers; `stop` cancels it.
    connecting = asyncio.ensure_future(nats.connect(url, connect_timeout=_TIMEOUT_S, max_reconnect_attempts=-1))
    stopped = loop.run_in_executor(None, stop.wait)
    await asyncio.wait({connecting, stopped}, return_when=asyncio.FIRST_COMPLETED)
    if not connecting.done():
        connecting.cancel()
        return
    client = connecting.result()
    try:
        await client.subscribe(subject(board), cb=respond)
        await stopped
    finally:
        await client.close()
