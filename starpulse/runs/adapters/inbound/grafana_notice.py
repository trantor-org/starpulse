"""The Grafana notice receiver: `POST /intake/grafana`.

Grafana's webhook contact point posts one notice per group, retrying until it gets a 2xx. The notice is saved as one
`NOTICE_RECEIVED` event of the `alert-notice` machine, in the process that took the request, so no command starts per
notice. The event's id is the digest of the body, so Grafana's redelivery appends nothing. A consumer outside StarPulse
applies the project's rules to it.
"""

import hashlib
import hmac
import json
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only
    from starpulse.runs.adapters.inbound.cloudevents import CloudEventsIngest

#: The largest notice `data` accepted, as JSON text: the whole notice rides in the event, which the ingest's pointer cap would refuse.
MAX_NOTICE = 256 * 1024


def notice_webhook(
    events: CloudEventsIngest, producer: str, token: str
) -> Callable[[str | None, bytes], tuple[int, dict]]:
    """The route's seam: `(Authorization header, body)` to `(status, JSON body)`; a 503 makes Grafana send it again."""
    expected = f"Bearer {token}".encode()

    def webhook(authorization: str | None, raw: bytes) -> tuple[int, dict]:
        if not hmac.compare_digest((authorization or "").encode(), expected):
            return 401, {"error": "a bearer token is required"}
        try:
            notice = json.loads(raw)
        except ValueError:
            notice = None
        if not isinstance(notice, dict):
            return 400, {"error": "a Grafana notice is a JSON object"}
        digest = hashlib.sha256(raw).hexdigest()
        event = {
            "specversion": "1.0",
            "id": digest,
            "source": producer,
            "type": "NOTICE_RECEIVED",
            "machine": "alert-notice",
            "actor": "grafana",
            "run": digest,
            "data": notice,
        }
        status, body = events.write(producer, [event], max_data=MAX_NOTICE)
        return (202, {"accepted": True}) if status == 201 else (status, body)

    return webhook
