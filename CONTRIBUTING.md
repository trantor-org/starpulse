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
- The `python`, `web` and `build` checks must pass before it merges. `uv run pytest` and
  `pnpm --dir starpulse/web run check` run the first two locally; the README's Develop section sets them up.
- The maintainer squash-merges it. Its title becomes the commit on `main` and the line in the next release's
  notes, so write the title for someone who uses StarPulse.
- Nobody pushes to `main` directly, force-pushes it or deletes it.
- After a merge, the `dispatch` job in `ci.yml` runs once `python` and `web` pass on `main`. It sends trantor a
  `starpulse-green` `repository_dispatch` whose `sha` is the tested commit, and trantor's `starpulse-bump` workflow
  opens one pull request pinned to that commit. Pull requests and red runs send nothing. The job mints the
  workspace App token from the `WORKSPACE_APP_CLIENT_ID` and `WORKSPACE_APP_PRIVATE_KEY` secrets.

## License

A contribution is licensed under this project's [MIT License](LICENSE), the same terms you received it under.
There is no sign-off or contributor agreement.
