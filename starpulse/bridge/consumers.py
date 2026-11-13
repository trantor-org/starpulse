"""The durable JetStream consumer of each session: its filter subjects are the session's subscription.

The consumer is named for the session and carries its `Subscription` in metadata, so the server holds the only copy.
A consumer starts from the newest message of each subject (`LAST_PER_SUBJECT`), so a session that subscribes late is
given the latest state. An empty subscription deletes the consumer: an empty filter would mean every subject.
"""

from __future__ import annotations

from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.errors import NotFoundError

from starpulse.bridge.publisher import Publisher
from starpulse.bridge.subscriptions import Subscription

_KEY = "starpulse.subscription"


async def all_consumers(js, stream: str) -> list:  # noqa: ANN001
    """Every consumer of `stream`: the server lists a page of at most 256, so page on `offset` until one comes back empty."""
    found: list = []
    while page := await js.consumers_info(stream, offset=len(found)):
        found += page
    return found


class Consumers:
    def __init__(self, link: Publisher, stream: str) -> None:
        self._link, self._stream = link, stream

    def get(self, session: str) -> Subscription:
        async def read(js):  # noqa: ANN001, ANN202
            try:
                return await js.consumer_info(self._stream, session)
            except NotFoundError:
                return None

        info = self._link.run(read)
        return Subscription.loads((info.config.metadata or {}).get(_KEY, "") if info else "")

    def put(self, session: str, subscription: Subscription) -> None:
        """Make the consumer's filter the subscription's subjects; the consumer is gone when there are none."""
        filters = subscription.filters
        config = ConsumerConfig(
            durable_name=session,
            filter_subjects=filters,
            deliver_policy=DeliverPolicy.LAST_PER_SUBJECT,
            ack_policy=AckPolicy.EXPLICIT,
            metadata={_KEY: subscription.dumps()},
        )

        async def write(js):  # noqa: ANN001, ANN202
            if filters:
                await js.add_consumer(self._stream, config=config)
                return
            try:
                await js.delete_consumer(self._stream, session)
            except NotFoundError:
                pass

        self._link.run(write)

    def holding(self, origin: str) -> list[str]:
        """The sessions whose subscription holds subjects from `origin`."""

        async def read(js):  # noqa: ANN001, ANN202
            return await all_consumers(js, self._stream)

        held = []
        for info in self._link.run(read):
            if origin in Subscription.loads((info.config.metadata or {}).get(_KEY, "")).origins:
                held.append(info.name)
        return held
