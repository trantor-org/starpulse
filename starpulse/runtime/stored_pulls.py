"""The unfiltered `/api/pulls` answer, stored by the Delivery worker for `serve` to send as it is."""

import logging
import threading
import time
from collections.abc import Callable

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.snapshot_store import SnapshotStore
from starpulse.event_log.wake import StopEvent, save_on_change
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.views.model.encoding import encode

logger = logging.getLogger(__name__)

#: The view the answer is stored as, which `serve` reads.
VIEW = "pulls"
#: How long after a save the answer is stored: the list is ~5 MB to encode (0.6 s), and saves come in bursts, so the
#: saves of one window share one encode.
STORE_AFTER_S = 3.0


def keep_pulls(
    store: PullStore, log: EventLog, stop: StopEvent, debounce_s: float = STORE_AFTER_S
) -> Callable[[], None]:
    """What asks for `store`'s unfiltered list to be stored, encoded and gzipped, in `log`'s database: a thread stores
    it `debounce_s` after the first call of a window, until `stop`. `serve` sends the one stored before until then."""
    snapshots = SnapshotStore(log.engine, lambda data, held: b"")
    changed = threading.Event()

    def store_list() -> None:
        if stop.is_set():  # the thread's last call, which the process ending has no use for
            return
        try:
            # the body `pulls_response` makes of a read with no filter
            found = store.find(None, None, None, None, detailed=False, bodies=False)
            snapshots.put(VIEW, encode("pulls", {"pulls": found}), time.time())
        except Exception:
            logger.warning("pulls: the unfiltered list was not stored", exc_info=True)
            changed.set()  # the window's work is not done: the next window tries again, `debounce_s` later

    threading.Thread(
        target=save_on_change, args=(stop, changed, store_list, debounce_s), name="pulls-stored", daemon=True
    ).start()
    return changed.set
