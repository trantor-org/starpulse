"""How many pull requests are open in each repository the PR store holds, as a Prometheus metric."""

from starpulse.pulls.adapters.outbound.pulls import PullStore


def open_pulls_exposition(pulls: PullStore) -> str:
    """`starpulse_open_pulls` per repository: its OPEN records, 0 for a repository holding none."""
    open_now = [record["repo"] for record in pulls.find(state="OPEN", bodies=False)]
    return "\n".join(
        [
            "# HELP starpulse_open_pulls Open pull requests in the PR store, by repository.",
            "# TYPE starpulse_open_pulls gauge",
            *(f'starpulse_open_pulls{{repo="{repo}"}} {open_now.count(repo)}' for repo in pulls.repos()),
            "",
        ]
    )
