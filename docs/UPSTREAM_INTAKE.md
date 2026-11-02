# Hosted Upstream Intake

Kemory Community is an independent public repository. Hosted Kemory is a
private upstream design and implementation source, so a normal Git merge or
subtree mirror would cross identity, billing, telemetry, storage, and licensing
boundaries.

The intake workflow automates discovery while keeping integration reviewed:

1. `.github/workflows/upstream-intake.yml` runs daily and on demand.
2. It checks out hosted Kemory using the read-only
   `KEMORY_UPSTREAM_READ_TOKEN` repository secret.
3. `scripts/upstream_intake.py` compares hosted `main` with the accepted
   baseline in `config/upstream-sync.json`.
4. Each first-parent change is classified as `port`, `adapt`, `exclude`,
   `mixed`, or `review` from its changed paths.
5. A redacted summary is written to the Actions job summary, retained as an
   artifact, and committed to the fixed `automation/upstream-intake` branch.
6. The workflow opens or refreshes one pull request containing only the
   redacted observation. It closes that pull request when no candidates remain.
   The workflow never imports hosted code or advances the accepted baseline.
7. The job fails while review candidates exist, so the queue cannot be mistaken
   for a completed port.
8. A maintainer reviews details locally, implements compatible behavior on a
   Community branch, runs the Docker acceptance suite, updates the delta
   ledger, and only then advances the accepted baseline.

The repository must provide a read-only `KEMORY_UPSTREAM_READ_TOKEN` secret
that can clone `SeKondBrainAILabs/Kemory`. Use a fine-grained token limited to
that repository and replace any broader bootstrap credential as soon as one is
available. `KEMORY_COMMUNITY_SYNC_TOKEN` must be limited to writing branches
and pull requests in `SeKondBrainAILabs/kemory-community`; it creates the review
pull request because the organisation disables pull-request creation by the
workflow `GITHUB_TOKEN`. Branch protection and required human review continue
to gate `main`.

Run the same intake locally:

```bash
python scripts/upstream_intake.py \
  --source-repo /path/to/hosted-kemory \
  --source-ref origin/main
```

For a local-only detailed queue:

```bash
python scripts/upstream_intake.py \
  --source-repo /path/to/hosted-kemory \
  --source-ref origin/main \
  --include-details \
  --markdown-output .upstream/intake.md
```

`.upstream/` is ignored. Do not commit detailed hosted reports to the public
repository. Classification is triage, not proof of compatibility; each port
still needs code-level review and Community-specific tests.

The checked-in [`UPSTREAM_INTAKE_LATEST.md`](UPSTREAM_INTAKE_LATEST.md) and
[`upstream-observation.json`](../config/upstream-observation.json) are safe
public summaries. They intentionally contain no hosted commit subjects or
changed paths.
