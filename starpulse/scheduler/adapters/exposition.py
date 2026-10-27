"""The autopilot's switch, run ledger and admission tally as Prometheus series on the server's `/metrics`.

Each is read from the store on every scrape, so a server that does not run the loop shows the same counts the loop
wrote there.
"""

from __future__ import annotations

from sqlalchemy import func, select

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import scheduler_runs
from starpulse.scheduler.adapters.loop import TALLY_KEY
from starpulse.scheduler.model.toggle import KEY as SWITCH_KEY


def autopilot_exposition(log: EventLog) -> str:
    """The four `starpulse_autopilot_*` series as exposition text."""
    with log.engine.connect() as db:
        runs = db.execute(select(func.count()).select_from(scheduler_runs)).scalar() or 0
    tally = log.state(TALLY_KEY)[1] or {}
    switched = log.setting_updated_at(SWITCH_KEY) or 0
    return "\n".join(
        [
            "# HELP starpulse_autopilot_enabled Whether the autopilot switch is on (1) or off (0).",
            "# TYPE starpulse_autopilot_enabled gauge",
            f"starpulse_autopilot_enabled {int(log.setting(SWITCH_KEY) is True)}",
            "# HELP starpulse_autopilot_switch_changed_timestamp_seconds Unix time the autopilot switch was last written.",
            "# TYPE starpulse_autopilot_switch_changed_timestamp_seconds gauge",
            f"starpulse_autopilot_switch_changed_timestamp_seconds {int(switched)}",
            "# HELP starpulse_autopilot_ledger_runs Rows in the StarPulse autopilot run ledger.",
            "# TYPE starpulse_autopilot_ledger_runs gauge",
            f"starpulse_autopilot_ledger_runs {runs}",
            "# HELP starpulse_autopilot_decisions_total Admission verdicts the autopilot has logged.",
            "# TYPE starpulse_autopilot_decisions_total counter",
            *(
                f'starpulse_autopilot_decisions_total{{verdict="{verdict}"}} {tally.get(verdict, 0)}'
                for verdict in ("admitted", "refused")
            ),
            "",
        ]
    )
