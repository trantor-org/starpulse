window.SNAP = {
 "now": 1790884705.3177073,
 "flows": {
  "board": {
   "name": "board",
   "machine": {
    "states": [
     {
      "id": "new",
      "name": "New",
      "initial": true,
      "final": false
     },
     {
      "id": "ready",
      "name": "Ready",
      "initial": false,
      "final": false
     },
     {
      "id": "waiting",
      "name": "Waiting",
      "initial": false,
      "final": false
     },
     {
      "id": "in_progress",
      "name": "In progress",
      "initial": false,
      "final": false
     },
     {
      "id": "review",
      "name": "Review",
      "initial": false,
      "final": false
     },
     {
      "id": "needs_attention",
      "name": "Needs attention",
      "initial": false,
      "final": false
     },
     {
      "id": "done",
      "name": "Done",
      "initial": false,
      "final": false
     },
     {
      "id": "completed",
      "name": "Completed",
      "initial": false,
      "final": true
     },
     {
      "id": "archived",
      "name": "Archived",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "new",
      "target": "ready",
      "event": "CREATE_READY"
     },
     {
      "source": "new",
      "target": "waiting",
      "event": "CREATE_WAITING"
     },
     {
      "source": "new",
      "target": "waiting",
      "event": "CREATE_WAITING_ON_DEPS"
     },
     {
      "source": "new",
      "target": "in_progress",
      "event": "CREATE_IN_PROGRESS"
     },
     {
      "source": "ready",
      "target": "in_progress",
      "event": "CLAIM"
     },
     {
      "source": "ready",
      "target": "waiting",
      "event": "WAIT_ON_DEPS"
     },
     {
      "source": "ready",
      "target": "waiting",
      "event": "CRITERIA_UNMET"
     },
     {
      "source": "ready",
      "target": "archived",
      "event": "ARCHIVE"
     },
     {
      "source": "waiting",
      "target": "waiting",
      "event": "DEP_RESOLVED"
     },
     {
      "source": "waiting",
      "target": "ready",
      "event": "DEPS_DONE"
     },
     {
      "source": "waiting",
      "target": "ready",
      "event": "CRITERIA_MET"
     },
     {
      "source": "waiting",
      "target": "in_progress",
      "event": "START_WAITING"
     },
     {
      "source": "waiting",
      "target": "archived",
      "event": "ARCHIVE"
     },
     {
      "source": "in_progress",
      "target": "waiting",
      "event": "PARK_ON_TASK"
     },
     {
      "source": "in_progress",
      "target": "waiting",
      "event": "PARK_ON_CRITERIA"
     },
     {
      "source": "in_progress",
      "target": "in_progress",
      "event": "PR_OPENED"
     },
     {
      "source": "in_progress",
      "target": "review",
      "event": "REVIEW"
     },
     {
      "source": "in_progress",
      "target": "done",
      "event": "FINALIZE"
     },
     {
      "source": "in_progress",
      "target": "needs_attention",
      "event": "DEFER"
     },
     {
      "source": "in_progress",
      "target": "archived",
      "event": "ARCHIVE"
     },
     {
      "source": "review",
      "target": "done",
      "event": "MERGED"
     },
     {
      "source": "review",
      "target": "in_progress",
      "event": "SEND_BACK"
     },
     {
      "source": "review",
      "target": "archived",
      "event": "ARCHIVE"
     },
     {
      "source": "needs_attention",
      "target": "ready",
      "event": "RESUME_READY"
     },
     {
      "source": "needs_attention",
      "target": "in_progress",
      "event": "RESUME"
     },
     {
      "source": "needs_attention",
      "target": "archived",
      "event": "ARCHIVE"
     },
     {
      "source": "done",
      "target": "completed",
      "event": "SWEEP"
     }
    ],
    "subflows": [
     {
      "state": "in_progress",
      "flow": "in-progress",
      "exits": {
       "review_recorded": "REVIEW",
       "needs_attention": "DEFER"
      },
      "parent": "board",
      "when": ""
     }
    ],
    "launches": {
     "nightly-audit": {
      "skill": "auditing-infrastructure",
      "flow": "auditing-infrastructure"
     },
     "weekly-code-audit": {
      "skill": "auditing-code",
      "flow": null
     },
     "board-autopilot": {
      "skill": "starting-tasks",
      "flow": "in-progress"
     },
     "alert-investigation": {
      "skill": "querying-observability",
      "flow": null
     },
     "dependency-update-investigation": {
      "skill": "investigating-dependency-updates",
      "flow": "dependency-update-investigation"
     },
     "skill-eval": {
      "skill": "running-skill-evals",
      "flow": "running-skill-evals"
     },
     "skill-optimize": {
      "skill": "running-skill-evals",
      "flow": "running-skill-evals"
     }
    },
    "writers": {
     "CREATE_READY": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py create"
      }
     ],
     "CREATE_WAITING": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py create"
      }
     ],
     "CREATE_WAITING_ON_DEPS": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py create"
      }
     ],
     "CREATE_IN_PROGRESS": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py create"
      },
      {
       "actor": "board-autopilot",
       "trigger": "find_or_create_task"
      }
     ],
     "CLAIM": [
      {
       "actor": "board-autopilot",
       "trigger": "bin/backlog_task.py dispatch"
      },
      {
       "actor": "agent",
       "trigger": "codex_task_lifecycle.claim_ready (start-prompt hook)"
      },
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py update --status \"In Progress\""
      }
     ],
     "WAIT_ON_DEPS": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py update --status Waiting"
      },
      {
       "actor": "board-autopilot",
       "trigger": "dependency sweep"
      }
     ],
     "PARK_ON_TASK": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py park --until-task"
      }
     ],
     "PARK_ON_CRITERIA": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py park --until"
      }
     ],
     "DEP_RESOLVED": [
      {
       "actor": "board-dependency-reconciliation",
       "trigger": "bin/board_dependency_promotion_dispatch.py"
      }
     ],
     "DEPS_DONE": [
      {
       "actor": "board-dependency-reconciliation",
       "trigger": "bin/board_dependency_reconciliation.py"
      }
     ],
     "CRITERIA_MET": [
      {
       "actor": "board-dependency-reconciliation",
       "trigger": "board_lanes.sync_start_criteria_lanes"
      }
     ],
     "CRITERIA_UNMET": [
      {
       "actor": "board-dependency-reconciliation",
       "trigger": "board_lanes.sync_start_criteria_lanes"
      }
     ],
     "START_WAITING": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py update --status \"In Progress\""
      }
     ],
     "PR_OPENED": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py update --add-ref"
      }
     ],
     "REVIEW": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py review"
      }
     ],
     "FINALIZE": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py finalize"
      }
     ],
     "DEFER": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py park --operator"
      },
      {
       "actor": "board-autopilot",
       "trigger": "board_lanes.defer"
      }
     ],
     "RESUME_READY": [
      {
       "actor": "operator",
       "trigger": "bin/backlog_task.py update --status Ready"
      }
     ],
     "RESUME": [
      {
       "actor": "operator",
       "trigger": "bin/backlog_task.py update --status \"In Progress\""
      }
     ],
     "MERGED": [
      {
       "actor": "main-follow",
       "trigger": "bin/board_reconcile_merged.py"
      }
     ],
     "SEND_BACK": [
      {
       "actor": "operator",
       "trigger": "bin/backlog_task.py update --status \"In Progress\""
      }
     ],
     "SWEEP": [
      {
       "actor": "backlog-sweep",
       "trigger": "bin/backlog_task.py sweep"
      }
     ],
     "ARCHIVE": [
      {
       "actor": "agent",
       "trigger": "bin/backlog_task.py archive"
      }
     ]
    },
    "dagActors": [
     "backlog-sweep",
     "board-autopilot",
     "board-dependency-reconciliation",
     "main-follow"
    ]
   },
   "agents": [
    {
     "id": "TASK-2205",
     "title": "Rename the demo fixture",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [
      "TASK-2199",
      "TASK-2204"
     ],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1779"
     ]
    },
    {
     "id": "TASK-2203",
     "title": "Harden the board snapshot",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-63",
      "size-3"
     ],
     "dependencies": [
      "TASK-2204",
      "TASK-2205",
      "TASK-2206"
     ],
     "prs": []
    },
    {
     "id": "TASK-2246",
     "title": "Simplify the review queue after a rebase",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "adr-needed",
      "kind-execute",
      "size-2"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1791"
     ]
    },
    {
     "id": "TASK-2239",
     "title": "Trim the alert rule",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1793"
     ]
    },
    {
     "id": "TASK-2150",
     "title": "Simplify the retry budget",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-diagnose",
      "size-2"
     ],
     "dependencies": [
      "TASK-2222"
     ],
     "prs": []
    },
    {
     "id": "TASK-2232",
     "title": "Retire the lint rule after a rebase",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1794"
     ]
    },
    {
     "id": "TASK-2237",
     "title": "Rename the export path",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1789"
     ]
    },
    {
     "id": "TASK-2233",
     "title": "Move the nightly run under load",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "board",
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/backlog.md/pull/24"
     ]
    },
    {
     "id": "TASK-2251",
     "title": "Harden the import check",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "ci",
      "dagu",
      "kind-diagnose",
      "size-3",
      "testing",
      "whole-repo-gate-2026-10-01"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1796"
     ]
    },
    {
     "id": "TASK-2253",
     "title": "Rename the lint rule with a test",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-67",
      "size-3"
     ],
     "dependencies": [
      "TASK-2254",
      "TASK-2255",
      "TASK-2256",
      "TASK-2257"
     ],
     "prs": []
    },
    {
     "id": "TASK-2234",
     "title": "Cache the sync worker on cold start",
     "state": "needs_attention",
     "model": "@agent-sonnet-high",
     "labels": [
      "board",
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2254",
     "title": "Wire the nightly run with a clear error",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "adr-needed",
      "kind-execute",
      "size-8"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1797"
     ]
    },
    {
     "id": "TASK-2236",
     "title": "Measure the migration step for new users",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1795"
     ]
    },
    {
     "id": "TASK-2255",
     "title": "Trim the sync worker in the sample repo",
     "state": "waiting",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-diagnose",
      "size-2"
     ],
     "dependencies": [
      "TASK-2254",
      "TASK-2257"
     ],
     "prs": []
    },
    {
     "id": "TASK-2256",
     "title": "Tune the cache layer without a restart",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "adr-needed",
      "kind-decide",
      "size-3"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2257",
     "title": "Audit the alert rule in one pass",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "adr-needed",
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2258",
     "title": "Add the config loader",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "board",
      "kind-execute",
      "size-2"
     ],
     "dependencies": [
      "TASK-2233"
     ],
     "prs": []
    },
    {
     "id": "TASK-1236",
     "title": "Document the sync worker",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3",
      "testing"
     ],
     "dependencies": [
      "TASK-1768",
      "TASK-2045",
      "TASK-2046",
      "TASK-2048"
     ],
     "prs": []
    },
    {
     "id": "TASK-1349",
     "title": "Split the release notes in one pass",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3",
      "testing"
     ],
     "dependencies": [
      "TASK-1768"
     ],
     "prs": []
    },
    {
     "id": "TASK-1489",
     "title": "Audit the alert rule",
     "state": "waiting",
     "model": "@agent-sonnet-medium",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-2",
      "skills"
     ],
     "dependencies": [
      "TASK-1470",
      "TASK-1486",
      "TASK-1488",
      "TASK-1813",
      "TASK-1814",
      "TASK-1823",
      "TASK-1878"
     ],
     "prs": []
    },
    {
     "id": "TASK-1566",
     "title": "Wire the config loader in one pass",
     "state": "waiting",
     "model": "@agent-sonnet-high",
     "labels": [
      "frigate",
      "kind-execute",
      "local-model",
      "size-5",
      "nas"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1672",
     "title": "Retire the alert rule with a clear error",
     "state": "in_progress",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1673",
     "title": "Move the release notes",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1674",
     "title": "Cache the review queue without a restart",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1675",
     "title": "Harden the card layout",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1676",
     "title": "Measure the health probe behind a flag",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1677",
     "title": "Rename the label filter",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1678",
     "title": "Wire the board snapshot after a rebase",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1679",
     "title": "Trim the import check after a rebase",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1680",
     "title": "Tune the search index under load",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1681",
     "title": "Audit the report page on cold start",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1682",
     "title": "Add the token scope for new users",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1683",
     "title": "Fix the session timer",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1684",
     "title": "Document the cache layer under load",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1685",
     "title": "Split the retry budget with a test",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1710",
     "title": "Wire the status badge for the demo",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [
      "TASK-1841",
      "TASK-1842"
     ],
     "prs": []
    },
    {
     "id": "TASK-1744",
     "title": "Tune the cache layer for new users",
     "state": "waiting",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2",
      "validation"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1355"
     ]
    },
    {
     "id": "TASK-1779",
     "title": "Fix the demo fixture in one pass",
     "state": "ready",
     "model": "@agent-sonnet-medium",
     "labels": [
      "agent-profile",
      "kind-execute",
      "size-2"
     ],
     "dependencies": [
      "TASK-1772",
      "TASK-1773",
      "TASK-1774",
      "TASK-1775",
      "TASK-1778"
     ],
     "prs": []
    },
    {
     "id": "TASK-1832",
     "title": "Retire the export path on cold start",
     "state": "waiting",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2",
      "validation"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1878",
     "title": "Simplify the label filter",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-3",
      "skill-eval"
     ],
     "dependencies": [
      "TASK-1823",
      "TASK-1876",
      "TASK-1877"
     ],
     "prs": []
    },
    {
     "id": "TASK-1882",
     "title": "Cache the release notes",
     "state": "waiting",
     "model": "@agent-sonnet-medium",
     "labels": [
      "host-a",
      "disk",
      "kind-execute",
      "size-2"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-1888",
     "title": "Tune the webhook handler in one pass",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-26",
      "size-3"
     ],
     "dependencies": [
      "TASK-1261",
      "TASK-1763",
      "TASK-2043"
     ],
     "prs": []
    },
    {
     "id": "TASK-1889",
     "title": "Audit the sync worker behind a flag",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-2",
      "size-3"
     ],
     "dependencies": [
      "TASK-1236",
      "TASK-1349",
      "TASK-2041",
      "TASK-2044",
      "TASK-2045",
      "TASK-2048",
      "TASK-2051",
      "TASK-2221"
     ],
     "prs": []
    },
    {
     "id": "TASK-1890",
     "title": "Add the report page",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-35",
      "size-3"
     ],
     "dependencies": [
      "TASK-1489",
      "TASK-1633",
      "TASK-1876",
      "TASK-1877",
      "TASK-1878",
      "TASK-1981",
      "TASK-2000",
      "TASK-2001",
      "TASK-2002",
      "TASK-2009",
      "TASK-2012",
      "TASK-2013",
      "TASK-2014",
      "TASK-2015",
      "TASK-2016",
      "TASK-2017",
      "TASK-2018",
      "TASK-2019",
      "TASK-2020",
      "TASK-2021",
      "TASK-2022",
      "TASK-2023",
      "TASK-2024"
     ],
     "prs": []
    },
    {
     "id": "TASK-1892",
     "title": "Document the export path",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-39",
      "size-3"
     ],
     "dependencies": [
      "TASK-1832"
     ],
     "prs": []
    },
    {
     "id": "TASK-1894",
     "title": "Simplify the alert rule on cold start",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-42",
      "size-3"
     ],
     "dependencies": [
      "TASK-1710",
      "TASK-1842"
     ],
     "prs": []
    },
    {
     "id": "TASK-1896",
     "title": "Retire the review queue after a rebase",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-44",
      "size-3"
     ],
     "dependencies": [
      "TASK-1672",
      "TASK-1673",
      "TASK-1674",
      "TASK-1675",
      "TASK-1676",
      "TASK-1677",
      "TASK-1678",
      "TASK-1679",
      "TASK-1680",
      "TASK-1681",
      "TASK-1682",
      "TASK-1683",
      "TASK-1684",
      "TASK-1685"
     ],
     "prs": []
    },
    {
     "id": "TASK-1899",
     "title": "Harden the label filter",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-47",
      "size-3"
     ],
     "dependencies": [
      "TASK-1752",
      "TASK-1753",
      "TASK-1755",
      "TASK-1938",
      "TASK-1939"
     ],
     "prs": []
    },
    {
     "id": "TASK-1901",
     "title": "Rename the import check",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-49",
      "size-3"
     ],
     "dependencies": [
      "TASK-1774",
      "TASK-1777",
      "TASK-1778",
      "TASK-1779",
      "TASK-1853"
     ],
     "prs": []
    },
    {
     "id": "TASK-1929",
     "title": "Move the lint rule in the sample repo",
     "state": "in_progress",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-52",
      "size-3"
     ],
     "dependencies": [
      "TASK-1930",
      "TASK-1931",
      "TASK-1932"
     ],
     "prs": []
    },
    {
     "id": "TASK-1948",
     "title": "Measure the cache layer",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-53",
      "size-3"
     ],
     "dependencies": [
      "TASK-1949",
      "TASK-1950",
      "TASK-1951",
      "TASK-1952",
      "TASK-1953",
      "TASK-1954",
      "TASK-1955",
      "TASK-1956",
      "TASK-1957",
      "TASK-1993",
      "TASK-2005",
      "TASK-2052",
      "TASK-2061",
      "TASK-2115"
     ],
     "prs": []
    },
    {
     "id": "TASK-1971",
     "title": "Fix the report page for new users",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-55",
      "size-3"
     ],
     "dependencies": [
      "TASK-1972",
      "TASK-1973",
      "TASK-1974",
      "TASK-1975",
      "TASK-1976",
      "TASK-1977",
      "TASK-1978",
      "TASK-2059"
     ],
     "prs": []
    },
    {
     "id": "TASK-1978",
     "title": "Cache the card layout in one pass",
     "state": "waiting",
     "model": "@agent-sonnet-high",
     "labels": [
      "adr-needed",
      "kind-diagnose",
      "size-1"
     ],
     "dependencies": [
      "TASK-2059"
     ],
     "prs": []
    },
    {
     "id": "TASK-2005",
     "title": "Split the health probe in the sample repo",
     "state": "waiting",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-mechanical",
      "size-1"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2009",
     "title": "Move the retry budget",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2012",
     "title": "Measure the sync worker behind a flag",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2013",
     "title": "Rename the report page for the demo",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2014",
     "title": "Wire the migration step without a restart",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2015",
     "title": "Trim the export path",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2016",
     "title": "Tune the review queue for large boards",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2017",
     "title": "Audit the card layout",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2018",
     "title": "Add the status badge for new users",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2019",
     "title": "Fix the label filter after a rebase",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2020",
     "title": "Document the board snapshot under load",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2021",
     "title": "Split the digest job",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2022",
     "title": "Simplify the demo fixture for new users",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2023",
     "title": "Verify the release notes",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2024",
     "title": "Retire the nightly run",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "evaluation",
      "kind-execute",
      "size-5",
      "skills"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2030",
     "title": "Wire the retry budget",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-57",
      "size-3"
     ],
     "dependencies": [
      "TASK-2031",
      "TASK-2032",
      "TASK-2033",
      "TASK-2088",
      "TASK-2089",
      "TASK-2094",
      "TASK-2111",
      "TASK-2114",
      "TASK-2135"
     ],
     "prs": []
    },
    {
     "id": "TASK-2042",
     "title": "Cache the digest job",
     "state": "waiting",
     "model": "@agent-sonnet-high",
     "labels": [
      "enrichment",
      "kind-execute",
      "rag",
      "size-5",
      "validation"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2043",
     "title": "Harden the demo fixture without a restart",
     "state": "waiting",
     "model": "@agent-sonnet-high",
     "labels": [
      "enrichment",
      "kind-execute",
      "rag",
      "size-5"
     ],
     "dependencies": [
      "TASK-2042"
     ],
     "prs": []
    },
    {
     "id": "TASK-2057",
     "title": "Move the config loader",
     "state": "needs_attention",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-41",
      "size-3"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2059",
     "title": "Harden the card layout",
     "state": "needs_attention",
     "model": "@agent-sonnet-high",
     "labels": [
      "adr-needed",
      "kind-diagnose",
      "size-2"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1643",
      "https://github.com/trantor-org/acme/pull/1647",
      "https://github.com/trantor-org/acme/pull/1682",
      "https://github.com/trantor-org/acme/pull/1685"
     ]
    },
    {
     "id": "TASK-2066",
     "title": "Add the token scope",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-58",
      "size-3"
     ],
     "dependencies": [
      "TASK-2067",
      "TASK-2068",
      "TASK-2069",
      "TASK-2070",
      "TASK-2071",
      "TASK-2072",
      "TASK-2073",
      "TASK-2075",
      "TASK-2076",
      "TASK-2077",
      "TASK-2078",
      "TASK-2079",
      "TASK-2080",
      "TASK-2081",
      "TASK-2082",
      "TASK-2083",
      "TASK-2084",
      "TASK-2085",
      "TASK-2086",
      "TASK-2087"
     ],
     "prs": []
    },
    {
     "id": "TASK-2086",
     "title": "Simplify the health probe in one pass",
     "state": "needs_attention",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2147",
     "title": "Fix the token scope in the sample repo",
     "state": "waiting",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2",
      "validation"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2163",
     "title": "Fix the demo fixture",
     "state": "in_progress",
     "model": "@agent-opus-medium",
     "labels": [
      "adr-needed",
      "kind-decide",
      "size-3"
     ],
     "dependencies": [
      "TASK-2156",
      "TASK-2162"
     ],
     "prs": []
    },
    {
     "id": "TASK-2164",
     "title": "Document the release notes with a clear error",
     "state": "waiting",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2"
     ],
     "dependencies": [
      "TASK-2157",
      "TASK-2159",
      "TASK-2160",
      "TASK-2161",
      "TASK-2162",
      "TASK-2163"
     ],
     "prs": []
    },
    {
     "id": "TASK-2172",
     "title": "Measure the lint rule under load",
     "state": "in_progress",
     "model": "",
     "labels": [
      "adr-needed",
      "kind-decide",
      "retrospective",
      "size-3"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2173",
     "title": "Rename the webhook handler on cold start",
     "state": "waiting",
     "model": "",
     "labels": [
      "kind-execute",
      "retrospective",
      "size-2"
     ],
     "dependencies": [
      "TASK-2172"
     ],
     "prs": []
    },
    {
     "id": "TASK-2176",
     "title": "Tune the alert rule under load",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-62",
      "size-3"
     ],
     "dependencies": [
      "TASK-2177",
      "TASK-2178",
      "TASK-2179",
      "TASK-2180",
      "TASK-2181",
      "TASK-2182",
      "TASK-2183"
     ],
     "prs": []
    },
    {
     "id": "TASK-2183",
     "title": "Verify the digest job for the demo",
     "state": "ready",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2"
     ],
     "dependencies": [
      "TASK-2179",
      "TASK-2182"
     ],
     "prs": []
    },
    {
     "id": "TASK-2198",
     "title": "Simplify the config loader for the demo",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [
      "TASK-2199"
     ],
     "prs": []
    },
    {
     "id": "TASK-2210",
     "title": "Add the retry budget with a test",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-64",
      "size-3"
     ],
     "dependencies": [
      "TASK-2211",
      "TASK-2212",
      "TASK-2213",
      "TASK-2214",
      "TASK-2215",
      "TASK-2216",
      "TASK-2217",
      "TASK-2218",
      "TASK-2247",
      "TASK-2248",
      "TASK-2249",
      "TASK-2250",
      "TASK-2287"
     ],
     "prs": []
    },
    {
     "id": "TASK-2213",
     "title": "Split the sync worker without a restart",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-1"
     ],
     "dependencies": [
      "TASK-2212"
     ],
     "prs": []
    },
    {
     "id": "TASK-2215",
     "title": "Verify the migration step behind a flag",
     "state": "in_progress",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [
      "TASK-2214"
     ],
     "prs": []
    },
    {
     "id": "TASK-2216",
     "title": "Retire the export path for the demo",
     "state": "waiting",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [
      "TASK-2212",
      "TASK-2214",
      "TASK-2215",
      "TASK-2247",
      "TASK-2248",
      "TASK-2249",
      "TASK-2250"
     ],
     "prs": []
    },
    {
     "id": "TASK-2217",
     "title": "Move the cache layer for new users",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [
      "TASK-2212"
     ],
     "prs": []
    },
    {
     "id": "TASK-2218",
     "title": "Cache the alert rule",
     "state": "waiting",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-1"
     ],
     "dependencies": [
      "TASK-2216",
      "TASK-2217"
     ],
     "prs": []
    },
    {
     "id": "TASK-2224",
     "title": "Tune the release notes",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [
      "TASK-2223"
     ],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1802"
     ]
    },
    {
     "id": "TASK-2225",
     "title": "Audit the review queue behind a flag",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [
      "TASK-2224"
     ],
     "prs": []
    },
    {
     "id": "TASK-2230",
     "title": "Simplify the import check",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2231",
     "title": "Verify the retry budget for the demo",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-1"
     ],
     "dependencies": [
      "TASK-2229"
     ],
     "prs": []
    },
    {
     "id": "TASK-2235",
     "title": "Harden the report page for new users",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-65",
      "size-3"
     ],
     "dependencies": [
      "TASK-2236",
      "TASK-2237",
      "TASK-2238",
      "TASK-2239",
      "TASK-2240",
      "TASK-2241",
      "TASK-2242",
      "TASK-2244"
     ],
     "prs": []
    },
    {
     "id": "TASK-2240",
     "title": "Tune the status badge with a clear error",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1798"
     ]
    },
    {
     "id": "TASK-2241",
     "title": "Audit the migration step without a restart",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1801"
     ]
    },
    {
     "id": "TASK-2244",
     "title": "Document the demo fixture behind a flag",
     "state": "ready",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2"
     ],
     "dependencies": [
      "TASK-2236"
     ],
     "prs": []
    },
    {
     "id": "TASK-2247",
     "title": "Verify the search index",
     "state": "needs_attention",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-diagnose",
      "size-2"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2248",
     "title": "Retire the health probe on cold start",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2249",
     "title": "Move the token scope on cold start",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [
      "TASK-2215"
     ],
     "prs": []
    },
    {
     "id": "TASK-2250",
     "title": "Cache the session timer for new users",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-3"
     ],
     "dependencies": [
      "TASK-2215"
     ],
     "prs": []
    },
    {
     "id": "TASK-2252",
     "title": "Measure the retry budget under load",
     "state": "needs_attention",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-mechanical",
      "size-1"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2259",
     "title": "Fix the webhook handler for the demo",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "adr-needed",
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2260",
     "title": "Document the card layout",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1803"
     ]
    },
    {
     "id": "TASK-2261",
     "title": "Split the status badge for large boards",
     "state": "review",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1807",
      "https://github.com/trantor-org/acme/pull/1816"
     ]
    },
    {
     "id": "TASK-2262",
     "title": "Simplify the label filter",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1805"
     ]
    },
    {
     "id": "TASK-2263",
     "title": "Verify the board snapshot on cold start",
     "state": "done",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-5"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/skills/pull/34"
     ]
    },
    {
     "id": "TASK-2264",
     "title": "Retire the digest job",
     "state": "ready",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-68",
      "size-3"
     ],
     "dependencies": [
      "TASK-2265",
      "TASK-2266",
      "TASK-2267",
      "TASK-2268",
      "TASK-2269"
     ],
     "prs": []
    },
    {
     "id": "TASK-2265",
     "title": "Move the demo fixture after a rebase",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1808"
     ]
    },
    {
     "id": "TASK-2266",
     "title": "Cache the release notes",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1809"
     ]
    },
    {
     "id": "TASK-2267",
     "title": "Harden the review queue with a test",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-mechanical",
      "size-1"
     ],
     "dependencies": [
      "TASK-2266"
     ],
     "prs": []
    },
    {
     "id": "TASK-2268",
     "title": "Measure the search index for new users",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-mechanical",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1810"
     ]
    },
    {
     "id": "TASK-2269",
     "title": "Rename the health probe with a clear error",
     "state": "done",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-execute",
      "size-2"
     ],
     "dependencies": [
      "TASK-2239"
     ],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1811"
     ]
    },
    {
     "id": "TASK-2270",
     "title": "Wire the token scope in the sample repo",
     "state": "done",
     "model": "@agent-sonnet-high",
     "labels": [
      "config-drift-auto",
      "kind-diagnose",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1817"
     ]
    },
    {
     "id": "TASK-2271",
     "title": "Trim the session timer in one pass",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5",
      "testing"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2272",
     "title": "Tune the nightly run",
     "state": "review",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1818"
     ]
    },
    {
     "id": "TASK-2273",
     "title": "Audit the sync worker",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2274",
     "title": "Add the report page without a restart",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-69",
      "size-3"
     ],
     "dependencies": [
      "TASK-2275",
      "TASK-2276",
      "TASK-2277",
      "TASK-2278",
      "TASK-2279",
      "TASK-2280",
      "TASK-2281",
      "TASK-2282",
      "TASK-2283",
      "TASK-2284"
     ],
     "prs": []
    },
    {
     "id": "TASK-2275",
     "title": "Fix the token scope after a rebase",
     "state": "review",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": [
      "https://github.com/trantor-org/acme/pull/1822"
     ]
    },
    {
     "id": "TASK-2276",
     "title": "Document the export path for large boards",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2277",
     "title": "Split the cache layer on cold start",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2278",
     "title": "Simplify the alert rule for the demo",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-3"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2279",
     "title": "Verify the config loader",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2280",
     "title": "Retire the webhook handler under load",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2281",
     "title": "Move the card layout",
     "state": "in_progress",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-execute",
      "size-5"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2282",
     "title": "Cache the status badge with a test",
     "state": "in_progress",
     "model": "@agent-sonnet-medium",
     "labels": [
      "kind-mechanical",
      "size-2"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2283",
     "title": "Harden the label filter for new users",
     "state": "waiting",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-diagnose",
      "size-2"
     ],
     "dependencies": [
      "TASK-2276"
     ],
     "prs": []
    },
    {
     "id": "TASK-2284",
     "title": "Measure the board snapshot in the sample repo",
     "state": "waiting",
     "model": "@agent-sonnet-high",
     "labels": [
      "kind-diagnose",
      "size-1"
     ],
     "dependencies": [
      "TASK-2277"
     ],
     "prs": []
    },
    {
     "id": "TASK-2285",
     "title": "Rename the digest job",
     "state": "ready",
     "model": "@agent-sonnet-high",
     "labels": [
      "ci",
      "dagu",
      "kind-diagnose",
      "size-3",
      "testing",
      "whole-repo-gate-2026-10-01"
     ],
     "dependencies": [],
     "prs": []
    },
    {
     "id": "TASK-2286",
     "title": "Wire the demo fixture with a test",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "retro-m-70",
      "size-3"
     ],
     "dependencies": [
      "TASK-2288"
     ],
     "prs": []
    },
    {
     "id": "TASK-2287",
     "title": "Trim the release notes",
     "state": "waiting",
     "model": "@agent-opus-medium",
     "labels": [
      "adr-needed",
      "kind-decide",
      "size-3"
     ],
     "dependencies": [
      "TASK-2215"
     ],
     "prs": []
    },
    {
     "id": "TASK-2288",
     "title": "Tune the label filter for the demo",
     "state": "in_progress",
     "model": "@agent-opus-medium",
     "labels": [
      "kind-decide",
      "size-3"
     ],
     "dependencies": [],
     "prs": []
    }
   ]
  },
  "in-progress": {
   "name": "in-progress",
   "machine": {
    "states": [
     {
      "id": "start",
      "name": "Start",
      "initial": true,
      "final": false
     },
     {
      "id": "worktree_ready",
      "name": "Worktree ready",
      "initial": false,
      "final": false
     },
     {
      "id": "red_proven",
      "name": "Red proven",
      "initial": false,
      "final": false
     },
     {
      "id": "green",
      "name": "Green",
      "initial": false,
      "final": false
     },
     {
      "id": "checkpointed",
      "name": "Checkpointed",
      "initial": false,
      "final": false
     },
     {
      "id": "docs_reconciled",
      "name": "Docs reconciled",
      "initial": false,
      "final": false
     },
     {
      "id": "lint_green",
      "name": "Lint green",
      "initial": false,
      "final": false
     },
     {
      "id": "committed",
      "name": "Committed",
      "initial": false,
      "final": false
     },
     {
      "id": "pushed",
      "name": "Pushed",
      "initial": false,
      "final": false
     },
     {
      "id": "pr_opened",
      "name": "Pr opened",
      "initial": false,
      "final": false
     },
     {
      "id": "ci_green",
      "name": "Ci green",
      "initial": false,
      "final": false
     },
     {
      "id": "pr_ready",
      "name": "Pr ready",
      "initial": false,
      "final": false
     },
     {
      "id": "review_recorded",
      "name": "Review recorded",
      "initial": false,
      "final": true
     },
     {
      "id": "needs_attention",
      "name": "Needs attention",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "start",
      "target": "worktree_ready",
      "event": "WORKTREE_READY"
     },
     {
      "source": "worktree_ready",
      "target": "red_proven",
      "event": "RED_PROVEN"
     },
     {
      "source": "worktree_ready",
      "target": "worktree_ready",
      "event": "RED_WRONG"
     },
     {
      "source": "worktree_ready",
      "target": "checkpointed",
      "event": "AC_CHECKPOINTED"
     },
     {
      "source": "red_proven",
      "target": "green",
      "event": "GREEN"
     },
     {
      "source": "green",
      "target": "red_proven",
      "event": "RED_PROVEN"
     },
     {
      "source": "green",
      "target": "green",
      "event": "GREEN"
     },
     {
      "source": "green",
      "target": "checkpointed",
      "event": "AC_CHECKPOINTED"
     },
     {
      "source": "checkpointed",
      "target": "red_proven",
      "event": "RED_PROVEN"
     },
     {
      "source": "checkpointed",
      "target": "checkpointed",
      "event": "AC_CHECKPOINTED"
     },
     {
      "source": "checkpointed",
      "target": "docs_reconciled",
      "event": "DOCS_RECONCILED"
     },
     {
      "source": "docs_reconciled",
      "target": "lint_green",
      "event": "LINT_GREEN"
     },
     {
      "source": "docs_reconciled",
      "target": "docs_reconciled",
      "event": "LINT_RED"
     },
     {
      "source": "lint_green",
      "target": "lint_green",
      "event": "LINT_GREEN"
     },
     {
      "source": "lint_green",
      "target": "committed",
      "event": "COMMITTED"
     },
     {
      "source": "committed",
      "target": "committed",
      "event": "LINT_RED"
     },
     {
      "source": "committed",
      "target": "pushed",
      "event": "PUSHED"
     },
     {
      "source": "pushed",
      "target": "pushed",
      "event": "LINT_RED"
     },
     {
      "source": "pushed",
      "target": "pr_opened",
      "event": "PR_OPENED"
     },
     {
      "source": "pr_opened",
      "target": "pr_opened",
      "event": "LINT_RED"
     },
     {
      "source": "pr_opened",
      "target": "pr_opened",
      "event": "COMMITTED"
     },
     {
      "source": "pr_opened",
      "target": "pr_opened",
      "event": "PUSHED"
     },
     {
      "source": "pr_opened",
      "target": "ci_green",
      "event": "CI_GREEN"
     },
     {
      "source": "pr_opened",
      "target": "pr_opened",
      "event": "CI_RED"
     },
     {
      "source": "pr_opened",
      "target": "needs_attention",
      "event": "CI_BLOCKED"
     },
     {
      "source": "ci_green",
      "target": "ci_green",
      "event": "PUSHED"
     },
     {
      "source": "ci_green",
      "target": "needs_attention",
      "event": "CI_BLOCKED"
     },
     {
      "source": "ci_green",
      "target": "pr_ready",
      "event": "PR_READY"
     },
     {
      "source": "pr_ready",
      "target": "review_recorded",
      "event": "REVIEW_RECORDED"
     }
    ],
    "subflows": [
     {
      "state": "pr_opened",
      "flow": "triaging-cr-reviews",
      "exits": {},
      "parent": "in-progress",
      "when": "a PR is open"
     }
    ]
   },
   "agents": [
    {
     "id": "f4cfdf0d-4309-4c51-b115-5bc7d2b1e395",
     "title": "Document the status badge after a rebase",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2086",
     "active": 1790882061.034,
     "state": "checkpointed",
     "steps": 4,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745274.899
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790747292.875
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790747294.996
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790747915.804
      }
     ]
    },
    {
     "id": "c9d16d54-9bb0-4097-aac9-d4b436d9f5ff",
     "title": "Move the release notes",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2227",
     "active": 1790881252.996,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834544.965
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834671.713
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834672.056
      }
     ]
    },
    {
     "id": "d858843a-255d-4945-9f98-e28479456db7",
     "title": "Harden the review queue for the demo",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2111",
     "active": 1790881991.627,
     "state": "pr_opened",
     "steps": 18,
     "trail": [
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790747823.677
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790747859.231
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790747920.78
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790747958.316
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790747996.777
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790748652.306
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790748659.557
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790748860.148
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790749051.391
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790749054.324
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790749842.189
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790749844.663
      }
     ]
    },
    {
     "id": "49944a3f-535a-52dc-8dfb-8b88480c906c",
     "title": "Retire the sync worker with a test",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2288",
     "active": 1790884704.956738,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790884542.717
      }
     ]
    },
    {
     "id": "d817221b-08f6-4260-9eb5-ee4a83504582",
     "title": "Split the lint rule for the demo",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2162",
     "active": 1790882635.367,
     "state": "pr_opened",
     "steps": 12,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790810661.222
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810785.19
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810950.101
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790811482.088
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790811565.426
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790811581.075
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790811643.49
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790811646.732
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790811659.37
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790833160.501
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790833163.872
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790833199.069
      }
     ]
    },
    {
     "id": "9f7cff54-04ae-5ad6-abe3-f7681e88b9f1",
     "title": "Move the release notes",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2246",
     "active": 1790869995.6350954,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790839387.657
      }
     ]
    },
    {
     "id": "7c7a6225-7799-499e-9e0f-c479dce9f9c4",
     "title": "Verify the digest job",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2226",
     "active": 1790881244.931,
     "state": "pr_opened",
     "steps": 9,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834458.889
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834495.778
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834503.367
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834503.656
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790834514.249
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790834516.991
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790834552.277
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790834554.403
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790834566.195
      }
     ]
    },
    {
     "id": "9ae2798b-46b8-41de-abd3-86f012b84406",
     "title": "Move the release notes",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2215",
     "active": 1790884610.8318298,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790883220.108
      }
     ]
    },
    {
     "id": "f034b5b3-be51-4af4-a8de-3e4fa5316ed8",
     "title": "Add the demo fixture",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2190",
     "active": 1790882567.84,
     "state": "pr_opened",
     "steps": 9,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790810584.529
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810648.148
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810648.831
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790810659.663
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790810662.496
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790810700.335
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790810740.747
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790810747.457
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790810757.289
      }
     ]
    },
    {
     "id": "5d140953-754a-4976-a454-31bc1fc2d53a",
     "title": "Split the migration step under load",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2220",
     "active": 1790882796.147,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790821607.61
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790821763.423
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790821764.166
      }
     ]
    },
    {
     "id": "357304f8-99ec-4320-803b-b8f3859105c5",
     "title": "Retire the config loader with a test",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2199",
     "active": 1790884208.216,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790801423.995
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790802216.988
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790802434.526
      }
     ]
    },
    {
     "id": "9842d0d8-48fb-49f1-81a2-b5a55f94a9b8",
     "title": "Add the digest job",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2205",
     "active": 1790882495.263,
     "state": "pr_opened",
     "steps": 22,
     "trail": [
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790836456.67
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790836532.669
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790837100.622
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790837103.907
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790837762.395
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790837970.201
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790837975.719
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790839404.236
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790839524.748
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790840337.258
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790840339.227
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790840899.795
      }
     ]
    },
    {
     "id": "93d07ac3-992d-4ca5-94ef-9de182893a36",
     "title": "Rename the health probe for the demo",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-1693",
     "active": 1790882981.773,
     "state": "pr_opened",
     "steps": 18,
     "trail": [
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790793978.815
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790794132.055
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790794150.335
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790794166.526
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790795458.269
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790795677.236
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790796137.914
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790796272.899
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790796582.521
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790796664.12
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790796912.775
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790797017.059
      }
     ]
    },
    {
     "id": "77bd0e4a-154c-45b4-a7b6-b640be6d3cdb",
     "title": "Rename the lint rule",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2120",
     "active": 1790882077.284,
     "state": "checkpointed",
     "steps": 4,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745316.365
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745953.211
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745954.062
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790746265.1
      }
     ]
    },
    {
     "id": "0a15c86d-8331-41a5-94e8-44474cea20ea",
     "title": "Tune the retry budget",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2219",
     "active": 1790882302.447,
     "state": "pr_opened",
     "steps": 9,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790810316.382
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810635.186
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810635.936
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810636.508
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790810649.561
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790810659.1
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790810710.043
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790810713.709
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790810733.997
      }
     ]
    },
    {
     "id": "cd904e59-9600-4130-9070-98c238fd9658",
     "title": "Retire the demo fixture in one pass",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2105",
     "active": 1790881927.413,
     "state": "docs_reconciled",
     "steps": 4,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745150.683
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745223.669
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745223.962
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790745223.969
      }
     ]
    },
    {
     "id": "9905f6b2-e0a1-4029-8820-93697d570040",
     "title": "Audit the review queue",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-1690",
     "active": 1790881872.358,
     "state": "pr_opened",
     "steps": 14,
     "trail": [
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745674.222
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790745742.894
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790745757.169
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790745859.667
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790745967.033
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790746155.979
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790746302.666
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790746305.531
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790746329.239
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790746766.404
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790746769.005
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790747431.614
      }
     ]
    },
    {
     "id": "3ebd9f58-aec2-45b0-a212-22973933892e",
     "title": "Fix the card layout",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2140",
     "active": 1790884355.856,
     "state": "pr_opened",
     "steps": 12,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790797967.951
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798146.559
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798147.202
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798148.011
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790798169.289
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790798179.027
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790798272.781
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790798310.252
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790798312.186
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790798323.112
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790798622.845
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790798625.149
      }
     ]
    },
    {
     "id": "020a25af-313a-466a-8936-7638d440985b",
     "title": "Document the cache layer under load",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2204",
     "active": 1790882002.122,
     "state": "pushed",
     "steps": 10,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790813666.805
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790813753.187
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790813753.97
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790814545.889
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790814565.176
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790814574.201
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790815321.59
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790815353.348
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790815385.258
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790815387.085
      }
     ]
    },
    {
     "id": "b1942b0a-bb8d-574c-ab36-edc65e8bed2a",
     "title": "Simplify the release notes for new users",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2150",
     "active": 1790870158.846,
     "state": "pr_opened",
     "steps": 11,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834126.373
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834548.92
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834550.696
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834552.0
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790834567.452
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790834609.443
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790834673.126
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790834680.647
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790834697.883
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790834961.243
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790834966.631
      }
     ]
    },
    {
     "id": "4e85eac0-aaf4-4a92-9c53-b9c1d8eb0850",
     "title": "Document the status badge after a rebase",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2188",
     "active": 1790884178.764,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790801391.069
      }
     ]
    },
    {
     "id": "a1a3e5e6-09ed-4192-934f-e42aeaa7fbe5",
     "title": "Audit the config loader",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2098",
     "active": 1790883420.749,
     "state": "docs_reconciled",
     "steps": 6,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790797801.197
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798069.712
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798071.115
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790798093.117
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790798097.799
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790798170.154
      }
     ]
    },
    {
     "id": "082e3162-6020-4e54-8a6b-16691c1ea8de",
     "title": "Add the config loader on cold start",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-1695",
     "active": 1790883020.962,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790793035.618
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790793207.669
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790793208.524
      }
     ]
    },
    {
     "id": "ff00d8c6-5e21-4846-8b03-5ac84b6f623e",
     "title": "Tune the retry budget",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2228",
     "active": 1790881262.143,
     "state": "pr_opened",
     "steps": 8,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834475.867
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834598.628
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834599.529
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790834611.657
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790834612.023
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790834657.419
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790834659.663
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790834671.567
      }
     ]
    },
    {
     "id": "81e6f566-2b38-497d-8a13-06de6eaa5cfc",
     "title": "Audit the retry budget under load",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2270",
     "active": 1790882653.67431,
     "state": "checkpointed",
     "steps": 2,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790881453.871
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790882321.796
      }
     ]
    },
    {
     "id": "943d9ad3-745d-52b6-825b-b5e9ce827c86",
     "title": "Trim the label filter on cold start",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2172",
     "active": 1790870158.931,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790836318.279
      }
     ]
    },
    {
     "id": "6764de40-d782-4e16-93d9-6918216725be",
     "title": "Measure the session timer for large boards",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2251",
     "active": 1790881746.17,
     "state": "checkpointed",
     "steps": 2,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790871009.923
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790871080.782
      }
     ]
    },
    {
     "id": "0a354100-d157-47f4-a7a3-41647eaaa0d5",
     "title": "Tune the retry budget",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2142",
     "active": 1790884406.361,
     "state": "docs_reconciled",
     "steps": 6,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790798022.267
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798223.393
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798224.553
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798225.52
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790798239.989
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790798272.166
      }
     ]
    },
    {
     "id": "30e39189-b5d9-4a3b-8970-c24913b65c34",
     "title": "Wire the release notes",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2273",
     "active": 1790884482.057773,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790881707.889
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790883352.368
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790883353.014
      }
     ]
    },
    {
     "id": "a2864ff8-fd12-4c10-83e6-80f58d80d002",
     "title": "Tune the lint rule for new users",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2144",
     "active": 1790884506.691,
     "state": "docs_reconciled",
     "steps": 11,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790798120.647
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798378.48
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798664.69
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790798669.998
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790798814.426
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790798879.076
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790798939.482
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790798988.612
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790799036.838
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790799040.713
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790799430.568
      }
     ]
    },
    {
     "id": "949b015c-e1e7-4777-bfdf-bf803a07a3a2",
     "title": "Split the session timer",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2248",
     "active": 1790884581.1677861,
     "state": "docs_reconciled",
     "steps": 6,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790883366.372
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790883762.295
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790883924.604
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790884003.635
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790884543.206
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790884556.374
      }
     ]
    },
    {
     "id": "d69ee0fb-8ede-4102-a353-764a7b7a922f",
     "title": "Split the release notes for new users",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2178",
     "active": 1790884578.259,
     "state": "checkpointed",
     "steps": 5,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790798215.762
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790799863.292
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790800009.241
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790801917.686
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790801918.721
      }
     ]
    },
    {
     "id": "a84fd2af-9610-4405-b232-5511739bad39",
     "title": "Document the card layout after a rebase",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2156",
     "active": 1790883863.395,
     "state": "pr_opened",
     "steps": 11,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790793904.415
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790794103.666
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790794211.326
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790794217.939
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790794226.703
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790794283.728
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790794429.943
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790794432.333
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790794448.7
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790794662.823
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790794721.09
      }
     ]
    },
    {
     "id": "8df0b610-f495-4557-8478-7e8d8faa9910",
     "title": "Retire the demo fixture for new users",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2145",
     "active": 1790884517.117,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790798130.995
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798292.478
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798293.335
      }
     ]
    },
    {
     "id": "0868ac05-8003-44ff-aef1-1a3464d3d1fd",
     "title": "Document the session timer for new users",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2179",
     "active": 1790883281.683,
     "state": "pushed",
     "steps": 8,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790804102.414
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790805180.099
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790805180.693
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790805352.505
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790805458.939
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790806355.112
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790806390.014
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790806392.406
      }
     ]
    },
    {
     "id": "527046c2-7310-4cf1-a309-ac294268d909",
     "title": "Simplify the webhook handler for large boards",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2088",
     "active": 1790882020.188,
     "state": "pr_opened",
     "steps": 9,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745236.13
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790746421.785
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790749056.664
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790751825.87
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790751876.184
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790752030.405
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790752050.25
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790752113.44
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790752113.692
      }
     ]
    },
    {
     "id": "84239d9e-d44d-57ff-8e8f-ca3c05664209",
     "title": "Trim the digest job with a test",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2272",
     "active": 1790883625.561086,
     "state": "pr_opened",
     "steps": 18,
     "trail": [
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790881723.16
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790881832.431
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790881923.632
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790882143.711
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790882199.819
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790882203.126
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790882222.519
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790882455.548
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790882459.215
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790882462.14
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790883057.224
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790883057.677
      }
     ]
    },
    {
     "id": "f926cc09-776d-4af7-8fb7-47a1c73d6d11",
     "title": "Wire the release notes after a rebase",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2247",
     "active": 1790884580.3050802,
     "state": "pushed",
     "steps": 6,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790883337.172
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790884171.888
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790884209.449
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790884212.36
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790884447.342
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790884450.778
      }
     ]
    },
    {
     "id": "f2be7aa7-bf16-449b-bc50-efe0944be8f8",
     "title": "Add the webhook handler on cold start",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2122",
     "active": 1790882088.189,
     "state": "pr_opened",
     "steps": 18,
     "trail": [
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790746733.58
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790746758.131
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790746779.769
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790749315.381
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790749319.791
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790750433.074
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790750581.338
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790750588.739
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790751634.657
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790751659.846
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790752729.621
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790752750.539
      }
     ]
    },
    {
     "id": "20339c74-ed17-4fa0-9245-b870c1ad0e84",
     "title": "Fix the demo fixture",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2175",
     "active": 1790881270.827,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790791286.159
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790791613.959
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790791614.468
      }
     ]
    },
    {
     "id": "715454fe-81e9-5ca1-a249-3a15d28d61ca",
     "title": "Wire the digest job",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2259",
     "active": 1790877865.7764812,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790874131.772
      }
     ]
    },
    {
     "id": "25ae17b9-3e82-58fc-9ccd-58cacca249c7",
     "title": "Move the status badge with a test",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2261",
     "active": 1790883028.1259863,
     "state": "pr_opened",
     "steps": 21,
     "trail": [
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790878777.068
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790879312.313
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790879315.285
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790879753.228
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790879756.154
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790881504.98
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790881691.755
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790881695.621
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790881706.675
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790882565.639
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790882569.013
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790882571.459
      }
     ]
    },
    {
     "id": "ceda72ad-c345-4f70-9df1-0f07c2ca5bd8",
     "title": "Retire the health probe in one pass",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2087",
     "active": 1790882068.657,
     "state": "checkpointed",
     "steps": 2,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745338.698
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745591.045
      }
     ]
    },
    {
     "id": "06ed0490-0a40-5b3e-89dc-0dc2db85e7f0",
     "title": "Simplify the board snapshot on cold start",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2239",
     "active": 1790873867.251008,
     "state": "pr_opened",
     "steps": 10,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790836665.447
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837052.507
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837349.918
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837351.423
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790837397.074
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790837420.602
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790837476.657
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790837476.926
      },
      {
       "state": "pushed",
       "event": "LINT_RED",
       "at": 1790837760.068
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790838019.904
      }
     ]
    },
    {
     "id": "b6698a95-c49b-4ce0-bebe-79cb78df6941",
     "title": "Cache the demo fixture",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2257",
     "active": 1790884277.4057782,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790883420.081
      }
     ]
    },
    {
     "id": "a368b035-4ed6-4a12-9949-e48ef5ac1674",
     "title": "Tune the migration step",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2106",
     "active": 1790881934.883,
     "state": "docs_reconciled",
     "steps": 5,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745152.872
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745809.808
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745810.999
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790746056.68
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790746111.377
      }
     ]
    },
    {
     "id": "206a294c-b2df-44d8-b1e0-ad53a3ea8c09",
     "title": "Wire the webhook handler for new users",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2232",
     "active": 1790881225.018,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790870437.706
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790870791.086
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790871025.929
      }
     ]
    },
    {
     "id": "73dae332-fcca-4e72-9f81-1e7fa301ebb4",
     "title": "Move the label filter behind a flag",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2181",
     "active": 1790882693.748,
     "state": "pushed",
     "steps": 8,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790810706.25
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790833753.001
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790833753.595
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790833772.813
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790834290.972
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790834335.944
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790834400.836
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790834420.635
      }
     ]
    },
    {
     "id": "e4fa4733-1218-4ff5-9f06-aa0a964968c0",
     "title": "Document the status badge after a rebase",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2160",
     "active": 1790884675.672,
     "state": "docs_reconciled",
     "steps": 5,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834307.085
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834402.648
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790835002.483
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790835670.219
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790835743.772
      }
     ]
    },
    {
     "id": "37592927-87f9-4266-a5cd-f8910fbc98f6",
     "title": "Trim the board snapshot",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2180",
     "active": 1790883272.963,
     "state": "pushed",
     "steps": 12,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790804103.016
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790805708.978
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790805710.183
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790805710.881
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790805725.855
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790805751.52
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790805836.142
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790806407.516
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790806409.482
      },
      {
       "state": "pushed",
       "event": "LINT_RED",
       "at": 1790807610.214
      },
      {
       "state": "pushed",
       "event": "LINT_RED",
       "at": 1790808439.239
      },
      {
       "state": "pushed",
       "event": "LINT_RED",
       "at": 1790809429.646
      }
     ]
    },
    {
     "id": "f830e475-78d8-4873-a96a-05491b9cb7c9",
     "title": "Wire the cache layer behind a flag",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2234",
     "active": 1790881782.903,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790870994.107
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790871144.266
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790871727.949
      }
     ]
    },
    {
     "id": "20173dc2-220f-4b32-b89f-d0c20272fa38",
     "title": "Rename the release notes under load",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-1700",
     "active": 1790883083.421,
     "state": "pr_opened",
     "steps": 11,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790793102.188
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790793314.176
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790793320.15
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790793348.784
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790793395.164
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790793486.968
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790793511.336
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790793561.822
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790793564.448
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790793596.007
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790793832.168
      }
     ]
    },
    {
     "id": "306aa7cc-c8ba-439d-98e7-c0bfa9d81f43",
     "title": "Add the sync worker for the demo",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2193",
     "active": 1790882661.582,
     "state": "pr_opened",
     "steps": 11,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790810722.753
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790811115.485
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790811130.141
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790811160.872
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790811217.07
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790811267.746
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790811281.92
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790811302.729
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790811696.747
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790811877.086
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790811880.511
      }
     ]
    },
    {
     "id": "9516f987-e1b9-4fbf-91e7-d9162e7fb9bc",
     "title": "Measure the webhook handler after a rebase",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2124",
     "active": 1790881847.29,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745062.556
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745786.347
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745786.741
      }
     ]
    },
    {
     "id": "46b6393c-c7af-4720-808a-f57fa6dfac64",
     "title": "Wire the status badge for the demo",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2186",
     "active": 1790883376.68,
     "state": "docs_reconciled",
     "steps": 6,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790796990.192
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790797436.802
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790797442.063
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790797447.418
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790797461.332
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790797477.27
      }
     ]
    },
    {
     "id": "f07db94a-bf59-44cf-895e-2da9f8317559",
     "title": "Verify the digest job",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2185",
     "active": 1790882546.846,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790792564.623
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790792841.485
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790792842.765
      }
     ]
    },
    {
     "id": "a3e93b9a-2f59-4d9e-a8ae-c104c8060759",
     "title": "Fix the card layout",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2212",
     "active": 1790882495.219,
     "state": "pr_opened",
     "steps": 16,
     "trail": [
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790835937.948
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790835954.736
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790836078.34
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790836207.391
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790836423.204
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790836462.617
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790836479.961
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790837191.297
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790837198.69
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790837758.687
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790837929.205
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790837990.916
      }
     ]
    },
    {
     "id": "1d041253-6c68-58f9-bd01-f4fa8f5c35ee",
     "title": "Audit the config loader",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2271",
     "active": 1790883497.494469,
     "state": "pr_opened",
     "steps": 13,
     "trail": [
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790877856.992
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790877863.485
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790877972.597
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790878015.092
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790878076.014
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790878087.285
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790878112.344
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790881320.147
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790881320.499
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790883417.238
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790883421.219
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790883422.174
      }
     ]
    },
    {
     "id": "5cbfe1a9-8ebd-4dcc-9f75-e9b3e3d7b292",
     "title": "Split the migration step under load",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-1691",
     "active": 1790881879.458,
     "state": "pr_opened",
     "steps": 10,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745094.113
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745396.121
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745567.925
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790745711.862
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790745724.226
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790745930.428
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790745933.057
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790745958.627
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790746582.416
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790746585.739
      }
     ]
    },
    {
     "id": "ee68ac54-7cd3-490c-a880-208ce697ad85",
     "title": "Document the alert rule",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2163",
     "active": 1790884705.1987326,
     "state": "pr_opened",
     "steps": 10,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790881654.521
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790882018.771
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790882025.266
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790882623.65
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790882627.391
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790883000.395
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790883321.166
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790883349.502
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790883399.332
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790883432.905
      }
     ]
    },
    {
     "id": "56bd324b-b15a-425b-a0de-598a98f1c9fd",
     "title": "Retire the lint rule",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2275",
     "active": 1790884583.2894506,
     "state": "lint_green",
     "steps": 8,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790878269.494
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790878539.616
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790879875.274
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790883509.376
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790883652.581
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790883758.394
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790884177.896
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790884337.445
      }
     ]
    },
    {
     "id": "986cdc56-fbdd-4575-b2a5-b5ddbb877aae",
     "title": "Cache the release notes on cold start",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2217",
     "active": 1790884489.8135371,
     "state": "checkpointed",
     "steps": 2,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790883327.564
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790883721.74
      }
     ]
    },
    {
     "id": "90bc40b9-3002-4fd6-9ede-c70986d09094",
     "title": "Cache the release notes in one pass",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2194",
     "active": 1790881399.211,
     "state": "checkpointed",
     "steps": 4,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834611.856
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834809.765
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834810.283
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834810.883
      }
     ]
    },
    {
     "id": "56bf027d-0c9d-4724-b397-ed4ec9082150",
     "title": "Retire the lint rule",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2214",
     "active": 1790882495.516,
     "state": "pr_opened",
     "steps": 17,
     "trail": [
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790835543.226
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790835645.027
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790835649.326
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790836609.058
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790836836.006
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790836849.263
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790836876.18
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790837441.756
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790837645.282
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790837664.544
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790839427.011
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790839441.029
      }
     ]
    },
    {
     "id": "5a211f7b-7b06-4649-8818-2b60e86747e1",
     "title": "Split the migration step under load",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2166",
     "active": 1790881471.398,
     "state": "checkpointed",
     "steps": 2,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790833720.459
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790833749.718
      }
     ]
    },
    {
     "id": "e360da6c-cd72-4bed-ae3a-982b9c13451c",
     "title": "Retire the nightly run under load",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-1696",
     "active": 1790883064.341,
     "state": "pr_opened",
     "steps": 15,
     "trail": [
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790793573.89
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790793682.134
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790794031.584
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790794035.431
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790794125.568
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790794720.706
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790794720.787
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790795121.898
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790795122.019
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790795415.432
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790795477.618
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790795477.727
      }
     ]
    },
    {
     "id": "136888a9-8b7e-5e11-8dd9-2067bd7bfb5e",
     "title": "Retire the release notes",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2262",
     "active": 1790883061.6123948,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790877296.315
      }
     ]
    },
    {
     "id": "9ea0b248-1753-4007-ac98-b2bd1811106d",
     "title": "Move the release notes",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2245",
     "active": 1790882495.784,
     "state": "pushed",
     "steps": 8,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790836847.953
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837100.628
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837101.721
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790837120.112
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790837712.772
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790837846.794
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790837908.398
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790837911.364
      }
     ]
    },
    {
     "id": "7055ab41-c3ea-45b2-84c8-cd97dac7f7bc",
     "title": "Trim the cache layer for the demo",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2161",
     "active": 1790884692.966,
     "state": "docs_reconciled",
     "steps": 4,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834349.647
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834450.641
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837391.554
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790837406.011
      }
     ]
    },
    {
     "id": "de81b1cd-e3d6-41b3-a7de-55c9fb6f90bf",
     "title": "Audit the retry budget under load",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2123",
     "active": 1790882097.885,
     "state": "checkpointed",
     "steps": 4,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745353.842
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790746029.745
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790746030.334
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790746522.351
      }
     ]
    },
    {
     "id": "7439a05f-3b29-59d4-aa5a-4f2cd7330e91",
     "title": "Trim the cache layer",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2260",
     "active": 1790877648.772625,
     "state": "worktree_ready",
     "steps": 1,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790874644.802
      }
     ]
    },
    {
     "id": "39508486-1b80-4ea6-9335-9fd86c28f255",
     "title": "Simplify the export path for the demo",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2224",
     "active": 1790881510.175,
     "state": "pr_opened",
     "steps": 10,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790874324.839
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790874484.076
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790874510.029
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790874510.135
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790874540.727
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790874647.659
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790874670.435
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790874691.569
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790875367.216
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790875369.042
      }
     ]
    },
    {
     "id": "f20666ef-a23b-5661-9711-4ad28ac42380",
     "title": "Cache the search index with a test",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2221",
     "active": 1790870158.9434,
     "state": "checkpointed",
     "steps": 4,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790833510.143
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834045.877
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834046.54
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834047.061
      }
     ]
    },
    {
     "id": "1a456f2d-a1e9-4b66-8562-9eb71eac4966",
     "title": "Audit the config loader",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2225",
     "active": 1790884702.8147852,
     "state": "pr_opened",
     "steps": 11,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790881486.045
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790882050.201
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790882080.133
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790882152.731
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790882206.461
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790882254.963
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790882540.244
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790882544.307
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790882653.226
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790883438.529
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790883441.389
      }
     ]
    },
    {
     "id": "c85f372d-b3c4-4c82-aebb-9ad4643ab266",
     "title": "Split the status badge",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2206",
     "active": 1790882495.583,
     "state": "pr_opened",
     "steps": 21,
     "trail": [
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790837062.216
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790837309.624
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790837516.453
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790837905.827
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790837909.108
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790837924.54
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790839317.734
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790839324.502
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790839350.276
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790839546.777
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790839550.839
      },
      {
       "state": "pr_opened",
       "event": "LINT_RED",
       "at": 1790839617.312
      }
     ]
    },
    {
     "id": "bbffb77f-f1f0-4e2c-a7a5-77f8e66a635c",
     "title": "Rename the lint rule",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-1694",
     "active": 1790882994.569,
     "state": "pr_opened",
     "steps": 11,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790793029.398
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790793411.657
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790793717.795
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790793789.876
      },
      {
       "state": "docs_reconciled",
       "event": "LINT_RED",
       "at": 1790793848.952
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790793949.464
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790794073.938
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790794134.275
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790794154.42
      },
      {
       "state": "pr_opened",
       "event": "COMMITTED",
       "at": 1790794898.284
      },
      {
       "state": "pr_opened",
       "event": "PUSHED",
       "at": 1790794900.92
      }
     ]
    },
    {
     "id": "0495bae2-209b-468c-b75c-b1ff37285a45",
     "title": "Trim the release notes",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2229",
     "active": 1790881271.391,
     "state": "pr_opened",
     "steps": 7,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834488.397
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834610.068
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790834617.559
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790834627.64
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790834708.354
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790834711.243
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790834730.512
      }
     ]
    },
    {
     "id": "4315b304-5a43-5b3a-b36c-2b4c736b79e9",
     "title": "Harden the review queue with a test",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2243",
     "active": 1790870158.879,
     "state": "checkpointed",
     "steps": 4,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790836562.379
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837315.328
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837316.335
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790837341.168
      }
     ]
    },
    {
     "id": "501e8107-7df1-4b98-bc6a-2f4a70eec493",
     "title": "Split the nightly run",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2159",
     "active": 1790882597.038,
     "state": "pr_opened",
     "steps": 9,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790810624.197
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810846.085
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810847.087
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790833038.146
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790833053.335
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790833095.91
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790833110.188
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790833113.351
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790833129.907
      }
     ]
    },
    {
     "id": "c092e86d-ec42-4353-ad1f-3aaf9318e39a",
     "title": "Measure the search index",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2182",
     "active": 1790882496.236,
     "state": "lint_green",
     "steps": 7,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834647.278
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834781.641
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834782.389
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790835001.97
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790835241.149
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790835252.15
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790839313.974
      }
     ]
    },
    {
     "id": "201dc0e6-3472-4c48-bef2-b9aca26495fe",
     "title": "Move the token scope",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2223",
     "active": 1790881235.648,
     "state": "pr_opened",
     "steps": 9,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790834445.618
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834585.797
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834586.644
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790834587.391
      },
      {
       "state": "docs_reconciled",
       "event": "DOCS_RECONCILED",
       "at": 1790834601.076
      },
      {
       "state": "lint_green",
       "event": "LINT_GREEN",
       "at": 1790834608.057
      },
      {
       "state": "committed",
       "event": "COMMITTED",
       "at": 1790834670.322
      },
      {
       "state": "pushed",
       "event": "PUSHED",
       "at": 1790834673.545
      },
      {
       "state": "pr_opened",
       "event": "PR_OPENED",
       "at": 1790834687.946
      }
     ]
    },
    {
     "id": "d7c168bd-7a52-45cc-abef-43c75cf4ea90",
     "title": "Verify the digest job",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2143",
     "active": 1790884431.917,
     "state": "checkpointed",
     "steps": 3,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790798084.669
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798823.19
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790798824.945
      }
     ]
    },
    {
     "id": "a116d33c-1278-4dc0-9b80-ea50489134fd",
     "title": "Document the lint rule for new users",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2033",
     "active": 1790882044.875,
     "state": "checkpointed",
     "steps": 5,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790745268.194
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745724.614
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745725.793
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790745726.749
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790747144.425
      }
     ]
    },
    {
     "id": "5b9e678c-5d00-574b-9d51-430110ed6345",
     "title": "Split the migration step under load",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2254",
     "active": 1790874099.792554,
     "state": "checkpointed",
     "steps": 2,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790871102.226
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790872109.047
      }
     ]
    },
    {
     "id": "39fa9de7-2de4-479d-899a-c83abbc7e75b",
     "title": "Verify the token scope in one pass",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2189",
     "active": 1790882558.09,
     "state": "checkpointed",
     "steps": 5,
     "trail": [
      {
       "state": "worktree_ready",
       "event": "WORKTREE_READY",
       "at": 1790810570.569
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810628.184
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810635.696
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810642.342
      },
      {
       "state": "checkpointed",
       "event": "AC_CHECKPOINTED",
       "at": 1790810806.475
      }
     ]
    }
   ]
  },
  "triaging-cr-reviews": {
   "name": "triaging-cr-reviews",
   "machine": {
    "states": [
     {
      "id": "start",
      "name": "Start",
      "initial": true,
      "final": false
     },
     {
      "id": "audit_active",
      "name": "Audit active",
      "initial": false,
      "final": false
     },
     {
      "id": "dismissal_replied",
      "name": "Dismissal replied",
      "initial": false,
      "final": false
     },
     {
      "id": "audit_recorded",
      "name": "Audit recorded",
      "initial": false,
      "final": false
     },
     {
      "id": "approval_requested",
      "name": "Approval requested",
      "initial": false,
      "final": true
     },
     {
      "id": "fix_verified",
      "name": "Fix verified",
      "initial": false,
      "final": false
     },
     {
      "id": "fix_replied",
      "name": "Fix replied",
      "initial": false,
      "final": false
     },
     {
      "id": "completed",
      "name": "Completed",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "start",
      "target": "audit_active",
      "event": "AUDIT_STARTED"
     },
     {
      "source": "start",
      "target": "fix_verified",
      "event": "FIX_VERIFIED"
     },
     {
      "source": "start",
      "target": "completed",
      "event": "TASK_COMPLETED"
     },
     {
      "source": "audit_active",
      "target": "audit_active",
      "event": "REVIEW_QUERIED"
     },
     {
      "source": "audit_active",
      "target": "dismissal_replied",
      "event": "DISMISSAL_REPLIED"
     },
     {
      "source": "audit_active",
      "target": "audit_active",
      "event": "DISMISSAL_RESOLVED"
     },
     {
      "source": "audit_active",
      "target": "audit_recorded",
      "event": "AUDIT_RECORDED"
     },
     {
      "source": "dismissal_replied",
      "target": "audit_active",
      "event": "DISMISSAL_RESOLVED"
     },
     {
      "source": "audit_recorded",
      "target": "approval_requested",
      "event": "APPROVAL_REQUESTED"
     },
     {
      "source": "fix_verified",
      "target": "fix_replied",
      "event": "FIX_THREAD_REPLIED"
     },
     {
      "source": "fix_verified",
      "target": "start",
      "event": "FIX_THREAD_RESOLVED"
     },
     {
      "source": "fix_replied",
      "target": "start",
      "event": "FIX_THREAD_RESOLVED"
     }
    ]
   },
   "agents": []
  },
  "auditing-docs": {
   "name": "auditing-docs",
   "machine": {
    "states": [
     {
      "id": "start",
      "name": "Start",
      "initial": true,
      "final": false
     },
     {
      "id": "reading",
      "name": "Reading",
      "initial": false,
      "final": false
     },
     {
      "id": "reader_tested",
      "name": "Reader tested",
      "initial": false,
      "final": false
     },
     {
      "id": "passages_classified",
      "name": "Passages classified",
      "initial": false,
      "final": false
     },
     {
      "id": "reported",
      "name": "Reported",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "start",
      "target": "reading",
      "event": "AUDIT_STARTED"
     },
     {
      "source": "reading",
      "target": "reading",
      "event": "DOCUMENT_READ"
     },
     {
      "source": "reading",
      "target": "reading",
      "event": "GOVERNANCE_READ"
     },
     {
      "source": "reading",
      "target": "reading",
      "event": "CLAIMS_VERIFIED"
     },
     {
      "source": "reading",
      "target": "reader_tested",
      "event": "READER_TESTED"
     },
     {
      "source": "reader_tested",
      "target": "reader_tested",
      "event": "CLASSIFICATION_RULES_READ"
     },
     {
      "source": "reader_tested",
      "target": "passages_classified",
      "event": "PASSAGES_CLASSIFIED"
     },
     {
      "source": "passages_classified",
      "target": "passages_classified",
      "event": "RECOMMENDATION_RULES_READ"
     },
     {
      "source": "passages_classified",
      "target": "reported",
      "event": "FINDINGS_REPORTED"
     }
    ]
   },
   "agents": []
  },
  "auditing-infrastructure": {
   "name": "auditing-infrastructure",
   "machine": {
    "states": [
     {
      "id": "start",
      "name": "Start",
      "initial": true,
      "final": false
     },
     {
      "id": "scoped",
      "name": "Scoped",
      "initial": false,
      "final": false
     },
     {
      "id": "evidence_read",
      "name": "Evidence read",
      "initial": false,
      "final": false
     },
     {
      "id": "report_written",
      "name": "Report written",
      "initial": false,
      "final": false
     },
     {
      "id": "docs_linted",
      "name": "Docs linted",
      "initial": false,
      "final": false
     },
     {
      "id": "stamp_owing",
      "name": "Stamp owing",
      "initial": false,
      "final": false
     },
     {
      "id": "stamped",
      "name": "Stamped",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "start",
      "target": "scoped",
      "event": "SCOPE_DELTA_SELECTED"
     },
     {
      "source": "start",
      "target": "scoped",
      "event": "SCOPE_FULL_SELECTED"
     },
     {
      "source": "start",
      "target": "evidence_read",
      "event": "CURRENT_EVIDENCE_READ"
     },
     {
      "source": "scoped",
      "target": "evidence_read",
      "event": "CURRENT_EVIDENCE_READ"
     },
     {
      "source": "evidence_read",
      "target": "report_written",
      "event": "REPORT_WRITTEN"
     },
     {
      "source": "evidence_read",
      "target": "evidence_read",
      "event": "LOCAL_FIX_MADE"
     },
     {
      "source": "evidence_read",
      "target": "evidence_read",
      "event": "FALSE_POSITIVE_DISMISSED"
     },
     {
      "source": "evidence_read",
      "target": "evidence_read",
      "event": "FINDING_FLAGGED"
     },
     {
      "source": "evidence_read",
      "target": "evidence_read",
      "event": "FOLLOWUP_TASK_CREATED"
     },
     {
      "source": "report_written",
      "target": "report_written",
      "event": "LOCAL_FIX_MADE"
     },
     {
      "source": "report_written",
      "target": "report_written",
      "event": "FOLLOWUP_TASK_CREATED"
     },
     {
      "source": "report_written",
      "target": "report_written",
      "event": "DOCS_LINT_FAILED"
     },
     {
      "source": "report_written",
      "target": "docs_linted",
      "event": "DOCS_LINTED"
     },
     {
      "source": "docs_linted",
      "target": "docs_linted",
      "event": "FOLLOWUP_TASK_CREATED"
     },
     {
      "source": "docs_linted",
      "target": "stamped",
      "event": "BASELINE_STAMPED"
     },
     {
      "source": "docs_linted",
      "target": "stamp_owing",
      "event": "BASELINE_STAMPED"
     },
     {
      "source": "stamp_owing",
      "target": "stamped",
      "event": "FOLLOWUP_TASK_CREATED"
     }
    ]
   },
   "agents": []
  },
  "authoring-skills": {
   "name": "authoring-skills",
   "machine": {
    "states": [
     {
      "id": "guidance_pending",
      "name": "Guidance pending",
      "initial": true,
      "final": false
     },
     {
      "id": "guidance_read",
      "name": "Guidance read",
      "initial": false,
      "final": false
     },
     {
      "id": "skill_drafted",
      "name": "Skill drafted",
      "initial": false,
      "final": false
     },
     {
      "id": "skill_tested",
      "name": "Skill tested",
      "initial": false,
      "final": false
     },
     {
      "id": "lint_passed",
      "name": "Lint passed",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "guidance_pending",
      "target": "guidance_read",
      "event": "GUIDANCE_READ"
     },
     {
      "source": "guidance_read",
      "target": "skill_drafted",
      "event": "SKILL_DRAFTED"
     },
     {
      "source": "skill_drafted",
      "target": "skill_tested",
      "event": "SKILL_TESTED"
     },
     {
      "source": "skill_tested",
      "target": "skill_drafted",
      "event": "SKILL_TRIMMED"
     },
     {
      "source": "skill_tested",
      "target": "skill_tested",
      "event": "LINT_FAILED"
     },
     {
      "source": "skill_tested",
      "target": "lint_passed",
      "event": "LINT_PASSED"
     }
    ]
   },
   "agents": [
    {
     "id": "f4cfdf0d-4309-4c51-b115-5bc7d2b1e395",
     "title": "Document the status badge after a rebase",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2086",
     "active": 1790882061.034,
     "state": "lint_passed",
     "steps": 5,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790745989.541
      },
      {
       "state": "skill_drafted",
       "event": "SKILL_DRAFTED",
       "at": 1790746151.397
      },
      {
       "state": "skill_tested",
       "event": "SKILL_TESTED",
       "at": 1790747367.119
      },
      {
       "state": "skill_tested",
       "event": "LINT_FAILED",
       "at": 1790747776.168
      },
      {
       "state": "lint_passed",
       "event": "LINT_PASSED",
       "at": 1790747867.293
      }
     ]
    },
    {
     "id": "9ae2798b-46b8-41de-abd3-86f012b84406",
     "title": "Move the release notes",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2215",
     "active": 1790884730.4941778,
     "state": "guidance_read",
     "steps": 1,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790883904.97
      }
     ]
    },
    {
     "id": "f034b5b3-be51-4af4-a8de-3e4fa5316ed8",
     "title": "Add the demo fixture",
     "model": "claude-opus-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2190",
     "active": 1790882567.84,
     "state": "guidance_read",
     "steps": 1,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790810613.162
      }
     ]
    },
    {
     "id": "9842d0d8-48fb-49f1-81a2-b5a55f94a9b8",
     "title": "Add the digest job",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2205",
     "active": 1790882495.263,
     "state": "skill_drafted",
     "steps": 2,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790835800.45
      },
      {
       "state": "skill_drafted",
       "event": "SKILL_DRAFTED",
       "at": 1790835813.577
      }
     ]
    },
    {
     "id": "cd904e59-9600-4130-9070-98c238fd9658",
     "title": "Retire the demo fixture in one pass",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2105",
     "active": 1790881927.413,
     "state": "guidance_read",
     "steps": 1,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790745150.761
      }
     ]
    },
    {
     "id": "943d9ad3-745d-52b6-825b-b5e9ce827c86",
     "title": "Trim the label filter on cold start",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2172",
     "active": 1790870158.931,
     "state": "skill_drafted",
     "steps": 2,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790836380.767
      },
      {
       "state": "skill_drafted",
       "event": "SKILL_DRAFTED",
       "at": 1790838084.952
      }
     ]
    },
    {
     "id": "84239d9e-d44d-57ff-8e8f-ca3c05664209",
     "title": "Trim the digest job with a test",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2272",
     "active": 1790883625.561086,
     "state": "skill_drafted",
     "steps": 2,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790881405.957
      },
      {
       "state": "skill_drafted",
       "event": "SKILL_DRAFTED",
       "at": 1790881415.367
      }
     ]
    },
    {
     "id": "1d041253-6c68-58f9-bd01-f4fa8f5c35ee",
     "title": "Audit the config loader",
     "model": "claude-opus-5-5",
     "kind": "unattended",
     "badges": [],
     "task": "TASK-2271",
     "active": 1790883497.494469,
     "state": "guidance_read",
     "steps": 1,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790877901.133
      }
     ]
    },
    {
     "id": "c85f372d-b3c4-4c82-aebb-9ad4643ab266",
     "title": "Split the status badge",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2206",
     "active": 1790882495.583,
     "state": "skill_drafted",
     "steps": 2,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790836699.366
      },
      {
       "state": "skill_drafted",
       "event": "SKILL_DRAFTED",
       "at": 1790836715.121
      }
     ]
    },
    {
     "id": "c092e86d-ec42-4353-ad1f-3aaf9318e39a",
     "title": "Measure the search index",
     "model": "claude-sonnet-5-5",
     "kind": "interactive",
     "badges": [],
     "task": "TASK-2182",
     "active": 1790882496.236,
     "state": "skill_tested",
     "steps": 5,
     "trail": [
      {
       "state": "guidance_read",
       "event": "GUIDANCE_READ",
       "at": 1790834685.836
      },
      {
       "state": "skill_drafted",
       "event": "SKILL_DRAFTED",
       "at": 1790834711.801
      },
      {
       "state": "skill_tested",
       "event": "SKILL_TESTED",
       "at": 1790834782.716
      },
      {
       "state": "skill_drafted",
       "event": "SKILL_TRIMMED",
       "at": 1790835128.35
      },
      {
       "state": "skill_tested",
       "event": "SKILL_TESTED",
       "at": 1790838237.122
      }
     ]
    }
   ]
  },
  "graph-traversal": {
   "name": "graph-traversal",
   "machine": {
    "states": [
     {
      "id": "start",
      "name": "Start",
      "initial": true,
      "final": false
     },
     {
      "id": "oriented",
      "name": "Oriented",
      "initial": false,
      "final": false
     },
     {
      "id": "anchored",
      "name": "Anchored",
      "initial": false,
      "final": false
     },
     {
      "id": "expanded",
      "name": "Expanded",
      "initial": false,
      "final": false
     },
     {
      "id": "read",
      "name": "Read",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "start",
      "target": "oriented",
      "event": "ORIENTED"
     },
     {
      "source": "oriented",
      "target": "anchored",
      "event": "ANCHORED"
     },
     {
      "source": "anchored",
      "target": "expanded",
      "event": "EXPANDED"
     },
     {
      "source": "anchored",
      "target": "read",
      "event": "READ"
     },
     {
      "source": "expanded",
      "target": "anchored",
      "event": "ANCHORED"
     },
     {
      "source": "expanded",
      "target": "expanded",
      "event": "EXPANDED"
     },
     {
      "source": "expanded",
      "target": "read",
      "event": "READ"
     }
    ]
   },
   "agents": []
  },
  "investigating-dependency-updates": {
   "name": "investigating-dependency-updates",
   "machine": {
    "states": [
     {
      "id": "start",
      "name": "Start",
      "initial": true,
      "final": false
     },
     {
      "id": "change_read",
      "name": "Change read",
      "initial": false,
      "final": false
     },
     {
      "id": "notes_read",
      "name": "Notes read",
      "initial": false,
      "final": false
     },
     {
      "id": "surface_checked",
      "name": "Surface checked",
      "initial": false,
      "final": false
     },
     {
      "id": "reported",
      "name": "Reported",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "start",
      "target": "change_read",
      "event": "CHANGE_READ"
     },
     {
      "source": "change_read",
      "target": "change_read",
      "event": "CHANGE_READ"
     },
     {
      "source": "change_read",
      "target": "notes_read",
      "event": "NOTES_READ"
     },
     {
      "source": "change_read",
      "target": "surface_checked",
      "event": "SURFACE_CHECKED"
     },
     {
      "source": "notes_read",
      "target": "notes_read",
      "event": "CHANGE_READ"
     },
     {
      "source": "notes_read",
      "target": "notes_read",
      "event": "NOTES_READ"
     },
     {
      "source": "notes_read",
      "target": "surface_checked",
      "event": "SURFACE_CHECKED"
     },
     {
      "source": "surface_checked",
      "target": "surface_checked",
      "event": "CHANGE_READ"
     },
     {
      "source": "surface_checked",
      "target": "surface_checked",
      "event": "NOTES_READ"
     },
     {
      "source": "surface_checked",
      "target": "surface_checked",
      "event": "SURFACE_CHECKED"
     },
     {
      "source": "surface_checked",
      "target": "reported",
      "event": "REPORT_RETURNED"
     }
    ],
    "writers": {
     "CHANGE_READ": [
      {
       "actor": "dependency-update-investigation",
       "trigger": "bin/dependency_update_investigation_dispatch.py"
      }
     ],
     "NOTES_READ": [
      {
       "actor": "dependency-update-investigation",
       "trigger": "bin/dependency_update_investigation_dispatch.py"
      }
     ],
     "SURFACE_CHECKED": [
      {
       "actor": "dependency-update-investigation",
       "trigger": "bin/dependency_update_investigation_dispatch.py"
      }
     ],
     "REPORT_RETURNED": [
      {
       "actor": "dependency-update-investigation",
       "trigger": "bin/dependency_update_investigation_dispatch.py"
      }
     ]
    }
   },
   "agents": [
    {
     "id": "56b5b85c-e34e-49f3-a8a6-50c950b4ce60",
     "title": "Retire the lint rule",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": null,
     "active": 1790882753.720684,
     "state": "reported",
     "steps": 6,
     "trail": [
      {
       "state": "change_read",
       "event": "CHANGE_READ",
       "at": 1790882724.173
      },
      {
       "state": "change_read",
       "event": "CHANGE_READ",
       "at": 1790882724.535
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790882729.277
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790882733.535
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790882740.219
      },
      {
       "state": "reported",
       "event": "REPORT_RETURNED",
       "at": 1790882749.651
      }
     ]
    },
    {
     "id": "51badb72-be8c-4aea-94e0-6e959c6f43e8",
     "title": "Fix the health probe after a rebase",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": null,
     "active": 1790881586.0394378,
     "state": "reported",
     "steps": 5,
     "trail": [
      {
       "state": "change_read",
       "event": "CHANGE_READ",
       "at": 1790881564.046
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790881573.884
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790881574.292
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790881575.402
      },
      {
       "state": "reported",
       "event": "REPORT_RETURNED",
       "at": 1790881582.587
      }
     ]
    },
    {
     "id": "c74121a4-b45d-42fc-a9fa-96237b2b5e2d",
     "title": "Move the release notes under load",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": null,
     "active": 1790877047.157258,
     "state": "reported",
     "steps": 7,
     "trail": [
      {
       "state": "change_read",
       "event": "CHANGE_READ",
       "at": 1790877019.892
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790877025.552
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790877031.822
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790877032.198
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790877032.886
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790877035.627
      },
      {
       "state": "reported",
       "event": "REPORT_RETURNED",
       "at": 1790877042.366
      }
     ]
    },
    {
     "id": "2307f2a8-72bd-45bc-ae6f-803da6fa8bde",
     "title": "Fix the search index without a restart",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": null,
     "active": 1790882531.187214,
     "state": "reported",
     "steps": 3,
     "trail": [
      {
       "state": "change_read",
       "event": "CHANGE_READ",
       "at": 1790882507.945
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790882514.117
      },
      {
       "state": "reported",
       "event": "REPORT_RETURNED",
       "at": 1790882525.97
      }
     ]
    },
    {
     "id": "7a5acc88-3037-486f-8b16-ce42f9b5b30a",
     "title": "Verify the digest job",
     "model": "claude-sonnet-5-5",
     "kind": "unattended",
     "badges": [],
     "task": null,
     "active": 1790874496.4774654,
     "state": "reported",
     "steps": 6,
     "trail": [
      {
       "state": "change_read",
       "event": "CHANGE_READ",
       "at": 1790874472.316
      },
      {
       "state": "change_read",
       "event": "CHANGE_READ",
       "at": 1790874472.674
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790874480.251
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790874483.588
      },
      {
       "state": "surface_checked",
       "event": "SURFACE_CHECKED",
       "at": 1790874483.994
      },
      {
       "state": "reported",
       "event": "REPORT_RETURNED",
       "at": 1790874491.039
      }
     ]
    }
   ]
  },
  "realigning-stale-docs": {
   "name": "realigning-stale-docs",
   "machine": {
    "states": [
     {
      "id": "start",
      "name": "Start",
      "initial": true,
      "final": false
     },
     {
      "id": "authority_verified",
      "name": "Authority verified",
      "initial": false,
      "final": false
     },
     {
      "id": "surfaces_searched",
      "name": "Surfaces searched",
      "initial": false,
      "final": false
     },
     {
      "id": "hits_classified",
      "name": "Hits classified",
      "initial": false,
      "final": false
     },
     {
      "id": "claims_updated",
      "name": "Claims updated",
      "initial": false,
      "final": false
     },
     {
      "id": "stale_forms_researched",
      "name": "Stale forms researched",
      "initial": false,
      "final": false
     },
     {
      "id": "complete",
      "name": "Complete",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "start",
      "target": "authority_verified",
      "event": "AUTHORITY_VERIFIED"
     },
     {
      "source": "authority_verified",
      "target": "surfaces_searched",
      "event": "SURFACES_SEARCHED"
     },
     {
      "source": "surfaces_searched",
      "target": "hits_classified",
      "event": "HITS_CLASSIFIED"
     },
     {
      "source": "hits_classified",
      "target": "claims_updated",
      "event": "CLAIMS_UPDATED"
     },
     {
      "source": "claims_updated",
      "target": "stale_forms_researched",
      "event": "STALE_FORMS_RESEARCHED"
     },
     {
      "source": "stale_forms_researched",
      "target": "claims_updated",
      "event": "CLAIMS_UPDATED"
     },
     {
      "source": "stale_forms_researched",
      "target": "stale_forms_researched",
      "event": "VALIDATION_FAILED"
     },
     {
      "source": "stale_forms_researched",
      "target": "complete",
      "event": "VALIDATION_PASSED"
     }
    ]
   },
   "agents": []
  },
  "running-skill-evals": {
   "name": "running-skill-evals",
   "machine": {
    "states": [
     {
      "id": "needed",
      "name": "Needed",
      "initial": true,
      "final": false
     },
     {
      "id": "ready",
      "name": "Ready",
      "initial": false,
      "final": false
     },
     {
      "id": "asked",
      "name": "Asked",
      "initial": false,
      "final": false
     },
     {
      "id": "approved",
      "name": "Approved",
      "initial": false,
      "final": false
     },
     {
      "id": "running",
      "name": "Running",
      "initial": false,
      "final": false
     },
     {
      "id": "scored",
      "name": "Scored",
      "initial": false,
      "final": false
     },
     {
      "id": "recorded",
      "name": "Recorded",
      "initial": false,
      "final": true
     },
     {
      "id": "declined",
      "name": "Declined",
      "initial": false,
      "final": false
     },
     {
      "id": "needs_attention",
      "name": "Needs attention",
      "initial": false,
      "final": true
     }
    ],
    "transitions": [
     {
      "source": "needed",
      "target": "needed",
      "event": "PREFLIGHT_BLOCKED"
     },
     {
      "source": "needed",
      "target": "ready",
      "event": "PREFLIGHT_READY"
     },
     {
      "source": "ready",
      "target": "asked",
      "event": "APPROVAL_ASKED"
     },
     {
      "source": "asked",
      "target": "approved",
      "event": "APPROVED"
     },
     {
      "source": "asked",
      "target": "declined",
      "event": "DECLINED"
     },
     {
      "source": "approved",
      "target": "running",
      "event": "RUN_STARTED"
     },
     {
      "source": "running",
      "target": "needed",
      "event": "RUN_FAULTED"
     },
     {
      "source": "running",
      "target": "scored",
      "event": "RUN_SCORED"
     },
     {
      "source": "scored",
      "target": "recorded",
      "event": "RESULT_RECORDED"
     },
     {
      "source": "declined",
      "target": "needs_attention",
      "event": "DEFERRAL_RECORDED"
     }
    ]
   },
   "agents": []
  }
 },
 "dags": [
  {
   "name": "alert-investigation",
   "status": "succeeded",
   "runId": "alert-investigation-18a560c26e75881d",
   "startedAt": "2026-10-01T18:13:27Z",
   "finishedAt": "2026-10-01T18:13:37Z",
   "steps": [
    {
     "name": "ack",
     "depends": [],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "triage",
     "depends": [
      "ack"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "investigate",
     "depends": [
      "triage"
     ],
     "status": "succeeded",
     "kind": "agent"
    },
    {
     "name": "reason",
     "depends": [
      "investigate"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "remediate",
     "depends": [
      "reason"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "fix",
     "depends": [
      "remediate"
     ],
     "status": "succeeded",
     "kind": "agent"
    },
    {
     "name": "finalize",
     "depends": [
      "fix"
     ],
     "status": "succeeded",
     "kind": "code"
    }
   ]
  },
  {
   "name": "apply-on-merge",
   "status": "succeeded",
   "runId": "apply-on-merge-d222b1539cc2f35040672d377282c2e8c96a1e6b",
   "startedAt": "2026-10-01T19:30:36Z",
   "finishedAt": "2026-10-01T19:30:42Z",
   "steps": [
    {
     "name": "validate_event",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "classify",
     "depends": [
      "validate_event"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_migrations",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_images",
     "depends": [
      "apply_migrations"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_nas",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_deploy",
     "depends": [
      "apply_images"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_systemd",
     "depends": [
      "apply_deploy"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "push_dashboards",
     "depends": [
      "apply_systemd"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_rulesets",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_board",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_starpulse",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_session_start",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_skills_claude",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_skills_codex",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply_skills_nas",
     "depends": [
      "classify"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "verify_applied",
     "depends": [
      "push_dashboards",
      "apply_nas",
      "apply_rulesets",
      "apply_board",
      "apply_starpulse",
      "apply_session_start",
      "apply_skills_claude",
      "apply_skills_codex",
      "apply_skills_nas"
     ],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "backlog-sweep",
   "status": "succeeded",
   "runId": "034YJcNoLQJXUsSpiSlvLt",
   "startedAt": "2026-10-01T10:30:02Z",
   "finishedAt": "2026-10-01T10:30:50Z",
   "steps": [
    {
     "name": "sweep",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "board-autopilot",
   "status": "succeeded",
   "runId": "034OvpC17syE3rBt5DwRQz",
   "startedAt": "2026-09-15T01:20:19Z",
   "finishedAt": "2026-09-15T01:26:06Z",
   "steps": [
    {
     "name": "board_autopilot",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "board-dependency-reconciliation",
   "status": "succeeded",
   "runId": "034YWhMfnX04xyLvTz67Up",
   "startedAt": "2026-10-01T19:23:03Z",
   "finishedAt": "2026-10-01T19:23:06Z",
   "steps": [
    {
     "name": "board_dependency_reconciliation",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "cleanup-workspace",
   "status": "succeeded",
   "runId": "034YKM1s992UkdaczXcGJk",
   "startedAt": "2026-10-01T11:00:03Z",
   "finishedAt": "2026-10-01T11:00:30Z",
   "steps": [
    {
     "name": "reclaim_trash_ownership",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "cleanup",
     "depends": [
      "reclaim_trash_ownership"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "cleanup_worktrees",
     "depends": [
      "reclaim_trash_ownership"
     ],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "coderabbit-usage-metrics",
   "status": "succeeded",
   "runId": "034YWJ1Ina71pnTtFDKvsi",
   "startedAt": "2026-10-01T19:07:02Z",
   "finishedAt": "2026-10-01T19:07:05Z",
   "steps": [
    {
     "name": "sample",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "cr-sweep",
   "status": "succeeded",
   "runId": "cr-sweep-d222b1539cc2f35040672d377282c2e8c96a1e6b",
   "startedAt": "2026-10-01T19:30:16Z",
   "finishedAt": "2026-10-01T19:30:21Z",
   "steps": [
    {
     "name": "validate_event",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "sweep",
     "depends": [
      "validate_event"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "release",
     "depends": [
      "sweep"
     ],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "deliver",
   "status": "succeeded",
   "runId": "034YUctW10uiebDfUSe4y3",
   "startedAt": "2026-10-01T17:58:35Z",
   "finishedAt": "2026-10-01T18:02:06Z",
   "steps": [
    {
     "name": "refuse",
     "depends": [],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "lint",
     "depends": [
      "refuse"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "commit",
     "depends": [
      "lint"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "push",
     "depends": [
      "commit"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "open_pr",
     "depends": [
      "push"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "wait_ci",
     "depends": [
      "open_pr"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "ready",
     "depends": [
      "wait_ci"
     ],
     "status": "succeeded",
     "kind": "code"
    }
   ]
  },
  {
   "name": "dependabot-alert-gap",
   "status": "not_started",
   "runId": "",
   "startedAt": "",
   "finishedAt": "",
   "steps": [
    {
     "name": "alert_gap",
     "depends": [],
     "status": "not_started",
     "kind": null
    }
   ]
  },
  {
   "name": "dependency-update-investigation",
   "status": "succeeded",
   "runId": "dependency-update-investigation-8f87bec288cfc6d798b3df0b373cff7",
   "startedAt": "2026-10-01T19:25:14Z",
   "finishedAt": "2026-10-01T19:25:57Z",
   "steps": [
    {
     "name": "validate_event",
     "depends": [],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "read",
     "depends": [
      "validate_event"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "investigate",
     "depends": [
      "read"
     ],
     "status": "succeeded",
     "kind": "agent"
    },
    {
     "name": "post",
     "depends": [
      "investigate"
     ],
     "status": "succeeded",
     "kind": "code"
    }
   ]
  },
  {
   "name": "drift-to-task",
   "status": "succeeded",
   "runId": "034YXDJijKAj18jwr7Yutz",
   "startedAt": "2026-10-01T19:44:02Z",
   "finishedAt": "2026-10-01T19:44:06Z",
   "steps": [
    {
     "name": "drift_to_task",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "github-actions-queue-metrics",
   "status": "succeeded",
   "runId": "034YXU3PVc2S7ihpapD9cj",
   "startedAt": "2026-10-01T19:55:03Z",
   "finishedAt": "2026-10-01T19:55:21Z",
   "steps": [
    {
     "name": "sample",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "github-rulesets-drift",
   "status": "succeeded",
   "runId": "034YPvQ37GSjgi2WBkEzvB",
   "startedAt": "2026-10-01T14:47:02Z",
   "finishedAt": "2026-10-01T14:47:05Z",
   "steps": [
    {
     "name": "drift",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "grafana-db-snapshot",
   "status": "succeeded",
   "runId": "034YWcnfNSRMclcdcK2lMN",
   "startedAt": "2026-10-01T19:20:03Z",
   "finishedAt": "2026-10-01T19:20:06Z",
   "steps": [
    {
     "name": "snapshot",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "grafana-rule-health",
   "status": "succeeded",
   "runId": "034YXU3PbPGiopKgyfmNq7",
   "startedAt": "2026-10-01T19:55:03Z",
   "finishedAt": "2026-10-01T19:55:04Z",
   "steps": [
    {
     "name": "push",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "graph-refresh",
   "status": "succeeded",
   "runId": "graph-refresh-d222b1539cc2f35040672d377282c2e8c96a1e6b",
   "startedAt": "2026-10-01T19:31:02Z",
   "finishedAt": "2026-10-01T19:31:32Z",
   "steps": [
    {
     "name": "validate_event",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "reindex",
     "depends": [
      "validate_event"
     ],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "verify_revision",
     "depends": [
      "reindex"
     ],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "healthcheck",
   "status": "succeeded",
   "runId": "034YXU3PVZRpvbYaUCMPek",
   "startedAt": "2026-10-01T19:55:03Z",
   "finishedAt": "2026-10-01T19:55:08Z",
   "steps": [
    {
     "name": "run",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "main-follow",
   "status": "succeeded",
   "runId": "034YXU3PVTQEV5fWdoe6Ez",
   "startedAt": "2026-10-01T19:55:03Z",
   "finishedAt": "2026-10-01T19:55:44Z",
   "steps": [
    {
     "name": "main_follow",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "memory-reindex",
   "status": "succeeded",
   "runId": "034YWYEf3MF5Ng0mUHReQa",
   "startedAt": "2026-10-01T19:17:02Z",
   "finishedAt": "2026-10-01T19:17:05Z",
   "steps": [
    {
     "name": "reindex",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "mutation-metrics",
   "status": "succeeded",
   "runId": "manual-task1768-post2046",
   "startedAt": "2026-09-30T22:47:48Z",
   "finishedAt": "2026-10-01T00:12:06Z",
   "steps": [
    {
     "name": "run",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "nightly-audit",
   "status": "succeeded",
   "runId": "034YHPRbMzSROUUiE9gqbP",
   "startedAt": "2026-10-01T09:00:02Z",
   "finishedAt": "2026-10-01T09:01:26Z",
   "steps": [
    {
     "name": "prepare",
     "depends": [],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "execute",
     "depends": [
      "prepare"
     ],
     "status": "succeeded",
     "kind": "agent"
    },
    {
     "name": "validate",
     "depends": [
      "execute"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "finalize",
     "depends": [
      "validate"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "work_completed",
     "depends": [
      "finalize"
     ],
     "status": "succeeded",
     "kind": "code"
    }
   ]
  },
  {
   "name": "phantom-deletes-to-task",
   "status": "succeeded",
   "runId": "034VwXmcqCUDNlPXHPf2t9",
   "startedAt": "2026-09-27T06:37:01Z",
   "finishedAt": "2026-09-27T06:37:13Z",
   "steps": [
    {
     "name": "phantom_deletes_to_task",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "postgres-backup",
   "status": "succeeded",
   "runId": "034YHPRbN7Y4nvFo92QOcq",
   "startedAt": "2026-10-01T09:00:02Z",
   "finishedAt": "2026-10-01T09:00:24Z",
   "steps": [
    {
     "name": "dump",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "metrics",
     "depends": [
      "dump"
     ],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "postgres-restore-verify",
   "status": "succeeded",
   "runId": "034W2zwsqOfsy6RR5RF13O",
   "startedAt": "2026-09-27T11:00:01Z",
   "finishedAt": "2026-09-27T11:00:23Z",
   "steps": [
    {
     "name": "verify",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "rag-audit-nominations",
   "status": "succeeded",
   "runId": "034Wie0NzRDaiTtyZS4rea",
   "startedAt": "2026-09-28T15:17:02Z",
   "finishedAt": "2026-09-28T15:17:15Z",
   "steps": [
    {
     "name": "run",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "rag-metrics",
   "status": "succeeded",
   "runId": "034YXX65DUv5bww8DbhnYD",
   "startedAt": "2026-10-01T19:57:02Z",
   "finishedAt": "2026-10-01T19:57:15Z",
   "steps": [
    {
     "name": "run",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "semantic-tag-merges",
   "status": "succeeded",
   "runId": "034Wi0ReRI47MYF9JXcqHi",
   "startedAt": "2026-09-28T14:51:03Z",
   "finishedAt": "2026-09-28T14:51:15Z",
   "steps": [
    {
     "name": "propose",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "session-transcript-stats",
   "status": "succeeded",
   "runId": "034YXPUPBaZKPSIXvybgQ8",
   "startedAt": "2026-10-01T19:52:02Z",
   "finishedAt": "2026-10-01T19:55:53Z",
   "steps": [
    {
     "name": "run",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "signals",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "links",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "setup-vm-apply",
   "status": "succeeded",
   "runId": "034YJ7x5j5eJpLIcdl83BV",
   "startedAt": "2026-10-01T10:10:02Z",
   "finishedAt": "2026-10-01T10:10:24Z",
   "steps": [
    {
     "name": "apply",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "skill-conformance",
   "status": "succeeded",
   "runId": "034XcVsoRi3MlcdhfKUTEg",
   "startedAt": "2026-09-29T22:13:33-07:00",
   "finishedAt": "2026-09-29T22:17:00-07:00",
   "steps": [
    {
     "name": "judge",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "skill-eval",
   "status": "aborted",
   "runId": "034Q4kVJxT9uiG41rJ3SSb",
   "startedAt": "2026-09-17T00:05:54Z",
   "finishedAt": "2026-09-17T00:45:16Z",
   "steps": [
    {
     "name": "skill_eval",
     "depends": [],
     "status": "aborted",
     "kind": null
    }
   ]
  },
  {
   "name": "skill-optimize",
   "status": "not_started",
   "runId": "",
   "startedAt": "",
   "finishedAt": "",
   "steps": [
    {
     "name": "skill_optimize",
     "depends": [],
     "status": "not_started",
     "kind": null
    }
   ]
  },
  {
   "name": "superseded-images-sweep",
   "status": "succeeded",
   "runId": "034YL5fwR9DTcwHds3c1NR",
   "startedAt": "2026-10-01T11:30:02Z",
   "finishedAt": "2026-10-01T11:30:07Z",
   "steps": [
    {
     "name": "sweep",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "tag-analytics",
   "status": "succeeded",
   "runId": "034YXJP3xUhgNArOnwEjrn",
   "startedAt": "2026-10-01T19:48:02Z",
   "finishedAt": "2026-10-01T19:48:26Z",
   "steps": [
    {
     "name": "run",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "tag-optimizer",
   "status": "succeeded",
   "runId": "034YNq5WfBULDQrJECBTH9",
   "startedAt": "2026-10-01T13:22:11Z",
   "finishedAt": "2026-10-01T13:26:40Z",
   "steps": [
    {
     "name": "publish",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "replay",
     "depends": [
      "publish"
     ],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "tag-performers",
   "status": "succeeded",
   "runId": "034WiFf0V6vE72fh02gtX0",
   "startedAt": "2026-09-28T15:01:00Z",
   "finishedAt": "2026-09-28T15:06:26Z",
   "steps": [
    {
     "name": "list",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "tag-signals",
   "status": "succeeded",
   "runId": "034XscxOQNRSoJUEM4turO",
   "startedAt": "2026-09-30T09:10:10-07:00",
   "finishedAt": "2026-09-30T09:10:36-07:00",
   "steps": [
    {
     "name": "run",
     "depends": [],
     "status": "succeeded",
     "kind": null
    },
    {
     "name": "apply",
     "depends": [
      "run"
     ],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "testcontainers-sweep",
   "status": "succeeded",
   "runId": "034YW8MxFQsAUvqE6ger1f",
   "startedAt": "2026-10-01T19:00:03Z",
   "finishedAt": "2026-10-01T19:00:05Z",
   "steps": [
    {
     "name": "sweep",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "trace-cluster-report",
   "status": "not_started",
   "runId": "",
   "startedAt": "",
   "finishedAt": "",
   "steps": [
    {
     "name": "report",
     "depends": [],
     "status": "not_started",
     "kind": null
    }
   ]
  },
  {
   "name": "nas-apply-merged",
   "status": "succeeded",
   "runId": "034YXJP3xJDriuYAZRk0dy",
   "startedAt": "2026-10-01T19:48:02Z",
   "finishedAt": "2026-10-01T19:48:04Z",
   "steps": [
    {
     "name": "forward",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  },
  {
   "name": "weekly-code-audit",
   "status": "succeeded",
   "runId": "034W4TF18UFSuZNaLNYcRR",
   "startedAt": "2026-09-27T12:00:01Z",
   "finishedAt": "2026-09-27T12:10:50Z",
   "steps": [
    {
     "name": "prepare",
     "depends": [],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "execute",
     "depends": [
      "prepare"
     ],
     "status": "succeeded",
     "kind": "agent"
    },
    {
     "name": "validate",
     "depends": [
      "execute"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "finalize",
     "depends": [
      "validate"
     ],
     "status": "succeeded",
     "kind": "code"
    },
    {
     "name": "work_completed",
     "depends": [
      "finalize"
     ],
     "status": "succeeded",
     "kind": "code"
    }
   ]
  },
  {
   "name": "whole-repo-gate",
   "status": "failed",
   "runId": "034YWdSscrbuUQamEmbpyQ",
   "startedAt": "2026-10-01T19:20:26Z",
   "finishedAt": "2026-10-01T19:34:04Z",
   "steps": [
    {
     "name": "whole_repo_gate",
     "depends": [],
     "status": "failed",
     "kind": null
    }
   ]
  },
  {
   "name": "worktree-reap",
   "status": "succeeded",
   "runId": "034YWYEexMVBLoCyp3I24a",
   "startedAt": "2026-10-01T19:17:02Z",
   "finishedAt": "2026-10-01T19:19:10Z",
   "steps": [
    {
     "name": "reap",
     "depends": [],
     "status": "succeeded",
     "kind": null
    }
   ]
  }
 ],
 "writers": {
  "CREATE_READY": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py create"
   }
  ],
  "CREATE_WAITING": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py create"
   }
  ],
  "CREATE_WAITING_ON_DEPS": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py create"
   }
  ],
  "CREATE_IN_PROGRESS": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py create"
   },
   {
    "actor": "board-autopilot",
    "trigger": "find_or_create_task"
   }
  ],
  "CLAIM": [
   {
    "actor": "board-autopilot",
    "trigger": "bin/backlog_task.py dispatch"
   },
   {
    "actor": "agent",
    "trigger": "codex_task_lifecycle.claim_ready (start-prompt hook)"
   },
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py update --status \"In Progress\""
   }
  ],
  "WAIT_ON_DEPS": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py update --status Waiting"
   },
   {
    "actor": "board-autopilot",
    "trigger": "dependency sweep"
   }
  ],
  "PARK_ON_TASK": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py park --until-task"
   }
  ],
  "PARK_ON_CRITERIA": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py park --until"
   }
  ],
  "DEP_RESOLVED": [
   {
    "actor": "board-dependency-reconciliation",
    "trigger": "bin/board_dependency_promotion_dispatch.py"
   }
  ],
  "DEPS_DONE": [
   {
    "actor": "board-dependency-reconciliation",
    "trigger": "bin/board_dependency_reconciliation.py"
   }
  ],
  "CRITERIA_MET": [
   {
    "actor": "board-dependency-reconciliation",
    "trigger": "board_lanes.sync_start_criteria_lanes"
   }
  ],
  "CRITERIA_UNMET": [
   {
    "actor": "board-dependency-reconciliation",
    "trigger": "board_lanes.sync_start_criteria_lanes"
   }
  ],
  "START_WAITING": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py update --status \"In Progress\""
   }
  ],
  "PR_OPENED": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py update --add-ref"
   }
  ],
  "REVIEW": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py review"
   }
  ],
  "FINALIZE": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py finalize"
   }
  ],
  "DEFER": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py park --operator"
   },
   {
    "actor": "board-autopilot",
    "trigger": "board_lanes.defer"
   }
  ],
  "RESUME_READY": [
   {
    "actor": "operator",
    "trigger": "bin/backlog_task.py update --status Ready"
   }
  ],
  "RESUME": [
   {
    "actor": "operator",
    "trigger": "bin/backlog_task.py update --status \"In Progress\""
   }
  ],
  "MERGED": [
   {
    "actor": "main-follow",
    "trigger": "bin/board_reconcile_merged.py"
   }
  ],
  "SEND_BACK": [
   {
    "actor": "operator",
    "trigger": "bin/backlog_task.py update --status \"In Progress\""
   }
  ],
  "SWEEP": [
   {
    "actor": "backlog-sweep",
    "trigger": "bin/backlog_task.py sweep"
   }
  ],
  "ARCHIVE": [
   {
    "actor": "agent",
    "trigger": "bin/backlog_task.py archive"
   }
  ]
 },
 "launches": [
  {
   "dag": "nightly-audit",
   "skill": "auditing-infrastructure",
   "flow": "auditing-infrastructure"
  },
  {
   "dag": "weekly-code-audit",
   "skill": "auditing-code",
   "flow": null
  },
  {
   "dag": "board-autopilot",
   "skill": "starting-tasks",
   "flow": "in-progress"
  },
  {
   "dag": "alert-investigation",
   "skill": "querying-observability",
   "flow": null
  },
  {
   "dag": "dependency-update-investigation",
   "skill": "investigating-dependency-updates",
   "flow": "dependency-update-investigation"
  },
  {
   "dag": "skill-eval",
   "skill": "running-skill-evals",
   "flow": "running-skill-evals"
  },
  {
   "dag": "skill-optimize",
   "skill": "running-skill-evals",
   "flow": "running-skill-evals"
  }
 ],
 "cues": [
  {
   "dag": "apply-on-merge",
   "event": "MERGED",
   "state": "done",
   "on": "each merge to main"
  },
  {
   "dag": "graph-refresh",
   "event": "MERGED",
   "state": "done",
   "on": "each merge to main"
  }
 ],
 "domains": [
  {
   "name": "Delivery & CI",
   "dags": [
    {
     "name": "apply-on-merge",
     "runSafe": false
    },
    {
     "name": "coderabbit-usage-metrics",
     "runSafe": true
    },
    {
     "name": "cr-sweep",
     "runSafe": false
    },
    {
     "name": "deliver",
     "runSafe": false
    },
    {
     "name": "dependabot-alert-gap",
     "runSafe": false
    },
    {
     "name": "github-actions-queue-metrics",
     "runSafe": true
    },
    {
     "name": "github-rulesets-drift",
     "runSafe": true
    },
    {
     "name": "mutation-metrics",
     "runSafe": true
    },
    {
     "name": "setup-vm-apply",
     "runSafe": false
    },
    {
     "name": "nas-apply-merged",
     "runSafe": false
    },
    {
     "name": "whole-repo-gate",
     "runSafe": true
    }
   ]
  },
  {
   "name": "Board",
   "dags": [
    {
     "name": "backlog-sweep",
     "runSafe": false
    },
    {
     "name": "board-autopilot",
     "runSafe": false
    },
    {
     "name": "board-dependency-reconciliation",
     "runSafe": false
    },
    {
     "name": "drift-to-task",
     "runSafe": false
    },
    {
     "name": "main-follow",
     "runSafe": false
    },
    {
     "name": "phantom-deletes-to-task",
     "runSafe": false
    },
    {
     "name": "worktree-reap",
     "runSafe": false
    }
   ]
  },
  {
   "name": "Agent jobs & evals",
   "dags": [
    {
     "name": "alert-investigation",
     "runSafe": false
    },
    {
     "name": "dependency-update-investigation",
     "runSafe": false
    },
    {
     "name": "nightly-audit",
     "runSafe": false
    },
    {
     "name": "session-transcript-stats",
     "runSafe": true
    },
    {
     "name": "skill-conformance",
     "runSafe": true
    },
    {
     "name": "skill-eval",
     "runSafe": false
    },
    {
     "name": "skill-optimize",
     "runSafe": false
    },
    {
     "name": "trace-cluster-report",
     "runSafe": true
    },
    {
     "name": "weekly-code-audit",
     "runSafe": false
    }
   ]
  },
  {
   "name": "Retrieval & tags",
   "dags": [
    {
     "name": "graph-refresh",
     "runSafe": true
    },
    {
     "name": "memory-reindex",
     "runSafe": true
    },
    {
     "name": "rag-audit-nominations",
     "runSafe": false
    },
    {
     "name": "rag-metrics",
     "runSafe": true
    },
    {
     "name": "semantic-tag-merges",
     "runSafe": false
    },
    {
     "name": "tag-analytics",
     "runSafe": true
    },
    {
     "name": "tag-optimizer",
     "runSafe": false
    },
    {
     "name": "tag-performers",
     "runSafe": false
    },
    {
     "name": "tag-signals",
     "runSafe": false
    }
   ]
  },
  {
   "name": "Host ops & backups",
   "dags": [
    {
     "name": "cleanup-workspace",
     "runSafe": false
    },
    {
     "name": "grafana-db-snapshot",
     "runSafe": false
    },
    {
     "name": "grafana-rule-health",
     "runSafe": true
    },
    {
     "name": "healthcheck",
     "runSafe": true
    },
    {
     "name": "postgres-backup",
     "runSafe": false
    },
    {
     "name": "postgres-restore-verify",
     "runSafe": false
    },
    {
     "name": "superseded-images-sweep",
     "runSafe": false
    },
    {
     "name": "testcontainers-sweep",
     "runSafe": false
    }
   ]
  }
 ],
 "descriptions": {
  "TASK-2205": "Synthetic demo task: rename the demo fixture.",
  "TASK-2203": "Synthetic demo task: harden the board snapshot.",
  "TASK-2246": "Synthetic demo task: simplify the review queue after a rebase.",
  "TASK-2239": "Synthetic demo task: trim the alert rule.",
  "TASK-2150": "Synthetic demo task: simplify the retry budget.",
  "TASK-2232": "Synthetic demo task: retire the lint rule after a rebase.",
  "TASK-2237": "Synthetic demo task: rename the export path.",
  "TASK-2233": "Synthetic demo task: move the nightly run under load.",
  "TASK-2251": "Synthetic demo task: harden the import check.",
  "TASK-2253": "Synthetic demo task: rename the lint rule with a test.",
  "TASK-2234": "Synthetic demo task: cache the sync worker on cold start.",
  "TASK-2254": "Synthetic demo task: wire the nightly run with a clear error.",
  "TASK-2236": "Synthetic demo task: measure the migration step for new users.",
  "TASK-2255": "Synthetic demo task: trim the sync worker in the sample repo.",
  "TASK-2256": "Synthetic demo task: tune the cache layer without a restart.",
  "TASK-2257": "Synthetic demo task: audit the alert rule in one pass.",
  "TASK-2258": "Synthetic demo task: add the config loader.",
  "TASK-1236": "Synthetic demo task: document the sync worker.",
  "TASK-1349": "Synthetic demo task: split the release notes in one pass.",
  "TASK-1489": "Synthetic demo task: audit the alert rule.",
  "TASK-1566": "Synthetic demo task: wire the config loader in one pass.",
  "TASK-1672": "Synthetic demo task: retire the alert rule with a clear error.",
  "TASK-1673": "Synthetic demo task: move the release notes.",
  "TASK-1674": "Synthetic demo task: cache the review queue without a restart.",
  "TASK-1675": "Synthetic demo task: harden the card layout.",
  "TASK-1676": "Synthetic demo task: measure the health probe behind a flag.",
  "TASK-1677": "Synthetic demo task: rename the label filter.",
  "TASK-1678": "Synthetic demo task: wire the board snapshot after a rebase.",
  "TASK-1679": "Synthetic demo task: trim the import check after a rebase.",
  "TASK-1680": "Synthetic demo task: tune the search index under load.",
  "TASK-1681": "Synthetic demo task: audit the report page on cold start.",
  "TASK-1682": "Synthetic demo task: add the token scope for new users.",
  "TASK-1683": "Synthetic demo task: fix the session timer.",
  "TASK-1684": "Synthetic demo task: document the cache layer under load.",
  "TASK-1685": "Synthetic demo task: split the retry budget with a test.",
  "TASK-1710": "Synthetic demo task: wire the status badge for the demo.",
  "TASK-1744": "Synthetic demo task: tune the cache layer for new users.",
  "TASK-1779": "Synthetic demo task: fix the demo fixture in one pass.",
  "TASK-1832": "Synthetic demo task: retire the export path on cold start.",
  "TASK-1878": "Synthetic demo task: simplify the label filter.",
  "TASK-1882": "Synthetic demo task: cache the release notes.",
  "TASK-1888": "Synthetic demo task: tune the webhook handler in one pass.",
  "TASK-1889": "Synthetic demo task: audit the sync worker behind a flag.",
  "TASK-1890": "Synthetic demo task: add the report page.",
  "TASK-1892": "Synthetic demo task: document the export path.",
  "TASK-1894": "Synthetic demo task: simplify the alert rule on cold start.",
  "TASK-1896": "Synthetic demo task: retire the review queue after a rebase.",
  "TASK-1899": "Synthetic demo task: harden the label filter.",
  "TASK-1901": "Synthetic demo task: rename the import check.",
  "TASK-1929": "Synthetic demo task: move the lint rule in the sample repo.",
  "TASK-1948": "Synthetic demo task: measure the cache layer.",
  "TASK-1971": "Synthetic demo task: fix the report page for new users.",
  "TASK-1978": "Synthetic demo task: cache the card layout in one pass.",
  "TASK-2005": "Synthetic demo task: split the health probe in the sample repo.",
  "TASK-2009": "Synthetic demo task: move the retry budget.",
  "TASK-2012": "Synthetic demo task: measure the sync worker behind a flag.",
  "TASK-2013": "Synthetic demo task: rename the report page for the demo.",
  "TASK-2014": "Synthetic demo task: wire the migration step without a restart.",
  "TASK-2015": "Synthetic demo task: trim the export path.",
  "TASK-2016": "Synthetic demo task: tune the review queue for large boards.",
  "TASK-2017": "Synthetic demo task: audit the card layout.",
  "TASK-2018": "Synthetic demo task: add the status badge for new users.",
  "TASK-2019": "Synthetic demo task: fix the label filter after a rebase.",
  "TASK-2020": "Synthetic demo task: document the board snapshot under load.",
  "TASK-2021": "Synthetic demo task: split the digest job.",
  "TASK-2022": "Synthetic demo task: simplify the demo fixture for new users.",
  "TASK-2023": "Synthetic demo task: verify the release notes.",
  "TASK-2024": "Synthetic demo task: retire the nightly run.",
  "TASK-2030": "Synthetic demo task: wire the retry budget.",
  "TASK-2042": "Synthetic demo task: cache the digest job.",
  "TASK-2043": "Synthetic demo task: harden the demo fixture without a restart.",
  "TASK-2057": "Synthetic demo task: move the config loader.",
  "TASK-2059": "Synthetic demo task: harden the card layout.",
  "TASK-2066": "Synthetic demo task: add the token scope.",
  "TASK-2086": "Synthetic demo task: simplify the health probe in one pass.",
  "TASK-2147": "Synthetic demo task: fix the token scope in the sample repo.",
  "TASK-2163": "Synthetic demo task: fix the demo fixture.",
  "TASK-2164": "Synthetic demo task: document the release notes with a clear error.",
  "TASK-2172": "Synthetic demo task: measure the lint rule under load.",
  "TASK-2173": "Synthetic demo task: rename the webhook handler on cold start.",
  "TASK-2176": "Synthetic demo task: tune the alert rule under load.",
  "TASK-2183": "Synthetic demo task: verify the digest job for the demo.",
  "TASK-2198": "Synthetic demo task: simplify the config loader for the demo.",
  "TASK-2210": "Synthetic demo task: add the retry budget with a test.",
  "TASK-2213": "Synthetic demo task: split the sync worker without a restart.",
  "TASK-2215": "Synthetic demo task: verify the migration step behind a flag.",
  "TASK-2216": "Synthetic demo task: retire the export path for the demo.",
  "TASK-2217": "Synthetic demo task: move the cache layer for new users.",
  "TASK-2218": "Synthetic demo task: cache the alert rule.",
  "TASK-2224": "Synthetic demo task: tune the release notes.",
  "TASK-2225": "Synthetic demo task: audit the review queue behind a flag.",
  "TASK-2230": "Synthetic demo task: simplify the import check.",
  "TASK-2231": "Synthetic demo task: verify the retry budget for the demo.",
  "TASK-2235": "Synthetic demo task: harden the report page for new users.",
  "TASK-2240": "Synthetic demo task: tune the status badge with a clear error.",
  "TASK-2241": "Synthetic demo task: audit the migration step without a restart.",
  "TASK-2244": "Synthetic demo task: document the demo fixture behind a flag.",
  "TASK-2247": "Synthetic demo task: verify the search index.",
  "TASK-2248": "Synthetic demo task: retire the health probe on cold start.",
  "TASK-2249": "Synthetic demo task: move the token scope on cold start.",
  "TASK-2250": "Synthetic demo task: cache the session timer for new users.",
  "TASK-2252": "Synthetic demo task: measure the retry budget under load.",
  "TASK-2259": "Synthetic demo task: fix the webhook handler for the demo.",
  "TASK-2260": "Synthetic demo task: document the card layout.",
  "TASK-2261": "Synthetic demo task: split the status badge for large boards.",
  "TASK-2262": "Synthetic demo task: simplify the label filter.",
  "TASK-2263": "Synthetic demo task: verify the board snapshot on cold start.",
  "TASK-2264": "Synthetic demo task: retire the digest job.",
  "TASK-2265": "Synthetic demo task: move the demo fixture after a rebase.",
  "TASK-2266": "Synthetic demo task: cache the release notes.",
  "TASK-2267": "Synthetic demo task: harden the review queue with a test.",
  "TASK-2268": "Synthetic demo task: measure the search index for new users.",
  "TASK-2269": "Synthetic demo task: rename the health probe with a clear error.",
  "TASK-2270": "Synthetic demo task: wire the token scope in the sample repo.",
  "TASK-2271": "Synthetic demo task: trim the session timer in one pass.",
  "TASK-2272": "Synthetic demo task: tune the nightly run.",
  "TASK-2273": "Synthetic demo task: audit the sync worker.",
  "TASK-2274": "Synthetic demo task: add the report page without a restart.",
  "TASK-2275": "Synthetic demo task: fix the token scope after a rebase.",
  "TASK-2276": "Synthetic demo task: document the export path for large boards.",
  "TASK-2277": "Synthetic demo task: split the cache layer on cold start.",
  "TASK-2278": "Synthetic demo task: simplify the alert rule for the demo.",
  "TASK-2279": "Synthetic demo task: verify the config loader.",
  "TASK-2280": "Synthetic demo task: retire the webhook handler under load.",
  "TASK-2281": "Synthetic demo task: move the card layout.",
  "TASK-2282": "Synthetic demo task: cache the status badge with a test.",
  "TASK-2283": "Synthetic demo task: harden the label filter for new users.",
  "TASK-2284": "Synthetic demo task: measure the board snapshot in the sample repo.",
  "TASK-2285": "Synthetic demo task: rename the digest job.",
  "TASK-2286": "Synthetic demo task: wire the demo fixture with a test.",
  "TASK-2287": "Synthetic demo task: trim the release notes.",
  "TASK-2288": "Synthetic demo task: tune the label filter for the demo."
 }
};
