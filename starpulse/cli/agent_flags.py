"""The argparse flags the task and doc verbs share, apart from `agent_tasks` so building the parser imports none of the board."""

from __future__ import annotations

import argparse


def writer_flags(sub: argparse.ArgumentParser) -> None:
    """Add the flags that name the session and harness a task write is made from."""
    sub.add_argument(
        "--session",
        default="",
        help="the session writing, recorded as the assignee of a claimed task and on the change (else `STARPULSE_SESSION`)",
    )
    sub.add_argument(
        "--harness", default="", help="the harness of that session (`claude`, `cursor`), else `STARPULSE_HARNESS`"
    )


def create_flags(sub: argparse.ArgumentParser) -> None:
    """Add the detail flags of a task a `create` or `miss` command files; the title is the caller's."""
    sub.add_argument("--description", help="the task's Description section")
    sub.add_argument("--priority", help="`high`, `medium` or `low`")
    sub.add_argument("--impact", help="how much the work matters: `high`, `medium` or `low`")
    sub.add_argument("--urgency", help="how soon the work matters: `high`, `medium` or `low`")
    sub.add_argument("--milestone", help="the milestone's id (`m-106`)")
    sub.add_argument("--source", help="the key a producer files its task under, so a rerun finds it again")
    sub.add_argument(
        "--profile", "--assignee", dest="profile", help="the agent profile it is routed to (`@agent-standard-high`)"
    )
    sub.add_argument("--label", action="append", help="a label; repeat for several")
    sub.add_argument("--dependency", action="append", help="a task it depends on; repeat for several")
    sub.add_argument("--ac", action="append", help="an Acceptance Criterion; repeat for several, in order")
    sub.add_argument("--status", help="the lane to open it in, else the board's first (`Waiting`)")
    sub.add_argument("--type", help="the task's type (`bug`)")
    sub.add_argument("--reference", action="append", help="a reference; repeat for several")
    sub.add_argument(
        "--documentation",
        action="append",
        help="a documentation link, or an open doc's id (`doc-12`) for its file; repeat for several",
    )
    sub.add_argument("--dod", action="append", help="a Definition of Done item; repeat for several, in order")
