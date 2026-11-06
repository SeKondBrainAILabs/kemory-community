#!/usr/bin/env python3
"""Inventory hosted Kemory changes without crossing Community boundaries.

The report is redacted by default because the upstream repository is private
while this repository is public. Passing ``--include-details`` is intended for
local maintainer review and Actions artifacts with appropriately restricted
access; those reports must not be committed to this repository.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "upstream-sync.json"
DECISION_ORDER = {"exclude": 0, "review": 1, "port": 2, "adapt": 3, "mixed": 4}


class IntakeError(RuntimeError):
    """Raised when the upstream repository cannot produce a safe report."""


@dataclass(frozen=True)
class CommitRecord:
    commit: str
    subject: str
    paths: tuple[str, ...]
    decision: str


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise IntakeError(detail)
    return result.stdout.strip()


def _git_bytes(repository: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise IntakeError(detail or "git command failed")
    return result.stdout


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"cannot read upstream sync config {path}: {exc}") from exc
    if config.get("schema_version") != 1:
        raise IntakeError("upstream sync config schema_version must be 1")
    if not config.get("accepted_baseline") or not config.get("rules"):
        raise IntakeError("upstream sync config requires accepted_baseline and rules")
    return config


def decision_for_path(path: str, config: dict[str, Any]) -> str:
    for rule in config["rules"]:
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in rule["patterns"]):
            return str(rule["decision"])
    return str(config.get("default_decision", "review"))


def decision_for_paths(paths: tuple[str, ...], config: dict[str, Any]) -> str:
    decisions = {decision_for_path(path, config) for path in paths}
    if not decisions:
        return "review"
    if len(decisions) == 1:
        return decisions.pop()
    if decisions == {"exclude", "review"}:
        return "exclude"
    if "exclude" in decisions:
        return "mixed"
    return max(decisions, key=lambda value: DECISION_ORDER.get(value, 99))


def collect_commits(
    repository: Path,
    baseline: str,
    source_ref: str,
    config: dict[str, Any],
) -> tuple[str, list[CommitRecord]]:
    head = _git(repository, "rev-parse", "--verify", f"{source_ref}^{{commit}}")
    resolved_baseline = _git(repository, "rev-parse", "--verify", f"{baseline}^{{commit}}")
    ancestor = subprocess.run(
        ["git", "-C", str(repository), "merge-base", "--is-ancestor", resolved_baseline, head],
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise IntakeError(f"accepted baseline {resolved_baseline} is not an ancestor of {head}")
    raw_log = _git_bytes(
        repository,
        "log",
        "--reverse",
        "--first-parent",
        "--diff-merges=first-parent",
        "--no-renames",
        "--name-only",
        "-z",
        "--format=%x1e%H%x00%s%x00",
        f"{resolved_baseline}..{head}",
    )
    records: list[CommitRecord] = []
    for raw_record in raw_log.split(b"\x1e"):
        if not raw_record.strip(b"\x00\n"):
            continue
        fields = raw_record.split(b"\x00")
        if len(fields) < 2:
            raise IntakeError("could not parse streamed upstream log")
        commit = fields[0].decode("ascii").strip()
        subject = fields[1].decode("utf-8", errors="replace").strip()
        paths = tuple(
            path
            for value in fields[2:]
            if (path := value.decode("utf-8", errors="surrogateescape").strip())
        )
        records.append(
            CommitRecord(
                commit=commit,
                subject=subject,
                paths=paths,
                decision=decision_for_paths(paths, config),
            )
        )
    return head, records


def build_report(
    *,
    baseline: str,
    head: str,
    records: list[CommitRecord],
    include_details: bool,
    max_details: int,
) -> dict[str, Any]:
    counts = Counter(record.decision for record in records)
    candidate_count = sum(counts[name] for name in ("port", "adapt", "mixed", "review"))
    report: dict[str, Any] = {
        "schema_version": 1,
        "accepted_baseline": baseline,
        "observed_head": head,
        "first_parent_commit_count": len(records),
        "candidate_count": candidate_count,
        "decision_counts": dict(sorted(counts.items())),
        "details_included": include_details,
    }
    if include_details:
        selected = [record for record in records if record.decision != "exclude"][-max_details:]
        report["candidates"] = [
            {
                "commit": record.commit,
                "subject": record.subject,
                "paths": list(record.paths),
                "decision": record.decision,
            }
            for record in selected
        ]
        report["details_truncated"] = candidate_count > len(selected)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Kemory Upstream Intake",
        "",
        f"- Accepted baseline: `{report['accepted_baseline']}`",
        f"- Observed head: `{report['observed_head']}`",
        f"- First-parent commits: **{report['first_parent_commit_count']}**",
        f"- Review candidates: **{report['candidate_count']}**",
        "",
        "## Classification",
        "",
        "| Decision | Commits |",
        "| --- | ---: |",
    ]
    for decision, count in report["decision_counts"].items():
        lines.append(f"| `{decision}` | {count} |")
    if report.get("details_included"):
        lines.extend(["", "## Candidate Details", ""])
        for candidate in report.get("candidates", []):
            lines.append(
                f"- `{candidate['commit'][:12]}` `{candidate['decision']}` {candidate['subject']}"
            )
            for changed_path in candidate["paths"]:
                lines.append(f"  - `{changed_path}`")
        if report.get("details_truncated"):
            lines.extend(["", "Candidate details are truncated; use a larger `--max-details` locally."])
    else:
        lines.extend(
            [
                "",
                "Commit subjects and changed paths are intentionally redacted from the default report.",
                "Run locally with `--include-details` for maintainer review.",
            ]
        )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--source-ref", default="origin/main")
    parser.add_argument("--baseline")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--include-details", action="store_true")
    parser.add_argument("--max-details", type=int, default=200)
    parser.add_argument("--fail-on-candidates", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
        baseline = args.baseline or config["accepted_baseline"]
        head, records = collect_commits(args.source_repo, baseline, args.source_ref, config)
        report = build_report(
            baseline=baseline,
            head=head,
            records=records,
            include_details=args.include_details,
            max_details=max(1, args.max_details),
        )
    except IntakeError as exc:
        print(f"upstream-intake: {exc}", file=sys.stderr)
        return 2

    rendered = render_markdown(report)
    print(rendered, end="")
    for target, content in (
        (args.json_output, json.dumps(report, indent=2, sort_keys=True) + "\n"),
        (args.markdown_output, rendered),
    ):
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    if args.fail_on_candidates and report["candidate_count"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
