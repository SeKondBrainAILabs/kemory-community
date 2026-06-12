---
title: Privacy Policy
---

# Privacy Policy

Kemory Community Edition is local-first software for personal AI-agent
memory. The community build is designed to run on your machine and keep
your data under your control.

## What Kemory stores locally

Kemory stores memory records, namespaces, chats, artifacts, configuration,
indexes, and operational metadata on your local machine. By default:

- Database data is stored under `~/.kemory-community/data/pgdata/`.
- Artifacts are stored under `~/.kemory-community/artifacts/`.
- Configuration is stored under `~/.kemory-community/`.

If you opt into an external Postgres database, your database provider's
own privacy and security practices apply to that database.

## What Kemory sends out

Kemory Community Edition does not include hosted telemetry.

The community build may send data to external services only when needed
for features you configure:

- Groq receives prompts and related context for L3 summaries and other
  model-backed features, using the Groq API key you provide.
- Hugging Face may be contacted on first run to download the default local
  embedding model, `BAAI/bge-small-en-v1.5`.
- If you configure a non-default embedding or model provider, requests are
  sent to that provider according to the provider settings you choose.

Kemory does not send your local memories, chats, or artifacts to the hosted
Kemory service.

## API keys

API keys are used only for the providers you configure. Do not share your
local Kemory configuration directory with untrusted users.

## Logs

Logs may contain request metadata, error details, and local diagnostic
information. Avoid sharing logs publicly if they may include private content
or secrets.

## Contact

For privacy questions, open a GitHub Discussion:
https://github.com/SeKondBrainAILabs/kemory-community/discussions

For security issues, email security@kemory.s9n.ai instead of opening a
public issue.
