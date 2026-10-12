// The Kanban mockup's saved Board: a live snapshot's board tasks, trimmed to what a card draws.
window.BOARD = {
 "now": 1791341988.2474327,
 "names": {
  "new": "New",
  "ready": "Ready",
  "waiting": "Waiting",
  "in_progress": "In Progress",
  "review": "Review",
  "needs_attention": "Needs Attention",
  "done": "Done",
  "completed": "Completed",
  "archived": "Archived"
 },
 "tasks": [
  {
   "id": "TASK-2021",
   "title": "Split the digest job",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697453.0
  },
  {
   "id": "TASK-2022",
   "title": "Simplify the demo fixture for new users",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697461.0
  },
  {
   "id": "TASK-2023",
   "title": "Verify the release notes",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697496.0
  },
  {
   "id": "TASK-2024",
   "title": "Retire the nightly run",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697504.0
  },
  {
   "id": "TASK-2147",
   "title": "Fix the token scope in the sample repo",
   "lane": "waiting",
   "milestone": "m-54",
   "labels": [
    "kind-decide",
    "size-2",
    "validation"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790834640.0
  },
  {
   "id": "TASK-2198",
   "title": "Simplify the config loader for the demo",
   "lane": "ready",
   "milestone": "m-51",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790802914.0
  },
  {
   "id": "TASK-2274",
   "title": "Add the report page without a restart",
   "lane": "done",
   "milestone": "m-69",
   "labels": [
    "kind-decide",
    "retro-m-69",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2281"
   ],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791341751.3693955
   },
   "moves": {},
   "entered": 1791341849.8201823
  },
  {
   "id": "TASK-2281",
   "title": "Move the card layout",
   "lane": "done",
   "milestone": "m-69",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2370,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791339799.4946258
   },
   "moves": {},
   "entered": 1791339915.1907432
  },
  {
   "id": "TASK-2322",
   "title": "Add the migration step after a rebase",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2009"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790957151.0
  },
  {
   "id": "TASK-2402",
   "title": "Add the status badge after a rebase",
   "lane": "waiting",
   "milestone": "m-53",
   "labels": [
    "kind-mechanical",
    "size-1",
    "validation"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791227834.0
  },
  {
   "id": "TASK-2412",
   "title": "Measure the session timer",
   "lane": "waiting",
   "milestone": "m-53",
   "labels": [
    "kind-decide",
    "size-2"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790979565.0
  },
  {
   "id": "TASK-2419",
   "title": "Fix the retry budget with a test",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "kind-decide",
    "retro-m-75",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2432"
   ],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791316604.0
  },
  {
   "id": "TASK-2432",
   "title": "Tune the demo fixture under load",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2327,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791314286.0
  },
  {
   "id": "TASK-2501",
   "title": "Split the config loader",
   "lane": "waiting",
   "milestone": "m-78",
   "labels": [
    "kind-decide",
    "retro-m-78",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2510",
    "TASK-2511",
    "TASK-2956"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791012829.0
  },
  {
   "id": "TASK-2510",
   "title": "Wire the review queue for new users",
   "lane": "done",
   "milestone": "m-78",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432"
   ],
   "prs": [
    {
     "number": 59,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791322217.0
  },
  {
   "id": "TASK-2511",
   "title": "Trim the search index after a rebase",
   "lane": "done",
   "milestone": "m-78",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432"
   ],
   "prs": [
    {
     "number": 60,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791321012.0
  },
  {
   "id": "TASK-2516",
   "title": "Document the sync worker",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "kind-decide",
    "retro-m-80",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2518",
    "TASK-2519",
    "TASK-2523",
    "TASK-2524",
    "TASK-2525",
    "TASK-2526",
    "TASK-2527",
    "TASK-2528",
    "TASK-2529",
    "TASK-2530",
    "TASK-2531",
    "TASK-2720",
    "TASK-2967",
    "TASK-2973",
    "TASK-2980"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791047277.0
  },
  {
   "id": "TASK-2518",
   "title": "Simplify the token scope behind a flag",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432",
    "TASK-2510"
   ],
   "prs": [
    {
     "number": 69,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2378,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791331448.6116517
   },
   "moves": {},
   "entered": 1791331515.0
  },
  {
   "id": "TASK-2519",
   "title": "Verify the export path with a clear error",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432"
   ],
   "prs": [
    {
     "number": 68,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791329555.337958
   },
   "moves": {},
   "entered": 1791329642.0
  },
  {
   "id": "TASK-2523",
   "title": "Harden the webhook handler on cold start",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432"
   ],
   "prs": [
    {
     "number": 71,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2373,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "ci_green",
    "at": 1791332300.439406
   },
   "moves": {},
   "entered": 1791332712.0
  },
  {
   "id": "TASK-2524",
   "title": "Measure the card layout",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432",
    "TASK-2523"
   ],
   "prs": [
    {
     "number": 76,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2389,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791335891.5293465
   },
   "moves": {},
   "entered": 1791336316.1810617
  },
  {
   "id": "TASK-2525",
   "title": "Rename the status badge after a rebase",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432",
    "TASK-2519"
   ],
   "prs": [
    {
     "number": 73,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791334766.866086
   },
   "moves": {},
   "entered": 1791334812.0
  },
  {
   "id": "TASK-2526",
   "title": "Wire the migration step under load",
   "lane": "in_progress",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432",
    "TASK-2524",
    "TASK-2519",
    "TASK-2525"
   ],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "ci_green",
    "at": 1791341478.7952237
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791336759.6644437
  },
  {
   "id": "TASK-2527",
   "title": "Trim the board snapshot on cold start",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432",
    "TASK-2518"
   ],
   "prs": [
    {
     "number": 74,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2398,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791337965.4698327
   },
   "moves": {},
   "entered": 1791338112.0605123
  },
  {
   "id": "TASK-2528",
   "title": "Tune the review queue",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432"
   ],
   "prs": [
    {
     "number": 72,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791329902.6439605
   },
   "moves": {},
   "entered": 1791330024.0
  },
  {
   "id": "TASK-2529",
   "title": "Audit the card layout with a clear error",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432"
   ],
   "prs": [
    {
     "number": 70,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791329377.8453295
   },
   "moves": {},
   "entered": 1791329551.0
  },
  {
   "id": "TASK-2530",
   "title": "Add the health probe",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2432",
    "TASK-2526",
    "TASK-2518"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791047435.0
  },
  {
   "id": "TASK-2531",
   "title": "Fix the label filter in one pass",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [
    "TASK-2432",
    "TASK-2530"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791047449.0
  },
  {
   "id": "TASK-2559",
   "title": "Trim the report page under load",
   "lane": "waiting",
   "milestone": "m-81",
   "labels": [
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791066188.0
  },
  {
   "id": "TASK-2595",
   "title": "Fix the lint rule with a clear error",
   "lane": "done",
   "milestone": "m-58",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 22,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2294,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791301403.0
  },
  {
   "id": "TASK-2597",
   "title": "Split the search index",
   "lane": "done",
   "milestone": "m-58",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2595"
   ],
   "prs": [
    {
     "number": 2307,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791309442.0
  },
  {
   "id": "TASK-2610",
   "title": "Add the card layout",
   "lane": "waiting",
   "milestone": "m-58",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791132273.0
  },
  {
   "id": "TASK-2637",
   "title": "Rename the lint rule for new users",
   "lane": "waiting",
   "milestone": "m-83",
   "labels": [
    "kind-decide",
    "retro-m-83",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2648"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791140661.0
  },
  {
   "id": "TASK-2648",
   "title": "Retire the digest job after a rebase",
   "lane": "waiting",
   "milestone": "m-83",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791163663.0
  },
  {
   "id": "TASK-2664",
   "title": "Retire the webhook handler under load",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "kind-decide",
    "retro-m-85",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2674",
    "TASK-2892",
    "TASK-2924"
   ],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791313761.0
  },
  {
   "id": "TASK-2674",
   "title": "Add the import check",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791310116.0
  },
  {
   "id": "TASK-2682",
   "title": "Cache the cache layer",
   "lane": "waiting",
   "milestone": "m-86",
   "labels": [
    "kind-decide",
    "retro-m-86",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2685",
    "TASK-2686"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791163911.0
  },
  {
   "id": "TASK-2685",
   "title": "Rename the webhook handler with a clear error",
   "lane": "waiting",
   "milestone": "m-86",
   "labels": [
    "kind-diagnose",
    "size-2"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791215770.0
  },
  {
   "id": "TASK-2686",
   "title": "Wire the sync worker",
   "lane": "waiting",
   "milestone": "m-86",
   "labels": [
    "kind-diagnose",
    "size-1"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791164778.0
  },
  {
   "id": "TASK-2688",
   "title": "Tune the alert rule",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "kind-decide",
    "retro-m-87",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2742",
    "TASK-2743"
   ],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791338330.2590647
   },
   "moves": {},
   "entered": 1791338407.869398
  },
  {
   "id": "TASK-2701",
   "title": "Rename the token scope",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "kind-decide",
    "retro-m-88",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2706",
    "TASK-2904",
    "TASK-2907"
   ],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791324989.0736969
   },
   "moves": {},
   "entered": 1791325026.0
  },
  {
   "id": "TASK-2702",
   "title": "Wire the export path with a test",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "kind-decide",
    "retro-m-89",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2715",
    "TASK-2883"
   ],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791337867.8812537
   },
   "moves": {},
   "entered": 1791337900.361732
  },
  {
   "id": "TASK-2706",
   "title": "Add the migration step for large boards",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 49,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2308,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791311074.0
  },
  {
   "id": "TASK-2715",
   "title": "Harden the session timer under load",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "kind-diagnose",
    "size-2",
    "starpulse"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791337271.019204
   },
   "moves": {},
   "entered": 1791337316.610325
  },
  {
   "id": "TASK-2720",
   "title": "Tune the session timer",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 67,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2364,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791328132.6828978
   },
   "moves": {},
   "entered": 1791328305.0
  },
  {
   "id": "TASK-2742",
   "title": "Simplify the cache layer for new users",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "kind-execute",
    "size-5",
    "starpulse"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 42,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2263,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791335756.67845
   },
   "moves": {},
   "entered": 1791336007.0
  },
  {
   "id": "TASK-2743",
   "title": "Verify the retry budget",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "kind-diagnose",
    "size-2",
    "starpulse"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2742"
   ],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791337205.8626652
   },
   "moves": {},
   "entered": 1791337253.4568079
  },
  {
   "id": "TASK-2759",
   "title": "Verify the search index with a test",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "kind-diagnose",
    "size-2"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791226246.0
  },
  {
   "id": "TASK-2767",
   "title": "Trim the sync worker for large boards",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "alert-investigation-handoff-alert-investigation-9438429d39fb2d28-human",
    "alert-owner-healthcheck-failed-dagu-jobs--host-a-cr-sweep",
    "kind-diagnose",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791336841.9238803
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791336921.9423747
  },
  {
   "id": "TASK-2780",
   "title": "Measure the search index without a restart",
   "lane": "waiting",
   "milestone": "m-94",
   "labels": [
    "kind-decide",
    "retro-m-94",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2782",
    "TASK-2783",
    "TASK-2784"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791233508.0
  },
  {
   "id": "TASK-2782",
   "title": "Wire the token scope for large boards",
   "lane": "done",
   "milestone": "m-94",
   "labels": [
    "kind-decide",
    "size-8"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2260,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791302175.0
  },
  {
   "id": "TASK-2783",
   "title": "Trim the export path behind a flag",
   "lane": "done",
   "milestone": "m-94",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2782"
   ],
   "prs": [
    {
     "number": 2299,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791306071.0
  },
  {
   "id": "TASK-2784",
   "title": "Tune the webhook handler for the demo",
   "lane": "in_progress",
   "milestone": "m-94",
   "labels": [
    "kind-diagnose",
    "size-2"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2783"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791307925.0
  },
  {
   "id": "TASK-2793",
   "title": "Move the card layout with a clear error",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791268629.0
  },
  {
   "id": "TASK-2813",
   "title": "Rename the review queue",
   "lane": "waiting",
   "milestone": "m-96",
   "labels": [
    "kind-decide",
    "retro-m-96",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2816",
    "TASK-2817",
    "TASK-2818",
    "TASK-2819"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791247250.0
  },
  {
   "id": "TASK-2816",
   "title": "Tune the demo fixture on cold start",
   "lane": "done",
   "milestone": "m-96",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2236,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 51,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2303,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791308859.0
  },
  {
   "id": "TASK-2817",
   "title": "Audit the release notes",
   "lane": "done",
   "milestone": "m-96",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2236,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 54,
     "checks": "failing",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2306,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791310481.0
  },
  {
   "id": "TASK-2818",
   "title": "Add the nightly run after a rebase",
   "lane": "done",
   "milestone": "m-96",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2236,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 53,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2300,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791307669.0
  },
  {
   "id": "TASK-2819",
   "title": "Fix the search index",
   "lane": "waiting",
   "milestone": "m-96",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2236,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791311039.0
  },
  {
   "id": "TASK-2826",
   "title": "Cache the webhook handler",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2767"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791255786.0
  },
  {
   "id": "TASK-2831",
   "title": "Trim the digest job for the demo",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "kind-decide",
    "retro-m-98",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2835"
   ],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791305918.0
  },
  {
   "id": "TASK-2835",
   "title": "Fix the board snapshot with a test",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "execution-ready",
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2289,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791301502.0
  },
  {
   "id": "TASK-2842",
   "title": "Cache the token scope without a restart",
   "lane": "done",
   "milestone": "m-92",
   "labels": [
    "kind-execute",
    "size-2",
    "starpulse"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2278,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791302272.0
  },
  {
   "id": "TASK-2844",
   "title": "Measure the cache layer behind a flag",
   "lane": "done",
   "milestone": "m-92",
   "labels": [
    "kind-execute",
    "size-1",
    "starpulse"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [
    "TASK-2842"
   ],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791304046.0
  },
  {
   "id": "TASK-2852",
   "title": "Document the review queue in the sample repo",
   "lane": "done",
   "milestone": "m-99",
   "labels": [
    "bin",
    "deploy",
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2291,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791301788.0
  },
  {
   "id": "TASK-2853",
   "title": "Split the card layout",
   "lane": "waiting",
   "milestone": "m-99",
   "labels": [
    "kind-decide",
    "retro-m-99",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2852",
    "TASK-2856",
    "TASK-2857",
    "TASK-2858",
    "TASK-2860",
    "TASK-2861",
    "TASK-2862"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791267515.0
  },
  {
   "id": "TASK-2856",
   "title": "Retire the board snapshot without a restart",
   "lane": "waiting",
   "milestone": "m-99",
   "labels": [
    "bin",
    "deploy",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791318347.0
  },
  {
   "id": "TASK-2857",
   "title": "Move the import check in one pass",
   "lane": "done",
   "milestone": "m-99",
   "labels": [
    "agent-jobs",
    "bin",
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2292,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791301723.0
  },
  {
   "id": "TASK-2858",
   "title": "Cache the demo fixture behind a flag",
   "lane": "waiting",
   "milestone": "m-99",
   "labels": [
    "agent-jobs",
    "bin",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791303616.0
  },
  {
   "id": "TASK-2860",
   "title": "Measure the nightly run for the demo",
   "lane": "waiting",
   "milestone": "m-99",
   "labels": [
    "agent-jobs",
    "bin",
    "kind-mechanical",
    "size-5"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [
    "TASK-2858"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791268208.0
  },
  {
   "id": "TASK-2861",
   "title": "Rename the search index after a rebase",
   "lane": "done",
   "milestone": "m-99",
   "labels": [
    "bin",
    "kind-mechanical",
    "size-3"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2293,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791301660.0
  },
  {
   "id": "TASK-2862",
   "title": "Wire the report page",
   "lane": "done",
   "milestone": "m-99",
   "labels": [
    "bin",
    "kind-mechanical",
    "size-5",
    "skill-evals"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2286,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791302274.0
  },
  {
   "id": "TASK-2866",
   "title": "Add the sync worker",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "kind-decide",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 50,
     "checks": "failing",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791304549.0
  },
  {
   "id": "TASK-2867",
   "title": "Fix the status badge under load",
   "lane": "done",
   "milestone": "m-84",
   "labels": [
    "adr-needed",
    "kind-decide",
    "size-2"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2287,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791302026.0
  },
  {
   "id": "TASK-2868",
   "title": "Document the migration step",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "bin",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791304104.0
  },
  {
   "id": "TASK-2873",
   "title": "Move the review queue behind a flag",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2305,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791311096.0
  },
  {
   "id": "TASK-2875",
   "title": "Harden the health probe without a restart",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 117,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791305644.0
  },
  {
   "id": "TASK-2876",
   "title": "Measure the label filter",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2342,
     "checks": "pass",
     "merged": false,
     "threads": 0
    },
    {
     "number": 2360,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 124,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791328262.8592687
   },
   "moves": {},
   "entered": 1791328522.0
  },
  {
   "id": "TASK-2877",
   "title": "Rename the board snapshot on cold start",
   "lane": "waiting",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791272745.0
  },
  {
   "id": "TASK-1349",
   "title": "Split the release notes in one pass",
   "lane": "needs_attention",
   "milestone": "m-2",
   "labels": [
    "kind-execute",
    "size-3",
    "testing"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791266571.0
  },
  {
   "id": "TASK-1489",
   "title": "Audit the alert rule",
   "lane": "waiting",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-2",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-1878"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790616796.0
  },
  {
   "id": "TASK-1566",
   "title": "Wire the config loader in one pass",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "frigate",
    "kind-execute",
    "local-model",
    "size-5",
    "nas"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790630426.0
  },
  {
   "id": "TASK-1672",
   "title": "Retire the alert rule with a clear error",
   "lane": "needs_attention",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790922569.0
  },
  {
   "id": "TASK-1674",
   "title": "Cache the review queue without a restart",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553613.0
  },
  {
   "id": "TASK-1675",
   "title": "Harden the card layout",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553632.0
  },
  {
   "id": "TASK-1676",
   "title": "Measure the health probe behind a flag",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553650.0
  },
  {
   "id": "TASK-1677",
   "title": "Rename the label filter",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553669.0
  },
  {
   "id": "TASK-1678",
   "title": "Wire the board snapshot after a rebase",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553686.0
  },
  {
   "id": "TASK-1679",
   "title": "Trim the import check after a rebase",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553702.0
  },
  {
   "id": "TASK-1680",
   "title": "Tune the search index under load",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553719.0
  },
  {
   "id": "TASK-1681",
   "title": "Audit the report page on cold start",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553774.0
  },
  {
   "id": "TASK-1682",
   "title": "Add the token scope for new users",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553801.0
  },
  {
   "id": "TASK-1683",
   "title": "Fix the session timer",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553845.0
  },
  {
   "id": "TASK-1684",
   "title": "Document the cache layer under load",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553894.0
  },
  {
   "id": "TASK-1685",
   "title": "Split the retry budget with a test",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790553928.0
  },
  {
   "id": "TASK-1710",
   "title": "Wire the status badge for the demo",
   "lane": "ready",
   "milestone": "m-42",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790700916.0
  },
  {
   "id": "TASK-1779",
   "title": "Fix the demo fixture in one pass",
   "lane": "ready",
   "milestone": "m-49",
   "labels": [
    "agent-profile",
    "kind-decide",
    "size-2"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790651625.0
  },
  {
   "id": "TASK-1878",
   "title": "Simplify the label filter",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-execute",
    "size-3",
    "skill-eval"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790645111.0
  },
  {
   "id": "TASK-1882",
   "title": "Cache the release notes",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "host-a",
    "disk",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790700685.0
  },
  {
   "id": "TASK-1889",
   "title": "Audit the sync worker behind a flag",
   "lane": "waiting",
   "milestone": "m-2",
   "labels": [
    "kind-decide",
    "retro-m-2",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-1349"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790638757.0
  },
  {
   "id": "TASK-1890",
   "title": "Add the report page",
   "lane": "waiting",
   "milestone": "m-35",
   "labels": [
    "kind-decide",
    "retro-m-35",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-1489",
    "TASK-1878",
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
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790638765.0
  },
  {
   "id": "TASK-1894",
   "title": "Simplify the alert rule on cold start",
   "lane": "waiting",
   "milestone": "m-42",
   "labels": [
    "kind-decide",
    "retro-m-42",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-1710"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790638791.0
  },
  {
   "id": "TASK-1896",
   "title": "Retire the review queue after a rebase",
   "lane": "waiting",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "retro-m-44",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-1672",
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
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790638809.0
  },
  {
   "id": "TASK-1901",
   "title": "Rename the import check",
   "lane": "waiting",
   "milestone": "m-49",
   "labels": [
    "kind-decide",
    "retro-m-49",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-1779"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790638840.0
  },
  {
   "id": "TASK-2009",
   "title": "Move the retry budget",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2925",
    "TASK-2941"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791323467.0
  },
  {
   "id": "TASK-2012",
   "title": "Measure the sync worker behind a flag",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697384.0
  },
  {
   "id": "TASK-2013",
   "title": "Rename the report page for the demo",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697390.0
  },
  {
   "id": "TASK-2014",
   "title": "Wire the migration step without a restart",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697397.0
  },
  {
   "id": "TASK-2015",
   "title": "Trim the export path",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697404.0
  },
  {
   "id": "TASK-2016",
   "title": "Tune the review queue for large boards",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697412.0
  },
  {
   "id": "TASK-2017",
   "title": "Audit the card layout",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697420.0
  },
  {
   "id": "TASK-2018",
   "title": "Add the status badge for new users",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697427.0
  },
  {
   "id": "TASK-2019",
   "title": "Fix the label filter after a rebase",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697435.0
  },
  {
   "id": "TASK-2020",
   "title": "Document the board snapshot under load",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "size-5",
    "skills"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "in_progress": {
     "allowed": true,
     "skill": ""
    },
    "waiting": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1790697444.0
  },
  {
   "id": "TASK-2880",
   "title": "Tune the report page after a rebase",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791301482.0
  },
  {
   "id": "TASK-2883",
   "title": "Fix the cache layer",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2297,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791305721.0
  },
  {
   "id": "TASK-2884",
   "title": "Document the retry budget in the sample repo",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2876"
   ],
   "prs": [
    {
     "number": 2380,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791332541.7757075
   },
   "moves": {},
   "entered": 1791332742.0
  },
  {
   "id": "TASK-2885",
   "title": "Split the lint rule without a restart",
   "lane": "waiting",
   "milestone": "m-100",
   "labels": [
    "kind-decide",
    "retro-m-100",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2873",
    "TASK-2875",
    "TASK-2876",
    "TASK-2877",
    "TASK-2884",
    "TASK-2961",
    "TASK-2963",
    "TASK-2974",
    "TASK-2978",
    "TASK-2983",
    "TASK-2984",
    "TASK-2985"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791303339.0
  },
  {
   "id": "TASK-2888",
   "title": "Retire the status badge with a clear error",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 50,
     "checks": "failing",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791306921.0
  },
  {
   "id": "TASK-2889",
   "title": "Move the migration step",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "kind-decide",
    "retro-m-102",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2888",
    "TASK-2890",
    "TASK-2891"
   ],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791311681.0
  },
  {
   "id": "TASK-2890",
   "title": "Cache the export path for large boards",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [
    "TASK-2888"
   ],
   "prs": [
    {
     "number": 2311,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791310317.0
  },
  {
   "id": "TASK-2891",
   "title": "Harden the digest job",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [
    "TASK-2890"
   ],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791310862.0
  },
  {
   "id": "TASK-2892",
   "title": "Measure the alert rule on cold start",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 114,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 118,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791306334.0
  },
  {
   "id": "TASK-2895",
   "title": "Trim the card layout",
   "lane": "done",
   "milestone": "m-103",
   "labels": [
    "kind-decide",
    "size-8"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791307122.0
  },
  {
   "id": "TASK-2896",
   "title": "Tune the import check on cold start",
   "lane": "done",
   "milestone": "m-103",
   "labels": [
    "kind-decide",
    "retro-m-103",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2895",
    "TASK-2897",
    "TASK-2898"
   ],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791308519.0
  },
  {
   "id": "TASK-2897",
   "title": "Audit the demo fixture for new users",
   "lane": "done",
   "milestone": "m-103",
   "labels": [
    "kind-decide",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791306848.0
  },
  {
   "id": "TASK-2898",
   "title": "Add the release notes with a clear error",
   "lane": "done",
   "milestone": "m-103",
   "labels": [
    "kind-decide",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791306689.0
  },
  {
   "id": "TASK-2900",
   "title": "Document the search index in one pass",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "kind-diagnose",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791309103.0
  },
  {
   "id": "TASK-2901",
   "title": "Split the report page with a test",
   "lane": "waiting",
   "milestone": "m-98",
   "labels": [
    "kind-diagnose",
    "size-2"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791317396.0
  },
  {
   "id": "TASK-2902",
   "title": "Simplify the token scope",
   "lane": "waiting",
   "milestone": "m-98",
   "labels": [
    "kind-diagnose",
    "size-2"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791305795.0
  },
  {
   "id": "TASK-2903",
   "title": "Verify the session timer without a restart",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "kind-decide",
    "size-1"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2310,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791308096.0
  },
  {
   "id": "TASK-2904",
   "title": "Retire the cache layer",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 57,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2348,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791324316.0
  },
  {
   "id": "TASK-2907",
   "title": "Harden the webhook handler for the demo",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 56,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791309091.0
  },
  {
   "id": "TASK-2908",
   "title": "Measure the sync worker",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "adr-needed",
    "kind-decide",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2312,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791309093.0
  },
  {
   "id": "TASK-2909",
   "title": "Rename the status badge for large boards",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2908"
   ],
   "prs": [
    {
     "number": 2338,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791322627.0
  },
  {
   "id": "TASK-2910",
   "title": "Wire the migration step",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2320,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791311974.0
  },
  {
   "id": "TASK-2911",
   "title": "Trim the export path with a test",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "kind-decide",
    "retro-m-105",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2910",
    "TASK-2913",
    "TASK-2915",
    "TASK-2916"
   ],
   "prs": [],
   "live": null,
   "moves": {},
   "entered": 1791314306.0
  },
  {
   "id": "TASK-2912",
   "title": "Tune the review queue for new users",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791323558.0042558
   },
   "moves": {},
   "entered": 1791323586.0
  },
  {
   "id": "TASK-2913",
   "title": "Audit the card layout in the sample repo",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2314,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791310493.0
  },
  {
   "id": "TASK-2914",
   "title": "Add the health probe under load",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "kind-decide",
    "retro-m-104",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2908",
    "TASK-2909",
    "TASK-2912"
   ],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791324221.1418898
   },
   "moves": {},
   "entered": 1791324244.0
  },
  {
   "id": "TASK-2915",
   "title": "Fix the label filter with a test",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2319,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791313006.0
  },
  {
   "id": "TASK-2916",
   "title": "Document the board snapshot",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2315,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791313215.0
  },
  {
   "id": "TASK-2922",
   "title": "Cache the report page without a restart",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "adr-needed",
    "kind-diagnose",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2324,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791316524.0
  },
  {
   "id": "TASK-2924",
   "title": "Measure the session timer under load",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "kind-mechanical",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 119,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791311416.0
  },
  {
   "id": "TASK-2925",
   "title": "Rename the cache layer",
   "lane": "done",
   "milestone": "m-35",
   "labels": [
    "adr-needed",
    "kind-decide",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2335,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791316161.0
  },
  {
   "id": "TASK-2926",
   "title": "Wire the retry budget for new users",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "adr-needed",
    "kind-decide",
    "size-2"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2321,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791313343.0
  },
  {
   "id": "TASK-2928",
   "title": "Tune the migration step under load",
   "lane": "done",
   "milestone": "m-106",
   "labels": [
    "adr-needed",
    "kind-decide",
    "size-2"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2332,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791314758.0
  },
  {
   "id": "TASK-2929",
   "title": "Audit the export path",
   "lane": "done",
   "milestone": "m-106",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2928"
   ],
   "prs": [
    {
     "number": 2337,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791317249.0
  },
  {
   "id": "TASK-2930",
   "title": "Add the digest job with a test",
   "lane": "done",
   "milestone": "m-106",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2928",
    "TASK-2929"
   ],
   "prs": [
    {
     "number": 2347,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791322683.0
  },
  {
   "id": "TASK-2931",
   "title": "Fix the alert rule",
   "lane": "done",
   "milestone": "m-106",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2928",
    "TASK-2930"
   ],
   "prs": [
    {
     "number": 63,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791323515.2252655
   },
   "moves": {},
   "entered": 1791323719.0
  },
  {
   "id": "TASK-2932",
   "title": "Document the config loader without a restart",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 122,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791314305.0
  },
  {
   "id": "TASK-2933",
   "title": "Split the review queue in one pass",
   "lane": "waiting",
   "milestone": "m-106",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791323857.8935466
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791323898.0
  },
  {
   "id": "TASK-2935",
   "title": "Verify the health probe with a clear error",
   "lane": "waiting",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791314495.0
  },
  {
   "id": "TASK-2936",
   "title": "Retire the label filter for the demo",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "kind-mechanical",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2329,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791314372.0
  },
  {
   "id": "TASK-2937",
   "title": "Move the board snapshot after a rebase",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "kind-mechanical",
    "size-1"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 121,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791314725.0
  },
  {
   "id": "TASK-2938",
   "title": "Cache the import check",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "kind-decide",
    "size-1"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2330,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791314491.0
  },
  {
   "id": "TASK-2940",
   "title": "Measure the release notes for new users",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2336,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791318024.0
  },
  {
   "id": "TASK-2941",
   "title": "Rename the nightly run after a rebase",
   "lane": "done",
   "milestone": "m-35",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2339,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791323287.8153322
   },
   "moves": {},
   "entered": 1791323465.0
  },
  {
   "id": "TASK-2942",
   "title": "Wire the search index under load",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2361,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791330264.7756279
   },
   "moves": {},
   "entered": 1791330321.0
  },
  {
   "id": "TASK-2943",
   "title": "Trim the report page under load",
   "lane": "waiting",
   "milestone": "m-75",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2988"
   ],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "needs_attention",
    "at": 1791331351.9956045
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791337681.412143
  },
  {
   "id": "TASK-2944",
   "title": "Tune the retry budget",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2344,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791322695.0
  },
  {
   "id": "TASK-2945",
   "title": "Audit the lint rule with a clear error",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "kind-decide",
    "size-1"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2340,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791318035.0
  },
  {
   "id": "TASK-2947",
   "title": "Fix the sync worker in one pass",
   "lane": "done",
   "milestone": "m-107",
   "labels": [
    "adr-needed",
    "kind-decide",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2343,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": null,
   "moves": {},
   "entered": 1791322776.0
  },
  {
   "id": "TASK-2948",
   "title": "Document the status badge with a test",
   "lane": "waiting",
   "milestone": "m-107",
   "labels": [
    "kind-decide",
    "retro-m-107",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2947",
    "TASK-2949",
    "TASK-2950",
    "TASK-2951",
    "TASK-2952",
    "TASK-2953"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791317553.0
  },
  {
   "id": "TASK-2949",
   "title": "Split the migration step behind a flag",
   "lane": "done",
   "milestone": "m-107",
   "labels": [
    "kind-execute",
    "size-8"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2947"
   ],
   "prs": [
    {
     "number": 2353,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791328745.3422155
   },
   "moves": {},
   "entered": 1791328831.0
  },
  {
   "id": "TASK-2950",
   "title": "Simplify the export path",
   "lane": "done",
   "milestone": "m-107",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2949"
   ],
   "prs": [
    {
     "number": 2385,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791334303.5221822
   },
   "moves": {},
   "entered": 1791334558.0
  },
  {
   "id": "TASK-2951",
   "title": "Verify the digest job without a restart",
   "lane": "waiting",
   "milestone": "m-107",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791334663.8705814
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791334677.0
  },
  {
   "id": "TASK-2952",
   "title": "Retire the alert rule",
   "lane": "waiting",
   "milestone": "m-107",
   "labels": [
    "kind-decide",
    "size-8"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [
    "TASK-2947",
    "TASK-2951",
    "TASK-2901"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791317706.0
  },
  {
   "id": "TASK-2953",
   "title": "Move the config loader on cold start",
   "lane": "waiting",
   "milestone": "m-107",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [
    "TASK-2952"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791317754.0
  },
  {
   "id": "TASK-2956",
   "title": "Measure the health probe after a rebase",
   "lane": "waiting",
   "milestone": "m-78",
   "labels": [
    "kind-mechanical",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 59,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791322886.9530654
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791329913.0
  },
  {
   "id": "TASK-2959",
   "title": "Trim the import check",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2356,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791326139.0680635
   },
   "moves": {},
   "entered": 1791326723.0
  },
  {
   "id": "TASK-2960",
   "title": "Tune the search index in the sample repo",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "kind-decide",
    "size-1"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2352,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791325013.4742274
   },
   "moves": {},
   "entered": 1791325161.0
  },
  {
   "id": "TASK-2961",
   "title": "Audit the report page",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 123,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791325957.5726473
   },
   "moves": {},
   "entered": 1791326538.0
  },
  {
   "id": "TASK-2963",
   "title": "Fix the session timer",
   "lane": "waiting",
   "milestone": "m-100",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791326687.9775498
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791326887.0
  },
  {
   "id": "TASK-2964",
   "title": "Document the cache layer with a clear error",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "adr-needed",
    "kind-mechanical",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [
    "TASK-2942"
   ],
   "prs": [
    {
     "number": 57,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2377,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791331266.686969
   },
   "moves": {},
   "entered": 1791331331.0
  },
  {
   "id": "TASK-2965",
   "title": "Split the retry budget",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "adr-needed",
    "kind-decide",
    "size-2"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2355,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791325570.034233
   },
   "moves": {},
   "entered": 1791325783.0
  },
  {
   "id": "TASK-2967",
   "title": "Verify the webhook handler",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2365,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791338639.1772223
   },
   "moves": {},
   "entered": 1791340638.014468
  },
  {
   "id": "TASK-2968",
   "title": "Retire the sync worker for the demo",
   "lane": "done",
   "milestone": "m-108",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2369,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791337565.8883781
   },
   "moves": {},
   "entered": 1791337647.0144382
  },
  {
   "id": "TASK-2969",
   "title": "Move the status badge for the demo",
   "lane": "waiting",
   "milestone": "m-108",
   "labels": [
    "kind-decide",
    "retro-m-108",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-2968",
    "TASK-2971",
    "TASK-2972"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791326651.0
  },
  {
   "id": "TASK-2971",
   "title": "Harden the export path",
   "lane": "done",
   "milestone": "m-108",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2368,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791329514.0486124
   },
   "moves": {},
   "entered": 1791329632.0
  },
  {
   "id": "TASK-2972",
   "title": "Measure the digest job on cold start",
   "lane": "waiting",
   "milestone": "m-108",
   "labels": [
    "adr-needed",
    "kind-diagnose",
    "size-2"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791326880.0
  },
  {
   "id": "TASK-2973",
   "title": "Rename the alert rule for new users",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "kind-mechanical",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 68,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791329847.1414506
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791333057.0
  },
  {
   "id": "TASK-2974",
   "title": "Wire the config loader in the sample repo",
   "lane": "in_progress",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2983"
   ],
   "prs": [
    {
     "number": 124,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2360,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791329037.4140956
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791335261.0
  },
  {
   "id": "TASK-2975",
   "title": "Trim the review queue in the sample repo",
   "lane": "done",
   "milestone": "",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2372,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791330846.0453897
   },
   "moves": {},
   "entered": 1791330970.0
  },
  {
   "id": "TASK-2976",
   "title": "Tune the board snapshot in one pass",
   "lane": "done",
   "milestone": "",
   "labels": [
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "checkpointed",
    "at": 1791331047.9334624
   },
   "moves": {},
   "entered": 1791331071.0
  },
  {
   "id": "TASK-2977",
   "title": "Audit the import check with a test",
   "lane": "done",
   "milestone": "",
   "labels": [
    "adr-needed",
    "ci",
    "kind-diagnose",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2381,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791332010.8423822
   },
   "moves": {},
   "entered": 1791333202.0
  },
  {
   "id": "TASK-2978",
   "title": "Add the demo fixture",
   "lane": "waiting",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [
    "TASK-2884",
    "TASK-2974",
    "TASK-2985"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791331097.0
  },
  {
   "id": "TASK-2979",
   "title": "Fix the release notes without a restart",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2381,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791333751.4619856
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791336938.8502576
  },
  {
   "id": "TASK-2980",
   "title": "Document the nightly run",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "kind-mechanical",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791334852.085815
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791334889.0
  },
  {
   "id": "TASK-2981",
   "title": "Split the search index behind a flag",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 75,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791334778.6286137
   },
   "moves": {},
   "entered": 1791334817.0
  },
  {
   "id": "TASK-2982",
   "title": "Simplify the report page",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2370,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "lint_green",
    "at": 1791341193.000166
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791340589.961225
  },
  {
   "id": "TASK-2983",
   "title": "Verify the token scope for the demo",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2388,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791334825.2200885
   },
   "moves": {},
   "entered": 1791335056.0
  },
  {
   "id": "TASK-2984",
   "title": "Retire the session timer",
   "lane": "needs_attention",
   "milestone": "m-100",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "needs_attention",
    "at": 1791340621.764007
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791340621.1360836
  },
  {
   "id": "TASK-2985",
   "title": "Move the cache layer for large boards",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2386,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791334309.977648
   },
   "moves": {},
   "entered": 1791334502.0
  },
  {
   "id": "TASK-2986",
   "title": "Cache the retry budget",
   "lane": "done",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 77,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2394,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791336070.151984
   },
   "moves": {},
   "entered": 1791336741.8914237
  },
  {
   "id": "TASK-2987",
   "title": "Harden the lint rule for new users",
   "lane": "done",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2392,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791336889.6977205
   },
   "moves": {},
   "entered": 1791336914.338116
  },
  {
   "id": "TASK-2988",
   "title": "Measure the webhook handler for new users",
   "lane": "needs_attention",
   "milestone": "m-75",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "needs_attention",
    "at": 1791335025.9631844
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791335025.0
  },
  {
   "id": "TASK-2989",
   "title": "Rename the sync worker in the sample repo",
   "lane": "done",
   "milestone": "",
   "labels": [
    "alert-owner-mutation-survivor-aged",
    "alert-owner-mutation-sweep-stale",
    "unattended"
   ],
   "assignee": "",
   "dependencies": [],
   "prs": [
    {
     "number": 2393,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "ci_green",
    "at": 1791336609.8711617
   },
   "moves": {},
   "entered": 1791336651.7822793
  },
  {
   "id": "TASK-2990",
   "title": "Wire the status badge under load",
   "lane": "done",
   "milestone": "",
   "labels": [
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2397,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791337189.099467
   },
   "moves": {},
   "entered": 1791337464.5129158
  },
  {
   "id": "TASK-2991",
   "title": "Trim the migration step with a test",
   "lane": "done",
   "milestone": "",
   "labels": [
    "kind-diagnose",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2989"
   ],
   "prs": [
    {
     "number": 2393,
     "checks": "pass",
     "merged": true,
     "threads": 0
    },
    {
     "number": 2401,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791339237.071407
   },
   "moves": {},
   "entered": 1791340664.4765594
  },
  {
   "id": "TASK-2993",
   "title": "Audit the review queue",
   "lane": "done",
   "milestone": "",
   "labels": [
    "kind-diagnose",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2405,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791339960.6819994
   },
   "moves": {},
   "entered": 1791340077.2283661
  },
  {
   "id": "TASK-2994",
   "title": "Add the card layout in one pass",
   "lane": "done",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-2"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 79,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791338985.4561944
   },
   "moves": {},
   "entered": 1791339936.9204617
  },
  {
   "id": "TASK-2995",
   "title": "Fix the status badge for large boards",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-diagnose",
    "size-1"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791340289.374892
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791340312.020916
  },
  {
   "id": "TASK-2996",
   "title": "Document the label filter behind a flag",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "kind-decide",
    "size-1"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2402,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791338549.7022357
   },
   "moves": {},
   "entered": 1791340520.2553742
  },
  {
   "id": "TASK-2997",
   "title": "Split the board snapshot for the demo",
   "lane": "in_progress",
   "milestone": "m-89",
   "labels": [
    "kind-execute",
    "size-2",
    "starpulse"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "committed",
    "at": 1791341843.9077046
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791338007.54204
  },
  {
   "id": "TASK-2998",
   "title": "Simplify the import check without a restart",
   "lane": "review",
   "milestone": "m-89",
   "labels": [
    "kind-decide",
    "size-2"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2404,
     "checks": "pass",
     "merged": false,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791340796.315805
   },
   "moves": {
    "done": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791340796.304506
  },
  {
   "id": "TASK-2999",
   "title": "Verify the demo fixture",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "kind-execute",
    "size-3",
    "starpulse"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 81,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791339900.2743473
   },
   "moves": {},
   "entered": 1791340523.075901
  },
  {
   "id": "TASK-3000",
   "title": "Retire the release notes on cold start",
   "lane": "waiting",
   "milestone": "m-87",
   "labels": [
    "kind-execute",
    "size-5",
    "starpulse"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 82,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "pr_opened",
    "at": 1791340191.1503844
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791340673.669691
  },
  {
   "id": "TASK-3001",
   "title": "Move the nightly run",
   "lane": "waiting",
   "milestone": "m-87",
   "labels": [
    "kind-diagnose",
    "size-2",
    "starpulse"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-3000"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791338066.1799147
  },
  {
   "id": "TASK-3002",
   "title": "Cache the search index for new users",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "kind-decide",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "lint_green",
    "at": 1791340424.4363751
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791338113.4339268
  },
  {
   "id": "TASK-3003",
   "title": "Harden the report page after a rebase",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "kind-execute",
    "size-3",
    "starpulse"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [
    {
     "number": 2406,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791340356.117874
   },
   "moves": {},
   "entered": 1791340447.1567743
  },
  {
   "id": "TASK-3004",
   "title": "Measure the token scope under load",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "kind-diagnose",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "lint_green",
    "at": 1791341969.8577702
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791338250.2855096
  },
  {
   "id": "TASK-3005",
   "title": "Rename the session timer",
   "lane": "needs_attention",
   "milestone": "m-87",
   "labels": [
    "kind-execute",
    "size-2",
    "starpulse"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "needs_attention",
    "at": 1791338775.4815416
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791338775.1134768
  },
  {
   "id": "TASK-3006",
   "title": "Wire the cache layer for new users",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "kind-decide",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2411,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791341140.4775808
   },
   "moves": {},
   "entered": 1791341713.3602476
  },
  {
   "id": "TASK-3007",
   "title": "Trim the retry budget",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "kind-execute",
    "size-1"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [
    {
     "number": 2401,
     "checks": "pass",
     "merged": true,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791340716.259662
   },
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791340760.1233954
  },
  {
   "id": "TASK-3008",
   "title": "Tune the report page without a restart",
   "lane": "review",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [
    "TASK-2994"
   ],
   "prs": [
    {
     "number": 84,
     "checks": "pass",
     "merged": false,
     "threads": 0
    }
   ],
   "live": {
    "machine": "in-progress",
    "state": "review_recorded",
    "at": 1791341977.8600388
   },
   "moves": {
    "done": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341977.85236
  },
  {
   "id": "TASK-3009",
   "title": "Audit the migration step in one pass",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-diagnose",
    "size-5"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341850.6981335
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341808.7837713
  },
  {
   "id": "TASK-3010",
   "title": "Add the export path behind a flag",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341845.7525802
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341788.7701657
  },
  {
   "id": "TASK-3011",
   "title": "Fix the digest job with a clear error",
   "lane": "waiting",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "retro-m-109",
    "size-3"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [
    "TASK-3010",
    "TASK-3012",
    "TASK-3013",
    "TASK-3014",
    "TASK-3015",
    "TASK-3016",
    "TASK-3017",
    "TASK-3018",
    "TASK-3019",
    "TASK-3020",
    "TASK-3021",
    "TASK-3022",
    "TASK-3023",
    "TASK-3024",
    "TASK-3025"
   ],
   "prs": [],
   "live": null,
   "moves": {
    "ready": {
     "allowed": true,
     "skill": ""
    },
    "in_progress": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791340773.550473
  },
  {
   "id": "TASK-3012",
   "title": "Document the alert rule without a restart",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341847.5098283
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341792.7873302
  },
  {
   "id": "TASK-3013",
   "title": "Split the config loader",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341849.4536066
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341797.0542786
  },
  {
   "id": "TASK-3014",
   "title": "Simplify the review queue",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341845.401866
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341785.708719
  },
  {
   "id": "TASK-3015",
   "title": "Verify the card layout on cold start",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341836.3461933
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341760.4874425
  },
  {
   "id": "TASK-3016",
   "title": "Retire the health probe",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341842.3515997
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341774.5560918
  },
  {
   "id": "TASK-3017",
   "title": "Move the label filter after a rebase",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341830.9536452
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341756.8628986
  },
  {
   "id": "TASK-3018",
   "title": "Cache the board snapshot under load",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341832.6864343
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341750.527222
  },
  {
   "id": "TASK-3019",
   "title": "Harden the import check on cold start",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341825.5969934
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341747.455327
  },
  {
   "id": "TASK-3020",
   "title": "Measure the demo fixture",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341824.9471242
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341758.7632062
  },
  {
   "id": "TASK-3021",
   "title": "Rename the release notes with a clear error",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-execute",
    "size-2",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341804.79113
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341739.3201141
  },
  {
   "id": "TASK-3022",
   "title": "Wire the nightly run",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-diagnose",
    "size-3",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341804.6711628
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341742.9913065
  },
  {
   "id": "TASK-3023",
   "title": "Trim the search index in one pass",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-execute",
    "size-2",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-standard-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341807.3023758
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341745.3809166
  },
  {
   "id": "TASK-3024",
   "title": "Tune the cache layer with a test",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-execute",
    "size-8",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341768.9412942
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341728.6636782
  },
  {
   "id": "TASK-3025",
   "title": "Audit the retry budget with a clear error",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "size-2",
    "starpulse",
    "ui"
   ],
   "assignee": "@agent-deep-medium",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "lint_green",
    "at": 1791341937.2792673
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341593.4700902
  },
  {
   "id": "TASK-3026",
   "title": "Add the lint rule",
   "lane": "in_progress",
   "milestone": "m-69",
   "labels": [
    "kind-execute",
    "size-5"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341854.91151
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341817.3392947
  },
  {
   "id": "TASK-3027",
   "title": "Fix the webhook handler without a restart",
   "lane": "in_progress",
   "milestone": "m-69",
   "labels": [
    "kind-execute",
    "size-3"
   ],
   "assignee": "@agent-standard-high",
   "dependencies": [],
   "prs": [],
   "live": {
    "machine": "in-progress",
    "state": "worktree_ready",
    "at": 1791341850.1790388
   },
   "moves": {
    "waiting": {
     "allowed": true,
     "skill": ""
    },
    "review": {
     "allowed": true,
     "skill": ""
    },
    "done": {
     "allowed": true,
     "skill": ""
    },
    "needs_attention": {
     "allowed": true,
     "skill": ""
    },
    "ready": {
     "allowed": true,
     "skill": ""
    }
   },
   "entered": 1791341798.0577416
  }
 ]
};
