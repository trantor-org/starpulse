"""The revision a PUT's `base` names, and the lock that makes its compare and its write one step."""

import hashlib
import json
import threading
from collections.abc import Mapping
from typing import Any

lock = threading.Lock()


def revised(record: Mapping[str, Any]) -> dict[str, Any]:
    """`record` with its `revision`: a hash of every field a write may change, so a PUT read before another write is stale."""
    digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:16]
    return {**record, "revision": digest}
