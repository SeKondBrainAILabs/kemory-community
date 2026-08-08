# Contributing

Thanks for considering a contribution to Kemory Community Edition.

## Quick start

```bash
git clone https://github.com/SeKondBrainAILabs/kemory-community.git
cd kemory-community
# (Once backend code lands via the subtree split:)
make dev   # boots API + dashboard locally
make test  # runs pytest + vitest matrix
```

The backend, dashboard and CLI now live in this repository — they were
imported from hosted Kemory by subtree split and are maintained here.

Upstream changes are replayed **manually, by feature cohort**, not mirrored:
each hosted commit is classified port / adapt / exclude against the community
boundaries and landed in its own PR. The process and the full decision history
are in [docs/HOSTED_DELTA_LEDGER.md](docs/HOSTED_DELTA_LEDGER.md). There is no
scheduled sync job, by design — a mirror would defeat the classification that
keeps hosted concerns out of this repository.

## Branch model

- `main` - protected, requires PR + 1 review + CI green.
- Feature branches: `feat/<short-slug>`, `fix/<short-slug>`,
  `docs/<short-slug>`, etc. Upstream replays use `community/<slug>`.

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/).
Common prefixes: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`,
`test:`, `perf:`.

## DCO sign-off (REQUIRED)

Every commit must carry a `Signed-off-by:` line, asserting the
[Developer Certificate of Origin](https://developercertificate.org/).
Use `git commit -s` to add it automatically.

## Changelog entries

If your PR is user-visible, add a bullet to `[Unreleased]` in
`CHANGELOG.md`.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).

## Questions

Open a [Discussion](https://github.com/SeKondBrainAILabs/kemory-community/discussions)
in the Q&A category. Bugs and feature requests go in Issues.
