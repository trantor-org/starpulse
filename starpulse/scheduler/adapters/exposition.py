"""The autopilot's switch, run ledger, admission tally and per-gate tally as Prometheus series on the server's `/metrics`.

Each is read from the store on every scrape, so a server that does not run the loop shows the same counts the loop
wrote there.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import scheduler_runs
from starpulse.scheduler.adapters.loop import GATE_TALLY_KEY, TALLY_KEY
from starpulse.scheduler.model.admission import GATES
from starpulse.scheduler.model.decision_log import EMPTY as EMPTY_DECISION_LOG
from starpulse.scheduler.model.decision_log import KEY as DECISION_LOG_KEY
from starpulse.scheduler.model.toggle import KEY as SWITCH_KEY


def autopilot_log(log: EventLog) -> dict[str, Any]:
    """The decision log the scheduler kept in the store: verdicts per local day, the starts and the first restore."""
    return log.state(DECISION_LOG_KEY)[1] or EMPTY_DECISION_LOG


def autopilot_exposition(log: EventLog) -> str:
    """The `starpulse_autopilot_*` series as exposition text."""
    with log.engine.connect() as db:
        runs = db.execute(select(func.count()).select_from(scheduler_runs)).scalar() or 0
    tally = log.state(TALLY_KEY)[1] or {}
    gate_tally = log.state(GATE_TALLY_KEY)[1] or {}
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
            "# HELP starpulse_autopilot_gate_decisions_total Tasks each admission gate passed (admitted) or bound on (refused).",
            "# TYPE starpulse_autopilot_gate_decisions_total counter",
            *(
                f'starpulse_autopilot_gate_decisions_total{{gate="{gate}",verdict="{verdict}"}} '
                f"{gate_tally.get(f'{gate}/{verdict}', 0)}"
                for gate in GATES
                for verdict in ("admitted", "refused")
            ),
            "",
        ]
    )
