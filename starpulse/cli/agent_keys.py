"""The output keys each agent verb documents in `starpulse help --agent`, and the snapshot keys a server must answer."""

SNAPSHOT_KEYS = (
    "graphs",
    "flows",
    "dags",
    "pools",
    "pulls",
    "mergeStrip",
    "mergePins",
    "machineStrip",
    "claims",
    "settled",
    "move_sets",
    "milestone_done",
    "archived_today",
    "interactive",
    "roles",
    "error",
    "cues",
    "domains",
    "dashboards",
    "boardUrl",
    "capabilities",
    "reading",
    "now",
)

# What makes a document a StarPulse snapshot; any other key may come or go between releases.
SNAPSHOT_IDENTITY_KEYS = ("graphs", "flows", "machineStrip", "now")


TASK_KEYS = (
    "id",
    "key",
    "title",
    "lane",
    "phase",
    "substate",
    "unlinked",
    "skill",
    "interactive",
    "done_at",
    "profile",
    "assignee",
    "milestone",
    "type",
    "impact",
    "urgency",
    "labels",
    "dependencies",
    "waiting_on",
    "criteria",
    "pause_reason",
    "readable",
    "source",
    "prs",
    "moves",
    "released",
    "frozen",
    "members",
    "description",
)


MOVE_KEYS = ("ok", "task", "to", "reason", "skill", "advice")


DISPATCH_KEYS = ("ok", "task", "session", "reason", "skill")


LIFECYCLE_KEYS = ("ok", "task", "to", "reason", "skill")


MILESTONE_KEYS = ("id", "title", "outcome", "specs", "adrs", "retro", "description", "archived", "revision")


PULL_KEYS = (
    "repo",
    "number",
    "state",
    "isDraft",
    "mergeable",
    "baseRefName",
    "headRefOid",
    "body",
    "checks",
    "requiredChecks",
    "threads",
    "unresolvedThreads",
    "headRefName",
    "updatedAt",
    "mergedAt",
    "mergeSha",
    "fetchedAt",
    "files",
)


DOC_KEYS = ("id", "title", "type", "created_date", "updated_date", "path", "body", "archived", "revision")
