import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "upstream_intake.py"
SPEC = importlib.util.spec_from_file_location("upstream_intake", SCRIPT)
assert SPEC and SPEC.loader
upstream_intake = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = upstream_intake
SPEC.loader.exec_module(upstream_intake)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, relative_path: str, content: str, message: str) -> str:
    target = repo / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", relative_path)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_path_rules_keep_hosted_identity_out_and_flag_memory_ports():
    config = upstream_intake.load_config(ROOT / "config" / "upstream-sync.json")

    assert upstream_intake.decision_for_path("keycloak/realm.json", config) == "exclude"
    assert upstream_intake.decision_for_path("backend/billing/routes.py", config) == "exclude"
    assert upstream_intake.decision_for_path("backend/mcp/ui/vault_overview.html", config) == "exclude"
    assert upstream_intake.decision_for_path("kemory/search/reranker.py", config) == "port"
    assert upstream_intake.decision_for_path("backend/api/routes/memories.py", config) == "adapt"
    assert upstream_intake.decision_for_paths(
        ("keycloak/realm.json", "kemory/search/reranker.py"), config
    ) == "mixed"


def test_default_report_redacts_private_upstream_details(tmp_path):
    repo = tmp_path / "hosted"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    baseline = _commit(repo, "README.md", "base\n", "private baseline subject")
    head = _commit(repo, "kemory/search/reranker.py", "change\n", "private feature subject")
    config = upstream_intake.load_config(ROOT / "config" / "upstream-sync.json")

    observed, records = upstream_intake.collect_commits(repo, baseline, "HEAD", config)
    report = upstream_intake.build_report(
        baseline=baseline,
        head=observed,
        records=records,
        include_details=False,
        max_details=10,
    )
    rendered = upstream_intake.render_markdown(report)

    assert observed == head
    assert report["candidate_count"] == 1
    assert "candidates" not in report
    assert "private feature subject" not in json.dumps(report)
    assert "kemory/search/reranker.py" not in rendered
    assert "intentionally redacted" in rendered


def test_detailed_report_is_explicit_and_bounded(tmp_path):
    records = [
        upstream_intake.CommitRecord(
            commit=f"{index:040x}",
            subject=f"subject {index}",
            paths=(f"kemory/search/{index}.py",),
            decision="port",
        )
        for index in range(3)
    ]

    report = upstream_intake.build_report(
        baseline="a" * 40,
        head="b" * 40,
        records=records,
        include_details=True,
        max_details=2,
    )

    assert [item["subject"] for item in report["candidates"]] == ["subject 1", "subject 2"]
    assert report["details_truncated"] is True
