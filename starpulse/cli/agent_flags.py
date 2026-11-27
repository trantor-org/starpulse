"""The argparse flags the task and doc verbs share, apart from `agent_tasks` so building the parser imports none of the board."""

import argparse


def writer_flags(sub: argparse.ArgumentParser) -> None:
    """Add the flags that name the session and harness a task write is made from."""
    sub.add_argument(
        "--session",
        default="",
        help="the session writing, the one a dispatch pins to the task and recorded on the change (else `STARPULSE_SESSION`)",
    )
    sub.add_argument(
        "--harness", default="", help="the harness of that session (`claude`), else `STARPULSE_HARNESS`"
    )


def create_flags(sub: argparse.ArgumentParser) -> None:
    """Add the detail flags of a task a `create` command files; the title is the caller's."""
    sub.add_argument(
        "--brief",
        metavar="FILE",
        help="the task's brief as a JSON object, `-` for stdin: `outcome`, `why`, `current_state`, `scope`, "
        "`out_of_scope`, `blast_radius`, `stop_conditions`, and `rollback` when `blast_radius.undo` is 2 or more",
    )
    sub.add_argument(
        "--duplicate-search-queries",
        action="append",
        dest="duplicate_queries",
        help="words to search the board for a task that does this work, which the server records; repeat for several",
    )
    sub.add_argument("--description", help=argparse.SUPPRESS)
    sub.add_argument("--priority", help="`high`, `medium` or `low`")
    sub.add_argument("--impact", help="how much the work matters: `high`, `medium` or `low`")
    sub.add_argument("--urgency", help="how soon the work matters: `high`, `medium` or `low`")
    sub.add_argument(
        "--tier", help="the task's tier: `regression`, `bug`, `leverage`, `standard` (default) or `decide`"
    )
    sub.add_argument("--milestone", help="the milestone's id (`m-106`)")
    sub.add_argument("--source", help="the key a producer files its task under, so a rerun finds it again")
    sub.add_argument(
        "--request-key", help="the key of this create; a rerun under it returns the task the first send filed"
    )
    sub.add_argument("--follows", help="the id of the finished task this one follows up (`TASK-9`)")
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
