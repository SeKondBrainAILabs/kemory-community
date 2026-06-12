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

For now (during the scaffolding phase), the backend code lives in
`SeKondBrainAILabs/agent_memory_vault` and is pulled into this repo
via a weekly subtree sync. See `.github/workflows/sync-from-main.yml`.

## Branch model

- `main` - protected, requires PR + 1 review + CI green.
- `dev-sync` - auto-receives the weekly subtree pull from
  `agent_memory_vault`. Manually promoted to `main` after review.
- Feature branches: `feat/<short-slug>`, `fix/<short-slug>`,
  `docs/<short-slug>`, etc.

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
