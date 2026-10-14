# Contributing to StarPulse

StarPulse takes changes two ways: anyone can open an issue, and collaborators open pull requests.

## Open an issue

Report a bug, ask for a feature or propose a change by
[opening an issue](https://github.com/trantor-org/starpulse/issues/new/choose). The bug form asks for the
version, how you ran StarPulse and what you saw; the feature form asks what you are trying to do. An accepted
issue is fixed by the maintainer or a collaborator, and its pull request links back to it.

Pull requests are open to collaborators only, and GitHub refuses one from anyone else. To become a
collaborator, say so in an issue.

## Open a pull request (collaborators)

- Branch from `main` in this repository and keep a pull request to one change, with tests for what it changes.
- The `python`, `web`, `static-checks` and `build` checks must pass before it merges. `uv run pytest` and
  `pnpm --dir starpulse/web run check` run the first two locally; [docs/development.md](docs/development.md) sets them up and says
  how to regenerate the API schema and types that `static-checks` compares.
- The maintainer adds it to the merge queue. The queue squashes it onto `main` plus every pull request ahead of it,
  reruns the required checks on that candidate, and merges only a green one, so a pull request never needs
  rebasing to stay current. Its title becomes the commit on `main` and the line in the next release's
  notes, so write the title for someone who uses StarPulse.
- Nobody pushes to `main` directly, force-pushes it or deletes it.
- At merge, `dispatch-merged.yml` pins the merged commit on trantor, once the workspace App's check runs (`python`, `web`,
  `static-checks`, `trantor-contract`) on the merge-queue candidate or pull request that tested that tree have passed: its `Pin the starpulse SHA` step runs trantor's `bin/starpulse_ops/starpulse_pin.sh` on the
  self-hosted runner, and no `repository_dispatch` is sent. A push to `main` runs no test job: the queue already tested the
  commit `main` received. The push run's `dispatch` job runs the same step as a fallback, and the script re-checks the
  App's checks before pinning and does nothing for a SHA already pinned. Pull requests and merge-queue candidates pin
  nothing. The step reads the `WORKSPACE_APP_CLIENT_ID`, `WORKSPACE_APP_PRIVATE_KEY` and `TRANTOR_PIN_DEPLOY_KEY`
  secrets.

## License

A contribution is licensed under this project's [MIT License](LICENSE), the same terms you received it under.
There is no sign-off or contributor agreement.
