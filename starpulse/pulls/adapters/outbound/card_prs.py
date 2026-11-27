"""The pull requests a task's read-model row holds: the scalar fields its card draws, restated when the pull store saves
one or a task's links change, so a list reads them with no pull store lookup."""

from collections.abc import Callable, Iterable
from typing import Any

from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.github.model.pulls import pull_at
from starpulse.pulls.adapters.outbound.pulls import PullStore

#: The fields of a stored pull request: the card's own; the drawer's others (`body`, `files`, ...) are read when asked.
CARD = ("repo", "number", "state", "isDraft", "mergeable", "checks", "threads", "mergedAt", "mergeSha")


def card_prs(pulls: PullStore, links: list[str]) -> list[dict[str, Any]]:
    """The stored pull requests the pages `links` name, each as its card draws it; one the store holds none of is left out."""
    cited = [at for at in map(pull_at, links) if at]
    return [{key: record.get(key) for key in CARD} for at in cited for record in pulls.find(at.repo, at.number, bodies=False)]


def restater(model: ReadModel, pulls: PullStore, cited: Callable[[str], list[str]]) -> Callable[[Iterable[str]], None]:
    """The call that sets the pull requests of each task id it is given from the store as it stands."""

    def restate(ids: Iterable[str]) -> None:
        wanted = list(dict.fromkeys(ids))
        if wanted:
            model.store_prs({task: card_prs(pulls, cited(task)) for task in wanted})

    return restate


def saved(model: ReadModel, restate: Callable[[Iterable[str]], None]) -> Callable[[list[tuple[str, int]]], None]:
    """The listener of the pull store's saves (`PullStore.subscribe_saves`): it restates each task citing a saved pull request."""
    return lambda keys: restate(task for repo, number in keys for task in model.citing(f"change:github:{repo}:{number}"))
