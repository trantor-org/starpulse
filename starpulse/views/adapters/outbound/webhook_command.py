"""The command a `POST /api/webhook` hands its body to."""

from __future__ import annotations

import hmac
import subprocess
from collections.abc import Callable, Sequence

#: Seconds the command may take before the delivery fails and the sender retries it.
TIMEOUT_S = 30


def command_webhook(argv: Sequence[str], token: str) -> Callable[[str | None, bytes], tuple[int, dict]]:
    """A webhook that runs `argv` with the body on stdin once the bearer token matches: 202 on exit 0, else 502."""
    expected = f"Bearer {token}".encode()

    def webhook(authorization: str | None, raw: bytes) -> tuple[int, dict]:
        if not hmac.compare_digest((authorization or "").encode(), expected):
            return 401, {"error": "a bearer token is required"}
        try:
            proc = subprocess.run(list(argv), input=raw, capture_output=True, timeout=TIMEOUT_S, check=False)
        except subprocess.TimeoutExpired:
            return 502, {"error": f"the webhook command took over {TIMEOUT_S}s"}
        if proc.returncode == 0:
            return 202, {"accepted": True}
        return 502, {"error": f"webhook command exited {proc.returncode}: {proc.stderr.decode(errors='replace').strip()[-500:]}"}

    return webhook
