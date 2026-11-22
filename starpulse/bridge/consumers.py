"""The durable JetStream consumer of each session: its filter subjects are the session's subscription.

The consumer is named for the session and carries its `Subscription` in metadata, so the server holds the only copy.
A consumer starts from the newest message of each subject (`LAST_PER_SUBJECT`), so a session that subscribes late is
given the latest state, except a holder's resume published before the consumer existed (`JetStreamMailbox.fetch`
acks it unsent). An empty subscription deletes the consumer: an empty filter would mean every subject.
"""

import json
import logging

from nats.js.api import AckPolicy, ConsumerConfig, ConsumerInfo, DeliverPolicy
from nats.js.errors import NotFoundError

from starpulse.bridge.publisher import Publisher
from starpulse.bridge.subscriptions import Subscription

logger = logging.getLogger(__name__)
_KEY = "starpulse.subscription"


async def all_consumers(js, stream: str) -> list:  # noqa: ANN001
    """Every consumer of `stream`: the server lists a page of at most 256, so page on `offset` until one comes back empty.

    Each entry is parsed alone: nats-py cannot read a non-UTC offset in a timestamp, and one such consumer would fail the page.
    """
    found: list = []
    seen = 0
    while True:
        resp = await js._api_request(  # noqa: SLF001
            f"{js._prefix}.CONSUMER.LIST.{stream}",  # noqa: SLF001
            json.dumps({"offset": seen}).encode(),
            timeout=js._timeout,  # noqa: SLF001
        )
        if not (page := resp["consumers"]):
            return found
        seen += len(page)
        for raw in page:
            try:
                found.append(ConsumerInfo.from_response(raw))
            except ValueError:
                logger.exception("skipped consumer %s: unreadable timestamp", raw.get("name"))


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

    def sessions(self) -> dict[str, Subscription]:
        """Every consumer of the stream with its subscription."""

        async def read(js):  # noqa: ANN001, ANN202
            return await all_consumers(js, self._stream)

        return {info.name: Subscription.loads((info.config.metadata or {}).get(_KEY, "")) for info in self._link.run(read)}

    def holding(self, origin: str) -> list[str]:
        """The sessions whose subscription holds subjects from `origin`."""
        return [name for name, subscription in self.sessions().items() if origin in subscription.origins]
