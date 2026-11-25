"""What the read-model followers read, as statements for `EventLog.run_on_wake`: no event announces a row the fold wrote, so
a follower of the folded rows reads their newest position, and the fold reads the events head too."""

from starpulse.event_log.readmodel.tables import machine_tasks, snapshot_deltas, tasks
from starpulse.event_log.signals import HEAD
from starpulse.event_log.store import NEWEST_EVENT

_TASKS = f"SELECT max(seq) FROM {tasks.name}"
_MACHINES = f"SELECT max(seq) FROM {machine_tasks.name}"

#: The folded task and machine rows a follower publishes changes of.
FOLDED_ROWS = f"SELECT ({_TASKS}), ({_MACHINES})"
#: The machine rows alone.
MACHINE_ROWS = _MACHINES
#: What the fold reads: the Task Events and the log's own events, where the machine events travel.
_TASK_EVENTS = NEWEST_EVENT
EVENTS = f"SELECT ({_TASK_EVENTS}), ({HEAD})"
#: The fold itself: the events it folds and the rows it publishes.
FOLD = f"SELECT ({_TASK_EVENTS}), ({HEAD}), ({_TASKS}), ({_MACHINES})"
#: The deltas the Board writer stored.
DELTAS = f"SELECT max(seq) FROM {snapshot_deltas.name}"
