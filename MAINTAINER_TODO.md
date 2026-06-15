# Maintainer TODO

Things the scaffolding agent could not perform. Do each section below
to complete the public-repo setup.

## 1. Apply repo settings (if agent lacked perms)

```bash
gh repo edit --add-topic kemory --add-topic memory --add-topic ai-agents \
  --add-topic llm --add-topic mcp --add-topic groq --add-topic vector \
  --add-topic rag --add-topic local-first --add-topic oss

gh repo edit --description "Local-first, OSS memory for AI agents. Same wire protocol as hosted Kemory. Apache-2.0." \
  --homepage "https://community.kemory.s9n.ai"

gh repo edit --enable-discussions --enable-issues --enable-projects
gh api -X PATCH "/repos/SeKondBrainAILabs/kemory-community" -f has_wiki=false

gh api -X PUT "/repos/SeKondBrainAILabs/kemory-community/branches/main/protection" --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["ci / noop-pass"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "required_signatures": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
```

NOTE: `required_signatures` is **off** for v0.1 - flip on later when
the team has SSH/GPG signing infrastructure across the org.

## 2. Discussions categories (web UI - gh CLI is fiddly)

In the repo Discussions tab, create:

- **Announcements** (announcement format)
- **Q&A** (question format)
- **Show and tell** (open-ended)
- **Ideas** (open-ended)
- **General** (open-ended)

## 3. Repo secrets (Settings -> Secrets and variables -> Actions)

Add when needed (do NOT commit values):

- `NPM_TOKEN` - automation token scoped to the `kemory-community` package
- `GROQ_API_KEY_TEST` - low-quota Groq key for CI L3 tests
- `APPLE_DEVELOPER_ID_CERT` + `APPLE_DEVELOPER_ID_PASSWORD` - macOS binary signing (can wait until first real release)
- `APPLE_NOTARY_API_KEY_ID` + `APPLE_NOTARY_API_KEY_ISSUER_ID` + `APPLE_NOTARY_API_PRIVATE_KEY` - notarization

## 4. DNS

Create a CNAME record:

```text
community.kemory.s9n.ai -> SeKondBrainAILabs.github.io
```

Propagation takes 5-30 minutes.

## 5. GitHub Pages

Settings -> Pages:
- Source: `main` branch, `/docs` folder
- Custom domain: `community.kemory.s9n.ai`
- Enforce HTTPS: on (will be greyed until DNS propagates)

## 6. npm reservation

```bash
npm login
npm publish --access public
```

The v0.1 package is the Docker setup CLI. The tag release workflow builds
and pushes the API/dashboard images to GHCR before publishing npm.

## 7. Privacy policy (also needed for Chrome extension Web Store)

`docs/privacy.md` has been drafted in this scaffold PR. Review the wording
before configuring GitHub Pages or submitting any extension review.

## 8. Once the adapter refactor in `agent_memory_vault` lands

- [x] Import community-safe backend, `kemory`, `kemory_cli`, and dashboard
  subtrees from `agent_memory_vault` after the adapter refactor landed.
- [x] Add a Docker community-config verifier for `pgvector`, `local_fs`,
  `local_single_user`, and `noop` telemetry.
- [x] Wire npm `kemory-community init --runtime docker` / `up` to the
  community port registry (`8111`, `5175`, `5434`).
- [x] Add canonical `kemory_*` MCP tool aliases while retaining `s9nmem_*`
  and `kora_*` compatibility.
- [x] Update `.github/workflows/release.yml` with Docker image publishing
  plus npm publish steps.
- [ ] Update branch protection's `required_status_checks` from
  `["ci / noop-pass"]` to `["ci / smoke", "Community Config / pgvector + local_fs + local_single_user + noop"]`.
