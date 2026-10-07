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
   "title": "Tune triaging-cr-reviews to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune verifying-claims to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune completing-tasks to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune operating-unraid to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Validate the first live alert remediation the dispatcher runs",
   "lane": "waiting",
   "milestone": "m-54",
   "labels": [
    "agent-resolvable",
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
   "title": "Make designing-ui fire on the canonical UI cases its eval scores",
   "lane": "ready",
   "milestone": "m-51",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-69 and settle whether Cross-cutting audit fixes 2026-10 has reached its end state",
   "lane": "done",
   "milestone": "m-69",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Promote worktree_reap git runner to a shared git CLI seam and fail closed when git cannot list files",
   "lane": "done",
   "milestone": "m-69",
   "labels": [
    "agent-resolvable",
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
   "title": "Stop starting-tasks from entering the worktree under Claude so the isolation guard stops refusing ordinary commands",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Confirm the weekly trace-cluster-report and skill-conformance DAGs ran on their Monday schedule",
   "lane": "waiting",
   "milestone": "m-53",
   "labels": [
    "kind-mechanical",
    "needs-human",
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
   "title": "Validate native web search stopped after the AGENTS.md routing fix merged",
   "lane": "waiting",
   "milestone": "m-53",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-75 and settle whether Flow View public package: IC launch has reached its end state",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Run the clean-machine quickstart and publish the flow view package",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Retro m-78 and settle whether Flow View 0.2: GitHub Actions runs and HTTP ingest has reached its end state",
   "lane": "waiting",
   "milestone": "m-78",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Add a token-guarded HTTP ingest for flow view run events",
   "lane": "done",
   "milestone": "m-78",
   "labels": [
    "agent-resolvable",
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
   "title": "Add a GitHub Actions runs adapter to the flow view",
   "lane": "done",
   "milestone": "m-78",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-80 and settle whether Flow View hub: configured flow graph and orbit card has reached its end state",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Forward IC events to the hub over HTTPS ingest with per-instance tokens and the opt-in filter",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Gate the hub behind built-in OIDC sign-in with allowed groups, tested on a mock OIDC container",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Serve level aggregates on the flow metric definitions, including orbit shares and dwell",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Compute trajectory analytics for the level: variants, outliers, absorbing chain, betweenness and dominator gates",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Add the insights API for findings from an external engine",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Draw the level above the Board as the approved orbit card",
   "lane": "in_progress",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Show the IC's forwarding panel listing what is sent to the hub",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Add a Jira adapter that imports a project's workflow as the Board machine",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Add a GitHub adapter for pull requests, checks and Copilot",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Deploy a dogfood flow view hub on ai-vm-1 behind the mock OIDC container",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Verify the dogfood hub is live and agrees with the Backlog Board dashboard after the deploy merge",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Check m-81's 7-day gate-refusal outcome against the 40% target",
   "lane": "waiting",
   "milestone": "m-81",
   "labels": [
    "agent-resolvable",
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
   "title": "Bind a session to the task it claims and gate Stop on the task's holder",
   "lane": "done",
   "milestone": "m-58",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Refuse writes in a task worktree from a session that does not hold the task",
   "lane": "done",
   "milestone": "m-58",
   "labels": [
    "agent-resolvable",
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
   "title": "Post the Laya shadow agreement report on 50 live alert runs",
   "lane": "waiting",
   "milestone": "m-58",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Retro m-83 and settle whether Offload cheap skill subtasks has reached its end state",
   "lane": "waiting",
   "milestone": "m-83",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Verify hand start calls per task fell to 0.3 or below after the start command merged",
   "lane": "waiting",
   "milestone": "m-83",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-85 and settle whether Radarr rejects lossless audio, declared from the repo has reached its end state",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Confirm the audio conversion job cleared lossless tracks from the live movie library",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-86 and settle whether Alert Discord pings only when someone must act has reached its end state",
   "lane": "waiting",
   "milestone": "m-86",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Check that held alerts drop no-op verdicts and post every actionable one",
   "lane": "waiting",
   "milestone": "m-86",
   "labels": [
    "agent-resolvable",
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
   "title": "Check that the dagu-jobs debounce lowered its no-op investigation share",
   "lane": "waiting",
   "milestone": "m-86",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-87 and settle whether StarPulse runs without Redis has reached its end state",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Retro m-88 and settle whether StarPulse opens on its own board has reached its end state",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Retro m-89 and settle whether StarPulse Kanban task editing and archive has reached its end state",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Add New task and Connect a tracker to the top right of the StarPulse Kanban",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Post-merge check: the live StarPulse board edits and archives a task",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "agent-resolvable",
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
   "title": "Keep StarPulse hub history in daily Postgres partitions with per-day team rollups",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Resume StarPulse's Board from saved state so a restart moves only the tasks that changed",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Check a flow-view restart restores the Board without replaying the projection stream",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "agent-resolvable",
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
   "title": "Clone the starpulse submodule in Renovate so lockfile updates keep its pnpm importer",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Investigate firing alert Healthcheck Failed \u2014 dagu-jobs: needs a human",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "alert-investigation-handoff-alert-investigation-9438429d39fb2d28-human",
    "alert-owner-healthcheck-failed-dagu-jobs--ai-vm-1-cr-sweep",
    "kind-diagnose",
    "needs-human",
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
   "title": "Retro m-94 and settle whether Remote Control sessions own their task branch has reached its end state",
   "lane": "waiting",
   "milestone": "m-94",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Create task branches as claude/task-*, renaming a spawned worktree's branch in place",
   "lane": "done",
   "milestone": "m-94",
   "labels": [
    "agent-resolvable",
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
   "title": "Spawn each Remote Control session in its own worktree and reap the untasked ones",
   "lane": "done",
   "milestone": "m-94",
   "labels": [
    "agent-resolvable",
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
   "title": "Check that a Remote Control session's desktop PR badge shows its claude/task-* PR",
   "lane": "in_progress",
   "milestone": "m-94",
   "labels": [
    "kind-diagnose",
    "needs-human",
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
   "title": "Check: the first rag-audit-nominations run after TASK-2792 skips dismissed queries and fills top_file",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-96 and settle whether StarPulse shows a DAG's fan-out has reached its end state",
   "lane": "waiting",
   "milestone": "m-96",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "StarPulse DAG glyph draws its fan-out: N/cap badge, step status and rings from active runs, tooltip line",
   "lane": "done",
   "milestone": "m-96",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "StarPulse DAG panel lists its in-flight runs with a Queue row and xN step chips",
   "lane": "done",
   "milestone": "m-96",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "StarPulse navigator lists every concurrency pool and the Recent feed shows run events",
   "lane": "done",
   "milestone": "m-96",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Check live StarPulse shows every in-flight deliver run and the queue count Dagu reports",
   "lane": "waiting",
   "milestone": "m-96",
   "labels": [
    "agent-resolvable",
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
   "title": "Validate healthcheck after fixes deploy",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-98 and settle whether Fast, correctly routed delivery has reached its end state",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Remove fixed polling tails from delivery observation",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "agent-resolvable",
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
   "title": "Run Dagu's StarPulse producers through the starpulse emit CLI and fail undeclared python -m starpulse entry points",
   "lane": "done",
   "milestone": "m-92",
   "labels": [
    "agent-resolvable",
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
   "title": "Verify a live DAG run reaches the flow view through starpulse emit after the producer CLI merge",
   "lane": "done",
   "milestone": "m-92",
   "labels": [
    "agent-resolvable",
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
   "title": "Deploy template compose targets from declared rows in bin/deploy",
   "lane": "done",
   "milestone": "m-99",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-99 and settle whether Consolidate bin entry points into subcommand CLIs has reached its end state",
   "lane": "waiting",
   "milestone": "m-99",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Validate declared-row compose deploys through a real apply-on-merge run",
   "lane": "waiting",
   "milestone": "m-99",
   "labels": [
    "agent-resolvable",
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
   "title": "Run every unattended agent job through one bin/agent_job.py launcher",
   "lane": "done",
   "milestone": "m-99",
   "labels": [
    "agent-jobs",
    "agent-resolvable",
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
   "title": "Validate scheduled agent jobs run through bin/agent_job.py after merge",
   "lane": "waiting",
   "milestone": "m-99",
   "labels": [
    "agent-jobs",
    "agent-resolvable",
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
   "title": "Delete the per-job unattended agent launchers from bin",
   "lane": "waiting",
   "milestone": "m-99",
   "labels": [
    "agent-jobs",
    "agent-resolvable",
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
   "title": "Replace the generate_*.py shims with one bin/generate entry point",
   "lane": "done",
   "milestone": "m-99",
   "labels": [
    "agent-resolvable",
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
   "title": "Fold skill-eval-coverage and skill-trigger-labels into skill-eval subcommands",
   "lane": "done",
   "milestone": "m-99",
   "labels": [
    "agent-resolvable",
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
   "title": "Design daily New/Completed/Archived counts on the Star Map",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Refuse milestone add without a --spec",
   "lane": "done",
   "milestone": "m-84",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Verify main-follow and the post-merge hook no longer dirty main's uv.lock",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Move the host-bound steps out of the Validate job",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "agent-resolvable",
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
   "title": "Declare CI Runner Farm and its Validate job image in the unraid repo",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Bring the Unraid validate pool online and document it",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Check the Unraid pool's 7-day share, failure rate and duration",
   "lane": "waiting",
   "milestone": "m-100",
   "labels": [
    "agent-resolvable",
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
   "title": "Run a lib mutation sweep so F6 can report lib's redundant tests",
   "lane": "needs_attention",
   "milestone": "m-2",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Run the first skill-optimization session end to end on one eligible skill",
   "lane": "waiting",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Evaluate and promote a blue Frigate model trained on the new event labels",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "frigate",
    "kind-execute",
    "local-model",
    "needs-human",
    "size-5",
    "unraid"
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
   "title": "Audit every Backlog Board Overview dashboard panel for accuracy and cut a correction milestone",
   "lane": "needs_attention",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Proxmox Fan Monitor v2 dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Proxmox VE v2 dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Service Health Dashboard (ai-vm-1) dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Slice Health dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every vLLM Monitoring v2 dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Frigate Camera Monitor dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Home Assistant dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every TRMNL Poll dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every UPS dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Service Health (Unraid) dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Mutation Testing dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Audit every Speedtest Monitor dashboard panel for accuracy and cut a correction milestone",
   "lane": "ready",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Validate the completing-tasks skill-eval suite passes on a seeded sandbox",
   "lane": "ready",
   "milestone": "m-42",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Re-enable board autopilot once sizing and assignment are enforced",
   "lane": "ready",
   "milestone": "m-49",
   "labels": [
    "agent-profile",
    "kind-decide",
    "needs-human",
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
   "title": "Re-measure the auditing-infrastructure A/A on the branched machine",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "agent-resolvable",
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
   "title": "Verify ai-vm-1 root disk peak stays below 70% for 14 days after TASK-1863 rollout",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "agent-resolvable",
    "ai-vm-1",
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
   "title": "Retro m-2 and settle whether Test Value has reached its end state",
   "lane": "waiting",
   "milestone": "m-2",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Retro m-35 and settle whether Per-transition skill evals and optimization has reached its end state",
   "lane": "waiting",
   "milestone": "m-35",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Retro m-42 and settle whether GitHub API budget has reached its end state",
   "lane": "waiting",
   "milestone": "m-42",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Retro m-44 and settle whether Grafana in-house dashboard accuracy audits has reached its end state",
   "lane": "waiting",
   "milestone": "m-44",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Retro m-49 and settle whether Task sizing and model-effort assignment has reached its end state",
   "lane": "waiting",
   "milestone": "m-49",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Tune starting-tasks to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Tune auditing-docs to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune auditing-infrastructure to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune authoring-docs to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune authoring-skills to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune authoring-tests to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune creating-tickets to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune lint-gate to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune realigning-stale-docs to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Tune searching-the-web to pass k of k on Haiku and Sonnet",
   "lane": "ready",
   "milestone": "m-35",
   "labels": [
    "evaluation",
    "kind-decide",
    "needs-human",
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
   "title": "Skip Unraid blackbox probe failures inside the Appdata.Backup window",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Wire the trantor board's task read, edit and archive into Board so the live StarPulse page offers Edit and Archive",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "agent-resolvable",
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
   "title": "Show the Unraid CI Runner Farm runners on the runners dashboard",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-100 and settle whether Unraid CI runner pool has reached its end state",
   "lane": "waiting",
   "milestone": "m-100",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Deliver the Star Map daily counts in starpulse (trantor-org/starpulse#50)",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "adr-needed",
    "kind-execute",
    "needs-human",
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
   "title": "Retro m-102 and settle whether Star Map daily counts has reached its end state",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Send task creation and settle times from trantor's Board to StarPulse",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Check the live Star Map shows today's New, Completed and Archived counts",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Treat Matroska A_MS/ACM (LPCM) audio as lossless in lossless-audio-convert",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "agent-resolvable",
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
   "title": "Spike: select additional Ruff simplification rules",
   "lane": "done",
   "milestone": "m-103",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-103 and settle whether Prove Python simplification candidates has reached its end state",
   "lane": "done",
   "milestone": "m-103",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Spike: prototype Typer on one leaf CLI",
   "lane": "done",
   "milestone": "m-103",
   "labels": [
    "agent-resolvable",
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
   "title": "Spike: prototype Pydantic Settings for memory-search",
   "lane": "done",
   "milestone": "m-103",
   "labels": [
    "agent-resolvable",
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
   "title": "Attribute the validate-lane queue regression by repo and rebalance StarPulse placement",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "agent-resolvable",
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
   "title": "Check validate and general lane queue wait after the Mutation gate change",
   "lane": "waiting",
   "milestone": "m-98",
   "labels": [
    "agent-resolvable",
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
   "title": "Check the CI watcher's tail after the last check finishes on live deliveries",
   "lane": "waiting",
   "milestone": "m-98",
   "labels": [
    "agent-resolvable",
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
   "title": "Name CI runner-lane moves as live-state cutovers that get a post-merge queue check",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "agent-resolvable",
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
   "title": "Give StarPulse's native board a task reader so its task view shows priority and acceptance criteria",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "adr-needed",
    "kind-execute",
    "needs-human",
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
   "title": "Retract a StarPulse board task whose Markdown file was deleted",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "agent-resolvable",
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
   "title": "Record the owned-boundary Pydantic policy in an ADR",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Produce and consume memorysearch:usage through one shared Pydantic model",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "agent-resolvable",
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
   "title": "Consolidate sync_doc_ips document traversal",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-105 and settle whether Bounded production Python consolidations has reached its end state",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Check the deployed usage stream still lands every search after the shared-model merge",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Consolidate observability stream-to-Postgres consumer shell",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "agent-resolvable",
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
   "title": "Retro m-104 and settle whether Validate owned boundaries through shared Pydantic models has reached its end state",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Unify changed-file discovery for lint and test gates",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "agent-resolvable",
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
   "title": "Consolidate citation-linter I/O and reporting",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "agent-resolvable",
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
   "title": "Cut the Mutation gate's hold on the validate lane",
   "lane": "done",
   "milestone": "m-98",
   "labels": [
    "adr-needed",
    "kind-diagnose",
    "needs-human",
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
   "title": "State the lossless-audio-convert schedule in UTC in its README",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "agent-resolvable",
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
   "title": "starting-tasks eval suite: match the start claim and classify the TASK-2893 run's other failures",
   "lane": "done",
   "milestone": "m-35",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Point completing-tasks' ready hint at deliver and stop the sizing example anchoring a design task at 3",
   "lane": "done",
   "milestone": "m-102",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Record the promoted-SHA starpulse gitlink policy in an ADR",
   "lane": "done",
   "milestone": "m-106",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Decide and perform one starpulse gitlink bump action in bin/starpulse_bump.py",
   "lane": "done",
   "milestone": "m-106",
   "labels": [
    "agent-resolvable",
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
   "title": "Run starpulse gitlink bumps from a starpulse-bump workflow and take starpulse off Renovate",
   "lane": "done",
   "milestone": "m-106",
   "labels": [
    "agent-resolvable",
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
   "title": "Dispatch the green starpulse SHA to trantor's starpulse-bump workflow from starpulse CI",
   "lane": "done",
   "milestone": "m-106",
   "labels": [
    "agent-resolvable",
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
   "title": "Run lossless-audio-convert at 04:15 MST instead of 04:15 UTC",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Check starpulse merges reach trantor main through unforced bump PRs within 30 minutes",
   "lane": "waiting",
   "milestone": "m-106",
   "labels": [
    "agent-resolvable",
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
   "title": "Confirm lossless-audio-convert's next scheduled run starts at 04:15 MST",
   "lane": "waiting",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Declare ffmpeg and mkvtoolnix in ai-vm-1's setup-vm package manifest",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Set REQUIRE_MEDIA_TOOLS=1 in trantor-org/unraid's test workflow",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Edit a milestone's outcome when a re-scope replaces the decision it names",
   "lane": "done",
   "milestone": "m-85",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Refuse directory arguments in the changed-file lint and test gates",
   "lane": "done",
   "milestone": "m-105",
   "labels": [
    "agent-resolvable",
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
   "title": "Attribute skill-eval board tasks by board diff when create output is truncated",
   "lane": "done",
   "milestone": "m-35",
   "labels": [
    "agent-resolvable",
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
   "title": "Refuse cross-site writes to the StarPulse server and bind it to localhost by default",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Check that a Claude Code session and an upstream Backlog.md project reach the page from PyPI StarPulse",
   "lane": "waiting",
   "milestone": "m-75",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Make bin/skill-eval --skill take several skills instead of silently keeping the last",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "agent-resolvable",
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
   "title": "Say in Slicing a spec to cite the accepted ADR each slice's subject already has",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "agent-resolvable",
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
   "title": "Record the scheduled mutation sweep policy in the mutation testing ADR",
   "lane": "done",
   "milestone": "m-107",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Retro m-107 and settle whether Mutation sweep off the PR path has reached its end state",
   "lane": "waiting",
   "milestone": "m-107",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Run a 4-hourly Dagu mutation sweep over the functions main changed",
   "lane": "done",
   "milestone": "m-107",
   "labels": [
    "agent-resolvable",
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
   "title": "File a survivor task per sweep and alert on survivor age and sweep staleness",
   "lane": "done",
   "milestone": "m-107",
   "labels": [
    "agent-resolvable",
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
   "title": "Check the mutation sweep runs on schedule, selects every merged function and files survivor tasks",
   "lane": "waiting",
   "milestone": "m-107",
   "labels": [
    "agent-resolvable",
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
   "title": "Remove the Mutation gate from PR CI and the main ruleset's required checks",
   "lane": "waiting",
   "milestone": "m-107",
   "labels": [
    "agent-resolvable",
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
   "title": "Check validate and general lane queue p90 after the Mutation gate leaves PR CI",
   "lane": "waiting",
   "milestone": "m-107",
   "labels": [
    "agent-resolvable",
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
   "title": "Document the flow view HTTP run ingest once the starpulse pin carries it",
   "lane": "waiting",
   "milestone": "m-78",
   "labels": [
    "agent-resolvable",
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
   "title": "Keep alloy reading container logs across a docker.sock recreation and alert when they stop",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "agent-resolvable",
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
   "title": "Check each Acceptance Criterion command's executable exists when writing it",
   "lane": "done",
   "milestone": "m-104",
   "labels": [
    "agent-resolvable",
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
   "title": "Give the Unraid farm runner image parity with the ai-vm-1 validate runners",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Check the Unraid farm slots pass Node and Chrome jobs after the parity image ships",
   "lane": "waiting",
   "milestone": "m-100",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Say in the StarPulse doc that the native board reads a task's full record once trantor's gitlink includes it",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Point cohort slicing at designing-ui and give a doc edit that waits on a submodule pin its own task",
   "lane": "done",
   "milestone": "m-88",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Carry the team key through trantor's board adapter and docs after the starpulse pin moves",
   "lane": "done",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Refuse live-schema Alembic writes outside the main checkout in env.py",
   "lane": "done",
   "milestone": "m-108",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Retro m-108 and settle whether main-follow stability has reached its end state",
   "lane": "waiting",
   "milestone": "m-108",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Make main-follow upgrade every Alembic head and name the migration failure's cause",
   "lane": "done",
   "milestone": "m-108",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Check main-follow stays free of Alembic drift failures for 14 days after m-108 merges",
   "lane": "waiting",
   "milestone": "m-108",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Document the flow view hub OIDC sign-in in the starpulse doc after the pin moves",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Roll out the Ubuntu 24.04 farm image and verify Validate on each Tower slot",
   "lane": "in_progress",
   "milestone": "m-100",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Bind a session's claim by the Holder marker, not by any Session Link line, so commenting on another session's task does not hold it",
   "lane": "done",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Confirm make check-drift passes after the Dagu listing pagination fix",
   "lane": "done",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Make host-coupled tests pass on Unraid validate-farm runner slots",
   "lane": "done",
   "milestone": "",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Verify the Unraid farm runners appear on the runners dashboard after TASK-2884 merges",
   "lane": "waiting",
   "milestone": "m-100",
   "labels": [
    "agent-resolvable",
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
   "title": "Verify the six host-coupled tests pass on a Tower validate slot",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Describe the StarPulse insights contract in the starpulse service doc",
   "lane": "waiting",
   "milestone": "m-80",
   "labels": [
    "agent-resolvable",
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
   "title": "Draw the Claude Code harness machine on the stock StarPulse page and fix the receiver README steps",
   "lane": "done",
   "milestone": "m-75",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Refuse parking a task whose own PR is red, and make completing-tasks' head table own runner-fault and tracked-failure reds",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "adr-needed",
    "kind-execute",
    "needs-human",
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
   "title": "Size pyright's --threads to the runner's memory so lint does not hang on 4 GB farm slots",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Verify no OOM kill in a farm slot's Lint the changed files after TASK-2983 merges",
   "lane": "needs_attention",
   "milestone": "m-100",
   "labels": [
    "adr-needed",
    "kind-execute",
    "needs-human",
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
   "title": "Fix the runner_state step's 403 under Dagu by loading the workspace env",
   "lane": "done",
   "milestone": "m-100",
   "labels": [
    "agent-resolvable",
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
   "title": "StarPulse lists in-flight Dagu runs that started before UTC midnight",
   "lane": "done",
   "milestone": "",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Make deliver's red verdict carry the failing check's findings so an agent acts on them instead of stalling",
   "lane": "done",
   "milestone": "",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Release StarPulse with the harness machine and show a Claude Code session on the PyPI page",
   "lane": "needs_attention",
   "milestone": "m-75",
   "labels": [
    "adr-needed",
    "kind-execute",
    "needs-human",
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
   "title": "Fix mutation sweep lib baseline crash and write mutation_sweep.prom on every run",
   "lane": "done",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Count bin/deliver.py's CI wait as bash_ci in session timing",
   "lane": "done",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Fix the lib baseline test that crashes the mutation sweep",
   "lane": "done",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Find where agent delivery time goes in CI and recommend cuts",
   "lane": "done",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Run starpulse CI pytest under xdist sized to the runner",
   "lane": "done",
   "milestone": "",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Check validate-lane queue p90 and starpulse pytest time after xdist lands",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Say in starting-tasks that a fork a sibling slice or post-merge check needs is filed, not only recommended",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "agent-resolvable",
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
   "title": "Record a StarPulse archive as the operator's human_intervened write, like an edit",
   "lane": "in_progress",
   "milestone": "m-89",
   "labels": [
    "agent-resolvable",
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
   "title": "Let file_changed_since and file_unchanged_since take a full timestamp so a same-day wait releases on the awaited merge",
   "lane": "review",
   "milestone": "m-89",
   "labels": [
    "agent-resolvable",
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
   "title": "Give StarPulse's native Markdown board edit and archive writers so its task view offers Edit and Archive",
   "lane": "done",
   "milestone": "m-89",
   "labels": [
    "agent-resolvable",
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
   "title": "Prune StarPulse's event log on a timer so retention bounds the table and a pruned cursor records a gap",
   "lane": "waiting",
   "milestone": "m-87",
   "labels": [
    "agent-resolvable",
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
   "title": "Check live StarPulse retention prunes the event log after TASK-3000 merges",
   "lane": "waiting",
   "milestone": "m-87",
   "labels": [
    "agent-resolvable",
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
   "title": "Drop the completing-tasks pre-deliver lint-changed run that deliver's lint phase repeats",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Gate a StarPulse pin bump on emit arguments, adopted tables and a gitlink on package main",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "agent-resolvable",
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
   "title": "Attribute and cut the Validate job's changed-files lint time",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Log the cursor a StarPulse reader resumes from at start",
   "lane": "needs_attention",
   "milestone": "m-87",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Size a slice spanning two ordered repositories up one step and name a decision's production caller when slicing",
   "lane": "done",
   "milestone": "m-87",
   "labels": [
    "agent-resolvable",
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
   "title": "Verify the mutation sweep completes past 663b7c7 after the stale mirror fix",
   "lane": "waiting",
   "milestone": "",
   "labels": [
    "agent-resolvable",
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
   "title": "Run only the tests a starpulse pull request affects, full suite on main",
   "lane": "review",
   "milestone": "",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Cut pyright's wall time in the changed-files lint gate",
   "lane": "in_progress",
   "milestone": "",
   "labels": [
    "adr-needed",
    "agent-resolvable",
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
   "title": "Design Kanban Waiting stacks that fold a Waiting task under its Waiting blocker",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Retro m-109 and settle whether StarPulse UI rework: design round has reached its end state",
   "lane": "waiting",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Design a 60-70% two-column Kanban task modal and a collapsible Connect a tracker modal",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Design a Star Map icon and move the Kanban search to the Star Map's navigator position with a clear button",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Design DAGs as constellations placed across the Star Map instead of one sun",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Design a state machine view that makes sub-machine relationships obvious",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Design variants of a larger Kanban start-session control that a near-miss cannot turn into opening the task",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Discover what the navigator's Layers section should become",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Design the DAG-to-state relationship view between Review, MERGED and Done",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Design CI history on the Star Map dot and panel and the Kanban card and modal",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Design Recent rail hover and click that light and open the event's task on the Kanban and Star Map",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-decide",
    "needs-human",
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
   "title": "Stop the Star Map search tooltip clipping its text at larger browser text sizes",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Find and fix the Star Map link that still opens a task on Backlog.md instead of the StarPulse Kanban",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-diagnose",
    "needs-human",
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
   "title": "Stop the Star Map DAG panel's text overflowing its bar at larger browser text sizes",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Size Star Map suns once a day by their share of the trailing week's task moves",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "kind-execute",
    "needs-human",
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
   "title": "Make designing-ui render every mockup and slice at 100%, 125% and 150% browser text size",
   "lane": "in_progress",
   "milestone": "m-109",
   "labels": [
    "agent-resolvable",
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
   "title": "Make the remaining direct git callers fail when git fails instead of reading it as nothing found",
   "lane": "in_progress",
   "milestone": "m-69",
   "labels": [
    "agent-resolvable",
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
   "title": "Migrate the three hand-rolled atomic writes to atomic_write_text and add a lint rule that flags new ones",
   "lane": "in_progress",
   "milestone": "m-69",
   "labels": [
    "agent-resolvable",
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
