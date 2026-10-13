"""`starpulse serve` with its arguments, reporting every 30 seconds whether the serving process holds a GIL.

An extension module built without free-threading support turns the GIL back on when it is first imported, which a route
can do long after start-up, so the report repeats for the whole run rather than once at start.
"""

import sys
import threading
import time

from starpulse.__main__ import main


def _report() -> None:
    while True:
        time.sleep(30)
        print(f"gil_enabled={sys._is_gil_enabled()}", file=sys.stderr, flush=True)


threading.Thread(target=_report, daemon=True).start()
sys.argv = ["starpulse", "serve", *sys.argv[1:]]
sys.exit(main())
