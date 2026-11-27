"""Feed pull requests."""


class PullMethods:
    def pull_requests(self) -> dict[str, list[str]]:
        """Each open task's pull request links, for the tasks that cite any."""
        prs = {agent["id"]: agent["prs"] for agent in self.open_tasks()}
        return {task: list(links) for task, links in prs.items() if links}

    def set_pulls(self, pulls: dict[str, list[dict]], answers: dict | None = None) -> None:
        """Take each task's pull request state and publish it when it differs from before; `answers` is what the
        projection kept."""
        with self._lock:
            if answers is not None:
                self._pull_answers = answers
            if pulls == self._pulls:
                return
            self._pulls = pulls
            self._publish("pulls", {"pulls": pulls})
        self._refresh_ledgers()
